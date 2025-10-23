from trytond.modules.account_invoice.tests.tools import set_fiscalyear_invoice_sequences
from trytond.modules.account.tests.tools import create_fiscalyear, create_chart, get_accounts, create_tax
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.tools import activate_modules
from proteus import Model
from decimal import Decimal
import unittest
from trytond.tests.test_tryton import drop_db
from datetime import date


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

        # Create company::
        _ = create_company()
        company = get_company()

        # Create fiscal year::
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts::
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create tax::
        tax = create_tax(Decimal('.10'))
        tax.verifactu_operation_key = 'F1'
        tax.tax_used = True
        tax.save()

        # Create certificate
        Certificate = Model.get('certificate')
        certificate = Certificate()
        certificate.name = 'Test Certificate'
        certificate.pem_certificate = b'dummy'
        certificate.private_key = b'dummy'
        certificate.save()

        # Set configuration
        Configuration = Model.get('account.configuration')
        config = Configuration(1)
        config.aeat_certificate_verifactu = certificate
        config.verifactu_start_date = date.today()
        config.save()

        # Create party::
        Party = Model.get('party.party')
        party = Party(name='Party')
        party.verifactu_identifier_type = '02'  # EU VAT
        party.save()

        # Create account category::
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.customer_taxes.append(tax)
        account_category.save()

        # Create product::
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'service'
        template.list_price = Decimal('20')
        template.account_category = account_category
        template.save()
        product, = template.products

        # Create payment term::
        PaymentTerm = Model.get('account.invoice.payment_term')
        payment_term = PaymentTerm(name='Term')
        line = payment_term.lines.new(type='percent', ratio=Decimal('.5'))
        line.relativedeltas.new(days=20)
        line = payment_term.lines.new(type='remainder')
        line.relativedeltas.new(days=40)
        payment_term.save()

        # Create invoice::
        Invoice = Model.get('account.invoice')
        InvoiceLine = Model.get('account.invoice.line')
        invoice = Invoice()
        invoice.party = party
        invoice.payment_term = payment_term
        invoice.type = 'out'

        # Add line
        line = InvoiceLine()
        invoice.lines.append(line)
        line.product = product
        line.account = revenue
        line.description = 'Test'
        line.quantity = 1
        line.unit_price = Decimal('10.0000')

        invoice.save()

        # Check verifactu fields
        self.assertTrue(invoice.is_verifactu)
        self.assertEqual(invoice.verifactu_operation_key, 'F1')
        self.assertEqual(invoice.verifactu_state, None)
        self.assertEqual(invoice.verifactu_pending_sending, False)

        # Do not post the invoice as webservice is down
