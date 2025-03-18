import os
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
import zeep
from lxml import etree
import logging
from trytond.pyson import Eval

LOGGER = logging.getLogger(__name__)

# URLs de producción y pruebas
# PROD_WSDL_URL = "https://www.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"
PROD_WSDL_URL = "https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"

TEST_WSDL_URL = "https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP"

class Invoice(ModelSQL, ModelView):
    """Invoice extended for VeriFactu integration"""
    __name__ = 'account.invoice'

    verifactu_status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected')
    ], 'VeriFactu Status', required=True)
    csv_code = fields.Char('CSV Code')
    last_verifactu_response = fields.Text('Last VeriFactu Response')

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._buttons.update({
            'send_to_verifactu': {
                'invisible': ~Eval('state').in_(['posted', 'paid']),
            },
        })

    @classmethod
    @ModelView.button
    def send_to_verifactu(cls, invoices):
        """Send invoices to VeriFactu"""
        for invoice in invoices:
            invoice._send_to_verifactu()

    def _send_to_verifactu(self):
        """Generate XML and send to AEAT"""
        xml_data = self.generate_verifactu_xml()
        response = self.send_soap_request(xml_data)
        self.process_response(response)

    def generate_verifactu_xml(self):
        """Generate XML according to VeriFactu XSD"""
        nsmap = {
            'soapenv': "http://schemas.xmlsoap.org/soap/envelope/",
            'sum': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd",
            'sum1': "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"
        }

        envelope = etree.Element(etree.QName(nsmap['soapenv'], 'Envelope'), nsmap=nsmap)
        header = etree.SubElement(envelope, etree.QName(nsmap['soapenv'], 'Header'))
        body = etree.SubElement(envelope, etree.QName(nsmap['soapenv'], 'Body'))
        reg_factu = etree.SubElement(body, etree.QName(nsmap['sum'], 'RegFactuSistemaFacturacion'))

        cabecera = etree.SubElement(reg_factu, etree.QName(nsmap['sum'], 'Cabecera'))
        obligado = etree.SubElement(cabecera, etree.QName(nsmap['sum1'], 'ObligadoEmision'))
        etree.SubElement(obligado, etree.QName(nsmap['sum1'], 'NombreRazon')).text = self.party.name
        etree.SubElement(obligado, etree.QName(nsmap['sum1'], 'NIF')).text = self.party.tax_identifier.code

        registro = etree.SubElement(reg_factu, etree.QName(nsmap['sum'], 'RegistroFactura'))
        alta = etree.SubElement(registro, etree.QName(nsmap['sum1'], 'RegistroAlta'))

        id_factura = etree.SubElement(alta, etree.QName(nsmap['sum1'], 'IDFactura'))
        etree.SubElement(id_factura, etree.QName(nsmap['sum1'], 'IDEmisorFactura')).text = self.party.tax_identifier.code
        etree.SubElement(id_factura, etree.QName(nsmap['sum1'], 'NumSerieFactura')).text = self.number
        etree.SubElement(id_factura, etree.QName(nsmap['sum1'], 'FechaExpedicionFactura')).text = self.invoice_date.strftime('%d-%m-%Y')

        etree.SubElement(alta, etree.QName(nsmap['sum1'], 'NombreRazonEmisor')).text = self.party.name
        etree.SubElement(alta, etree.QName(nsmap['sum1'], 'TipoFactura')).text = "F1"
        etree.SubElement(alta, etree.QName(nsmap['sum1'], 'DescripcionOperacion')).text = "Venta de productos"

        destinatario = etree.SubElement(alta, etree.QName(nsmap['sum1'], 'Destinatarios'))
        id_dest = etree.SubElement(destinatario, etree.QName(nsmap['sum1'], 'IDDestinatario'))
        etree.SubElement(id_dest, etree.QName(nsmap['sum1'], 'NombreRazon')).text = self.party.name
        etree.SubElement(id_dest, etree.QName(nsmap['sum1'], 'NIF')).text = self.party.tax_identifier.code

        return etree.tostring(envelope, pretty_print=True, encoding='UTF-8', xml_declaration=True)

    def send_soap_request(self, xml_data):
        """Send XML to AEAT SOAP service"""
        try:
            wsdl_url =  PROD_WSDL_URL if os.getenv('VERIFACTU_ENV') == 'prod' else TEST_WSDL_URL
            transport = zeep.Transport()
            #add debug line to print where am i executing to know the correct certificate path
            print('current path: ', os.path.dirname(__file__))
            transport.session.verify = '/home/jared/projectes/nantic_facturae/trytond/trytond/modules/aeat_verifactu/Certificado_RPJ_A39200019_CERTIFICADO_ENTIDAD_PRUEBAS_4_Pre.p12'
            client = zeep.Client(wsdl=wsdl_url, transport=transport)
            response = client.service.RegFactuSistemaFacturacion(xml_data)
            print('response ok')
            return response
        except Exception as e:
            print(e)
            LOGGER.error(f"Error sending invoice to VeriFactu: {e}")
            return {'error': str(e)}
            

    def process_response(self, response):
        print(response)
        """Process AEAT response"""
        self.last_verifactu_response = str(response)
        if isinstance(response, dict) and 'CSV' in response:
            self.csv_code = response['CSV']
            self.verifactu_status = 'accepted'
        elif isinstance(response, dict) and 'error' in response:
            self.verifactu_status = 'rejected'
        else:
            self.verifactu_status = 'sent'
        self.save()

    def query_verifactu_invoice(self):
        """Query invoice status from VeriFactu"""
        try:
            wsdl_url = PROD_WSDL_URL if os.getenv('VERIFACTU_ENV') == 'prod' else TEST_WSDL_URL
            client = zeep.Client(wsdl=wsdl_url)
            response = client.service.ConsultaFactuSistemaFacturacion()
            return response
        except Exception as e:
            LOGGER.error(f"Error querying invoice from VeriFactu: {e}")
            return {'error': str(e)}
