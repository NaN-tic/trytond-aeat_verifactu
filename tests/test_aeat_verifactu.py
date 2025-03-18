# This file is part aeat_verifactu module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import unittest


from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import suite as test_suite


class AeatVerifactuTestCase(ModuleTestCase):
    'Test Aeat Verifactu module'
    module = 'aeat_verifactu'


def suite():
    suite = test_suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
            AeatVerifactuTestCase))
    return suite
