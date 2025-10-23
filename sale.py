# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from decimal import Decimal
from trytond.pool import PoolMeta

ZERO = Decimal(0)


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'

    def create_invoice(self):
        invoice = super().create_invoice()
        if not invoice:
            return

        # TODO: Looks to me that those fields should be set in invoice
        # automatically, no need to inherit sale
        # Maybe in update_taxes() method?

        # create_invoice() from sale not add untaxed_amount and taxes fields
        # call on_change_lines to add untaxed_amount and taxes
        invoice.on_change_lines()
        if invoice.on_change_with_is_verifactu():
            if invoice.untaxed_amount < ZERO:
                invoice.verifactu_operation_key = 'R1'
            else:
                invoice.verifactu_operation_key = 'F1'

            tax = invoice.taxes and invoice.taxes[0]
            if not tax:
                return invoice

        return invoice
