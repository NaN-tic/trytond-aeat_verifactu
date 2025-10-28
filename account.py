# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields, ModelSQL
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.modules.company.model import CompanyValueMixin
from .aeat import (OPERATION_KEY, SEND_SPECIAL_REGIME_KEY,
    IVA_SUBJECTED, EXEMPTION_CAUSE)


class Configuration(metaclass=PoolMeta):
    __name__ = 'account.configuration'

    aeat_certificate_verifactu = fields.MultiValue(fields.Many2One('certificate',
        'AEAT Verifactu Certificate'))
    verifactu_start_date = fields.MultiValue(fields.Date('Verifactu Start Date',
            states={
                'readonly': Bool(Eval('verifactu_start_date', None)),
            }))

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'aeat_certificate_verifactu', 'veerifactu_start_date',
                'verifactu_start_date'}:
            return pool.get('account.configuration.default_verifactu')
        return super().multivalue_model(field)

    @classmethod
    def default_verifactu_start_date(cls, **pattern):
        return None


class ConfigurationDefaultVerifactu(ModelSQL, CompanyValueMixin):
    "Account Configuration Default Verifactu Values"
    __name__ = 'account.configuration.default_verifactu'

    aeat_certificate_verifactu = fields.Many2One('certificate',
        'AEAT Verifactu Certificate')
    verifactu_start_date = fields.Date('Verifactu Start Date')


class TemplateTax(metaclass=PoolMeta):
    __name__ = 'account.tax.template'

    verifactu_operation_key = fields.Selection(OPERATION_KEY,
        'Verifactu Operation Key')
    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY,
        'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE,
        'Exemption Cause')
    verifactu_tax_used = fields.Boolean('Used in Tax')

    @staticmethod
    def default_verifactu_tax_used():
        return True

    def _get_tax_value(self, tax=None):
        res = super()._get_tax_value(tax)
        for field in ('verifactu_operation_key', 'verifactu_issued_key',
                'verifactu_subjected_key', 'verifactu_exemption_cause',
                'verifactu_tax_used'):

            if not tax or getattr(tax, field) != getattr(self, field):
                res[field] = getattr(self, field)

        return res


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    verifactu_operation_key = fields.Selection(OPERATION_KEY, 'Verifactu Operation Key')
    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY, 'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE, 'Exemption Cause')
    verifactu_tax_used = fields.Boolean('Used in Tax')

