import unittest
from decimal import Decimal

from proteus import Model
from trytond.modules.account_invoice.tests.tools import create_payment_term
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from tools import setup


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules(['sale', 'aeat_verifactu'])

        vars = setup()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])

        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'goods'
        template.salable = True
        template.list_price = Decimal('10')
        template.account_category = vars.account_category
        template.save()
        product, = template.products

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create a sale
        Sale = Model.get('sale.sale')
        sale = Sale()
        sale.party = vars.party
        sale.payment_term = payment_term
        sale.invoice_method = 'order'

        line = sale.lines.new()
        line.product = product
        line.quantity = 1

        sale.save()
        sale.click('quote')
        sale.click('confirm')

        self.assertEqual(sale.state, 'processing')

        invoice, = sale.invoices

        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertTrue(invoice.is_verifactu)
        self.assertEqual(invoice.verifactu_operation_key, 'F1')
