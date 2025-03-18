# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from . import aeat


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'
    verifactu_identifier_type = fields.Selection(aeat.PARTY_IDENTIFIER_TYPE,
        'Verifactu Identifier Type', sort=False)
    verifactu_vat_code = fields.Function(fields.Char('Verifactu VAT Code', size=9),
        'get_verifactu_vat_data')

    def get_verifactu_vat_data(self, name=None):
        identifier = self.tax_identifier or (
            self.identifiers and self.identifiers[0])
        if identifier:
            if name == 'verifactu_vat_code':
                if (identifier.type == 'eu_vat' and
                        not identifier.code.startswith('ES') and
                        self.verifactu_identifier_type == '02'):
                    return identifier.code
                return identifier.code[2:]

    def default_verifactu_identifier_type():
        return 'SI'


class PartyIdentifier(metaclass=PoolMeta):
    __name__ = 'party.identifier'

    @classmethod
    def set_verifactu_identifier_type(cls, identifiers):
        pool = Pool()
        Party = pool.get('party.party')

        to_write = []
        for identifier in identifiers:
            if ((identifier.type == 'eu_vat' and identifier.code[:2] == 'ES')
                    or identifier.type in ('es_cif', 'es_dni', 'es_nie',
                        'es_nif')):
                verifactu_identifier_type = None
            elif identifier.type == 'eu_vat':
                verifactu_identifier_type = '02'
            elif identifier.type == 'eu_at_02':
                continue
            else:
                verifactu_identifier_type = '06'
            to_write.extend(([identifier.party], {
                'verifactu_identifier_type': verifactu_identifier_type}))

        if to_write:
            Party.write(*to_write)

    @classmethod
    def create(cls, vlist):
        identifiers = super().create(vlist)
        cls.set_verifactu_identifier_type(identifiers)
        return identifiers

    @classmethod
    def write(cls, *args):
        super().write(*args)

        def get_identifiers(identifiers):
            return list(set(identifiers))

        actions = iter(args)
        for identifiers, values in zip(actions, actions):
            cls.set_verifactu_identifier_type(get_identifiers(identifiers))

    @classmethod
    def delete(cls, identifiers):
        pool = Pool()
        Party = pool.get('party.party')

        parties = [i.party for i in identifiers]
        super().delete(identifiers)
        to_write = []
        for party in parties:
            if not party.tax_identifier:
                to_write.extend(([party], {
                    'verifactu_identifier_type': 'SI'}))
            else:
                cls.set_verifactu_identifier_type(party.identifiers)

        if to_write:
            Party.write(*to_write)
