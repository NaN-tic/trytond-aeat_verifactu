# This file is part grau module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from types import SimpleNamespace
from trytond.tests.test_tryton import ModuleTestCase

from trytond.modules.aeat_verifactu.invoice import Invoice


class GrauTestCase(ModuleTestCase):
    'Test Verifactu module'
    module = 'aeat_verifactu'

    def test_build_verifactu_records_keeps_local_chain(self):
        invoice_1 = SimpleNamespace(
            number='INV/1',
            verifactu_build_invoice=lambda previous_fingerprint=None,
            last_line=None: {
                'Huella': 'FP-1',
                'PreviousFingerprint': previous_fingerprint,
                'PreviousInvoice': getattr(last_line.invoice, 'number', None)
                    if last_line else None,
            })
        invoice_2 = SimpleNamespace(
            number='INV/2',
            verifactu_build_invoice=lambda previous_fingerprint=None,
            last_line=None: {
                'Huella': 'FP-2',
                'PreviousFingerprint': previous_fingerprint,
                'PreviousInvoice': getattr(last_line.invoice, 'number', None)
                    if last_line else None,
            })

        last_line = SimpleNamespace(
            invoice=SimpleNamespace(number='INV/0'),
            fingerprint='FP-0')

        records = Invoice.build_verifactu_records(
            [invoice_1, invoice_2],
            previous_fingerprint='FP-0',
            last_line=last_line)

        self.assertEqual(records[0]['RegistroAlta']['PreviousFingerprint'], 'FP-0')
        self.assertEqual(records[0]['RegistroAlta']['PreviousInvoice'], 'INV/0')
        self.assertEqual(records[1]['RegistroAlta']['PreviousFingerprint'], 'FP-1')
        self.assertEqual(records[1]['RegistroAlta']['PreviousInvoice'], 'INV/1')

del ModuleTestCase
