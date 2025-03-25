# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from logging import getLogger
from decimal import Decimal
from datetime import datetime, timedelta

from zeep import helpers
import json
from collections import namedtuple
from ast import literal_eval

from trytond.model import ModelSQL, ModelView, fields, Workflow
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.pyson import Eval, Bool, PYSONEncoder
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.config import config
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.tools import grouped_slice
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from . import tools
from . import service


_logger = getLogger(__name__)
_ZERO = Decimal(0)

# AEAT verifactu test
VERIFACTU_TEST = config.getboolean('aeat', 'verifactu_test', default=True)
MAX_VERIFACTU_LINES = config.getint('aeat', 'verifactu_lines', default=300)


def _decimal(x):
    return Decimal(x) if x is not None else None


def _date(x):
    return datetime.strptime(x, "%d-%m-%Y").date()


def _datetime(x):
    return datetime.strptime(x, "%d-%m-%Y %H:%M:%S")


COMMUNICATION_TYPE = [   # L0
    (None, ''),
    ('A0', 'Registration of invoices/records'),
    ('A1', 'Amendment of invoices/records (registration errors)'),
    # ('A4', 'Amendment of Invoice for Travellers'), # Not supported
    # ('A5', 'Travellers registration'), # Not supported
    # ('A6', 'Amendment of travellers tax devolutions'), # Not supported
    ('C0', 'Query Invoices'),  # Not in L0
    ('D0', 'Delete Invoices'),  # Not In L0
    ]

BOOK_KEY = [
    (None, ''),
    ('E', 'Issued Invoices'),
    ('I', 'Investment Goods'),
    ('R', 'Received Invoices'),
    ('U', 'Particular Intracommunity Operations'),
    ]

# TipoFactura
OPERATION_KEY = [    # L2_EMI - L2_RECI
    (None, ''),
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

# IDType
PARTY_IDENTIFIER_TYPE = [
    (None, 'VAT (for National operators)'),
    ('02', 'VAT (only for intracommunity operators)'),
    ('03', 'Passport'),
    ('04', 'Official identification document issued by the country '
        'or region of residence'),
    ('05', 'Residence certificate'),
    ('06', 'Other supporting document'),
    ('07', 'Not registered (only for Spanish VAT not registered)'),
    # Extra register add for the control of Simplified Invocies, but not in the
    #   verifactu list
    ('SI', 'Simplified Invoice'),
    ]

# Desglose -> DetalleDesglose -> ClaveRegimen
SEND_SPECIAL_REGIME_KEY = [  # L8.A
    (None, ''),
    ('01', 'General tax regime activity'),
    ('02', 'Export'),
    ('03', 'Activities to which the special scheme of used goods, '
        'works of art, antiquities and collectables (135-139 of the VAT Law)'),
    ('04', 'Special scheme for investment gold'),
    ('05', 'Special scheme for travel agencies'),
    ('06', 'Special scheme applicable to groups of entities, VAT (Advanced)'),
    ('07', 'Special cash basis scheme'),
    ('08', 'Activities subject to Canary Islands General Indirect Tax/Tax on '
        'Production, Services and Imports'),
    ('09', 'Invoicing of the provision of travel agency services acting as '
        'intermediaries in the name of and on behalf of other persons '
        '(Additional Provision 4, Royal Decree 1619/2012)'),
    ('10', 'Collections on behalf of third parties of professional fees or '
        'industrial property, copyright or other such rights by partners, '
        'associates or members undertaken by companies, associations, '
        'professional organisations or other entities that, amongst their '
        'functions, undertake collections'),
    ('11', 'Business premises lease activities subject to withholding'),
    ('14', 'Invoice with VAT pending accrual (work certifications with Public '
        'Administration recipients)'),
    ('15', 'Invoice with VAT pending accrual - '
        'operations of successive tract'),
    ('17', 'Operation covered by one of the regimes provided for in Chapter XI of Title IX (OSS and IOSS)'),
    ('18', 'Equivalence surcharge'),
    ('19', 'Operations of activities included in the Special Regime for Agriculture, Livestock and Fisheries (REAGYP)'),
    ('20', 'Simplified regime'),
    ]

AEAT_COMMUNICATION_STATE = [
    (None, ''),
    ('Correcto', 'Accepted'),
    ('ParcialmenteCorrecto', 'Partially Accepted'),
    ('Incorrecto', 'Rejected')
    ]

AEAT_INVOICE_STATE = [
    (None, ''),
    ('Correcto', 'Accepted '),
    ('Correcta', 'Accepted'),  # You guys are disgusting
    ('AceptadoConErrores', 'Accepted with Errors '),
    ('AceptadaConErrores', 'Accepted with Errors'),  # Shame on AEAT
    ('Anulada', 'Deleted'),
    ('Incorrecto', 'Rejected'),
    ('duplicated_unsubscribed', 'Duplicated / Unsubscribed'),
]

PROPERTY_STATE = [  # L6
    ('0', ''),
    ('1', '1. Property with a land register reference located in any part '
        'of Spain, with the exception of the Basque Country and Navarre'),
    ('2', '2. Property located in the Autonomous Community of the Basque '
        'Country or the Chartered Community of Navarre.'),
    ('3', '3. Property in any of the foregoing locations '
        'with no land register reference'),
    ('4', '4. Property located abroad'),
    ]

# L9 - Iva Subjected
IVA_SUBJECTED = [
    (None, ''),
    ('S1', 'Subject - Not exempt. Non VAT reverse charge'),
    ('S2', 'Subject - Not exempt. VAT reverse charge'),
    ('N1', 'Exempt on acconunt of Articles 7, 14, others'),
    ('N2', 'Exempt by location rules'),
    ]

# L10 - Exemption cause
EXEMPTION_CAUSE = [
    (None, ''),
    ('E1', 'Exempt on account of Article 20'),
    ('E2', 'Exempt on account of Article 21'),
    ('E3', 'Exempt on account of Article 22'),
    ('E4', 'Exempt on account of Article 23 and Article 24'),
    ('E5', 'Exempt on account of Article 25'),
    ('E6', 'Exempt on other grounds'),
    ('NotSubject', 'Not Subject'),
    ]


class VerifactuReport(Workflow, ModelSQL, ModelView):
    ''' verifactu Report '''
    __name__ = 'aeat.verifactu.report'
    company = fields.Many2One('company.company', 'Company', required=True,
        states={
            'readonly': Eval('state') != 'draft',
        })
    company_vat = fields.Char('VAT', size=9,
        states={
            'required': Eval('state').in_(['confirmed', 'done']),
            'readonly': ~Eval('state').in_(['draft', 'confirmed']),
            })
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        required=True, states={
            'readonly': ((Eval('state') != 'draft')
                | (Eval('lines', [0]) & Eval('fiscalyear'))),
        })
    period = fields.Many2One('account.period', 'Period', required=True,
        domain=[('fiscalyear', '=', Eval('fiscalyear'))],
        states={
            'readonly': ((Eval('state') != 'draft')
                | (Eval('lines', [0]) & Eval('period'))),
        })
    load_date = fields.Date('Load Date',
        domain=['OR', [
                ('load_date', '=', None),
            ], [
                ('load_date', '>=', Eval('load_date_start')),
                ('load_date', '<=', Eval('load_date_end')),
            ]], help='Filter invoices to the date whitin the period.')
    load_date_start = fields.Function(fields.Date('Load Date Start'),
        'on_change_with_load_date_start')
    load_date_end = fields.Function(fields.Date('Load Date End'),
        'on_change_with_load_date_end')
    operation_type = fields.Selection(COMMUNICATION_TYPE, 'Operation Type',
        required=True,
        states={
            'readonly': ((~Eval('state').in_(['draft', 'confirmed']))
                | (Eval('lines', [0]) & Eval('operation_type'))),
        })
    book = fields.Selection(BOOK_KEY, 'Book', required=True,
        states={
            'readonly': ((~Eval('state').in_(['draft', 'confirmed']))
                | (Eval('lines', [0]) & Eval('book'))),
        })
    state = fields.Selection([
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('sending', 'Sending'),
            ('cancelled', 'Cancelled'),
            ('sent', 'Sent'),
        ], 'State', readonly=True)
    communication_state = fields.Selection(AEAT_COMMUNICATION_STATE,
        'Communication State', readonly=True)
    csv = fields.Char('CSV', readonly=True)
    version = fields.Selection([
            ('0.7', '0.7'),
            ('1.0', '1.0'),
            ('1.1', '1.1'),
            ], 'Version', required=True, readonly=True)
    lines = fields.One2Many('aeat.verifactu.report.lines', 'report',
        'Lines', states={
            'readonly': Eval('state') != 'draft',
        })
    # TODO crash GTK client 4.x with widget date in XML view and attribute
    # readonly = True. At the moment, use PYSON to readonly field in XML views.
    send_date = fields.DateTime('Send date',
        states={
            'invisible': Eval('state') != 'sent',
            'readonly': Bool(Eval('state') == 'sent'),
        })
    response = fields.Text('Response', readonly=True)
    aeat_register = fields.Text('Register sended to AEAT Webservice',
        readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'draft': {
                    'invisible': ~Eval('state').in_(['confirmed',
                            'cancelled']),
                    'icon': 'tryton-back',
                    },
                'confirm': {
                    'invisible': ~Eval('state').in_(['draft']),
                    'icon': 'tryton-forward',
                    },
                'send': {
                    'invisible': ~Eval('state').in_(['confirmed']),
                    'icon': 'tryton-ok',
                    },
                'cancel': {
                    'invisible': Eval('state').in_(['cancelled', 'sent']),
                    'icon': 'tryton-cancel',
                    },
                'load_invoices': {
                    'invisible': ~(Eval('state').in_(['draft'])
                        & Eval('operation_type').in_(['A0', 'A1'])),
                    },
                'process_response': {
                    'invisible': ~Eval('state').in_(['sending']),
                    }
                })

        cls._transitions |= set((
                ('draft', 'confirmed'),
                ('draft', 'cancelled'),
                ('confirmed', 'draft'),
                ('confirmed', 'sent'),
                ('confirmed', 'cancelled'),
                ('sending', 'sent'),
                ('cancelled', 'draft'),
                ))

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_fiscalyear():
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        try:
            fiscalyear = FiscalYear.find(
                Transaction().context.get('company'), test_state=False)
        except FiscalYearNotFoundError:
            return None
        return fiscalyear.id

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_version():
        return '1.1'

    @fields.depends('period')
    def on_change_period(self):
        if not self.period:
            self.load_date = None

    @fields.depends('company')
    def on_change_with_company_vat(self):
        if self.company:
            return self.company.party.verifactu_vat_code

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        if self.company:
            return self.company.currency.id

    @fields.depends('period')
    def on_change_with_load_date_start(self, name=None):
        return self.period.start_date if self.period else None

    @fields.depends('period')
    def on_change_with_load_date_end(self, name=None):
        return self.period.end_date if self.period else None

    @classmethod
    def get_allowed_companies(cls):
        company_filter = Transaction().context.get('company_filter')
        companies = Transaction().context.get('companies')
        company = Transaction().context.get('company')

        companies = []
        # context from user
        if company_filter and company_filter == 'one' and company:
            companies = [company]
        # context from cron; context has not companies and not company_filter
        elif not company_filter and company:
            companies = [company]
        return companies

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['communication_state'] = None
        default['csv'] = None
        default['send_date'] = None
        return super().copy(records, default=default)

    @classmethod
    def delete(cls, reports):
        # Cancel before delete
        for report in reports:
            if report.state != 'cancelled':
                raise UserError(gettext('aeat_verifactu.msg_delete_cancel',
                    report=report.rec_name))
        super().delete(reports)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, reports):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('confirmed')
    def confirm(cls, reports):
        for report in reports:
            report.check_invoice_state()
            report.check_duplicate_invoices()

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, reports):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('sent')
    def send(cls, reports):
        pool = Pool()
        Invoice = pool.get('account.invoice')

        for report in reports:
            if report.state != 'confirmed':
                continue
            report.check_invoice_state()
            if report.book == 'E':  # issued invoices
                if report.operation_type in {'A0', 'A1'}:
                    report.submit_issued_invoices()
                elif report.operation_type == 'C0':
                    report.query_issued_invoices()
                elif report.operation_type == 'D0':
                    report.delete_issued_invoices()
                else:
                    raise NotImplementedError
            else:
                raise NotImplementedError

        to_save = []
        for report in reports:
            if report.operation_type == 'C0':
                continue
            for line in report.lines:
                invoice = line.invoice
                if invoice:
                    invoice.verifactu_communication_type = report.operation_type
                    invoice.verifactu_state = line.state

                    to_save.append(invoice)

        Invoice.save(to_save)
        cls.write(reports, {
            'send_date': datetime.now(),
            })
        _logger.debug('Done sending reports to AEAT verifactu')

    @classmethod
    @ModelView.button
    @Workflow.transition('sent')
    def process_response(cls, reports):
        for report in reports:
            if report.response:
                cls._save_response(report.response)
                report.save()

    def check_invoice_state(self):
        for line in self.lines:
            if (line.invoice
                    and (line.invoice.state in ('draft', 'validated')
                        or (line.invoice.state == 'cancelled'
                            and line.invoice.cancel_move == None))):
                raise UserError(gettext(
                    'aeat_verifactu.msg_report_wrong_invoice_state',
                    invoice=line.invoice.rec_name))

    @classmethod
    @ModelView.button
    def load_invoices(cls, reports):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        ReportLine = pool.get('aeat.verifactu.report.lines')
        Configuration = Pool().get('account.configuration')
        Date = pool.get('ir.date')

        config = Configuration(1)
        today = Date.today()
        to_create = []
        for report in reports:
            if not report.load_date:
                load_date = (today - timedelta(
                    days=config.verifactu_default_offset_days
                    if config.verifactu_default_offset_days else 0))
                if (load_date >= report.load_date_start
                        and load_date < report.load_date_end):
                    report.load_date = load_date
                if (today >= report.load_date_start
                    and today < report.load_date_end):
                    report.load_date = today
                else:
                    report.load_date = report.load_date_end
                report.save()
            domain = [
                ('verifactu_book_key', '=', report.book),
                ('move.period', '=', report.period.id),
                ['OR',
                    ('state', 'in', ['posted', 'paid']),
                    [
                        ('state', '=', 'cancelled'),
                        ('cancel_move', '!=', None)
                        ],
                    ],
                ('verifactu_pending_sending', '=', True),
                ['OR', [
                        ('invoice_date', '<=', report.load_date),
                        ('accounting_date', '=', None),
                        ], [
                        ('accounting_date', '<=', report.load_date),
                        ]],]

            if report.book == 'E':
                domain.append(('type', '=', 'out'))
            else:
                domain.append(('type', '=', 'in'))

            if report.operation_type == 'A0':
                domain.append(('verifactu_state', 'in', [None, 'Incorrecto',
                            'Anulada']))

            elif report.operation_type in ('A1', 'A4'):
                domain.append(('verifactu_state', 'in', [
                            'AceptadoConErrores', 'AceptadaConErrores']))

            _logger.debug('Searching invoices for verifactu report: %s', domain)

            for invoice in Invoice.search(domain):
                if not all(x.report != report for x in invoice.verifactu_records):
                    continue
                to_create.append({
                    'report': report,
                    'invoice': invoice,
                    })

        if to_create:
            ReportLine.create(to_create)

    def _get_certificate(self):
        Configuration = Pool().get('account.configuration')
        config = Configuration(1)

        certificate = config.aeat_certificate_verifactu
        if not certificate:
            _logger.info('Missing AEAT Certificate verifactu configuration')
            raise UserError(gettext('aeat_verifactu.msg_missing_certificate'))
        return certificate

    def submit_issued_invoices(self):
        # get certificate from company
        certificate = self._get_certificate()

        if self.state != 'confirmed':
            _logger.info('This report %s has already been sended', self.id)
        else:
            _logger.info('Sending report %s to AEAT verifactu', self.id)
            headers = tools.get_headers(
                name=tools.unaccent(self.company.party.name),
                vat=self.company_vat,
                comm_kind=self.operation_type,
                version=self.version)

            with certificate.tmp_ssl_credentials() as (crt, key):
                srv = service.bind_issued_invoices_service(
                    crt, key, test=VERIFACTU_TEST)
                try:
                    res, request = srv.submit(
                        headers, (x.invoice for x in self.lines))
                    self.aeat_register = request
                except UserError as e:
                    raise UserError(str(e))
                except Exception as e:
                    raise UserError(str(e))
            if not self.response:
                self.state == 'sending'
                self.response = json.dumps(helpers.serialize_object(res), default=str)
                self.save()
                Transaction().commit()
        self._save_response(self.response)

    def delete_issued_invoices(self):
        # get certificate from company
        certificate = self._get_certificate()

        if self.state != 'confirmed':
            _logger.info('This report %s has already been sended', self.id)
        else:
            _logger.info('Deleting report %s from AEAT verifactu', self.id)
            headers = tools.get_headers(
                name=tools.unaccent(self.company.party.name),
                vat=self.company_vat,
                comm_kind=self.operation_type,
                version=self.version)

            with certificate.tmp_ssl_credentials() as (crt, key):
                srv = service.bind_issued_invoices_service(
                    crt, key, test=VERIFACTU_TEST)
                try:
                    res = srv.cancel(
                        headers, [
                            eval(line.verifactu_header) for line in self.lines])
                except Exception as e:
                    raise UserError(str(e))

            if not self.response:
                self.state == 'sending'
                self.response = json.dumps(helpers.serialize_object(res))
                self.save()
                Transaction().commit()
        self._save_response(self.response)

    def query_issued_invoices(self, last_invoice=None):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        VerifactuReportLine = pool.get('aeat.verifactu.report.lines')
        VerifactuReportLineTax = pool.get('aeat.verifactu.report.line.tax')

        # get certificate from company
        certificate = self._get_certificate()

        headers = tools.get_headers(
            name=tools.unaccent(self.company.party.name),
            vat=self.company_vat,
            comm_kind=self.operation_type,
            version=self.version)

        with certificate.tmp_ssl_credentials() as (crt, key):
            srv = service.bind_issued_invoices_service(
                crt, key, test=VERIFACTU_TEST)
            res = srv.query(
                headers,
                year=self.period.start_date.year,
                period=self.period.start_date.month,
                last_invoice=last_invoice)
            print(dir(res))
        registers = res.RegistroRespuestaConsultaFactuSistemaFacturacion

        # Selecte all the invoices in the same period of register asked.
        invoices_list = Invoice.search([
                ('company', '=', self.company),
                ('type', '=', 'out'),
                ('move.period', '=', self.period),
                ])
        invoices_ids = {}
        # If the invoice is a summary of invoices, ensure to set the number as
        # sended to verifactu. Mergin the invoice number with the first simplified
        # serial number.
        for invoice in invoices_list:
            number = invoice.number
            if invoice.verifactu_operation_key == 'F4':
                first_invoice = invoice.simplified_serial_number('first')
                number += first_invoice
            invoices_ids[number] = invoice.id

        pagination = res.IndicadorPaginacion
        last_invoice = registers and registers[-1].IDFactura
        lines_to_create = []
        for reg in registers:
            taxes_to_create = []
            taxes = None
            exemption = ''
            tipo_desglose = reg.DatosFacturaEmitida.TipoDesglose
            if tipo_desglose.DesgloseFactura:
                sujeta = tipo_desglose.DesgloseFactura.Sujeta
                no_sujeta = tipo_desglose.DesgloseFactura.NoSujeta
            else:
                if tipo_desglose.DesgloseTipoOperacion.PrestacionServicios:
                    sujeta = tipo_desglose.DesgloseTipoOperacion.\
                        PrestacionServicios.Sujeta
                    no_sujeta = tipo_desglose.DesgloseTipoOperacion.\
                        PrestacionServicios.NoSujeta
                else:
                    sujeta = tipo_desglose.DesgloseTipoOperacion.Entrega.Sujeta
                    no_sujeta = (
                        tipo_desglose.DesgloseTipoOperacion.Entrega.NoSujeta)

            if sujeta and sujeta.NoExenta:
                for detail in sujeta.NoExenta.DesgloseIVA.DetalleIVA:
                    taxes_to_create.append({
                            'base': _decimal(detail.BaseImponible),
                            'rate': _decimal(detail.TipoImpositivo),
                            'amount': _decimal(detail.CuotaRepercutida),
                            'surcharge_rate': _decimal(
                                detail.TipoRecargoEquivalencia),
                            'surcharge_amount': _decimal(
                                detail.CuotaRecargoEquivalencia),
                            })
                taxes = VerifactuReportLineTax.create(taxes_to_create)
            elif sujeta and sujeta.Exenta:
                exemption = sujeta.Exenta.DetalleExenta[0].CausaExencion
                for exempt in EXEMPTION_CAUSE:
                    if exempt[0] == exemption:
                        exemption = exempt[1]
                        break
            elif no_sujeta:
                # TODO: Control the possible respons
                #   'ImportePorArticulos7_14_Otros'
                #   'ImporteTAIReglasLocalizacion'
                pass

            verifactu_report_line = {
                'report': self.id,
                'invoice': invoices_ids.get(
                    reg.IDFactura.NumSerieFacturaEmisor),
                'state': reg.EstadoFactura.EstadoRegistro,
                'last_modify_date': _datetime(
                    reg.EstadoFactura.TimestampUltimaModificacion),
                'communication_code': reg.EstadoFactura.CodigoErrorRegistro,
                'communication_msg': (reg.EstadoFactura.
                    DescripcionErrorRegistro),
                'issuer_vat_number': (reg.IDFactura.IDEmisorFactura.NIF
                    or reg.IDFactura.IDEmisorFactura.IDOtro.ID),
                'serial_number': reg.IDFactura.NumSerieFacturaEmisor,
                'final_serial_number': (
                    reg.IDFactura.NumSerieFacturaEmisorResumenFin),
                'issue_date': _date(
                    reg.IDFactura.FechaExpedicionFacturaEmisor),
                'invoice_kind': reg.DatosFacturaEmitida.TipoFactura,
                'special_key': (reg.DatosFacturaEmitida.
                    ClaveRegimenEspecialOTrascendencia),
                'total_amount': _decimal(reg.DatosFacturaEmitida.ImporteTotal),
                'taxes': [('add', [t.id for t in taxes])] if taxes else [],
                'exemption_cause': exemption,
                'counterpart_name': (
                    reg.DatosFacturaEmitida.Contraparte.NombreRazon
                    if reg.DatosFacturaEmitida.Contraparte else None),
                'counterpart_id': (
                    (reg.DatosFacturaEmitida.Contraparte.NIF
                        or reg.DatosFacturaEmitida.Contraparte.IDOtro.ID)
                    if reg.DatosFacturaEmitida.Contraparte else None),
                'presenter': reg.DatosPresentacion.NIFPresentador,
                'presentation_date': _datetime(
                    reg.DatosPresentacion.TimestampPresentacion),
                'csv': reg.DatosPresentacion.CSV,
                'balance_state': reg.DatosPresentacion.CSV,
                'aeat_register': str(reg),
                }
            lines_to_create.append(verifactu_report_line)
        VerifactuReportLine.create(lines_to_create)

        if pagination == 'S':
            self.query_issued_invoices(last_invoice=last_invoice)

    def _save_response(self, res):
        if res:
            response = json.loads(res, object_hook=lambda d: namedtuple(
                    'verifactu', d.keys())(*d.values()))
            for (report_line, response_line) in zip(
                    self.lines, response.RespuestaLinea):
                if not report_line.communication_code:
                    report_line.state = response_line.EstadoRegistro
                    report_line.communication_code = (
                        response_line.CodigoErrorRegistro)
                    report_line.communication_msg = (
                        response_line.DescripcionErrorRegistro)
                    report_line.save()
            if not self.communication_state:
                self.communication_state = response.EstadoEnvio
            if not self.csv:
                self.csv = response.CSV
            self.response = ''
            self.save()

    @classmethod
    def get_issued_verifactu_reports(cls):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        VerifactuReportLine = pool.get('aeat.verifactu.report.lines')
        Configuration = pool.get('account.configuration')
        Date = pool.get('ir.date')

        config = Configuration(1)
        today = Date.today()

        companies = cls.get_allowed_companies()
        issued_invoices = {}
        for company in companies:
            issued_invoices[company] = {
                'A0': {},  # 'A0', 'Registration of invoices/records'
                'A1': {},  # 'A1', 'Amendment of invoices/records
                           #       (registration errors)'
                'D0': {},  # 'D0', 'Delete Invoices'
                }

            issued_invs = Invoice.search([
                    ('company', '=', company),
                    ['OR',
                        ('state', 'in', ['posted', 'paid']),
                        [
                            ('state', '=', 'cancelled'),
                            ('cancel_move', '!=', None)
                            ],
                        ],
                    ('verifactu_pending_sending', '=', True),
                    ('verifactu_state', 'in', ('Correcto', 'AceptadoConErrores')),
                    ('verifactu_header', '!=', None),
                    ('type', '=', 'out'),
                    ])

            # search issued invoices [delete]
            delete_issued_invoices = []
            # search issued invoices [modify]
            modify_issued_invoices = []
            for issued_inv in issued_invs:
                if not issued_inv.verifactu_records:
                    continue
                verifactu_record_id = max([s.id for s in issued_inv.verifactu_records])
                verifactu_record = VerifactuReportLine(verifactu_record_id)
                if issued_inv.verifactu_header:
                    if verifactu_record.verifactu_header and (
                            literal_eval(issued_inv.verifactu_header)
                            == literal_eval(verifactu_record.verifactu_header)):
                        modify_issued_invoices.append(issued_inv)
                    else:
                        delete_issued_invoices.append(issued_inv)

            periods = {}
            for invoice in delete_issued_invoices:
                period = invoice.move.period
                if period in periods:
                    periods[period].append(invoice,)
                else:
                    periods[period] = [invoice]
            issued_invoices[company]['D0'] = periods

            periods2 = {}
            for invoice in modify_issued_invoices:
                period = invoice.move.period
                if period in periods2:
                    periods2[period].append(invoice,)
                else:
                    periods2[period] = [invoice]
            issued_invoices[company]['A1'] = periods2

            invoice_date = (today - timedelta(
                    days=config.verifactu_default_offset_days)
                if config.verifactu_default_offset_days else today)
            # search issued invoices [new]
            new_issued_invoices = Invoice.search([
                    ('company', '=', company),
                    ('verifactu_book_key', '=', 'E'),
                    ['OR',
                        ('state', 'in', ['posted', 'paid']),
                        [
                            ('state', '=', 'cancelled'),
                            ('cancel_move', '!=', None)
                            ],
                        ],
                    ('verifactu_state', 'in', (None, 'Incorrecto', 'Anulada')),
                    ('verifactu_pending_sending', '=', True),
                    ('type', '=', 'out'),
                    ('move', '!=', None),
                    ('invoice_date', '<=', invoice_date),
                    ])

            new_issued_invoices += delete_issued_invoices

            periods1 = {}
            for invoice in new_issued_invoices:
                period = invoice.move.period
                if period in periods1:
                    periods1[period].append(invoice,)
                else:
                    periods1[period] = [invoice]
            issued_invoices[company]['A0'] = periods1

        book_type = 'E'  # Issued
        return cls.create_verifactu_book(issued_invoices, book_type)


    @classmethod
    def create_verifactu_book(cls, company_invoices, book):
        pool = Pool()
        VerifactuReport = pool.get('aeat.verifactu.report')
        VerifactuReportLine = pool.get('aeat.verifactu.report.lines')
        Company = pool.get('company.company')
        Configuration = pool.get('account.configuration')
        Date = pool.get('ir.date')

        config = Configuration(1)
        today = Date.today()

        cursor = Transaction().connection.cursor()
        report_line_table = VerifactuReportLine.__table__()

        reports = []
        for company, book_invoices in company_invoices.items():
            company = Company(company)
            company_vat = company.party.verifactu_vat_code
            for operation in ['D0', 'A1', 'A0']:
                values = book_invoices[operation]
                delete = True if operation == 'D0' else False
                for period, invoices in values.items():
                    for invs in grouped_slice(invoices, MAX_VERIFACTU_LINES):
                        report = VerifactuReport()
                        report.company = company
                        report.company_vat = company_vat
                        report.fiscalyear = period.fiscalyear
                        report.period = period
                        report.operation_type = operation
                        report.book = book
                        if (today >= report.load_date_start
                                and today < report.load_date_end):
                            report.load_date = (today -
                                timedelta(days=config.verifactu_default_offset_days
                                    if config.verifactu_default_offset_days else 0))
                        else:
                            report.load_date = report.load_date_end
                        report.save()
                        reports.append(report)

                        values = []
                        for inv in invs:
                            verifactu_header = str(inv.get_verifactu_header(inv, delete))
                            values.append(
                                [report.id, inv.id, verifactu_header, company.id])

                        cursor.execute(*report_line_table.insert(
                                columns=[report_line_table.report,
                                    report_line_table.invoice,
                                    report_line_table.verifactu_header,
                                    report_line_table.company],
                                values=values
                                ))
        return reports

    @classmethod
    def find_reports(cls, book='E'):
        companies = cls.get_allowed_companies()
        return cls.search([
                ('company', 'in', companies),
                ('state', 'in', ('draft', 'confirmed')),
                ('book', '=', book),
                ], count=True)

    @classmethod
    def calculate_verifactu(cls):
        pool = Pool()
        Configuration = pool.get('account.configuration')

        config = Configuration(1)

        if not config.aeat_pending_verifactu:
            return
        print('calculate_verifactu')
        if config.aeat_pending_verifactu:
            print('calculate_verifactu')
            reports = cls.find_reports(book='E')
            print(reports)
            if reports:
                _logger.info('Not calculate pending verifactu report '
                    'because is other reports pending to sending')
                return
            issued_reports = cls.get_issued_verifactu_reports()
            if config.aeat_pending_verifactu_send:
                cls.confirm(issued_reports)
                cls.send(issued_reports)

    def check_duplicate_invoices(self):
        if self.operation_type in ('A0', 'D0'):
            invoices = set()
            for line in self.lines:
                if line.invoice in invoices:
                    raise UserError(gettext(
                        'aeat_verifactu.msg_report_duplicated_invoice',
                        invoice=line.invoice.rec_name,
                        report=self.rec_name))
                invoices.add(line.invoice)


class VerifactuReportLine(ModelSQL, ModelView):
    '''
    AEAT verifactu Issued
    '''
    __name__ = 'aeat.verifactu.report.lines'

    report = fields.Many2One(
        'aeat.verifactu.report', 'Issued Report', ondelete='CASCADE')
    invoice = fields.Many2One('account.invoice', 'Invoice',
        domain=[
            ('type', 'in', Eval('invoice_types')),
            ],
        states={
            'required': Eval('_parent_report', {}).get(
                'operation_type') != 'C0',
        })
    invoice_types = fields.Function(
        fields.MultiSelection('get_invoice_types', "Invoice Types"),
        'on_change_with_invoice_types')
    state = fields.Selection(AEAT_INVOICE_STATE, 'State')
    last_modify_date = fields.DateTime('Last Modification Date', readonly=True)
    communication_code = fields.Integer(
        'Communication Code', readonly=True)
    communication_msg = fields.Char(
        'Communication Message', readonly=True)
    company = fields.Many2One(
        'company.company', 'Company', required=True)
    issuer_vat_number = fields.Char('Issuer VAT Number', readonly=True)
    serial_number = fields.Char('Serial Number', readonly=True)
    final_serial_number = fields.Char('Final Serial Number', readonly=True)
    issue_date = fields.Date('Issued Date', readonly=True)
    invoice_kind = fields.Char('Invoice Kind', readonly=True)
    special_key = fields.Char('Special Key', readonly=True)
    total_amount = fields.Numeric('Total Amount', readonly=True)
    counterpart_name = fields.Char('Counterpart Name', readonly=True)
    counterpart_id = fields.Char('Counterpart ID', readonly=True)
    taxes = fields.One2Many(
        'aeat.verifactu.report.line.tax', 'line', 'Tax Lines', readonly=True)
    presenter = fields.Char('Presenter', readonly=True)
    presentation_date = fields.DateTime('Presentation Date', readonly=True)
    csv = fields.Char('CSV', readonly=True)
    balance_state = fields.Char('Balance State', readonly=True)
    # TODO counterpart balance data
    vat_code = fields.Function(fields.Char('VAT Code'), 'get_vat_code')
    identifier_type = fields.Function(
        fields.Selection(PARTY_IDENTIFIER_TYPE,
        'Identifier Type'), 'get_identifier_type')
    invoice_operation_key = fields.Function(
        fields.Selection(OPERATION_KEY, 'verifactu Operation Key'),
        'get_invoice_operation_key')
    exemption_cause = fields.Char('Exemption Cause', readonly=True)
    aeat_register = fields.Text('Register from AEAT Webservice', readonly=True)
    verifactu_header = fields.Text('Header')
    huella = fields.Text('Huella', readonly=True)

    @classmethod
    def __register__(cls, module_name):
        table = cls.__table_handler__(module_name)

        exist_verifactu_excemption_key = table.column_exist('exemption_key')
        if exist_verifactu_excemption_key:
            table.column_rename('exemption_key', 'exemption_cause')

        super().__register__(module_name)

    def get_invoice_operation_key(self, name):
        return self.invoice.verifactu_operation_key if self.invoice else None

    def get_vat_code(self, name):
        if self.identifier_type and self.identifier_type == 'SI':
            return None
        elif self.invoice and self.invoice.party_tax_identifier:
            return self.invoice.party_tax_identifier.code
        elif self.invoice and self.invoice.party.tax_identifier:
            return self.invoice.party.tax_identifier.code
        else:
            return None

    def get_identifier_type(self, name):
        return self.invoice.party.verifactu_identifier_type if self.invoice else None

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['state'] = None
        default['communication_code'] = None
        default['communication_msg'] = None
        default['issuer_vat_number'] = None
        default['serial_number'] = None
        default['final_serial_number'] = None
        default['issue_date'] = None
        default['invoice_kind'] = None
        default['special_key'] = None
        default['total_amount'] = None
        default['taxes'] = None
        default['counterpart_name'] = None
        default['counterpart_id'] = None
        default['presenter'] = None
        default['presentation_date'] = None
        default['csv'] = None
        default['balance_state'] = None
        return super().copy(records, default=default)

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        VerifactuReport = pool.get('aeat.verifactu.report')

        to_write = []
        vlist = [x.copy() for x in vlist]
        for vals in vlist:
            invoice = (Invoice(id=vals['invoice'])
                if vals.get('invoice') else None)
            report = (VerifactuReport(id=vals['report'])
                if vals.get('report') else None)

            delete = (True if report and report.operation_type == 'D0' else
                False)
            vals['verifactu_header'] = (str(invoice.get_verifactu_header(invoice, delete))
                if invoice else '')
            if vals.get('state', None) == 'Correcto' and invoice:
                to_write.extend(([invoice], {
                        'verifactu_pending_sending': False,
                        }))
        if to_write:
            Invoice.write(*to_write)
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        pool = Pool()
        Invoice = pool.get('account.invoice')

        actions = iter(args)

        to_write = []
        for lines, values in zip(actions, actions):
            invoice_values = {
                'verifactu_pending_sending': False,
                }
            if values.get('state', None) == 'Correcto':
                invoices = [x.invoice for x in lines]
            else:
                invoices = [x.invoice for x in lines
                    if x.state == 'Correcto']
            if invoices:
                to_write.extend((invoices, invoice_values))

            invoice_vals = {
                'verifactu_pending_sending': False,
                'verifactu_state': 'duplicated_unsubscribed',
                }
            if values.get('communication_code', None) in (3000, 3001):
                invoices = [x.invoice for x in lines]
            else:
                invoices = [x.invoice for x in lines
                    if x.communication_code in (3000, 3001)]
            if invoices:
                to_write.extend((invoices, invoice_vals))

        super().write(*args)
        if to_write:
            Invoice.write(*to_write)

    @classmethod
    def delete(cls, lines):
        pool = Pool()
        Invoice = pool.get('account.invoice')

        to_save = []
        for line in lines:
            invoice = line.invoice
            if invoice:
                last_line = cls.search([
                        ('invoice', '=', invoice),
                        ('id', '!=', line.id),
                        ('report.operation_type', '!=', 'C0'),
                        ], order=[('report', 'DESC')], limit=1)
                last_line = last_line[0] if last_line else None
                if last_line:
                    invoice.verifactu_communication_type = (
                        last_line.report.operation_type)
                    invoice.verifactu_state = last_line.state
                    to_save.append(invoice)
                else:
                    invoice.verifactu_communication_type = None
                    invoice.verifactu_state = None
                    to_save.append(invoice)
        if to_save:
            Invoice.save(to_save)
        super().delete(lines)

    @classmethod
    def get_invoice_types(cls):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        return Invoice.fields_get(['type'])['type']['selection']

    @fields.depends('report', '_parent_report.book')
    def on_change_with_invoice_types(self, name=None):
        if self.report and self.report.book == 'E':
            return ['out']
        elif self.report and self.report.book == 'R':
            return ['in']
        return ['in', 'out']


class VerifactuReportLineTax(ModelSQL, ModelView):
    '''
    verifactu Report Line Tax
    '''
    __name__ = 'aeat.verifactu.report.line.tax'

    line = fields.Many2One(
        'aeat.verifactu.report.lines', 'Report Line', ondelete='CASCADE')

    base = fields.Numeric('Base', readonly=True)
    rate = fields.Numeric('Rate', readonly=True)
    amount = fields.Numeric('Amount', readonly=True)
    surcharge_rate = fields.Numeric('Surcharge Rate', readonly=True)
    surcharge_amount = fields.Numeric('Surcharge Amount', readonly=True)
    reagyp_rate = fields.Numeric('REAGYP Rate', readonly=True)
    reagyp_amount = fields.Numeric('REAGYP Amount', readonly=True)


class CreateVerifactuIssuedPendingView(ModelView):
    """
    Create AEAT verifactu Issued Pending View
    """
    __name__ = "aeat.verifactu.issued.pending.view"


class CreateVerifactuIssuedPending(Wizard):
    """
    Create AEAT verifactu Issued Pending
    """
    __name__ = "aeat.verifactu.issued.pending"
    start_state = 'view'
    view = StateView('aeat.verifactu.issued.pending.view',
        'aeat_verifactu.aeat_verifactu_issued_pending_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateAction('aeat_verifactu.act_aeat_verifactu_issued_report')

    def do_create_(self, action):
        Report = Pool().get('aeat.verifactu.report')

        reports = Report.find_reports(book='E')
        if reports:
            raise UserError(gettext('aeat_verifactu.reports_exist'))
        reports = Report.get_issued_verifactu_reports()
        reports = [x.id for x in reports] if reports else []
        action['pyson_domain'] = PYSONEncoder().encode([
            ('id', 'in', reports),
            ])
        return action, {}


class Report():
    __name__ = ''

    @fields.depends('exonerated_mod390', 'period')
    def on_change_with_exonerated_mod390(self, name=None):
        if self.period in ('4T', '12') and self.exonerated_mod390 == '0':
            return '1'
        else:
            return self.exonerated_mod390
