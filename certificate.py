# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from dominate.tags import (body, div, h1, p, b, head,
    html, title)

from trytond.pool import Pool
from trytond.transaction import check_access
from trytond.modules.html_report.html_report import HTMLReport
from trytond.modules.html_report.engine import DualRecord
from trytond.modules.voyager.i18n import _
from .invoice import VERSION


class CertificateReport(HTMLReport):
    __name__ = 'aeat.verifactu.certificate'

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        ActionReport = pool.get('ir.action.report')
        ModelAccess = pool.get('ir.model.access')

        ids = [int(x) for x in ids]

        action_id = data.get('action_id')
        if action_id is None:
            action_reports = ActionReport.search([
                    ('report_name', '=', cls.__name__)
                    ])
            assert action_reports, '%s not found' % cls
            report = action_reports[0]
        else:
            report = ActionReport(action_id)

        model = report.model or data.get('model')
        cls.check_access(report, model, ids)

        Model = None
        records = []
        if model:
            Model = pool.get(model)
            with check_access():
                ModelAccess.check(model, 'read')
                # Check read access
                Model.read(ids, ['id'])
                records = [DualRecord(x) for x in Model.browse(ids)]

        html = cls.html(report, records, data).render()
        extension = report.extension or report.template_extension
        if not Pool.test and extension == 'pdf':
            content = cls.weasyprint(html)
        else:
            content = html

        # TODO: Improve filename
        filename = 'certificate.html'
        return (extension, content, report.direct_print, filename)

    @classmethod
    def html(cls, report, records, data):
        layout = html()
        with layout:
            with head():
                title(_('DECLARACIÓN RESPONSABLE'))
            with body():
                with div():
                    h1('DECLARACIÓN RESPONSABLE DEL SISTEMA INFORMÁTICO DE FACTURACIÓN')
                    p('1.a) Nombre del sistema informático a que se refiere esta declaración responsable:')
                    p(b('Tryton'))
                    p('1.b) Código identificador del sistema informático a que se refiere el apartado a) de esta declaración responsable:')
                    p(b('-'))
                    p('1.c) Identificador completo de la versión concreta del sistema informático a que se refiere esta declaración responsable:')
                    p(b(VERSION))
                    p('1.d) Componentes, hardware y software, de que consta el sistema informático a que se refiere esta declaración responsable, junto con una breve descripción de lo que hace dicho sistema informático y de sus principales funcionalidades:')
                    p(b('Se trata únicamente de un software que permite facturar y gestionar la facturación realizada, entre otros, pues es un ERP, y que se puede instalar en cualquier equipo hardware que tenga las características mínimas requeridas por dicho software y un sistema operativo compatible con él. Este producto está pensado para ser instalado tanto en la nube (SAAS) como en las máquinas propias del usuario situadas en sus dependencias (on-premise). El producto es de 3 capas cliente-servidor-base de datos. Pudiéndose instalar cada uno en una máquina distinta. La parte de cliente no requiere de instalación, pues es entrono web. Este software cuenta con las funcionalidades habituales en este tipo de aplicaciones: capturar información de facturación, expedir facturas, consultar facturas, estadísticas de facturación, exportación de datos de facturación… Este software permite gestionar de forma independiente varias facturaciones dentro de él, cumpliendo separadamente con la normativa mencionada en el apartado 1.k) de esta declaración responsable para cada una de ellas, como si, en la práctica, se tratara de sistemas informáticos de facturación distintos.'))
                    p('1.e) Indicación de si el sistema informático a que se refiere esta declaración responsable se ha producido de tal manera que, a los efectos de cumplir con el Reglamento, solo pueda funcionar exclusivamente como «VERI*FACTU»:')
                    p(b('El software puede ser utilizado en modalidad VERI*FACTU y no admite el uso en modalidad No VERI*FACTU, aunque admite la posibilidad de utilizar el Sistema Inmediateo de Información, o bien utilizar otro software externo para la remisión de los registros de facturación a la Agencia Tributaria.'))
                    p('1.f) Indicación de si el sistema informático a que se refiere la declaración responsable permite ser usado por varios obligados tributarios o por un mismo usuario para dar soporte a la facturación de varios obligados tributarios:')
                    p(b('Sí'))
                    p('1.g) Tipos de firma utilizados para firmar los registros de facturación y de evento en el caso de que el sistema informático a que se refiere esta declaración responsable no sea utilizado como «VERI*FACTU».')
                    p(b('Dado que se trata de un producto de facturación que solo puede ser utilizado exclusivamente en la modalidad de «VERI*FACTU», no se realiza una firma electrónica expresa de los registros de facturación generados, ya que la normativa considera que quedan firmados al ser remitidos correctamente a los servicios electrónicos de la Agencia Tributaria con la debida autenticación mediante el adecuado certificado electrónico cualificado.'))
                    p('1.h) Razón social de la entidad productora del sistema informático a que se refiere esta declaración responsable:')
                    p(b('NaN Projectes de Programari Lliure, S.L.'))
                    p('1.i) Número de identificación fiscal (NIF) español de la entidad productora del sistema informático a que se refiere esta declaración responsable:')
                    p(b('ESB65247983'))
                    p('1.j) Dirección postal completa de contacto de la entidad productora del sistema informático a que se refiere esta declaración responsable:')
                    p(b('Carrer Antoni Cusidó, 92\n08208 - Sabadell (Barcelona)\nEspaña'))
                    p('1.k) La entidad productora del sistema informático a que se refiere esta declaración responsable hace constar que dicho sistema informático, en la versión indicada en ella, cumple con lo dispuesto en el artículo 29.2.j) de la Ley 58/2003, de 17 de diciembre, General Tributaria, en el Reglamento que establece los requisitos que deben adoptar los sistemas y programas informáticos o electrónicos que soporten los procesos de facturación de empresarios y profesionales, y la estandarización de formatos de los registros de facturación, aprobado por el Real Decreto 1007/2023, de 5 de diciembre, en la Orden HAC/1177/2024, de 17 de octubre, y en la sede electrónica de la Agencia Estatal de Administración Tributaria para todo aquello que complete las especificaciones de dicha orden.')
                    p(b(_('Dado que este es software libre desarrollado colaborativamente por varias personas y empresas de todo el mundo, NaN Projectes de Programari Lliure, S.L. asume, sin serlo, el papel de entidad productora del sistema informático Tryton a los efectos de sus clientes y hace constar que Tryton, en la forma en la que NaN Projectes de Programari Lliure lo implanta, cumple con lo dispuesto: En el artículo 29.2.j) de la Ley 58/2003, de 17 de diciembre, General Tributaria. En el Reglamento que establece los requisitos que deben adoptar los sistemas y programas informáticos o electrónicos que soporten los procesos de facturación de empresarios y profesionales, y la estandarización de formatos de los registros de facturación, aprobado por el Real Decreto 1007/2023, de 5 de diciembre. En la Orden HAC/1177/2024 por la que se desarrollan las especificaciones técnicas, funcionales y de contenido referidas en el Reglamento que establece los requisitos que deben adoptar los sistemas y programas informáticos o electrónicos que soporten los procesos de facturación de empresarios y profesionales, y la estandarización de formatos de los registros de facturación, aprobado por el Real Decreto 1007/2023, de 5 de diciembre, y en el artículo 6.5 del Reglamento por el que se regulan las obligaciones de facturación, aprobado por el Real Decreto 1619/2002, de 30 de noviembre. Y con lo dispuesto en la sede electrónica de la Agencia Estatal de Administración Tributaria para todo aquello que complete las especificaciones de la Orden HAC/1177/2024.')))
                    p('1.l) - Fecha en que la entidad productora de este sistema informático suscribe esta declaración responsable del mismo:')
                    p(b('01 de diciembre de 2025'))
                    p('- Lugar en que la entidad productora de este sistema informático suscribe esta declaración responsable del mismo:')
                    p(b('Sabadell (Barcelona) – España'))
                    h1('ANEXO')
                    p('2.a) Otras formas de contacto con la entidad productora del sistema informático a que se refiere esta declaración responsable:')
                    p(b('Teléfono: 935 531 803, Correo electrónico: info@nan-tic.com'))
                    p('2.b) Direcciones de internet de la entidad productora del sistema informático a que se refiere esta declaración responsable:')
                    p(b('Sitio web de la empresa: https://www.nan-tic.com. Información sobre este producto en el sitio web de la empresa: https://www.nan-tic.com/es/tryton-erp.'))
                    p('2.c) El sistema informático a que se refiere esta declaración responsable cumple las diferentes especificaciones técnicas y funcionales contenidas en la Orden HAC/1177/2024, de 17 de octubre, y en la sede electrónica de la Agencia Estatal de Administración Tributaria para todo aquello que complete las especificaciones de dicha orden, de la siguiente manera:')
                    p(b('Además del modo que es de obligado cumplimiento en ciertos casos (como el algoritmo de huella a emplear), otras implementaciones utilizadas son: el empleo de la tecnología transaccional del sistema gestor de base de datos utilizado para lograr la consolidación, en una sola unidad transaccional, de la expedición de la factura y la generación del registro de facturación correspondiente a la factura.'))
        return layout
