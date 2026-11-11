#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the read-only Paper execution recovery runner."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import alpaca_paper_crypto_execution_recovery_worker as worker


class FakeRecoveryAdapter:
    instances = []

    def __init__(self, db_path, client, event_ledger_path):
        self.db_path = db_path
        self.client = client
        self.event_ledger_path = event_ledger_path
        self.instances.append(self)

    def verify_account(self):
        return {"mode": "PAPER"}

    def recover_journaled_orders(self):
        return {
            "mode": "PAPER",
            "read_only": True,
            "orders_scanned": 1,
            "orders_reconciled": 1,
            "orders_unresolved": 0,
            "orders_failed": 0,
            "status": "SUCCESS",
            "orders": [],
        }


class FakeTradingClient:
    instances = []

    def __init__(self, key, secret, paper):
        self.paper = paper
        self.instances.append(self)


class RecoveryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "execution.sqlite3")
        self.events = self.db + ".events.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE crypto_paper_order_journal (client_order_id TEXT PRIMARY KEY)"
            )
        Path(self.events).touch()
        self.report = str(Path(self.tmp.name) / "report.json")
        os.environ.update({
            "ALPACA_PAPER": "true",
            "ALPACA_LIVE_ENABLED": "false",
            "ROCKET_TRADER_EXECUTION_MODE": "PAPER",
            "ALPACA_API_KEY": "paper-key",
            "ALPACA_SECRET_KEY": "paper-secret",
            "ROCKET_TRADER_CRYPTO_EXECUTION_DB": self.db,
            "ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB": self.events,
            "ROCKET_TRADER_RECOVERY_REPORT": self.report,
        })
        FakeRecoveryAdapter.instances = []
        FakeTradingClient.instances = []

    def tearDown(self):
        for key in (
            "ALPACA_PAPER", "ALPACA_LIVE_ENABLED", "ROCKET_TRADER_EXECUTION_MODE",
            "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
            "ROCKET_TRADER_CRYPTO_EXECUTION_DB",
            "ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB",
            "ROCKET_TRADER_RECOVERY_REPORT",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_runs_read_only_recovery_against_paper_client(self):
        output = StringIO()
        with patch.object(worker, "TradingClient", FakeTradingClient), \
             patch.object(worker, "AlpacaCryptoPaperExecutionAdapter", FakeRecoveryAdapter), \
             redirect_stdout(output):
            result = worker.main()
        self.assertEqual(result, 0)
        self.assertTrue(FakeTradingClient.instances[0].paper)
        self.assertEqual(len(FakeRecoveryAdapter.instances), 1)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "SUCCESS")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["orders_reconciled"], 1)

    def test_refuses_live_before_creating_broker_client(self):
        os.environ["ALPACA_LIVE_ENABLED"] = "true"
        with patch.object(worker, "TradingClient", FakeTradingClient):
            result = worker.main()
        self.assertEqual(result, 1)
        self.assertEqual(FakeTradingClient.instances, [])

    def test_refuses_missing_journal_instead_of_initializing_empty_database(self):
        os.environ["ROCKET_TRADER_CRYPTO_EXECUTION_DB"] = self.db + ".missing"
        stderr = StringIO()
        with patch.object(worker, "TradingClient", FakeTradingClient), redirect_stderr(stderr):
            result = worker.main()
        self.assertEqual(result, 1)
        self.assertEqual(FakeTradingClient.instances, [])
        self.assertIn("does not exist", stderr.getvalue())

    def test_refuses_missing_event_ledger(self):
        os.environ["ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB"] = self.events + ".missing"
        with patch.object(worker, "TradingClient", FakeTradingClient):
            result = worker.main()
        self.assertEqual(result, 1)
        self.assertEqual(FakeTradingClient.instances, [])

    def test_unresolved_recovery_returns_nonzero(self):
        class UnresolvedAdapter(FakeRecoveryAdapter):
            def recover_journaled_orders(self):
                return {"mode": "PAPER", "read_only": True, "status": "REQUIRES_REVIEW"}
        with patch.object(worker, "TradingClient", FakeTradingClient), \
             patch.object(worker, "AlpacaCryptoPaperExecutionAdapter", UnresolvedAdapter), \
             redirect_stdout(StringIO()):
            result = worker.main()
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
