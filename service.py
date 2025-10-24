from logging import getLogger
from requests import Session
from requests.exceptions import ConnectionError

from zeep import Client
from zeep.transports import Transport
from zeep.settings import Settings
from zeep.plugins import HistoryPlugin

from trytond.pool import Pool
from trytond.exceptions import UserError
from trytond.config import config
from .tools import LoggingPlugin

logger = getLogger(__name__)

# wsdl_prod = ('https://www2.agenciatributaria.gob.es/static_files/common/'
#     'internet/dep/aplicaciones/es/aeat/sverifactu_1_1_bis/fact/ws/')

WSDL_PROD = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
WSDL_TEST = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
WSDL_PROD = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
WSDL_TEST = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
WSDL_PROD = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')
WSDL_TEST = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')

PRODUCTION_ENV = config.getboolean('database', 'production', default=False)

def get_client(wsdl, public_crt, private_key, test=True):
    session = Session()
    session.cert = (public_crt, private_key)
    transport = Transport(session=session)
    settings = Settings(forbid_entities=False)
    plugins = [HistoryPlugin()]
    # TODO: manually handle sessionId? Not mandatory yet recommended...
    # http://www.agenciatributaria.es/AEAT.internet/Inicio/Ayuda/Modelos__Procedimientos_y_Servicios/Ayuda_P_G417____IVA__Llevanza_de_libros_registro__SII_/Ayuda_tecnica/Informacion_tecnica_SII/Preguntas_tecnicas_frecuentes/1__Cuestiones_Generales/16___Como_se_debe_utilizar_el_dato_sesionId__.shtml
    if test:
        plugins.append(LoggingPlugin())

    try:
        client = Client(wsdl=wsdl, transport=transport, plugins=plugins, settings=settings)
    except ConnectionError as e:
        raise UserError(str(e))

    return client


def bind_issued_invoices_service(crt, pkey, test=True):
    if PRODUCTION_ENV:
        wsdl = WSDL_PROD
        port_name = 'SistemaVerifactu'
    else:
        wsdl = WSDL_TEST
        port_name = 'SistemaVerifactuPruebas'

    wsdl += 'SistemaFacturacion.wsdl'
    cli = get_client(wsdl, crt, pkey, test)

    return IssuedInvoiceService(
        cli.bind('sfVerifactu', port_name))


class IssuedInvoiceService(object):
    def __init__(self, service):
        self.service = service

    def submit(self, headers, invoices, last_huella=None, last_line=None):
        pool = Pool()
        IssuedMapper = pool.get('aeat.verifactu.issued.invoice.mapper')
        mapper = IssuedMapper()

        body = [mapper.build_submit_request(i, last_huella, last_line) for i in invoices]
        logger.debug(body)
        res = self.service.RegFactuSistemaFacturacion(
            headers, body)
        logger.debug(res)
        return res, str(body)

    def cancel(self, headers, body):
        logger.debug(body)
        res = self.service.AnulacionLRFacturasEmitidas(headers, body)
        logger.debug(res)
        return res

    def query(self, headers, year=None, period=None, clave_paginacion=None):
        pool = Pool()
        IssuedMapper = pool.get('aeat.verifactu.issued.invoice.mapper')
        mapper = IssuedMapper()

        filter_ = mapper.build_query_filter(year=year, period=period,
            clave_paginacion=clave_paginacion)
        logger.debug(filter_)
        res = self.service.ConsultaFactuSistemaFacturacion(
            headers, filter_)
        logger.debug(res)
        return res
