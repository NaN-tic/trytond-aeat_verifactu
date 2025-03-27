# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields, ModelSQL
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.transaction import Transaction
from trytond.modules.company.model import CompanyValueMixin
from .aeat import (OPERATION_KEY, SEND_SPECIAL_REGIME_KEY,
    IVA_SUBJECTED, EXEMPTION_CAUSE)


class Configuration(metaclass=PoolMeta):
    __name__ = 'account.configuration'

    aeat_certificate_verifactu = fields.MultiValue(fields.Many2One('certificate',
        'AEAT Certificate Verifactu'))
    aeat_pending_verifactu = fields.MultiValue(fields.Boolean('AEAT Pending Verifactu',
        help='Automatically generate AEAT Pending Verifactu reports by cron'))
    aeat_pending_verifactu_send = fields.MultiValue(fields.Boolean('AEAT Pending Verifactu Send',
        states={
            'invisible': ~Eval('aeat_pending_verifactu', False),
        },
        help='Automatically send AEAT Pending Verifactu reports by cron'))
    #readonly if it is not none
    verifactu_start_date = fields.MultiValue(fields.Date('Verifactu Start Date',
        states={
            'readonly': Bool(Eval('verifactu_start_date', None)),
        },
        help='Start date for Verifactu'))

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'aeat_certificate_verifactu', 'aeat_pending_verifactu',
                'aeat_pending_verifactu_send', 'verifactu_default_offset_days',
                'verifactu_start_date'}:
            return pool.get('account.configuration.default_verifactu')
        return super().multivalue_model(field)

    @classmethod
    def default_aeat_pending_verifactu(cls, **pattern):
        return False

    @classmethod
    def default_aeat_pending_verifactu_send(cls, **pattern):
        return False

    @classmethod
    def default_verifactu_default_offset_days(cls, **pattern):
        return 0

    @classmethod
    def default_verifactu_start_date(cls, **pattern):
        return None


class ConfigurationDefaultVerifactu(ModelSQL, CompanyValueMixin):
    "Account Configuration Default Verifactu Values"
    __name__ = 'account.configuration.default_verifactu'

    aeat_certificate_verifactu = fields.Many2One('certificate',
        'AEAT Certificate Verifactu')
    aeat_pending_verifactu = fields.Boolean('AEAT Pending Verifactu',
        help='Automatically generate AEAT Pending Verifactu reports by cron')
    aeat_pending_verifactu_send = fields.Boolean('AEAT Pending Verifactu Send',
        states={
            'invisible': ~Eval('aeat_pending_verifactu', False),
        },
        help='Automatically send AEAT Pending Verifactu reports by cron')
    verifactu_start_date = fields.Date('Verifactu Start Date',
        help='Start date for Verifactu')


class TemplateTax(metaclass=PoolMeta):
    __name__ = 'account.tax.template'

    verifactu_operation_key = fields.Selection(OPERATION_KEY, 'Verifactu Operation Key')
    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY, 'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE, 'Exemption Cause')
    tax_used = fields.Boolean('Used in Tax')
    invoice_used = fields.Boolean('Used in invoice Total')

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().connection.cursor()
        table = cls.__table_handler__(module_name)
        sql_table = cls.__table__()

        exist_verifactu_excemption_key = table.column_exist('verifactu_excemption_key')
        exist_verifactu_intracomunity_key = table.column_exist('verifactu_intracomunity_key')

        super().__register__(module_name)

        if exist_verifactu_excemption_key:
            # Don't use UPDATE FROM because SQLite nor MySQL support it.
            cursor.execute(*sql_table.update([sql_table.verifactu_exemption_cause],
                    [sql_table.verifactu_excemption_key])),
            table.drop_column('verifactu_excemption_key')

        if exist_verifactu_intracomunity_key:
            table.drop_column('verifactu_intracomunity_key')

    def _get_tax_value(self, tax=None):
        res = super()._get_tax_value(tax)
        for field in ('verifactu_operation_key', 'verifactu_issued_key',
                'verifactu_subjected_key', 'verifactu_exemption_cause', 'tax_used', 'invoice_used'):

            if not tax or getattr(tax, field) != getattr(self, field):
                res[field] = getattr(self, field)

        return res


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    verifactu_operation_key = fields.Selection(OPERATION_KEY, 'Verifactu Operation Key')
    verifactu_issued_key = fields.Selection(SEND_SPECIAL_REGIME_KEY, 'Issued Key')
    verifactu_subjected_key = fields.Selection(IVA_SUBJECTED, 'Subjected Key')
    verifactu_exemption_cause = fields.Selection(EXEMPTION_CAUSE, 'Exemption Cause')
    tax_used = fields.Boolean('Used in Tax')
    invoice_used = fields.Boolean('Used in invoice Total')

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().connection.cursor()
        table = cls.__table_handler__(module_name)
        sql_table = cls.__table__()

        exist_verifactu_excemption_key = table.column_exist('verifactu_excemption_key')
        exist_verifactu_intracomunity_key = table.column_exist('verifactu_intracomunity_key')

        super().__register__(module_name)

        if exist_verifactu_excemption_key:
            # Don't use UPDATE FROM because SQLite nor MySQL support it.
            cursor.execute(*sql_table.update([sql_table.verifactu_exemption_cause],
                    [sql_table.verifactu_excemption_key])),
            table.drop_column('verifactu_excemption_key')

        if exist_verifactu_intracomunity_key:
            table.drop_column('verifactu_intracomunity_key')
