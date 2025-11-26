from decimal import Decimal
from proteus import Model
from trytond.modules.account.tests.tools import create_chart, create_fiscalyear, create_tax, get_accounts
from trytond.modules.account_invoice.tests.tools import set_fiscalyear_invoice_sequences
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.config import config as tconfig
from types import SimpleNamespace
from proteus import Wizard
import os

tconfig.add_section('cryptography')
tconfig.set('cryptography', 'fernet_key', '8BwFmKMykS2X2-gmwEwgfmA9hPN-pb4Ua5N2XyqAlh4=')
tconfig.add_section('aeat_verifactu')
tconfig.set('aeat_verifactu', 'nombre_razon', 'NaN Projectes de Programari Lliure, S.L.')
tconfig.set('aeat_verifactu', 'nif', 'B65247983')
tconfig.set('aeat_verifactu', 'nombre_sistema_informatico', 'Tryton')
tconfig.set('aeat_verifactu', 'id_sistema_informatico', '00')
tconfig.set('aeat_verifactu', 'numero_instalacion', '00')


def setup():
    vars = SimpleNamespace()

    # Create company
    _ = create_company()
    vars.company = get_company()

    # Create fiscal year
    fiscalyear = set_fiscalyear_invoice_sequences(create_fiscalyear(vars.company))
    fiscalyear.click('create_period')
    fiscalyear.es_verifactu_send_invoices = True
    fiscalyear.save()
    vars.fiscalyear = fiscalyear

    # Create chart of accounts
    _ = create_chart(vars.company)
    vars.accounts = get_accounts(vars.company)

    # Create tax
    tax = create_tax(Decimal('.10'))
    tax.save()
    vars.tax = tax

    # Create certificate
    Certificate = Model.get('certificate')
    certificate = Certificate()
    certificate.name = 'Test Certificate'
    certificate.save()
    with open(os.path.join(os.path.dirname(__file__), 'certificate.p12'), 'rb') as f:
        pfx_data = f.read()
    load_wizard = Wizard('certificate.load_pkcs12', models=[certificate])
    load_wizard.form.pfx = pfx_data
    load_wizard.form.password = '1234'
    load_wizard.execute('load')
    vars.certificate = certificate

    # Set configuration
    Configuration = Model.get('account.configuration')
    config = Configuration(1)
    config.aeat_certificate_verifactu = certificate
    config.save()
    vars.config = config

    # Create party
    Party = Model.get('party.party')
    party = Party(name='Customer')
    party.verifactu_identifier_type = '02'
    party.save()
    vars.party = party

    # Add VAT identifier
    PartyIdentifier = Model.get('party.identifier')
    identifier = PartyIdentifier()
    identifier.party = party
    identifier.type = 'eu_vat'
    identifier.code = 'ESB65247983'
    identifier.save()

    identifier = PartyIdentifier()
    identifier.party = vars.company.party
    identifier.type = 'eu_vat'
    identifier.code = 'ESB65247983'
    identifier.save()

    # Create product category
    ProductCategory = Model.get('product.category')
    account_category = ProductCategory(name="Account Category")
    account_category.accounting = True
    account_category.account_expense = vars.accounts['expense']
    account_category.account_revenue = vars.accounts['revenue']
    account_category.customer_taxes.append(vars.tax)
    account_category.save()
    vars.account_category = account_category

    return vars
