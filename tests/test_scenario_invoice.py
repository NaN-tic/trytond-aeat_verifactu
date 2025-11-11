from proteus import Model
from decimal import Decimal
import unittest
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.exceptions import UserError
from tools import setup

class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        # Activate aeat_verifactu module
        activate_modules(['aeat_verifactu'])

        vars = setup()

        # Create party
        party = vars.party
        party.name = 'Party'
        party.save()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'service'
        template.list_price = Decimal('20')
        template.account_category = vars.account_category
        template.save()
        product, = template.products

        # Create payment term
        PaymentTerm = Model.get('account.invoice.payment_term')
        payment_term = PaymentTerm(name='Term')
        line = payment_term.lines.new(type='percent', ratio=Decimal('.5'))
        line.relativedeltas.new(days=20)
        line = payment_term.lines.new(type='remainder')
        line.relativedeltas.new(days=40)
        payment_term.save()

        # Create invoice
        Invoice = Model.get('account.invoice')
        invoice = Invoice()
        invoice.party = party
        invoice.payment_term = payment_term
        invoice.type = 'out'

        # Add line
        line = invoice.lines.new()
        line.product = product
        line.account = vars.accounts['revenue']
        line.description = 'Test'
        line.quantity = 1
        line.unit_price = Decimal('10.0000')

        invoice.save()

        # Check verifactu fields
        self.assertEqual(invoice.verifactu_operation_key, None)
        self.assertEqual(invoice.verifactu_state, None)
        self.assertEqual(invoice.verifactu_pending_sending, False)

        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertTrue(invoice.is_verifactu)
        self.assertEqual(invoice.verifactu_operation_key, 'F1')

        vars.fiscalyear.es_verifactu_send_invoices = False
        with self.assertRaises(UserError):
            vars.fiscalyear.save()
