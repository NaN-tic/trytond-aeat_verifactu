# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pyson import Eval
from trytond.tools import grouped_slice
from trytond.i18n import gettext
from trytond.model import fields, ModelSQL
from trytond.pool import Pool, PoolMeta
from trytond.exceptions import UserError
from trytond.modules.company.model import CompanyValueMixin
from .aeat import SEND_SPECIAL_REGIME_KEY, IVA_SUBJECTED, EXEMPTION_CAUSE


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

