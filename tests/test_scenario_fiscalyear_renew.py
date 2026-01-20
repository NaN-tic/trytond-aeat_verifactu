# This file is part aeat_verifactu module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import unittest

from proteus import Model, Wizard
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules

from tools import setup


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test_renew_copies_verifactu_flag(self):
        activate_modules(['aeat_verifactu'])

        vars = setup()
        vars.fiscalyear.es_verifactu_send_invoices = False
        vars.fiscalyear.save()

        renew_fiscalyear = Wizard('account.fiscalyear.renew')
        renew_fiscalyear.form.reset_sequences = False
        renew_fiscalyear.execute('create_')
        new_fiscalyear, = renew_fiscalyear.actions[0]

        FiscalYear = Model.get('account.fiscalyear')
        self.assertEqual(
            FiscalYear(new_fiscalyear.id).es_verifactu_send_invoices,
            vars.fiscalyear.es_verifactu_send_invoices)

