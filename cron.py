# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import  PoolMeta


class Cron(metaclass=PoolMeta):
    __name__ = 'ir.cron'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.method.selection.extend([
                ('account.invoice|cron_update_verifactu_invoices',
                    "AEAT Verifactu Invoice Synchronization"),
                ('account.invoice|send_verifactu', "AEAT Verifactu"),
                ])
