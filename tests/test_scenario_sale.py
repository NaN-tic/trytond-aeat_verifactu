import unittest
from decimal import Decimal

from proteus import Model
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from datetime import date


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        # Activate modules
        activate_modules(['sale', 'aeat_verifactu'])

        # Create company
        _ = create_company()
        company = get_company()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create tax
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

        # Create parties
        Party = Model.get('party.party')
        customer = Party(name='Customer')
        customer.verifactu_identifier_type = '02'
        customer.save()

        # Create product
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.customer_taxes.append(tax)
        account_category.save()

        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])

        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'goods'
        template.salable = True
        template.list_price = Decimal('10')
        template.account_category = account_category
        template.save()
        product, = template.products

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create a sale
        Sale = Model.get('sale.sale')
        sale = Sale()
        sale.party = customer
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

        # Check verifactu fields on invoice
        self.assertTrue(invoice.is_verifactu)
        self.assertEqual(invoice.verifactu_operation_key, 'F1')

        # Do not post the invoice