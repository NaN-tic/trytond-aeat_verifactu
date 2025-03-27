# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.

from trytond.model import ModelSQL, ModelView, fields
from trytond.pyson import Eval
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.config import config

# AEAT verifactu test
VERIFACTU_TEST = config.getboolean('aeat', 'verifactu_test', default=True)
MAX_VERIFACTU_LINES = config.getint('aeat', 'verifactu_lines', default=300)


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

class VerifactuReportLine(ModelSQL, ModelView):
    '''
    AEAT verifactu Issued
    '''
    __name__ = 'aeat.verifactu.report.lines'

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

        to_write = []
        vlist = [x.copy() for x in vlist]
        for vals in vlist:
            invoice = (Invoice(id=vals['invoice'])
                if vals.get('invoice') else None)
            vals['verifactu_header'] = (str(invoice.get_verifactu_header(invoice, False))
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
    def get_invoice_types(cls):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        return Invoice.fields_get(['type'])['type']['selection']

    def on_change_with_invoice_types(self, name=None):
        return ['out']


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
