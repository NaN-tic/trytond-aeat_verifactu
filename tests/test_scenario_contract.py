import datetime
import unittest
from decimal import Decimal

from proteus import Model, Wizard
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

        d2015 = datetime.date(2015, 1, 1)

        # Install contract
        activate_modules(['contract', 'aeat_verifactu'])

        vars = setup(fiscalyear_date=d2015)

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create party
        customer = vars.party
        customer.customer_payment_term = payment_term
        customer.account_receivable = vars.accounts['receivable']
        customer.save()

        # Configure contract
        ContractConfig = Model.get('contract.configuration')
        Journal = Model.get('account.journal')
        contract_config = ContractConfig(1)
        contract_config.journal, = Journal.find([('type', '=', 'revenue')])
        contract_config.default_months_renewal = 1
        contract_config.default_review_alarm = datetime.timedelta(days=1)
        contract_config.default_review_limit_date = datetime.timedelta(days=1)
        contract_config.save()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        unit.rounding = 0.01
        unit.digits = 2
        unit.save()
        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'service'
        template.default_uom = unit
        template.type = 'service'
        template.list_price = Decimal('40')
        template.account_category = vars.account_category
        template.save()
        product, = template.products
        Service = Model.get('contract.service')
        service1 = Service(name='service1', product=product)
        service1.save()

        # Create Monthly Contract
        Contract = Model.get('contract')
        contract = Contract()
        contract.party = customer
        contract.reference = 'TEST'
        self.assertEqual(contract.payment_term, payment_term)
        contract.freq = 'monthly'
        contract.interval = 1
        contract.start_period_date = datetime.date(2015, 1, 1)
        contract.first_invoice_date = datetime.date(2015, 1, 1)
        contract.lines.new(service=service1,
                                   unit_price=Decimal(100),
                                   start_date=datetime.date(2015, 1, 1),
                                   end_date=datetime.date(2015, 3, 1))
        contract.save()
        contract.click('confirm')
        self.assertEqual(contract.state, 'confirmed')

        # Create consumptions for 2015-01-31
        Consumption = Model.get('contract.consumption')
        create_consumptions = Wizard('contract.create_consumptions')
        create_consumptions.form.date = datetime.date(2015, 1, 31)
        create_consumptions.execute('create_consumptions')
        consumptions = Consumption.find([])
        self.assertEqual(len(consumptions), 1)

        # Create invoice manually for the contract
        Invoice = Model.get('account.invoice')
        invoice = Invoice()
        invoice.party = customer
        invoice.reference = contract.reference
        invoice.type = 'out'
        line = invoice.lines.new()
        line.product = product
        line.account = vars.accounts['revenue']
        line.quantity = 1
        line.unit_price = Decimal('100')
        invoice.save()

        # Check invoice verifactu
        self.assertTrue(invoice.is_verifactu)
        self.assertEqual(invoice.verifactu_operation_key, 'F1')

        # Do not post the invoice