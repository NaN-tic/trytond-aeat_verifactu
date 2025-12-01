# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import cron
from . import invoice
from . import party
from . import account
from . import certificate


def register():
    Pool.register(
        account.Configuration,
        account.ConfigurationDefaultVerifactu,
        account.TemplateTax,
        account.Tax,
        account.FiscalYear,
        account.Period,
        cron.Cron,
        party.Party,
        invoice.Verifactu,
        invoice.Invoice,
        module='aeat_verifactu', type_='model')
    Pool.register(
        certificate.CertificateReport,
        module='aeat_verifactu', type_='report')
