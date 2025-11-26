# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pyson import Eval
from trytond.tools import grouped_slice
from trytond.i18n import gettext
from trytond.model import fields, ModelSQL
from trytond.pool import Pool, PoolMeta
from trytond.exceptions import UserError
from trytond.modules.company.model import CompanyValueMixin

# Desglose -> DetalleDesglose -> ClaveRegimen
SEND_SPECIAL_REGIME_KEY = [  # L8A
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


class Configuration(metaclass=PoolMeta):
    __name__ = 'account.configuration'

    aeat_certificate_verifactu = fields.MultiValue(fields.Many2One('certificate',
        'AEAT Verifactu Certificate'))

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'aeat_certificate_verifactu'}:
            return pool.get('account.configuration.default_verifactu')
        return super().multivalue_model(field)


class ConfigurationDefaultVerifactu(ModelSQL, CompanyValueMixin):
    "Account Configuration Default Verifactu Values"
    __name__ = 'account.configuration.default_verifactu'

    aeat_certificate_verifactu = fields.Many2One('certificate',
        'AEAT Verifactu Certificate')


class TemplateTax(metaclass=PoolMeta):
    __name__ = 'account.tax.template'

    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY,
        'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE,
        'Exemption Cause')

    def _get_tax_value(self, tax=None):
        res = super()._get_tax_value(tax)
        for field in ('verifactu_issued_key', 'verifactu_subjected_key',
                'verifactu_exemption_cause'):
            if not tax or getattr(tax, field) != getattr(self, field):
                res[field] = getattr(self, field)
        return res


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY, 'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE, 'Exemption Cause')


class FiscalYear(metaclass=PoolMeta):
    __name__ = 'account.fiscalyear'

    es_verifactu_send_invoices = fields.Function(
        fields.Boolean("Send invoices to Verifactu"),
        'get_es_verifactu_send_invoices',
        setter='set_es_verifactu_send_invoices')

    def get_es_verifactu_send_invoices(self, name):
        result = None
        for period in self.periods:
            if period.type != 'standard':
                continue
            value = period.es_verifactu_send_invoices
            if value is not None:
                if result is None:
                    result = value
                elif result != value:
                    result = None
                    break
        return result

    @classmethod
    def set_es_verifactu_send_invoices(cls, fiscalyears, name, value):
        pool = Pool()
        Period = pool.get('account.period')

        periods = []
        for fiscalyear in fiscalyears:
            periods.extend(
                p for p in fiscalyear.periods if p.type == 'standard')
        Period.write(periods, {name: value})


class RenewFiscalYear(metaclass=PoolMeta):
    __name__ = 'account.fiscalyear.renew'

    def create_fiscalyear(self):
        fiscalyear = super().create_fiscalyear()
        previous_fiscalyear = self.start.previous_fiscalyear
        periods = [
            p for p in previous_fiscalyear.periods if p.type == 'standard']
        if periods:
            last_period = periods[-1]
            fiscalyear.es_verifactu_send_invoices = (
                last_period.es_verifactu_send_invoices)
        return fiscalyear


class Period(metaclass=PoolMeta):
    __name__ = 'account.period'
    es_verifactu_send_invoices = fields.Boolean(
        "Send Invoices to Verifactu", states={
            'invisible': Eval('type') != 'standard',
            },
        help="Check to create Verifactu records for invoices in the period.")

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        to_check = []
        for periods, values in zip(actions, actions):
            if 'es_verifactu_send_invoices' in values:
                for period in periods:
                    if (period.es_verifactu_send_invoices
                            != values['es_verifactu_send_invoices']):
                        to_check.append(period)
        cls.check_es_verifactu_posted_invoices(to_check)
        super().write(*args)

    @classmethod
    def check_es_verifactu_posted_invoices(cls, periods):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        for sub_ids in grouped_slice(list(map(int, periods))):
            invoices = Invoice.search([
                    ('move.period', 'in', sub_ids),
                    ], limit=1)
            if invoices:
                invoice, = invoices
                raise UserError(gettext('aeat_verifactu.msg_posted_invoices',
                        period=invoice.move.period.rec_name))

