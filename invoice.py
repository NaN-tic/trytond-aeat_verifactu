# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import hashlib
from decimal import Decimal
from trytond.config import config
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError, UserWarning
from trytond.wizard import Wizard, StateView, StateTransition, Button
from .aeat import (
    OPERATION_KEY, COMMUNICATION_TYPE, AEAT_INVOICE_STATE)
from . import tools
from . import aeat
from datetime import datetime
from urllib.parse import urlencode

PRODUCTION_QR_URL = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
TEST_QR_URL = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"

PRODUCTION_ENV = config.getboolean('database', 'production', default=False)


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    verifactu_operation_key = fields.Selection(OPERATION_KEY, 'Verifactu Operation Key')
    verifactu_records = fields.One2Many('aeat.verifactu.report.line', 'invoice',
        "Verifactu Report Lines")
    verifactu_state = fields.Selection(AEAT_INVOICE_STATE,
            'Verifactu State', readonly=True)
    verifactu_communication_type = fields.Selection(
        COMMUNICATION_TYPE, 'Verifactu Communication Type', readonly=True)
    verifactu_pending_sending = fields.Boolean('Verifactu Pending Sending Pending',
            readonly=True)
    verifactu_header = fields.Text('Header')
    verifactu_sent = fields.Function(fields.Boolean('Verifactu Sent'),
            'get_verifactu_sent', searcher='search_verifactu_sent')
    verifactu_errors = fields.Function(fields.Boolean('Verifactu Errors'),
            'get_verifactu_errors', searcher='search_verifactu_errors')
    post_date = fields.Date('Post Date', readonly=True)
    is_verifactu = fields.Boolean('Is Verifactu', states={
            'readonly': Bool(Eval('company', False)),
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        verifactu_fields = {'verifactu_operation_key',
            'verifactu_state', 'verifactu_pending_sending',
            'verifactu_communication_type', 'verifactu_header'}
        cls._check_modify_exclude |= verifactu_fields
        if hasattr(cls, '_intercompany_excluded_fields'):
            cls._intercompany_excluded_fields += verifactu_fields
            cls._intercompany_excluded_fields += ['verifactu_records']

        # not allow modify reference when is supplier or not pending to sending
        readonly = (
            (Eval('state') != 'draft') & (Eval('type') == 'in') ) | (
            (Eval('state') != 'draft') & ~Bool(Eval('verifactu_pending_sending'))
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
    def get_verifactu_sent(cls, invoices, name):
        res = {}
        for invoice in invoices:
            if invoice.verifactu_records:
                res[invoice.id] = True
            else:
                res[invoice.id] = False
        return res

    @classmethod
    def search_verifactu_sent(cls, name, clause):
        _, operator, value = clause
        if operator not in ('=', '!='):
            return []
        domain = [('verifactu_records', '!=', None)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = [('verifactu_records', '=', None)]
        return domain

    @classmethod
    def get_verifactu_errors(cls, invoices, name):
        for invoice in invoices:
            if invoice.verifactu_records:
                last_record = invoice.verifactu_records[0]
                if last_record.state != 'Correcto':
                    return True

    @classmethod
    def search_verifactu_errors(cls, name, clause):
        _, operator, value = clause
        if operator not in ('=', '!='):
            return []
        domain = [('verifactu_records', '!=', None)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = [('verifactu_records', '=', None)]
        return domain

    @staticmethod
    def default_verifactu_pending_sending():
        return False

    @staticmethod
    def default_is_verifactu():
        return False

    def _credit(self, **values):
        credit = super()._credit(**values)
        # TODO: Verifactu operatioin key should be a selection in the credit
        # wizard with R1 as default
        credit.verifactu_operation_key = self.verifactu_operation_key
        credit.verifactu_operation_key = 'R1'
        return credit

    @fields.depends('company', 'type')
    def on_change_with_is_verifactu(self):
        Configuration = Pool().get('account.configuration')
        if type == 'out':
            config = Configuration(1)
            return config.aeat_certificate_verifactu

    def _set_verifactu_keys(self):
        tax = None
        for t in self.taxes:
            if t.tax and t.tax.verifactu_tax_used:
                tax = t.tax
                break
        if not tax:
            return
        self.verifactu_operation_key = tax.verifactu_operation_key

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Configuration = pool.get('account.configuration')

        vlist = [x.copy() for x in vlist]

        companies = set([i.get('company', -1) for i in vlist])
        is_verifactu = {}
        for company_id in companies:
            with Transaction().set_context(company=company_id):
                is_verifactu[company_id] = Configuration(1).aeat_certificate_verifactu
        for vals in vlist:
            if vals.get('is_verifactu'):
                continue
            company_id = vals.get('company', -1)
            vals['is_verifactu'] = is_verifactu.get(company_id, False)
        return super().create(vlist)

    @property
    def verifactu_keys_filled(self):
        if self.verifactu_operation_key and self.type == 'out':
            return True
        return False

    @fields.depends('verifactu_operation_key', methods=['_set_verifactu_keys'])
    def _on_change_lines_taxes(self):
        super()._on_change_lines_taxes()
        if not self.verifactu_operation_key:
            self._set_verifactu_keys()

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('verifactu_records')
        default.setdefault('verifactu_state')
        default.setdefault('verifactu_communication_type')
        default.setdefault('verifactu_pending_sending')
        default.setdefault('verifactu_header')
        return super().copy(records, default=default)

    def _get_verifactu_operation_key(self):
        return 'R1' if self.untaxed_amount < Decimal(0) else 'F1'

    @classmethod
    def reset_verifactu_keys(cls, invoices):
        for invoice in invoices:
            if invoice.state == 'cancelled':
                continue
            invoice.verifactu_operation_key = None
            invoice._set_verifactu_keys()
            if not invoice.verifactu_operation_key:
                invoice.verifactu_operation_key = invoice._get_verifactu_operation_key()
            if invoice.state in ('posted', 'paid'):
                invoice.verifactu_pending_sending = True

        cls.save(invoices)

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

        super().draft(invoices)

        invoices_verifactu = []
        to_write = []
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue
            to_write.extend(([invoice], {'verifactu_state': None}))
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
        if to_write:
            cls.write(*to_write)

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
    def post(cls, invoices):
        invoices2checkverifactu = []
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue
            if not invoice.move or invoice.move.state == 'draft':
                invoices2checkverifactu.append(invoice)

        super().post(invoices)

        for invoice in invoices2checkverifactu:
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
                    if x.state in ('Correcto', 'Correcta'):
                        invoice.verifactu_state = 'Correcta'
                        break
                else:
                    invoice.verifactu_state = 'PendienteEnvioSubsanacion'

        # Force verifactu_operation_key for Simplified invoices
        for invoice in invoices:
            if not invoice.simplified:
                continue
            first_invoice = invoice.simplified_serial_number('first')
            last_invoice = invoice.simplified_serial_number('last')
            if invoice.total_amount < 0:
                invoice.verifactu_operation_key = 'R5'
            elif ((not first_invoice and not last_invoice)
                    or first_invoice == last_invoice):
                invoice.verifactu_operation_key = 'F2'
            else:
                invoice.verifactu_operation_key = 'F3'

        cls.save(invoices)

        cls.send_verifactu()
        # TODO:
        #cls.__queue__.send_verifactu(invoices)

    @classmethod
    def send_verifactu(cls, invoices=None):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        VerifactuLine = pool.get('aeat.verifactu.report.line')
        VerifactuConfig = pool.get('account.configuration.default_verifactu')

        # invoices parameter is not used, because all pending invoices are sent
        # but we need it to be compatible with the queue system

        configs = VerifactuConfig.search([
                ('company', '=', Transaction().context.get('company')),
                ], limit=1)
        VerifactuConfig.lock(configs)

        verifactu_start_date = Configuration(1).verifactu_start_date
        if not verifactu_start_date:
            return
        invoices = cls.search([
                ('invoice_date', '>=', verifactu_start_date),
                ('type', '=', 'out'),
                ('is_verifactu', '=', True),
                ['OR',
                    ('verifactu_state', '=', 'Incorrecto'),
                    ('verifactu_state', '=', 'PendienteEnvio')],
                ], order=[('invoice_date', 'ASC')])
        huella, last_line = cls.synchro_query(invoices)
        if not invoices:
            return
        invoice = invoices[0]
        headers = tools.get_headers(
            name=tools.unaccent(invoice.company.party.name),
            vat=invoice.company.party.verifactu_vat_code,
            version='1.0')
        certificate = invoice._get_certificate()

        with certificate.tmp_ssl_credentials() as (crt, key):
            srv = aeat.VerifactuService.bind(crt, key)
            response, body = srv.submit(
                headers,
                invoices,
                last_huella=huella,
                last_line=last_line)
            lines_to_save = []
            invoices_to_save = []
            for x in response.RespuestaLinea:
                state = x['EstadoRegistro']
                if state in ('Correcto', 'Correcta', 'AceptadaConErrores',
                        'AceptadoConErrores'):
                    continue

                invoice = cls.search([
                        ('number', '=', x['IDFactura']['NumSerieFactura']),
                        ])[0]
                invoice.verifactu_state = state
                invoices_to_save.append(invoice)
                new_line = VerifactuLine()
                new_line.invoice = invoice
                new_line.state = state
                new_line.error_message = x['DescripcionErrorRegistro']
                lines_to_save.append(new_line)
            VerifactuLine.save(lines_to_save)
            cls.save(invoices_to_save)
        cls.synchro_query(invoices)

    def get_period(year, period, invoices):
        records = []
        if not invoices:
            return
        invoice = invoices[0]
        headers = tools.get_headers(
            name=tools.unaccent(invoice.company.party.name),
            vat=invoice.company.party.verifactu_vat_code,
            version='1.0')
        certificate = invoice._get_certificate()
        pagination = 'S'
        clave_paginacion = None
        while pagination == 'S':
            with certificate.tmp_ssl_credentials() as (crt, key):
                srv = aeat.VerifactuService.bind(crt, key)
                res = srv.query(headers, year=year, period=period, clave_paginacion=clave_paginacion)
                invoices = res.RegistroRespuestaConsultaFactuSistemaFacturacion
                if invoices:
                    records.extend(invoices)
            pagination = res.IndicadorPaginacion
            if pagination == 'S':
                clave_paginacion = res.ClavePaginacion
        return records

    @classmethod
    def synchro_query(cls, invoices):
        pool = Pool()
        VerifactuLine = pool.get('aeat.verifactu.report.line')

        records = []
        today = datetime.today()
        year = today.year
        period = today.month
        attempts = 24
        last_line = None
        while attempts > 0:
            records = cls.get_period(year, period, invoices)
            if not records:
                return None, None
            huella = None
            for record in records:
                huella = record['DatosRegistroFacturacion']['Huella']
                verifactu_lines = VerifactuLine.search([('huella', '=', huella)])
                if verifactu_lines:
                    attempts = 0
                    last_line = verifactu_lines[0]
                    break
                else:
                    new_line = VerifactuLine()
                    new_line.huella = huella
                    invoices = cls.search([
                            ('number', '=', record['IDFactura']['NumSerieFactura']),
                            ])
                    if not invoices:
                        raise UserError(gettext('aeat_verifactu.msg_invoice_not_found'))
                    invoice = invoices[0]
                    invoice.verifactu_state = record['EstadoRegistro']['EstadoRegistro']
                    new_line.invoice = invoice
                    new_line.state = record['EstadoRegistro']['EstadoRegistro']
                    new_line.save()
                    invoice.save()

            period -= 1
            if period == 0:
                period = 12
                year -= 1
            attempts -= 1
        return huella, last_line

    def _get_certificate(self):
        Configuration = Pool().get('account.configuration')
        config = Configuration(1)

        certificate = config.aeat_certificate_verifactu
        if not certificate:
            raise UserError(gettext('aeat_verifactu.msg_missing_certificate'))
        return certificate

    @classmethod
    def cancel(cls, invoices):
        result = super().cancel(invoices)
        to_write = []
        for invoice in invoices:
            if not invoice.is_verifactu:
                continue
            if not invoice.cancel_move:
                to_write.append(invoice)
        if to_write:
            cls.write(to_write, {
                'verifactu_pending_sending': False,
                })
        return result

    @classmethod
    def get_verifactu_header(cls, invoice, delete):
        if delete:
            rline = [x for x in invoice.verifactu_records if x.state == 'Correcto'
                and x.header is not None]
            if rline:
                return rline[0].header
        if invoice.type == 'out':
            request = aeat.VerifactuRequest(invoice)
            header = request.build_delete_request()
        return header

    def get_aeat_qr_url(self, name):
        if PRODUCTION_ENV:
            url = PRODUCTION_QR_URL
        else:
            url = TEST_QR_URL

        nif = self.company.party.verifactu_vat_code
        numserie = self.number
        fecha = self.invoice_date.strftime("%d-%m-%Y") if self.invoice_date else None
        importe = self.total_amount

        if not all([nif, numserie, fecha, importe]) or not self.is_verifactu:
            return

        params = {
            "nif": nif,
            "numserie": numserie,
            "fecha": fecha,
            "importe": importe,
            }
        query = urlencode(params)
        qr_url = f"{url}?{query}"
        return qr_url


class ResetVerifactuKeysStart(ModelView):
    """
    Reset to default Verifactu Keys Start
    """
    __name__ = "aeat.verifactu.reset.keys.start"


class ResetVerifactuKeysEnd(ModelView):
    """
    Reset to default Verifactu Keys End
    """
    __name__ = "aeat.verifactu.reset.keys.end"


class ResetVerifactuKeys(Wizard):
    """
    Reset to default Verifactu Keys
    """
    __name__ = "aeat.verifactu.reset.keys"

    start = StateView('aeat.verifactu.reset.keys.start',
        'aeat_verifactu.reset_keys_start_view', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Reset', 'reset', 'tryton-ok', default=True),
            ])
    reset = StateTransition()
    done = StateView('aeat.verifactu.reset.keys.end',
        'aeat_verifactu.reset_keys_end_view', [
            Button('Ok', 'end', 'tryton-ok', default=True),
            ])

    def transition_reset(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        Invoice.reset_verifactu_keys(self.records)
        Invoice.simplified_aeat_verifactu_invoices(self.records)
        return 'done'
