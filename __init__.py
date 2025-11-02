# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import cron
from . import invoice
from . import aeat
from . import party
from . import account


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
        aeat.VerifactuReportLine,
        aeat.VerifactuReportLineTax,
        module='aeat_verifactu', type_='model')
    Pool.register(
        invoice.ResetVerifactuKeys,
        module='aeat_verifactu', type_='wizard')
