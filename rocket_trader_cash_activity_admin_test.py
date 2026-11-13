#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for fail-closed cash activity administration."""

import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import rocket_trader_cash_activity_admin as admin
from rocket_trader_alpaca_activity_stager import AlpacaPaperActivityStager
from rocket_trader_realized_pnl_ledger import RealizedPnLLedger


class CashActivityAdminStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_path = os.path.join(self.tmp.name, "ledger.sqlite3")
        self.stager_path = os.path.join(self.tmp.name, "stager.sqlite3")
        self.env = patch.dict(os.environ, {
            "ROCKET_TRADER_DATA_DIR": self.tmp.name,
            "ROCKET_TRADER_LEDGER_DB": self.ledger_path,
            "ROCKET_TRADER_ACTIVITY_STAGER_DB": self.stager_path,
            "ROCKET_TRADER_INITIAL_CAPITAL_MXN": "1000.00",
            "ROCKET_TRADER_MILESTONE_MXN": "100000.00",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def invoke_list(self):
        output = io.StringIO()
        errors = io.StringIO()
        with patch.object(sys, "argv", ["rocket_trader_cash_activity_admin.py", "--list"]):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = admin.main()
        return code, output.getvalue(), errors.getvalue()

    def test_missing_state_files_are_not_created(self):
        code, _out, err = self.invoke_list()
        self.assertEqual(code, 1)
        self.assertIn("ledger database is missing", err)
        self.assertFalse(os.path.exists(self.ledger_path))
        self.assertFalse(os.path.exists(self.stager_path))

    def test_empty_sqlite_files_are_not_initialized(self):
        sqlite3.connect(self.ledger_path).close()
        sqlite3.connect(self.stager_path).close()
        code, _out, err = self.invoke_list()
        self.assertEqual(code, 1)
        self.assertIn("missing required tables", err)
        for path in (self.ledger_path, self.stager_path):
            with sqlite3.connect(path) as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            self.assertEqual(tables, [])

    def test_existing_valid_state_can_be_listed_without_broker_network(self):
        RealizedPnLLedger(self.ledger_path)
        AlpacaPaperActivityStager(
            db_path=self.stager_path,
            fetch_page=lambda _cursor, _size: [],
        )
        code, output, err = self.invoke_list()
        self.assertEqual(code, 0, err)
        self.assertIn("cash_activity_review", output)
        self.assertIn("operating_capital_mxn", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
