# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import hashlib
from decimal import Decimal
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError, UserWarning
from trytond.wizard import Wizard, StateView, StateTransition, Button
from .aeat import (
    OPERATION_KEY, COMMUNICATION_TYPE, AEAT_INVOICE_STATE)
from . import service
from . import tools
from datetime import datetime


_VERIFACTU_INVOICE_KEYS = ['verifactu_operation_key']


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    verifactu_operation_key = fields.Selection(OPERATION_KEY, 'Verifactu Operation Key')
    verifactu_records = fields.One2Many('aeat.verifactu.report.lines', 'invoice',
        "Verifactu Report Lines")
    verifactu_state = fields.Selection(AEAT_INVOICE_STATE,
            'Verifactu State', readonly=True)
    verifactu_communication_type = fields.Selection(
        COMMUNICATION_TYPE, 'Verifactu Communication Type', readonly=True)
    verifactu_pending_sending = fields.Boolean('Verifactu Pending Sending Pending',
            readonly=True)
    verifactu_header = fields.Text('Header')
    verifactu_sent = fields.Function(fields.Boolean('Verifactu Sent'),
            'get_verifactu_sent', searcher='search_verifactu_sent')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        verifactu_fields = {'verifactu_operation_key',
            'verifactu_state', 'verifactu_pending_sending',
            'verifactu_communication_type', 'verifactu_header'}
        cls._check_modify_exclude |= verifactu_fields
        if hasattr(cls, '_intercompany_excluded_fields'):
            cls._intercompany_excluded_fields += verifactu_fields
            cls._intercompany_excluded_fields += ['verifactu_records']

        # not allow modify reference when is supplier or not pending to sending
        readonly = (
            (Eval('state') != 'draft') & (Eval('type') == 'in') ) | (
            (Eval('state') != 'draft') & ~Bool(Eval('verifactu_pending_sending'))
            )
        if 'readonly' in cls.reference.states:
            cls.reference.states['readonly'] |= readonly

    @classmethod
    def __register__(cls, module_name):
        table = cls.__table_handler__(module_name)

        exist_verifactu_intracomunity_key = table.column_exist(
            'verifactu_intracomunity_key')
        exist_verifactu_subjected_key = table.column_exist('verifactu_subjected_key')
        exist_verifactu_excemption_key = table.column_exist('verifactu_excemption_key')

        super().__register__(module_name)

        if exist_verifactu_intracomunity_key:
            table.drop_column('verifactu_intracomunity_key')
        if exist_verifactu_subjected_key:
            table.drop_column('verifactu_subjected_key')
        if exist_verifactu_excemption_key:
            table.drop_column('verifactu_excemption_key')

    @classmethod
    def get_verifactu_sent(cls, invoices, name):
        for invoice in invoices:
            if invoice.verifactu_records:
                return True
        return False

    @classmethod
    def search_verifactu_sent(cls, name, clause):
        _, operator, value = clause
        if operator not in ('=', '!='):
            return []
        domain = [('verifactu_records', '!=', None)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = [('verifactu_records', '=', None)]
        return domain

    @staticmethod
    def default_verifactu_pending_sending():
        return False

    def _credit(self, **values):
        credit = super()._credit(**values)
        for field in _VERIFACTU_INVOICE_KEYS:
            setattr(credit, field, getattr(self, field))

        credit.verifactu_operation_key = 'R1'
        return credit

    def _set_verifactu_keys(self):
        tax = None
        for t in self.taxes:
            if t.tax and t.tax.tax_used:
                tax = t.tax
                break
        if not tax:
            return
        for field in _VERIFACTU_INVOICE_KEYS:
            setattr(self, field, getattr(tax, field))

    @property
    def verifactu_keys_filled(self):
        if self.verifactu_operation_key and self.type == 'out':
            return True
        return False

    @fields.depends(*_VERIFACTU_INVOICE_KEYS)
    def _on_change_lines_taxes(self):
        super()._on_change_lines_taxes()
        for field in _VERIFACTU_INVOICE_KEYS:
            if getattr(self, field):
                return
        self._set_verifactu_keys()

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('verifactu_records')
        default.setdefault('verifactu_state')
        default.setdefault('verifactu_communication_type')
        default.setdefault('verifactu_operation_key')
        default.setdefault('verifactu_pending_sending')
        default.setdefault('verifactu_header')
        return super().copy(records, default=default)

    def _get_verifactu_operation_key(self):
        return 'R1' if self.untaxed_amount < Decimal(0) else 'F1'

    @classmethod
    def reset_verifactu_keys(cls, invoices):
        to_write = []
        for invoice in invoices:
            if invoice.state == 'canceled':
                continue
            for field in _VERIFACTU_INVOICE_KEYS:
                setattr(invoice, field, None)
            invoice._set_verifactu_keys()
            if not invoice.verifactu_operation_key:
                invoice.verifactu_operation_key = invoice._get_verifactu_operation_key()
            values = invoice._save_values
            if invoice.state in ('posted', 'paid'):
                values['verifactu_pending_sending'] = True
            to_write.extend(([invoice], values))

        if to_write:
            cls.write(*to_write)

    @classmethod
    def process(cls, invoices):
        pool = Pool()
        Warning = pool.get('res.user.warning')

        super().process(invoices)

        invoices_verifactu = ''
        for invoice in invoices:
            if invoice.state != 'draft':
                continue
            if invoice.verifactu_state:
                invoices_verifactu += '\n%s: %s' % (
                    invoice.number, invoice.verifactu_state)
        if invoices_verifactu:
            warning_name = 'invoices_verifactu.' + hashlib.md5(
                ''.join(invoices_verifactu).encode('utf-8')).hexdigest()
            if Warning.check(warning_name):
                raise UserWarning(warning_name,
                        gettext('aeat_verifactu.msg_invoices_verifactu',
                        invoices='\n'.join(invoices_verifactu)))

    @classmethod
    def draft(cls, invoices):
        pool = Pool()
        Warning = pool.get('res.user.warning')

        super().draft(invoices)

        invoices_verifactu = []
        to_write = []
        for invoice in invoices:
            to_write.extend(([invoice], {'verifactu_pending_sending': False}))
            if invoice.verifactu_state:
                invoices_verifactu.append('%s: %s' % (
                    invoice.number, invoice.verifactu_state))
        if invoices_verifactu:
            warning_name = 'invoices_verifactu.' + hashlib.md5(
                ''.join(invoices_verifactu).encode('utf-8')).hexdigest()
            if Warning.check(warning_name):
                raise UserWarning(warning_name,
                        gettext('aeat_verifactu.msg_invoices_verifactu',
                        invoices='\n'.join(invoices_verifactu)))
        if to_write:
            cls.write(*to_write)

    def simplified_serial_number(self, type='first'):
        pool = Pool()
        try:
            SaleLine = pool.get('sale.line')
        except KeyError:
            SaleLine = None

        if self.type == 'out' and SaleLine is not None:
            origin_numbers = [
                line.origin.sale.number
                for line in self.lines
                if isinstance(line.origin, SaleLine)
                ]
            if origin_numbers and type == 'first':
                return min(origin_numbers)
            elif origin_numbers and type == 'last':
                return max(origin_numbers)
            else:
                return ''

    @classmethod
    def get_simplified_invoices(cls, invoices):
        simplified_parties = []  # Simplified party but not invoice
        simplified_invoices = []  # Simplified invoice but not party
        simplifieds = []  # Simplified party and invoice
        for invoice in invoices:
            if (invoice.party.verifactu_identifier_type == 'SI'
                    and (not invoice.verifactu_operation_key
                        or (invoice.verifactu_operation_key not in (
                            'F2', 'F4', 'R5')))):
                simplified_parties.append(invoice)
            elif (invoice.party.verifactu_identifier_type != 'SI'
                    and invoice.verifactu_operation_key
                    and invoice.verifactu_operation_key in ('F2', 'F4', 'R5')):
                simplified_invoices.append(invoice)
            elif (invoice.party.verifactu_identifier_type == 'SI'
                    and invoice.verifactu_operation_key in ('F2', 'F4', 'R5')):
                simplifieds.append(invoice)
        return simplified_parties, simplified_invoices, simplifieds

    @classmethod
    def check_aeat_verifactu_invoices(cls, invoices):
        pool = Pool()
        Warning = pool.get('res.user.warning')

        simplified_parties, simplified_invoices, _ = (
            cls.get_simplified_invoices(invoices))
        if simplified_parties:
            names = ', '.join(m.rec_name for m in simplified_parties[:5])
            if len(simplified_parties) > 5:
                names += '...'
            warning_name = ('%s.aeat_verifactu_simplified_party' % hashlib.md5(
                    str(simplified_parties).encode('utf-8')).hexdigest())
            if Warning.check(warning_name):
                raise UserWarning(warning_name, gettext(
                    'aeat_verifactu.msg_set_simplified_party', invoices=names))
        if simplified_invoices:
            names = ', '.join(m.rec_name for m in simplified_invoices[:5])
            if len(simplified_invoices) > 5:
                names += '...'
            warning_name = ('%s.aeat_verifactu_simplified_invoice' % hashlib.md5(
                    str(simplified_invoices).encode('utf-8')).hexdigest())
            if Warning.check(warning_name):
                raise UserWarning(warning_name, gettext(
                    'aeat_verifactu.msg_set_simplified_invoice', invoices=names))

    @classmethod
    def simplified_aeat_verifactu_invoices(cls, invoices):
        simplified_parties, simplified_invoices, simplifieds = (
            cls.get_simplified_invoices(invoices))
        invoice_keys = {'F2': [], 'F4': [], 'R5': []}
        # If the user accept the warning about change the key in the invoice,
        # because the party has the Simplified key, change the key.
        for invoice in simplified_parties:
            first_invoice = invoice.simplified_serial_number('first')
            last_invoice = invoice.simplified_serial_number('last')
            if invoice.total_amount < 0:
                invoice_keys['R5'].append(invoice)
            elif ((not first_invoice and not last_invoice)
                    or first_invoice == last_invoice):
                invoice_keys['F2'].append(invoice)
            else:
                invoice_keys['F4'].append(invoice)

        # Ensure that if is used the F4 key on Verifactu operation (Invoice summary
        # entry) have more than one simplified number. If not the invoice will
        # be declined, so we change the key before send.
        for invoice in simplified_invoices + simplifieds:
            first_invoice = invoice.simplified_serial_number('first')
            last_invoice = invoice.simplified_serial_number('last')
            if (invoice.verifactu_operation_key == 'F4'
                    and ((not first_invoice and not last_invoice)
                        or first_invoice == last_invoice)):
                invoice_keys['F2'].append(invoice)

        to_write = []
        for key, invoices in invoice_keys.items():
            if invoices:
                to_write.extend((invoices, {'verifactu_operation_key': key}))
        if to_write:
            cls.write(*to_write)

    @classmethod
    def post(cls, invoices):
        to_write = []

        invoices2checkverifactu = []
        for invoice in invoices:
            if not invoice.move or invoice.move.state == 'draft':
                invoices2checkverifactu.append(invoice)

        cls.check_aeat_verifactu_invoices(invoices)
        super().post(invoices)

        # TODO:
        # OUT invoice, check that all tax have the same TipoNoExenta and/or
        # the same Exenta
        # Suejta-Exenta --> Can only be one
        # NoSujeta --> Can only be one

        for invoice in invoices2checkverifactu:
            for tax in invoice.taxes:
                if (tax.tax.verifactu_subjected_key in ('S2', 'S3')
                        and invoice.verifactu_operation_key not in (
                            'F1', 'R1', 'R2', 'R3', 'R4')):
                    raise UserError(
                        gettext('aeat_verifactu.msg_verifactu_operation_key_wrong',
                            invoice=invoice))
        if to_write:
            cls.write(*to_write)

        # Control the simplified operation Verifactu key is setted correctly
        # cls.simplified_aeat_verifactu_invoices(invoices)
        cls.send_verifactu()

    @classmethod
    def send_verifactu(cls):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        verifactu_start_date = Configuration(1).verifactu_start_date
        if not verifactu_start_date:
            return
        invoices = cls.search([('verifactu_sent', '=', False),
                               ('invoice_date', '>=', verifactu_start_date)],
                              order=[('invoice_date', 'ASC')])
        print([x.invoice_date for x in invoices])
        huella, last_line = cls.syncro_query(invoices)
        invoice = invoices[0]
        headers = tools.get_headers(
            name=tools.unaccent(invoice.company.party.name),
            vat='B65247983',
            version='1.0')
        certificate = invoice._get_certificate()

        with certificate.tmp_ssl_credentials() as (crt, key):
            srv = service.bind_issued_invoices_service(
                crt, key, test=True)
            srv.submit(
                headers,
                invoices,
                last_huella=huella,
                last_line=last_line)
        cls.syncro_query(invoices)
        return True

    def get_period(year, period, invoices):
        records = []
        invoice = invoices[0]
        headers = tools.get_headers(
            name=tools.unaccent(invoice.company.party.name),
            vat='B65247983',
            version='1.0')
        certificate = invoice._get_certificate()
        pagination = 'S'
        clave_paginacion = None
        while pagination == 'S':
            with certificate.tmp_ssl_credentials() as (crt, key):
                srv = service.bind_issued_invoices_service(
                    crt, key, test=True)
                res = srv.query(headers, year=year, period=period, clave_paginacion=clave_paginacion)
                invoices = res.RegistroRespuestaConsultaFactuSistemaFacturacion
                if invoices:
                    records.extend(invoices)
            pagination = res.IndicadorPaginacion
            if pagination == 'S':
                clave_paginacion = res.ClavePaginacion
        return records

    @classmethod
    def syncro_query(cls, invoices):
        pool = Pool()
        VerifactuLine = pool.get('aeat.verifactu.report.lines')
        records = []
        today = datetime.today()
        year = today.year
        period = today.month
        attempts = 24
        while attempts > 0:
            records = cls.get_period(year, period, invoices)
            huella = None
            for record in records:
                huella = record['DatosRegistroFacturacion']['Huella']
                verifactu_line = VerifactuLine.search([('huella', '=', huella)])
                if verifactu_line:
                    attempts = 0
                    last_line = verifactu_line[0]
                    break
                else:
                    new_line = VerifactuLine()
                    new_line.huella = huella
                    invoices = cls.search([('number', '=', record['IDFactura']['NumSerieFactura'])])
                    if not invoices:
                        raise UserError(gettext('aeat_verifactu.msg_invoice_not_found'))
                    new_line.invoice = invoices[0]
                    new_line.state = record['EstadoRegistro']['EstadoRegistro']
                    new_line.save()
            period -= 1
            if period == 0:
                period = 12
                year -= 1
            attempts -= 1
        return huella, last_line

    def _get_certificate(self):
        Configuration = Pool().get('account.configuration')
        config = Configuration(1)

        certificate = config.aeat_certificate_verifactu
        if not certificate:
            raise UserError(gettext('aeat_verifactu.msg_missing_certificate'))
        return certificate


    @classmethod
    def cancel(cls, invoices):
        result = super().cancel(invoices)
        to_write = []
        for invoice in invoices:
            if not invoice.cancel_move:
                to_write.append(invoice)
        if to_write:
            cls.write(to_write, {'verifactu_pending_sending': False})
        return result

    @classmethod
    def get_verifactu_header(cls, invoice, delete):
        pool = Pool()
        IssuedMapper = pool.get('aeat.verifactu.issued.invoice.mapper')

        if delete:
            rline = [x for x in invoice.verifactu_records if x.state == 'Correcto'
                and x.verifactu_header is not None]
            if rline:
                return rline[0].verifactu_header
        if invoice.type == 'out':
            mapper = IssuedMapper()
            header = mapper.build_delete_request(invoice)
        return header


class ResetVerifactuKeysStart(ModelView):
    """
    Reset to default Verifactu Keys Start
    """
    __name__ = "aeat.verifactu.reset.keys.start"


class ResetVerifactuKeysEnd(ModelView):
    """
    Reset to default Verifactu Keys End
    """
    __name__ = "aeat.verifactu.reset.keys.end"


class ResetVerifactuKeys(Wizard):
    """
    Reset to default Verifactu Keys
    """
    __name__ = "aeat.verifactu.reset.keys"

    start = StateView('aeat.verifactu.reset.keys.start',
        'aeat_verifactu.aeat_verifactu_reset_keys_start_view', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Reset', 'reset', 'tryton-ok', default=True),
            ])
    reset = StateTransition()
    done = StateView('aeat.verifactu.reset.keys.end',
        'aeat_verifactu.aeat_verifactu_reset_keys_end_view', [
            Button('Ok', 'end', 'tryton-ok', default=True),
            ])

    def transition_reset(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        invoices = Invoice.browse(Transaction().context['active_ids'])
        Invoice.reset_verifactu_keys(invoices)
        Invoice.simplified_aeat_verifactu_invoices(invoices)
        return 'done'
