from logging import getLogger
from requests import Session
from requests.exceptions import ConnectionError

from zeep import Client
from zeep.transports import Transport
from zeep.settings import Settings
from zeep.plugins import HistoryPlugin

from trytond.pool import Pool
from trytond.exceptions import UserError
from .tools import LoggingPlugin

_logger = getLogger(__name__)

# wsdl_prod = ('https://www2.agenciatributaria.gob.es/static_files/common/'
#     'internet/dep/aplicaciones/es/aeat/sverifactu_1_1_bis/fact/ws/')

wsdl_prod = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
wsdl_test = ('https://prewww10.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/RequerimientoSOAP')
# wsdl_prod = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
# wsdl_test = ('https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP')
wsdl_prod = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')
wsdl_test = ('https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/')

def _get_client(wsdl, public_crt, private_key, test=True):
    print('entro get client')
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
    print('entro bind issued invoices service')
    wsdl = wsdl_prod + 'SistemaFacturacion.wsdl'
    port_name = 'SistemaVerifactu'
    if test:
        wsdl = wsdl_test + 'SistemaFacturacion.wsdl'
        port_name += 'Pruebas'

    cli = _get_client(wsdl, crt, pkey, test)

    return _IssuedInvoiceService(
        cli.bind('sfVerifactu', port_name))



class _IssuedInvoiceService(object):
    def __init__(self, service):
        self.service = service

    def submit(self, headers, invoices, last_huella=None, last_line=None):
        print('entro submit')
        pool = Pool()
        IssuedMapper = pool.get('aeat.verifactu.issued.invoice.mapper')
        mapper = IssuedMapper()

        body = [mapper.build_submit_request(i, last_huella, last_line) for i in invoices]

        print('body', body)
        _logger.debug(body)
        response_ = self.service.RegFactuSistemaFacturacion(
            headers, body)
        print(response_)
        _logger.debug(response_)
        return response_, str(body)

    def cancel(self, headers, body):
        print('entro cancel')
        _logger.debug(body)
        response_ = self.service.AnulacionLRFacturasEmitidas(
            headers, body)
        _logger.debug(response_)
        return response_

    def query(self, headers, year=None, period=None, clave_paginacion=None):
        print('entro query')
        pool = Pool()
        IssuedMapper = pool.get('aeat.verifactu.issued.invoice.mapper')
        mapper = IssuedMapper()

        filter_ = mapper.build_query_filter(year=year, period=period,
            clave_paginacion=clave_paginacion)
        _logger.debug(filter_)
        response_ = self.service.ConsultaFactuSistemaFacturacion(
            headers, filter_)
        print(len(response_.RegistroRespuestaConsultaFactuSistemaFacturacion))
        _logger.debug(response_)
        return response_
