# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from logging import getLogger
from operator import attrgetter
from datetime import datetime
import pytz

from trytond.i18n import gettext
from trytond.model import Model
from trytond.exceptions import UserError
from . import tools


_logger = getLogger(__name__)

_DATE_FMT = '%d-%m-%Y'

RECTIFIED_KINDS = frozenset({'R1', 'R2', 'R3', 'R4', 'R5'})
OTHER_ID_TYPES = frozenset({'02', '03', '04', '05', '06', '07'})

SEMESTER1_ISSUED_SPECIALKEY = '16'
SEMESTER1_RECIEVED_SPECIALKEY = '14'


class IssuedInvoiceMapper(Model):
    """
    Tryton Issued Invoice to AEAT mapper
    """
    __name__ = 'aeat.verifactu.issued.invoice.mapper'
    year = attrgetter('move.period.start_date.year')
    period = attrgetter('move.period.start_date.month')
    nif = attrgetter('company.party.verifactu_vat_code')
    issue_date = attrgetter('invoice_date')
    invoice_kind = attrgetter('verifactu_operation_key')
    rectified_invoice_kind = tools.fixed_value('I')

    def not_exempt_kind(self, tax):
        return attrgetter('verifactu_subjected_key')(tax)

    def exempt_kind(self, tax):
        return attrgetter('verifactu_exemption_cause')(tax)

    def not_subject(self, invoice):
        base = 0
        taxes = self.total_invoice_taxes(invoice)
        for tax in taxes:
            if (tax.tax.verifactu_exemption_cause == 'NotSubject' and
                    not tax.tax.service):
                base += self.get_tax_base(tax)
        return base

    def counterpart_nif(self, invoice):
        nif = ''
        if invoice.party.tax_identifier:
            nif = invoice.party.tax_identifier.code
        elif invoice.party.identifiers:
            nif = invoice.party.identifiers[0].code
        if nif.startswith('ES'):
            nif = nif[2:]
        return nif

    def get_tax_amount(self, tax):
        val = attrgetter('company_amount')(tax)
        return val

    def get_tax_base(self, tax):
        val = attrgetter('company_base')(tax)
        return val

    def get_invoice_total(self, invoice):
        taxes = self.total_invoice_taxes(invoice)
        taxes_base = 0
        taxes_amount = 0
        taxes_surcharge = 0
        taxes_used = {}
        for tax in taxes:
            base = self.get_tax_base(tax)
            taxes_amount += self.get_tax_amount(tax)
            taxes_surcharge += self.tax_equivalence_surcharge_amount(tax) or 0
            parent = tax.tax.parent if tax.tax.parent else tax.tax
            if (parent.id in list(taxes_used.keys()) and
                    base == taxes_used[parent.id]):
                continue
            taxes_base += base
            taxes_used[parent.id] = base
        return (taxes_amount + taxes_base + taxes_surcharge)

    def counterpart_id_type(self, invoice):
        for tax in invoice.taxes:
            if (self.exempt_kind(tax.tax) == 'E5' and
                    invoice.party.verifactu_identifier_type != '02'):
                raise UserError(gettext(
                        'aeat_verifactu.msg_wrong_identifier_type',
                        invoice=invoice.number,
                        party=invoice.party.rec_name))
        return invoice.party.verifactu_identifier_type

    counterpart_id = counterpart_nif
    total_amount = get_invoice_total
    tax_rate = attrgetter('tax.rate')
    tax_base = get_tax_base
    tax_amount = get_tax_amount

    def counterpart_name(self, invoice):
        if invoice.verifactu_operation_key == 'F5':
            return tools.unaccent(invoice.company.party.name)
        else:
            return tools.unaccent(invoice.party.name)

    def counterpart_country(self, invoice):
        return (invoice.invoice_address.country.code
            if invoice.invoice_address.country else '')

    def serial_number(self, invoice):
        return invoice.number if invoice.type == 'out' else (invoice.reference or '')

    def taxes(self, invoice):
        return [invoice_tax for invoice_tax in invoice.taxes if (
                invoice_tax.tax.tax_used and
                not invoice_tax.tax.recargo_equivalencia)]

    def total_invoice_taxes(self, invoice):
        return [invoice_tax for invoice_tax in invoice.taxes if (
                invoice_tax.tax.invoice_used and
                not invoice_tax.tax.recargo_equivalencia)]

    def _tax_equivalence_surcharge(self, invoice_tax):
        surcharge_tax = None
        for invoicetax in invoice_tax.invoice.taxes:
            if (invoicetax.tax.recargo_equivalencia and
                    invoice_tax.tax.recargo_equivalencia_related_tax ==
                    invoicetax.tax and invoicetax.base ==
                    invoicetax.base.copy_sign(invoice_tax.base)):
                surcharge_tax = invoicetax
                break
        return surcharge_tax

    def tax_equivalence_surcharge_amount(self, invoice_tax):
        surcharge_tax = self._tax_equivalence_surcharge(invoice_tax)
        if surcharge_tax:
            return self.tax_amount(surcharge_tax)

    def _build_period(self, invoice):
        return {
            'Ejercicio': self.year(invoice),
            'Periodo': tools._format_period(self.period(invoice)),
        }

    def _build_invoice_id(self, invoice):
        number = self.serial_number(invoice)
        ret = {
            'IDEmisorFactura': self.nif(invoice),
            'NumSerieFactura': number,
            'FechaExpedicionFactura':
                self.issue_date(invoice).strftime(_DATE_FMT),
        }
        return ret

    def _build_counterpart(self, invoice):
        ret = {
            'NombreRazon': self.counterpart_name(invoice),
        }
        id_type = self.counterpart_id_type(invoice)
        if id_type and id_type in OTHER_ID_TYPES:
            ret['IDOtro'] = {
                'IDType': id_type,
                'CodigoPais': self.counterpart_country(invoice),
                'ID': self.counterpart_id(invoice),
            }
        else:
            ret['NIF'] = self.counterpart_nif(invoice)
        return ret

    def _build_encadenamiento(self, last_line=None):
        if not last_line:
            return {"PrimerRegistro": "S"}
        invoice = last_line.invoice
        return {"RegistroAnterior": {
                    "IDEmisorFactura": self.nif(invoice),
                    "NumSerieFactura": invoice.number,
                    "FechaExpedicionFactura": invoice.invoice_date.strftime(_DATE_FMT),
                    "Huella": last_line.huella
                }}

    def _description(self, invoice):
        description = ''
        if invoice.description:
            description = tools.unaccent(invoice.description)
        if invoice.lines and invoice.lines[0].description:
            description = tools.unaccent(invoice.lines[0].description)
        description = self.serial_number(invoice)
        return description

    def build_query_filter(self, year=None, period=None, clave_paginacion=None):
        result = {
            'PeriodoImputacion': {
                'Ejercicio': year,
                'Periodo': tools._format_period(period),
                },
            'SistemaInformatico':tools.get_sistema_informatico(),
            }
        if clave_paginacion:
            result['ClavePaginacion'] = clave_paginacion
        return result

    def build_delete_request(self, invoice):
        return {
            'PeriodoLiquidacion': self._build_period(invoice),
            'IDFactura': self._build_invoice_id(invoice),
        }

    def build_submit_request(self, invoice, last_huella=None, last_line=None):
        request = {}
        request['RegistroAlta'] = self.build_issued_invoice(invoice, last_huella, last_line=last_line)
        return request


    def location_rules(self, invoice):
        base = 0
        taxes = self.total_invoice_taxes(invoice)
        for tax in taxes:
            if (tax.tax.verifactu_issued_key == '08' or
                    (tax.tax.verifactu_exemption_cause == 'NotSubject' and
                        tax.tax.service)):
                base += self.get_tax_base(tax)
        return base

    def build_huella(self, invoice, previous_hash=None, time=None):
        import hashlib
        data_string = f"IDEmisorFactura={self.nif(invoice)}&" \
              f"NumSerieFactura={invoice.number}&" \
              f"FechaExpedicionFactura={invoice.invoice_date.strftime('%d-%m-%Y')}&" \
              f"TipoFactura={self.invoice_kind(invoice)}&" \
              f"CuotaTotal={sum(self.tax_amount(tax) for tax in self.taxes(invoice))}&" \
              f"ImporteTotal={self.total_amount(invoice)}&" \
              f"Huella={previous_hash or ''}&" \
              f"FechaHoraHusoGenRegistro={time}"
        hash_object = hashlib.sha256(data_string.encode('utf-8'))
        return hash_object.hexdigest().upper()  # Salida en mayúsculas, formato hexadecimal

    def build_desglose(self, invoice):
        desgloses = []
        taxes = self.taxes(invoice)
        for tax in taxes:
            desglose = {}
            desglose["ClaveRegimen"] = tax.tax.verifactu_issued_key
            if tax.tax.verifactu_subjected_key is not None:
                desglose["CalificacionOperacion"]= tax.tax.verifactu_subjected_key
            else:
                desglose["OperacionExenta"] = tax.tax.verifactu_exemption_cause
            desglose["TipoImpositivo"] = tools._rate_to_percent(self.tax_rate(tax))
            desglose["BaseImponibleOimporteNoSujeto"] = self.tax_base(tax)
            desglose["CuotaRepercutida"] = self.tax_amount(tax)
            if tax.tax.recargo_equivalencia_related_tax:
                for tax2 in invoice.taxes:
                    if (tax2.tax.recargo_equivalencia and
                            tax.tax.recargo_equivalencia_related_tax ==
                            tax2.tax and tax2.base ==
                            tax2.base.copy_sign(tax.base)):
                        desglose["TipoRecargoEquivalencia"] = tools._rate_to_percent(
                            self.tax_rate(tax2))
                        desglose["CuotaRecargoEquivalencia"] = self.tax_amount(tax2)
                        desglose["ClaveRegimen"] = 18 # Recargo de equivalencia
                        break
            desgloses.append(desglose)
        return desgloses

    def build_issued_invoice(self, invoice, last_huella=None, last_line=None):
        tz = pytz.timezone("Europe/Madrid")
        dt_now = datetime.now(tz).replace(microsecond=0)
        formatted_now = dt_now.isoformat()
        ret = {
            "IDVersion": "1.0",
            "IDFactura": self._build_invoice_id(invoice),
            "NombreRazonEmisor": tools.unaccent(invoice.company.party.name),
            "TipoFactura": self.invoice_kind(invoice),
            "DescripcionOperacion": self._description(invoice),
            "Destinatarios": {
                "IDDestinatario": self._build_counterpart(invoice)
            },
            "Desglose": {
                "DetalleDesglose": self.build_desglose(invoice),
            },
            "CuotaTotal": sum(self.tax_amount(tax) for tax in self.taxes(invoice)),
            "ImporteTotal": self.total_amount(invoice),
            "Encadenamiento": self._build_encadenamiento(last_line),
            "SistemaInformatico": tools.get_sistema_informatico(),
            "FechaHoraHusoGenRegistro": formatted_now,
            "TipoHuella": "01",
            "Huella": self.build_huella(invoice, last_huella, formatted_now)
        }

        self._update_counterpart(ret, invoice)
        self._update_total_amount(ret, invoice)
        self._update_rectified_invoice(ret, invoice)
        print('=======', ret)
        return ret

    def _update_total_amount(self, ret, invoice):
        if (
            ret['TipoFactura'] == 'R5' and
            ret['TipoDesglose']['DesgloseFactura']['Sujeta'].get('NoExenta',
                None) and
            len(
                ret['TipoDesglose']['DesgloseFactura']['Sujeta']['NoExenta']
                ['DesgloseIVA']['DetalleIVA']
            ) == 1 and
            (
                ret['TipoDesglose']['DesgloseFactura']['Sujeta']['NoExenta']
                ['DesgloseIVA']['DetalleIVA'][0]['BaseImponible'] == 0
            )
        ):
            ret['ImporteTotal'] = self.total_amount(invoice)

    def _update_counterpart(self, ret, invoice):
        if ret['TipoFactura'] not in {'F2', 'F4', 'R5'}:
            ret['Contraparte'] = self._build_counterpart(invoice)

    def _update_rectified_invoice(self, ret, invoice):
        if ret['TipoFactura'] in RECTIFIED_KINDS:
            ret['TipoRectificativa'] = self.rectified_invoice_kind(invoice)
            if ret['TipoRectificativa'] == 'S':
                ret['ImporteRectificacion'] = {
                    'BaseRectificada': self.rectified_base(invoice),
                    'CuotaRectificada': self.rectified_amount(invoice),
                    # TODO: CuotaRecargoRectificado
                }

