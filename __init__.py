# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import cron
from . import invoice
from . import aeat
from . import party
from . import account
from . import aeat_mapping
from . import sale
from . import contract


def register():
    Pool.register(
        account.Configuration,
        account.ConfigurationDefaultVerifactu,
        account.TemplateTax,
        account.Tax,
        cron.Cron,
        party.Party,
        party.PartyIdentifier,
        invoice.Invoice,
        invoice.ResetVerifactuKeysStart,
        invoice.ResetVerifactuKeysEnd,
        aeat.CreateVerifactuIssuedPendingView,
        aeat.VerifactuReport,
        aeat.VerifactuReportLine,
        aeat.VerifactuReportLineTax,
        aeat_mapping.IssuedInvoiceMapper,
        module='aeat_verifactu', type_='model')
    Pool.register(
        contract.ContractConsumption,
        depends=['contract'],
        module='aeat_verifactu', type_='model')
    Pool.register(
        sale.Sale,
        depends=['sale'],
        module='aeat_verifactu', type_='model')
    Pool.register(
        invoice.ResetVerifactuKeys,
        aeat.CreateVerifactuIssuedPending,
        module='aeat_verifactu', type_='wizard')
