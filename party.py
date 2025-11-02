# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta
from . import aeat


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'
    verifactu_identifier_type = fields.Selection(aeat.PARTY_IDENTIFIER_TYPE,
        'Verifactu Identifier Type', sort=False)
    verifactu_vat_code = fields.Function(fields.Char('Verifactu VAT Code', size=9),
        'get_verifactu_vat')

    def get_verifactu_vat(self, name=None):
        identifier = self.tax_identifier or (
            self.identifiers and self.identifiers[0])
        if identifier:
            if name == 'verifactu_vat_code':
                if (identifier.type == 'eu_vat' and
                        not identifier.code.startswith('ES') and
                        self.verifactu_identifier_type == '02'):
                    return identifier.code
                return identifier.code[2:]
