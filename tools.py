# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import unicodedata
from logging import getLogger
from lxml import etree
from zeep import Plugin
from trytond.config import config
import trytond

NOMBRE_RAZON = config.get('aeat_verifactu', 'nombre_razon')
NIF = config.get('aeat_verifactu', 'nif')
NOMBRE_SISTEMA_INFORMATICO = config.get('aeat_verifactu',
    'nombre_sistema_informatico')
ID_SISTEMA_INFORMATICO = config.get('aeat_verifactu', 'id_sistema_informatico')
NUMERO_INSTALACION = config.get('aeat_verifactu', 'numero_instalacion')
TIPO_USO_POSIBLE_SOLO_VERIFACTU = 'N'
TIPO_USO_POSIBLE_MULTIOT = 'S'
INDICADOR_MULTIPLES_OT = 'S'

# Company = Pool().get('company.company')
# if len(Company.search([])) > 1:
#     INDICADOR_MULTIPLES_OT = 'S'
# else:
#     INDICADOR_MULTIPLES_OT = 'N'


src_chars = "/*+?Â¿!$[]{}@#`^:;<>=~%\\"
dst_chars = "________________________"

_logger = getLogger(__name__)


def normalize(text):
    if isinstance(text, str):
        text = text.encode('utf-8')
    return text


def unaccent(text):
    output = text
    for c in range(len(src_chars)):
        if c >= len(dst_chars):
            break
        output = output.replace(src_chars[c], dst_chars[c])
    output = unicodedata.normalize('NFKD', output).encode('ASCII',
        'ignore')
    return output.replace(b"_", b"").decode('ASCII')


def _format_period(period):
    return str(period).zfill(2)


def _rate_to_percent(rate):
    return None if rate is None else abs(round(100 * rate, 2))


def get_headers(name=None, vat=None, comm_kind=None, version='1.0'):
    return {
        'IDVersion': '1.0',
        'ObligadoEmision': {
            'NombreRazon': name,
            'NIF': vat,
            # TODO: NIFRepresentante
        },
    }

def get_sistema_informatico():
    sif =  {
        'NombreRazon': NOMBRE_RAZON,
        'NIF': NIF,
        'NombreSistemaInformatico': NOMBRE_SISTEMA_INFORMATICO,
        'IdSistemaInformatico': ID_SISTEMA_INFORMATICO,
        'Version': trytond.__version__,
        'NumeroInstalacion': NUMERO_INSTALACION,
        'TipoUsoPosibleSoloVerifactu': TIPO_USO_POSIBLE_SOLO_VERIFACTU,
        'TipoUsoPosibleMultiOT': TIPO_USO_POSIBLE_MULTIOT,
        'IndicadorMultiplesOT': INDICADOR_MULTIPLES_OT
        }
    return sif

class _FixedValue(object):

    def __init__(self, value):
        self._value = value

    def __call__(self, *args, **kwargs):
        return self._value


def fixed_value(value):
    return _FixedValue(value)


class LoggingPlugin(Plugin):

    def ingress(self, envelope, http_headers, operation):
        _logger.debug('http_headers: %s', http_headers)
        _logger.debug('operation: %s', operation)
        _logger.debug('envelope: %s', etree.tostring(
            envelope, pretty_print=True))
        return envelope, http_headers

    def egress(self, envelope, http_headers, operation, binding_options):
        _logger.debug('http_headers: %s', http_headers)
        _logger.debug('operation: %s', operation)
        _logger.debug('envelope: %s', etree.tostring(
            envelope, pretty_print=True))
        return envelope, http_headers

