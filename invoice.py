# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import time
from decimal import Decimal
import datetime
import hashlib
from types import SimpleNamespace
import pytz
from sql import Literal, Null
from sql.aggregate import Max
from sql.functions import Substring
from sql.conditionals import Case, Coalesce
from requests import Session
from urllib.parse import urlencode
from zeep import Client
from zeep.transports import Transport
from zeep.settings import Settings
from zeep.plugins import HistoryPlugin

import trytond
from trytond.config import config
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError, UserWarning
from trytond.tools import grouped_slice
from trytond.modules.account.exceptions import PeriodNotFoundError
from . import tools

PRODUCTION_QR_URL = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
TEST_QR_URL = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"

PRODUCTION_ENV = config.getboolean('database', 'production', default=False)

WSDL_PROD = 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/'
WSDL_TEST = 'https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/'

VERSION = trytond.__version__
VERSION = '.'.join(VERSION.split('.')[:2])

AEAT_INVOICE_STATE = [
    (None, ''),
    ('Correcto', 'Accepted'),
    ('AceptadoConErrores', 'Accepted with Errors'),
    ('Incorrecto', 'Rejected'),
    ]

OPERATION_KEY = [ # L2
    ('F1', 'Invoice (Art 6.7.3 y 7.3 of RD1619/2012)'),
    ('F2', 'Simplified Invoice (ticket) and Invoices without destination '
        'identidication (Art 6.1.d of RD1619/2012)'),
    ('F3', 'Invoice issued to replace simplified invoices issued and filed'),
    # R1: errores fundados de derecho y causas del artículo 80.Uno, Dos y Seis
    #    LIVA
    ('R1', 'Corrected Invoice '
        '(Art 80.1, 80.2 and 80.6 and error grounded in law)'),
    # R2: concurso de acreedores
    ('R2', 'Corrected Invoice (Art. 80.3)'),
    # R3: deudas incobrables
    ('R3', 'Credit Note (Art 80.4)'),
    # R4: resto de causas
    ('R4', 'Corrected Invoice (Other)'),
    ('R5', 'Corrected Invoice in simplified invoices'),
    ]


def get_sistema_informatico():
    pool = Pool()
    Company = pool.get('company.company')

    # TODO: We should check if the other companies are Spanish
    # and/or should be counted
    companies = Company.search([], count=True)

    return {
        'NombreRazon': config.get('aeat_verifactu', 'nombre_razon'),
        'NIF': config.get('aeat_verifactu', 'nif'),
        'NombreSistemaInformatico': config.get('aeat_verifactu',
            'nombre_sistema_informatico'),
        'IdSistemaInformatico': config.get('aeat_verifactu',
            'id_sistema_informatico'),
        'Version': VERSION,
        'NumeroInstalacion': config.get('aeat_verifactu',
            'numero_instalacion'),
        'TipoUsoPosibleSoloVerifactu': 'N',
        'TipoUsoPosibleMultiOT': 'S',
        'IndicadorMultiplesOT': 'S' if companies > 1 else 'N',
        }

def get_headers(company):
    return {
        'IDVersion': '1.0',
        'ObligadoEmision': {
            'NombreRazon': tools.unaccent(company.party.name),
            'NIF': company.party.verifactu_vat_code,
            # TODO: NIFRepresentante
        },
    }


class Verifactu(ModelSQL, ModelView):
    '''
    AEAT Verifactu
    '''
    __name__ = 'aeat.verifactu'

    invoice = fields.Many2One('account.invoice', 'Invoice', required=True,
        domain=[('type', '=', 'out')])
    state = fields.Selection(AEAT_INVOICE_STATE, 'State')
    company = fields.Many2One('company.company', 'Company', required=True)
    invoice_operation_key = fields.Function(fields.Selection(OPERATION_KEY,
            'Operation Key'), 'get_invoice_operation_key')
    fingerprint = fields.Text('Fingerprint', readonly=True)
    error_message = fields.Char('Error Message', readonly=True)

    def get_invoice_operation_key(self, name):
        return self.invoice.verifactu_operation_key if self.invoice else None

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('invoice')
        cls._order = [('id', 'DESC')]

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['state'] = None
        default['fingerprint'] = None
        default['error_message'] = None
        return super().copy(records, default=default)


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    verifactu_operation_key = fields.Selection([(None, '')] + OPERATION_KEY,
        'Verifactu Operation Key', states={
            'required': (Eval('is_verifactu', False)
                & Eval('state').in_(['posted', 'paid'])),
            })
    verifactu_to_send = fields.Function(fields.Boolean(
            'Verifactu Pending Sending'), 'get_verifactu_fields',
        searcher='search_verifactu_to_send')
    verifactu_state = fields.Function(fields.Selection(AEAT_INVOICE_STATE,
            'Verifactu State'), 'get_verifactu_fields',
        searcher='search_verifactu_state')
    is_verifactu = fields.Function(fields.Boolean('Is Verifactu'),
            'get_verifactu_fields', searcher='search_is_verifactu')
    verifactu_records = fields.One2Many('aeat.verifactu', 'invoice',
        "Verifactu Report Lines")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        verifactu_fields = {'verifactu_operation_key'}
        cls._check_modify_exclude |= verifactu_fields
        if hasattr(cls, '_intercompany_excluded_fields'):
            cls._intercompany_excluded_fields += verifactu_fields
            cls._intercompany_excluded_fields += ['verifactu_records']

        # not allow modify reference when is supplier or not pending to sending
        readonly = (
            (Eval('state') != 'draft') & (Eval('type') == 'in') ) | (
            (Eval('state') != 'draft') & ~Bool(Eval('verifactu_to_send'))
            )
        if 'readonly' in cls.reference.states:
            cls.reference.states['readonly'] |= readonly

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="verifactu"]', 'states', {
                'invisible': ~Eval('is_verifactu', False),
            }),
            ]

    @classmethod
    def get_verifactu_fields(cls, invoices, names):
        pool = Pool()
        Period = pool.get('account.period')
        Date = pool.get('ir.date')
        Verifactu = pool.get('aeat.verifactu')
        cursor = Transaction().connection.cursor()

        result = {name: {} for name in names}
        invoice_ids = [invoice.id for invoice in invoices if invoice.id]

        latest_verifactu = {}
        if invoice_ids and {'verifactu_state', 'verifactu_to_send'} & set(names):
            verifactu = Verifactu.__table__()
            query = verifactu.select(
                verifactu.invoice,
                Max(verifactu.id).as_('id'),
                where=verifactu.invoice.in_(invoice_ids),
                group_by=verifactu.invoice)
            cursor.execute(*query)
            latest_ids = dict(cursor.fetchall())
            if latest_ids:
                records = Verifactu.browse(list(latest_ids.values()))
                by_id = {record.id: record for record in records}
                for invoice_id, record_id in latest_ids.items():
                    latest_verifactu[invoice_id] = by_id[record_id]

        period_cache = {}
        today = None
        for invoice in invoices:
            is_verifactu = False
            if invoice.type == 'out':
                if invoice.journal and invoice.journal.exclude_verifactu:
                    is_verifactu = False
                elif invoice.move and invoice.move.period:
                    is_verifactu = bool(
                        invoice.move.period.es_verifactu_send_invoices)
                else:
                    if today is None:
                        today = Date.today()
                    accounting_date = (
                        invoice.accounting_date or invoice.invoice_date
                        or today)
                    key = (
                        invoice.company.id if invoice.company else None,
                        accounting_date,
                        )
                    if key not in period_cache:
                        period_cache[key] = False
                        if invoice.company:
                            with Transaction().set_context(
                                    company=invoice.company.id):
                                try:
                                    period = Period.find(
                                        invoice.company,
                                        date=accounting_date,
                                        test_state=False)
                                except PeriodNotFoundError:
                                    pass
                                else:
                                    period_cache[key] = bool(
                                        period.es_verifactu_send_invoices)
                    is_verifactu = period_cache[key]

            record = latest_verifactu.get(invoice.id)

            if 'is_verifactu' in result:
                result['is_verifactu'][invoice.id] = is_verifactu
            if 'verifactu_state' in result:
                result['verifactu_state'][invoice.id] = (
                    record.state if record else None)
            if 'verifactu_to_send' in result:
                to_send = False
                if is_verifactu and invoice.number:
                    state = record.state if record else None
                    if state in {None, 'Incorrecto'}:
                        error_message = (
                            (record.error_message or '').lower()
                            if record else '')
                        to_send = 'duplicad' not in error_message
                result['verifactu_to_send'][invoice.id] = to_send
        return result

    def get_is_verifactu(self, name):
        return self.__class__.get_verifactu_fields([self], [name])[name][self.id]

    @classmethod
    def search_is_verifactu(cls, name, clause):
        _, operator, value = clause
        if operator not in ('=', '!='):
            return []
        domain = [
            ('move.period.es_verifactu_send_invoices', '=', True),
            ('journal.exclude_verifactu', '!=', True),
            ('type', '=', 'out'),
            ]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = ['OR',
                ('move.period.es_verifactu_send_invoices', '!=', True),
                ('journal.exclude_verifactu', '=', True),
                ('type', '!=', 'out')]
        return domain

    def get_verifactu_to_send(self, name):
        return self.__class__.get_verifactu_fields([self], [name])[name][self.id]

    @classmethod
    def search_verifactu_to_send(cls, name, clause):
        _, operator, value = clause
        if operator not in ('=', '!='):
            return []
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = ['OR',
                ('verifactu_state', 'in', ('Correcto', 'AceptadoConErrores')),
                ('verifactu_state', '=', None),
                ]
        else:
            domain = [('verifactu_state', '=', 'Incorrecto')]
        return domain

    def get_verifactu_state(self, name):
        return self.__class__.get_verifactu_fields([self], [name])[name][self.id]

    @classmethod
    def search_verifactu_state(cls, name, clause):
        pool = Pool()
        Verifactu = pool.get('aeat.verifactu')

        verifactu = Verifactu.__table__()
        _, operator, value = clause
        invoice = cls.__table__()

        # Assign a sorted value: 'Correcto' always wins
        ordered_state = Case(
            (verifactu.state == 'Correcto', '1-Correcto'),
            (verifactu.state == 'AceptadoConErrores', '2-AceptadoConErrores'),
            (verifactu.state == 'Incorrecto', '3-Incorrecto'),
            else_=Null)

        subquery = verifactu.select(verifactu.invoice,
            Max(ordered_state).as_('best_raw'), group_by=verifactu.invoice)

        # Extract only the state name (after the dash)
        best_state = Substring(subquery.best_raw, 3)

        # Si no hi ha cap registre → best_state és NULL → 'Incorrecto'
        final_state = Coalesce(best_state, Literal('Incorrecto'))

        # Construïm la condició segons l'operador
        # Tryton normalitza els operadors, però gestionem els més habituals
        if operator in ('=', '!='):
            if value is None:
                condition = (final_state == None) if operator == '=' else (final_state != None)
            else:
                condition = (final_state == value) if operator == '=' else (final_state != value)
        elif operator in ('in', 'not in'):
            if not value:
                condition = Literal(False) if operator == 'in' else Literal(True)
            else:
                condition = final_state.in_(value)
                if operator == 'not in':
                    condition = ~condition
        else:
            condition = (final_state == value)

        query = invoice.join(subquery, 'LEFT', subquery.invoice == invoice.id
            ).select(invoice.id, where=condition)

        return [('id', 'in', query)]

    def _credit(self, **values):
        credit = super()._credit(**values)
        # TODO: Verifactu operatioin key should be a selection in the credit
        # wizard with R1 as default
        credit.verifactu_operation_key = self.verifactu_operation_key
        credit.verifactu_operation_key = 'R1'
        return credit


    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('verifactu_operation_key')
        default.setdefault('verifactu_records')
        return super().copy(records, default=default)

    def _get_verifactu_operation_key(self):
        return 'R1' if self.untaxed_amount < Decimal(0) else 'F1'

    @classmethod
    def process(cls, invoices):
        pool = Pool()
        Warning = pool.get('res.user.warning')

        super().process(invoices)

        invoices_verifactu = ''
        for invoice in invoices:
            if invoice.state != 'draft' or not invoice.is_verifactu:
                continue
            if invoice.verifactu_state:
                invoices_verifactu += '\n%s: %s' % (
                    invoice.number, invoice.verifactu_state)
        if invoices_verifactu:
            warning_name = 'invoices_verifactu.' + hashlib.md5(
                ''.join(invoices_verifactu).encode('utf-8')).hexdigest()
            if Warning.check(warning_name):
                raise UserWarning(warning_name,
                        gettext('aeat_verifactu.msg_invoices_verifactu',
                        invoices='\n'.join(invoices_verifactu)))

    @classmethod
    def draft(cls, invoices):
        pool = Pool()
        Warning = pool.get('res.user.warning')

        invoices_verifactu = []
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue
            if invoice.verifactu_state:
                invoices_verifactu.append('%s: %s' % (
                    invoice.number, invoice.verifactu_state))
        if invoices_verifactu:
            warning_name = 'invoices_verifactu.' + hashlib.md5(
                ''.join(invoices_verifactu).encode('utf-8')).hexdigest()
            if Warning.check(warning_name):
                raise UserWarning(warning_name,
                        gettext('aeat_verifactu.msg_invoices_verifactu',
                        invoices='\n'.join(invoices_verifactu)))

        super().draft(invoices)

    def simplified_serial_number(self, type='first'):
        pool = Pool()
        try:
            SaleLine = pool.get('sale.line')
        except KeyError:
            SaleLine = None

        if self.type == 'out' and SaleLine is not None:
            origin_numbers = [
                line.origin.sale.number
                for line in self.lines
                if isinstance(line.origin, SaleLine)
                ]
            if origin_numbers and type == 'first':
                return min(origin_numbers)
            elif origin_numbers and type == 'last':
                return max(origin_numbers)
            else:
                return ''

    @classmethod
    def _post(cls, invoices):
        to_check = []
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue

            invoice.verifactu_state = 'PendienteEnvio'
            if not invoice.move or invoice.move.state == 'draft':
                to_check.append(invoice)

        # Set verifactu_operation_key for all cases in which we can
        # know it automatically which basically only does not include
        # credit notes for non-simplified invoices
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue
            if invoice.simplified:
                first_invoice = invoice.simplified_serial_number('first')
                last_invoice = invoice.simplified_serial_number('last')
                if invoice.total_amount < 0:
                    invoice.verifactu_operation_key = 'R5'
                elif ((not first_invoice and not last_invoice)
                        or first_invoice == last_invoice):
                    invoice.verifactu_operation_key = 'F2'
                else:
                    invoice.verifactu_operation_key = 'F3'
            else:
                if invoice.total_amount >= 0:
                    invoice.verifactu_operation_key = 'F1'

            if not invoice.move or invoice.move.state == 'draft':
                to_check.append(invoice)


        for invoice in to_check:
            for tax in invoice.taxes:
                if (tax.tax.verifactu_subjected_key in ('S2', 'S3')
                        and invoice.verifactu_operation_key not in (
                            'F1', 'R1', 'R2', 'R3', 'R4')):
                    raise UserError(
                        gettext('aeat_verifactu.msg_verifactu_operation_key_wrong',
                            invoice=invoice))

            if not invoice.verifactu_records:
                invoice.verifactu_state = 'PendienteEnvio'
            else:
                for x in invoice.verifactu_records:
                    if x.state == 'Correcto':
                        invoice.verifactu_state = 'Correcto'
                        break
                else:
                    invoice.verifactu_state = 'PendienteEnvioSubsanacion'

        super()._post(invoices)

        if any(x.is_verifactu for x in invoices):
            cls.__queue__.send_verifactu(invoices)

    @staticmethod
    def verifactu_service(crt, pkey):
        if PRODUCTION_ENV:
            wsdl = WSDL_PROD
            port_name = 'SistemaVerifactu'
        else:
            wsdl = WSDL_TEST
            port_name = 'SistemaVerifactuPruebas'

        wsdl += 'SistemaFacturacion.wsdl'
        session = Session()
        session.cert = (crt, pkey)
        transport = Transport(session=session)
        settings = Settings(forbid_entities=False)
        plugins = [HistoryPlugin()]
        if not PRODUCTION_ENV:
            plugins.append(tools.LoggingPlugin())
        for retry in range(3):
            try:
                client = Client(wsdl=wsdl, transport=transport, plugins=plugins, settings=settings)
                break
            except Exception as e:
                if retry < 2:
                    time.sleep(2 ** retry)
                    continue
                raise UserError(str(e))
        return client.bind('sfVerifactu', port_name)

    @classmethod
    def build_verifactu_records(cls, invoices, last_line=None):
        body = []
        for invoice in invoices:
            record = invoice.verifactu_build_invoice(
                last_line=last_line)
            body.append({'RegistroAlta': record})
            last_line = SimpleNamespace(
                invoice=invoice, fingerprint=record['Huella'])
        return body

    @classmethod
    def verifactu_submit_records(cls, service, headers, records):
        responses = []
        for batch in grouped_slice(records, 1):
            batch = list(batch)
            responses += service.RegFactuSistemaFacturacion(headers, batch).RespuestaLinea
        return responses

    @classmethod
    def verifactu_query(cls, service, year=None, period=None,
            clave_paginacion=None):
        pool = Pool()
        Company = pool.get('company.company')

        company = Company(Transaction().context.get('company'))
        headers = get_headers(company)
        filter_ = {
            'PeriodoImputacion': {
                'Ejercicio': year,
                'Periodo': tools.format_period(period),
                },
            'SistemaInformatico': get_sistema_informatico(),
            }
        if clave_paginacion:
            filter_['ClavePaginacion'] = clave_paginacion
        return service.ConsultaFactuSistemaFacturacion(headers, filter_)

    @classmethod
    def get_batch_start_verifactu_info(cls, service, company):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        year = today.year
        period = today.month
        attempts = 24
        while attempts > 0:
            # Walk the remote period pages until we find the latest submitted
            # VeriFactu record that can anchor the current local batch.
            pagination = 'S'
            clave_paginacion = None
            while pagination == 'S':
                response = cls.verifactu_query(service,
                    year=year, period=period,
                    clave_paginacion=clave_paginacion)
                records = (
                    response.RegistroRespuestaConsultaFactuSistemaFacturacion
                    or [])
                if records:
                    # Recreate only the minimum invoice data needed to build
                    # the local chaining block for the first invoice.
                    record = records[0]
                    previous_invoice = SimpleNamespace(
                        company=company,
                        number=record['IDFactura']['NumSerieFactura'],
                        invoice_date=datetime.datetime.strptime(
                            record['IDFactura']['FechaExpedicionFactura'],
                            '%d-%m-%Y').date())
                    return SimpleNamespace(
                        invoice=previous_invoice,
                        fingerprint=record['DatosRegistroFacturacion']['Huella'])
                pagination = response.IndicadorPaginacion
                if pagination == 'S':
                    clave_paginacion = response.ClavePaginacion
            # No remote records in this period; keep looking backwards.
            period -= 1
            if period == 0:
                period = 12
                year -= 1
            attempts -= 1

    @classmethod
    def send_verifactu(cls, invoices=None):
        # 'invoices' parameter is not used, because all pending invoices are
        # sent but we need it to be compatible with the queue system
        pool = Pool()
        Verifactu = pool.get('aeat.verifactu')
        VerifactuConfig = pool.get('account.configuration.default_verifactu')
        Company = pool.get('company.company')

        company = Company(Transaction().context.get('company'))
        configs = VerifactuConfig.search([
                ('company', '=', company),
                ], limit=1)
        if not configs:
            return
        VerifactuConfig.lock(configs)

        config, = configs
        if not config.aeat_certificate_verifactu:
            return

        invoices = cls.search([
                ('company', '=', company),
                ('move.period.es_verifactu_send_invoices', '=', True),
                ('journal.exclude_verifactu', '!=', True),
                ('type', '=', 'out'),
                ('verifactu_to_send', '=', True),
                ], order=[('sequence', 'ASC'), ('number_digit', 'ASC'),
                    ('invoice_date', 'ASC'), ('id', 'ASC')])
        if not invoices:
            return
        certificate = cls._get_verifactu_certificate()
        with certificate.tmp_ssl_credentials() as (crt, key):
            service = cls.verifactu_service(crt, key)
            last_line = cls.get_batch_start_verifactu_info(service, company)
            records = cls.build_verifactu_records(
                invoices, last_line=last_line)
            responses = cls.verifactu_submit_records(
                service, get_headers(company), records)
            lines_to_save = []
            for invoice, record, response in zip(invoices, records, responses):
                state = response['EstadoRegistro']
                new_line = Verifactu()
                new_line.invoice = invoice
                new_line.company = company
                new_line.state = state
                new_line.fingerprint = record['RegistroAlta']['Huella']
                new_line.error_message = (
                    response['DescripcionErrorRegistro']
                    if 'DescripcionErrorRegistro' in response
                    else None)
                lines_to_save.append(new_line)
            Verifactu.save(lines_to_save)

    def verifactu_build_invoice(self, last_line=None):

        def verifactu_taxes():
            return [invoice_tax for invoice_tax in self.taxes if
                not invoice_tax.tax.tax_kind == 'surcharge']

        def _build_encadenamiento(previous_line):
            if not previous_line:
                return {
                    'PrimerRegistro': 'S',
                    }
            previous_invoice = previous_line.invoice
            return {
                'RegistroAnterior': {
                    'IDEmisorFactura': previous_invoice.company.party.verifactu_vat_code,
                    'NumSerieFactura': previous_invoice.number,
                    'FechaExpedicionFactura': previous_invoice.invoice_date.strftime(
                        '%d-%m-%Y'),
                    'Huella': previous_line.fingerprint,
                    }}

        def _build_desglose():
            desgloses = []
            for tax in verifactu_taxes():
                desglose = {}
                desglose['ClaveRegimen'] = tax.tax.verifactu_issued_key
                if tax.tax.verifactu_subjected_key is not None:
                    desglose['CalificacionOperacion']= tax.tax.verifactu_subjected_key
                    desglose['TipoImpositivo'] = tools._rate_to_percent(tax.tax.rate)
                    desglose['CuotaRepercutida'] = tax.company_amount
                else:
                    desglose['OperacionExenta'] = tax.tax.verifactu_exemption_cause
                desglose['BaseImponibleOimporteNoSujeto'] = tax.company_base
                if tax.tax.recargo_equivalencia_related_tax:
                    for tax2 in self.taxes:
                        if (tax2.tax.tax_kind == 'surcharge' and
                                tax.tax.recargo_equivalencia_related_tax ==
                                tax2.tax and tax2.base ==
                                tax2.base.copy_sign(tax.base)):
                            desglose['TipoRecargoEquivalencia'] = tools._rate_to_percent(
                                tax2.tax.rate)
                            desglose['CuotaRecargoEquivalencia'] = tax2.company_amount
                            desglose['ClaveRegimen'] = 18 # Recargo de equivalencia
                            break
                desgloses.append(desglose)
            return desgloses

        def _build_counterpart():
            ret = {
                'NombreRazon': tools.unaccent(self.party.name),
                }

            vat = ''
            vat_type = None
            if not self.simplified:
                identifier = self.party_tax_identifier
                if identifier:
                    vat = identifier.es_code()
                    vat_type = identifier.es_vat_type()
                    for tax in self.taxes:
                        if (tax.tax.verifactu_exemption_cause == 'E5' and
                                vat_type != '02'):
                            raise UserError(gettext(
                                    'aeat_verifactu.msg_wrong_identifier_type',
                                    invoice=self.number,
                                    party=self.party.rec_name))
            if vat_type and vat_type in {'02', '03', '04', '05', '06', '07'}:
                ret['IDOtro'] = {
                    'IDType': vat_type,
                    'CodigoPais': identifier.es_country(),
                    'ID': vat,
                    }
            else:
                ret['NIF'] = vat
            return ret

        def tax_equivalence_surcharge_amount(invoice_tax):
            surcharge_tax = None
            for invoicetax in invoice_tax.invoice.taxes:
                if (invoicetax.tax.tax_kind == 'surcharge' and
                        invoice_tax.tax.recargo_equivalencia_related_tax ==
                        invoicetax.tax and invoicetax.base ==
                        invoicetax.base.copy_sign(invoice_tax.base)):
                    surcharge_tax = invoicetax
                    break
            if surcharge_tax:
                return surcharge_tax.company_amount

        def get_invoice_total():
            taxes = [invoice_tax for invoice_tax in self.taxes if
                not invoice_tax.tax.tax_kind == 'surcharge']
            taxes_base = 0
            taxes_amount = 0
            taxes_surcharge = 0
            taxes_used = {}
            for tax in taxes:
                base = tax.company_base
                taxes_amount += tax.company_amount
                taxes_surcharge += tax_equivalence_surcharge_amount(tax) or 0
                parent = tax.tax.parent if tax.tax.parent else tax.tax
                if (parent.id in list(taxes_used.keys()) and
                        base == taxes_used[parent.id]):
                    continue
                taxes_base += base
                taxes_used[parent.id] = base
            return (taxes_amount + taxes_base + taxes_surcharge)


        tz = pytz.timezone('Europe/Madrid')
        dt_now = datetime.datetime.now(tz).replace(microsecond=0)
        formatted_now = dt_now.isoformat()
        previous_fingerprint = last_line.fingerprint if last_line else None

        # TODO: Review CuotaTotal as it is a string. How many digits are we using?
        # TODO: The same for ImporteTotal
        fingerprint_string = (
            f'IDEmisorFactura={self.company.party.verifactu_vat_code}&'
            f'NumSerieFactura={self.number}&'
            f'FechaExpedicionFactura={self.invoice_date.strftime("%d-%m-%Y")}&'
            f'TipoFactura={self.verifactu_operation_key}&'
            f'CuotaTotal={sum(tax.company_amount for tax in verifactu_taxes())}&'
            f'ImporteTotal={get_invoice_total()}&'
            f'Huella={previous_fingerprint or ""}&'
            f'FechaHoraHusoGenRegistro={formatted_now}')
        fingerprint_hash = hashlib.sha256(fingerprint_string.encode('utf-8'))
        fingerprint_hash = fingerprint_hash.hexdigest().upper()

        description = tools.unaccent(self.description or '')
        if not description:
            description = self.number

        ret = {
            'IDVersion': '1.0',
            'IDFactura': {
                'IDEmisorFactura': self.company.party.verifactu_vat_code,
                'NumSerieFactura': self.number,
                'FechaExpedicionFactura': self.invoice_date.strftime('%d-%m-%Y'),
                },
            'NombreRazonEmisor': tools.unaccent(self.company.party.name),
            'TipoFactura': self.verifactu_operation_key,
            'DescripcionOperacion': description,
            'Desglose': {
                'DetalleDesglose': _build_desglose(),
                },
            'CuotaTotal': sum(tax.company_amount for tax in verifactu_taxes()),
            'ImporteTotal': get_invoice_total(),
            'Encadenamiento': _build_encadenamiento(last_line),
            'SistemaInformatico': get_sistema_informatico(),
            'FechaHoraHusoGenRegistro':  formatted_now,
            'TipoHuella': '01',
            'Huella': fingerprint_hash,
            }

        # TODO
        if (self.verifactu_records
                and self.verifactu_state == 'PendienteEnvioSubsanacion'):

            ret['Subsanacion'] = 'S'
            ret['RechazoPrevio'] = 'S'

        if ret['TipoFactura'] not in {'F2', 'R5'}:
            ret['Destinatarios'] = {
                'IDDestinatario': _build_counterpart()
                }

        if ret['TipoFactura'] in {'R1', 'R2', 'R3', 'R4', 'R5'}:
            ret['TipoRectificativa'] = 'I'
        return ret

    @classmethod
    def _get_verifactu_certificate(self):
        Configuration = Pool().get('account.configuration')
        config = Configuration(1)

        certificate = config.aeat_certificate_verifactu
        if not certificate:
            raise UserError(gettext('aeat_verifactu.msg_missing_certificate'))
        return certificate

    def get_aeat_qr_url(self, name):
        res = super().get_aeat_qr_url(name)
        if (not self.is_verifactu or self.state not in {'posted', 'paid'}
                or not self.number or not self.invoice_date):
            return res

        if PRODUCTION_ENV:
            url = PRODUCTION_QR_URL
        else:
            url = TEST_QR_URL

        nif = self.company.party.verifactu_vat_code
        numserie = self.number
        fecha = self.invoice_date.strftime("%d-%m-%Y")
        importe = self.total_amount

        params = {
            "nif": nif,
            "numserie": numserie,
            "fecha": fecha,
            "importe": importe,
            }
        query = urlencode(params)
        qr_url = f"{url}?{query}"
        return qr_url
