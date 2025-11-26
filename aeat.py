# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from datetime import datetime
import pytz
import hashlib

import trytond
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.config import config
from trytond.i18n import gettext
from trytond.exceptions import UserError
from . import tools

from logging import getLogger
from requests import Session
from requests.exceptions import ConnectionError

from zeep import Client
from zeep.transports import Transport
from zeep.settings import Settings
from zeep.plugins import HistoryPlugin

from .tools import LoggingPlugin
from . import aeat

logger = getLogger(__name__)

# AEAT verifactu test
VERIFACTU_TEST = not config.getboolean('database', 'production', default=False)
MAX_VERIFACTU_LINES = config.getint('aeat', 'verifactu_lines', default=300)

DATE_FMT = '%d-%m-%Y'
RECTIFIED_KINDS = frozenset({'R1', 'R2', 'R3', 'R4', 'R5'})
OTHER_ID_TYPES = frozenset({'02', '03', '04', '05', '06', '07'})


# wsdl_prod = ('https://www2.agenciatributaria.gob.es/static_files/common/'
#     'internet/dep/aplicaciones/es/aeat/sverifactu_1_1_bis/fact/ws/')

WSDL_PROD = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
WSDL_TEST = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
WSDL_PROD = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
WSDL_TEST = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
WSDL_PROD = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')
WSDL_TEST = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')

PRODUCTION_ENV = config.getboolean('database', 'production', default=False)

# TipoFactura
OPERATION_KEY = [ # L2
    ('F1', 'Invoice (Art 6.7.3 y 7.3 of RD1619/2012)'),
    ('F2', 'Simplified Invoice (ticket) and Invoices without destination '
        'identidication (Art 6.1.d of RD1619/2012)'),
    ('F3', 'Invoice issued to replace simplified invoices issued and filed'),
    # R1: errores fundados de derecho y causas del artículo 80.Uno, Dos y Seis
    #    LIVA
    ('R1', 'Corrected Invoice '
        '(Art 80.1, 80.2 and 80.6 and error grounded in law)'),
    # R2: concurso de acreedores
    ('R2', 'Corrected Invoice (Art. 80.3)'),
    # R3: deudas incobrables
    ('R3', 'Credit Note (Art 80.4)'),
    # R4: resto de causas
    ('R4', 'Corrected Invoice (Other)'),
    ('R5', 'Corrected Invoice in simplified invoices'),
    ]

# IDType
PARTY_IDENTIFIER_TYPE = [ # L7
    (None, 'VAT (for National operators)'),
    ('02', 'VAT (only for intracommunity operators)'),
    ('03', 'Passport'),
    ('04', 'Official identification document issued by the country '
        'or region of residence'),
    ('05', 'Residence certificate'),
    ('06', 'Other supporting document'),
    ('07', 'Not registered (only for Spanish VAT not registered)'),
    # Extra register add for the control of Simplified Invocies, but not in the
    #   verifactu list
    ('SI', 'Simplified Invoice'),
    ]

# Desglose -> DetalleDesglose -> ClaveRegimen
SEND_SPECIAL_REGIME_KEY = [  # L8A
    (None, ''),
    ('01', 'General tax regime activity'),
    ('02', 'Export'),
    ('03', 'Activities to which the special scheme of used goods, '
        'works of art, antiquities and collectables (135-139 of the VAT Law)'),
    ('04', 'Special scheme for investment gold'),
    ('05', 'Special scheme for travel agencies'),
    ('06', 'Special scheme applicable to groups of entities, VAT (Advanced)'),
    ('07', 'Special cash basis scheme'),
    ('08', 'Activities subject to Canary Islands General Indirect Tax/Tax on '
        'Production, Services and Imports'),
    ('09', 'Invoicing of the provision of travel agency services acting as '
        'intermediaries in the name of and on behalf of other persons '
        '(Additional Provision 4, Royal Decree 1619/2012)'),
    ('10', 'Collections on behalf of third parties of professional fees or '
        'industrial property, copyright or other such rights by partners, '
        'associates or members undertaken by companies, associations, '
        'professional organisations or other entities that, amongst their '
        'functions, undertake collections'),
    ('11', 'Business premises lease activities subject to withholding'),
    ('14', 'Invoice with VAT pending accrual (work certifications with Public '
        'Administration recipients)'),
    ('15', 'Invoice with VAT pending accrual - '
        'operations of successive tract'),
    ('17', 'Operation covered by one of the regimes provided for in Chapter XI of Title IX (OSS and IOSS)'),
    ('18', 'Equivalence surcharge'),
    ('19', 'Operations of activities included in the Special Regime for Agriculture, Livestock and Fisheries (REAGYP)'),
    ('20', 'Simplified regime'),
    ]

AEAT_COMMUNICATION_STATE = [
    (None, ''),
    ('Correcto', 'Accepted'),
    ('ParcialmenteCorrecto', 'Partially Accepted'),
    ('Incorrecto', 'Rejected')
    ]

AEAT_INVOICE_STATE = [
    (None, ''),
    ('Correcto', 'Accepted'),
    ('AceptadoConErrores', 'Accepted with Errors'),
    ('Incorrecto', 'Rejected'),
    ]

PROPERTY_STATE = [  # L6
    ('0', ''),
    ('1', '1. Property with a land register reference located in any part '
        'of Spain, with the exception of the Basque Country and Navarre'),
    ('2', '2. Property located in the Autonomous Community of the Basque '
        'Country or the Chartered Community of Navarre.'),
    ('3', '3. Property in any of the foregoing locations '
        'with no land register reference'),
    ('4', '4. Property located abroad'),
    ]

# L9 - Iva Subjected
IVA_SUBJECTED = [
    (None, ''),
    ('S1', 'Subject - Not exempt. Non VAT reverse charge'),
    ('S2', 'Subject - Not exempt. VAT reverse charge'),
    ('N1', 'Exempt on acconunt of Articles 7, 14, others'),
    ('N2', 'Exempt by location rules'),
    ]

# L10 - Exemption cause
EXEMPTION_CAUSE = [
    (None, ''),
    ('E1', 'Exempt on account of Article 20'),
    ('E2', 'Exempt on account of Article 21'),
    ('E3', 'Exempt on account of Article 22'),
    ('E4', 'Exempt on account of Article 23 and Article 24'),
    ('E5', 'Exempt on account of Article 25'),
    ('E6', 'Exempt on other grounds'),
    ('NotSubject', 'Not Subject'),
    ]


class Verifactu(ModelSQL, ModelView):
    '''
    AEAT Verifactu
    '''
    __name__ = 'aeat.verifactu'

    invoice = fields.Many2One('account.invoice', 'Invoice', required=True,
        domain=[('type', '=', 'out')])
    state = fields.Selection(AEAT_INVOICE_STATE, 'State')
    communication_code = fields.Integer('Communication Code', readonly=True)
    company = fields.Many2One('company.company', 'Company', required=True)
    invoice_operation_key = fields.Function(fields.Selection(OPERATION_KEY,
            'Operation Key'), 'get_invoice_operation_key')
    fingerprint = fields.Text('Fingerprint', readonly=True)
    error_message = fields.Char('Error Message', readonly=True)

    def get_invoice_operation_key(self, name):
        return self.invoice.verifactu_operation_key if self.invoice else None

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('invoice')

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['state'] = None
        default['communication_code'] = None
        default['fingerprint'] = None
        default['error_message'] = None
        return super().copy(records, default=default)


def get_sistema_informatico():
    pool = Pool()
    Company = pool.get('company.company')

    # TODO: We should check if the other companies are Spanish
    # and/or should be counted
    companies = Company.search([], count=True)

    return {
        'NombreRazon': config.get('aeat_verifactu', 'nombre_razon'),
        'NIF': config.get('aeat_verifactu', 'nif'),
        'NombreSistemaInformatico': config.get('aeat_verifactu',
            'nombre_sistema_informatico'),
        'IdSistemaInformatico': config.get('aeat_verifactu',
            'id_sistema_informatico'),
        'Version': trytond.__version__,
        'NumeroInstalacion': config.get('aeat_verifactu',
            'numero_instalacion'),
        'TipoUsoPosibleSoloVerifactu': 'N',
        'TipoUsoPosibleMultiOT': 'S',
        'IndicadorMultiplesOT': 'S' if companies > 1 else 'N',
        }

def get_headers(company):
    return {
        'IDVersion': '1.0',
        'ObligadoEmision': {
            'NombreRazon': tools.unaccent(company.party.name),
            'NIF': company.party.verifactu_vat_code,
            # TODO: NIFRepresentante
        },
    }


class VerifactuRequest:

    def __init__(self, invoice):
        self.invoice = invoice

    def build_delete_request(self):
        return {
            'PeriodoLiquidacion': self._build_period(),
            'IDFactura': self._build_invoice_id(),
            }

    def build_submit_request(self, last_fingerprint=None, last_line=None):
        request = {}
        request['RegistroAlta'] = self.build_invoice(last_fingerprint, last_line=last_line)
        return request

    def get_invoice_total(self):
        taxes = self.total_invoice_taxes()
        taxes_base = 0
        taxes_amount = 0
        taxes_surcharge = 0
        taxes_used = {}
        for tax in taxes:
            base = tax.company_base
            taxes_amount += tax.company_amount
            taxes_surcharge += self.tax_equivalence_surcharge_amount(tax) or 0
            parent = tax.tax.parent if tax.tax.parent else tax.tax
            if (parent.id in list(taxes_used.keys()) and
                    base == taxes_used[parent.id]):
                continue
            taxes_base += base
            taxes_used[parent.id] = base
        return (taxes_amount + taxes_base + taxes_surcharge)

    def taxes(self):
        return [invoice_tax for invoice_tax in self.invoice.taxes if
            not invoice_tax.tax.recargo_equivalencia]

    def total_invoice_taxes(self):
        return [invoice_tax for invoice_tax in self.invoice.taxes if
            not invoice_tax.tax.recargo_equivalencia]

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
            return surcharge_tax.company_amount

    def _build_period(self):
        return {
            'Ejercicio': self.invoice.move.period.start_date.year,
            'Periodo': tools.format_period(
                self.invoice.move.period.start_date.month),
            }

    def _build_invoice_id(self):
        ret = {
            'IDEmisorFactura': self.invoice.company.party.verifactu_vat_code,
            'NumSerieFactura': self.invoice.number,
            'FechaExpedicionFactura': self.invoice.invoice_date.strftime(DATE_FMT),
            }
        return ret

    def _build_counterpart(self):
        ret = {
            'NombreRazon': tools.unaccent(self.invoice.party.name),
            }


        vat = ''
        if not self.invoice.simplified:
            identifier = self.invoice.party_tax_identifier
            if identifier:
                vat = identifier.es_code()
                vat_type = identifier.es_vat_type()
                for tax in self.invoice.taxes:
                    if (tax.tax.verifactu_exemption_cause == 'E5' and
                            vat_type != '02'):
                        raise UserError(gettext(
                                'aeat_verifactu.msg_wrong_identifier_type',
                                invoice=self.invoice.number,
                                party=self.invoice.party.rec_name))
        if vat_type and vat_type in OTHER_ID_TYPES:
            ret['IDOtro'] = {
                'IDType': vat_type,
                'CodigoPais': identifier.es_country(),
                'ID': vat,
                }
        else:
            ret['NIF'] = vat
        return ret

    def _build_encadenamiento(self, last_line=None):
        if not last_line:
            return {
                'PrimerRegistro': 'S',
                }
        invoice = last_line.invoice
        return {
            'RegistroAnterior': {
                'IDEmisorFactura': invoice.company.party.verifactu_vat_code,
                'NumSerieFactura': invoice.number,
                'FechaExpedicionFactura': invoice.invoice_date.strftime(
                    DATE_FMT),
                'Huella': last_line.fingerprint,
                }}

    def location_rules(self):
        base = 0
        taxes = self.total_invoice_taxes()
        for tax in taxes:
            if (tax.tax.verifactu_issued_key == '08' or
                    (tax.tax.verifactu_exemption_cause == 'NotSubject' and
                        tax.tax.service)):
                base += tax.company_base
        return base

    def build_fingerprint(self, previous_hash=None, time=None):
        data_string = (
            f'IDEmisorFactura={self.invoice.company.party.verifactu_vat_code}&'
            f'NumSerieFactura={self.invoice.number}&'
            f'FechaExpedicionFactura={self.invoice.invoice_date.strftime('%d-%m-%Y')}&'
            f'TipoFactura={self.invoice.verifactu_operation_key}&'
            f'CuotaTotal={sum(tax.company_amount for tax in self.taxes())}&'
            f'ImporteTotal={self.get_invoice_total()}&'
            f'Huella={previous_hash or ''}&'
            f'FechaHoraHusoGenRegistro={time}')
        hash_object = hashlib.sha256(data_string.encode('utf-8'))
        return hash_object.hexdigest().upper()

    def build_desglose(self):
        desgloses = []
        for tax in self.taxes():
            desglose = {}
            desglose['ClaveRegimen'] = tax.tax.verifactu_issued_key
            if tax.tax.verifactu_subjected_key is not None:
                desglose['CalificacionOperacion']= tax.tax.verifactu_subjected_key
                desglose['TipoImpositivo'] = tools._rate_to_percent(tax.tax.rate)
                desglose['CuotaRepercutida'] = tax.company_amount
            else:
                desglose['OperacionExenta'] = tax.tax.verifactu_exemption_cause
            desglose['BaseImponibleOimporteNoSujeto'] = tax.company_base
            if tax.tax.recargo_equivalencia_related_tax:
                for tax2 in self.invoice.taxes:
                    if (tax2.tax.recargo_equivalencia and
                            tax.tax.recargo_equivalencia_related_tax ==
                            tax2.tax and tax2.base ==
                            tax2.base.copy_sign(tax.base)):
                        desglose['TipoRecargoEquivalencia'] = tools._rate_to_percent(
                            tax2.tax.rate)
                        desglose['CuotaRecargoEquivalencia'] = tax2.company_amount
                        desglose['ClaveRegimen'] = 18 # Recargo de equivalencia
                        break
            desgloses.append(desglose)
        return desgloses

    def build_invoice(self, last_fingerprint=None, last_line=None):
        tz = pytz.timezone('Europe/Madrid')
        dt_now = datetime.now(tz).replace(microsecond=0)
        formatted_now = dt_now.isoformat()

        description = tools.unaccent(self.invoice.description or '')
        if not description:
            description = self.number
        ret = {
            'IDVersion': '1.0',
            'IDFactura': self._build_invoice_id(),
            'NombreRazonEmisor': tools.unaccent(self.invoice.company.party.name),
            'TipoFactura': self.invoice.verifactu_operation_key,
            'DescripcionOperacion': description,
            'Desglose': {
                'DetalleDesglose': self.build_desglose(),
                },
            'CuotaTotal': sum(tax.company_amount for tax in self.taxes()),
            'ImporteTotal': self.get_invoice_total(),
            'Encadenamiento': self._build_encadenamiento(last_line),
            'SistemaInformatico': get_sistema_informatico(),
            'FechaHoraHusoGenRegistro':  formatted_now,
            'TipoHuella': '01',
            'Huella': self.build_fingerprint(last_fingerprint, formatted_now)
            }

        if (self.invoice.verifactu_records
                and self.invoice.verifactu_state == 'PendienteEnvioSubsanacion'):

            ret['Subsanacion'] = 'S'
            ret['RechazoPrevio'] = 'S'

        if ret['TipoFactura'] not in {'F2', 'R5'}:
            ret['Destinatarios'] = {
                'IDDestinatario': self._build_counterpart()
                }

        if ret['TipoFactura'] in RECTIFIED_KINDS:
            ret['TipoRectificativa'] = 'I'
            if ret['TipoRectificativa'] == 'S':
                ret['ImporteRectificacion'] = {
                    'BaseRectificada': self.rectified_base(),
                    'CuotaRectificada': self.rectified_amount(),
                    # TODO: CuotaRecargoRectificado
                    }

        print('=======', ret)
        return ret


class VerifactuService(object):

    def __init__(self, service):
        self.service = service

    @staticmethod
    def get_client(wsdl, crt, pkey):
        session = Session()
        session.cert = (crt, pkey)
        transport = Transport(session=session)
        settings = Settings(forbid_entities=False)
        plugins = [HistoryPlugin()]
        if not PRODUCTION_ENV:
            plugins.append(LoggingPlugin())
        try:
            client = Client(wsdl=wsdl, transport=transport, plugins=plugins, settings=settings)
        except ConnectionError as e:
            raise UserError(str(e))

        return client

    @staticmethod
    def bind(crt, pkey):
        if PRODUCTION_ENV:
            wsdl = WSDL_PROD
            port_name = 'SistemaVerifactu'
        else:
            wsdl = WSDL_TEST
            port_name = 'SistemaVerifactuPruebas'

        wsdl += 'SistemaFacturacion.wsdl'
        cli = VerifactuService.get_client(wsdl, crt, pkey)
        return VerifactuService(cli.bind('sfVerifactu', port_name))

    def submit(self, company, invoices, last_fingerprint=None, last_line=None):
        headers = get_headers(company)
        body = []
        for invoice in invoices:
            request = aeat.VerifactuRequest(invoice)
            body.append(request.build_submit_request(
                last_fingerprint, last_line))
        return self.service.RegFactuSistemaFacturacion(headers, body)

    def cancel(self, company, body):
        headers = get_headers(company)
        return self.service.AnulacionLRFacturasEmitidas(headers, body)

    def query(self, company, year=None, period=None, clave_paginacion=None):
        headers = get_headers(company)
        filter_ = {
            'PeriodoImputacion': {
                'Ejercicio': year,
                'Periodo': tools.format_period(period),
                },
            'SistemaInformatico': get_sistema_informatico(),
            }
        if clave_paginacion:
            filter_['ClavePaginacion'] = clave_paginacion
        return self.service.ConsultaFactuSistemaFacturacion(headers, filter_)
