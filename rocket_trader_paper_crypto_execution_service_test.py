#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the fail-closed Paper crypto execution startup gate."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rocket_trader_paper_crypto_execution_service import (
    PaperCryptoExecutionService,
    PaperExecutionStartupError,
)
import rocket_trader_crypto_paper_execution as execution_adapter


def successful_recovery():
    return {
        "mode": "PAPER",
        "read_only": True,
        "orders_scanned": 2,
        "orders_reconciled": 2,
        "orders_unresolved": 0,
        "orders_failed": 0,
        "status": "SUCCESS",
        "orders": [],
    }


class PaperCryptoExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Mock()
        self.adapter.verify_account.return_value = {"mode": "PAPER"}
        self.adapter.recover_journaled_orders.return_value = successful_recovery()
        self.adapter.submit.return_value = {
            "accepted": True, "mode": "PAPER", "order_id": "paper-order-1",
        }
        self.service = PaperCryptoExecutionService(self.adapter)

    def test_submission_is_blocked_before_startup_recovery(self):
        with self.assertRaisesRegex(PaperExecutionStartupError, "gate is closed"):
            self.service.submit(object())
        self.adapter.submit.assert_not_called()
        self.adapter.verify_account.assert_not_called()

    def test_start_verifies_account_and_recovers_before_opening_gate(self):
        result = self.service.start()
        self.assertTrue(result["ready"])
        self.assertEqual(result["mode"], "PAPER")
        self.adapter.verify_account.assert_called_once_with()
        self.adapter.recover_journaled_orders.assert_called_once_with()
        self.assertTrue(self.service.health()["ready"])

    def test_successful_start_allows_paper_submission(self):
        self.service.start()
        result = self.service.submit("intent")
        self.assertTrue(result["accepted"])
        self.adapter.submit.assert_called_once_with("intent")

    def test_unresolved_journal_keeps_gate_closed(self):
        recovery = successful_recovery()
        recovery.update({
            "status": "REQUIRES_REVIEW",
            "orders_reconciled": 1,
            "orders_unresolved": 1,
        })
        self.adapter.recover_journaled_orders.return_value = recovery
        with self.assertRaisesRegex(PaperExecutionStartupError, "incomplete"):
            self.service.start()
        self.assertFalse(self.service.health()["ready"])
        with self.assertRaises(PaperExecutionStartupError):
            self.service.submit("intent")
        self.adapter.submit.assert_not_called()

    def test_malformed_recovery_counts_fail_closed_even_with_success_status(self):
        recovery = successful_recovery()
        recovery["orders_scanned"] = "2"
        self.adapter.recover_journaled_orders.return_value = recovery
        with self.assertRaisesRegex(PaperExecutionStartupError, "malformed"):
            self.service.start()
        self.assertFalse(self.service.health()["ready"])

    def test_recovery_must_be_read_only_paper_and_fully_reconciled(self):
        for field, value in (
            ("mode", "LIVE"),
            ("read_only", False),
            ("orders_failed", 1),
            ("orders_unresolved", 1),
            ("orders_reconciled", 1),
        ):
            with self.subTest(field=field):
                self.setUp()
                recovery = successful_recovery()
                recovery[field] = value
                self.adapter.recover_journaled_orders.return_value = recovery
                with self.assertRaises(PaperExecutionStartupError):
                    self.service.start()
                self.assertFalse(self.service.health()["ready"])

    def test_account_preflight_exception_keeps_gate_closed(self):
        self.adapter.verify_account.side_effect = RuntimeError("offline fake")
        with self.assertRaisesRegex(PaperExecutionStartupError, "verification/recovery failed"):
            self.service.start()
        self.adapter.recover_journaled_orders.assert_not_called()
        self.adapter.submit.assert_not_called()
        self.assertFalse(self.service.health()["ready"])

    def test_adapter_error_closes_gate_until_a_new_recovery_pass(self):
        self.service.start()
        self.adapter.submit.side_effect = RuntimeError("offline fake")
        with self.assertRaisesRegex(PaperExecutionStartupError, "gate closed"):
            self.service.submit("first")
        self.assertFalse(self.service.health()["ready"])
        with self.assertRaises(PaperExecutionStartupError):
            self.service.submit("second")
        self.adapter.submit.assert_called_once_with("first")
        self.adapter.submit.side_effect = None
        self.service.start()
        self.assertTrue(self.service.health()["ready"])

    def test_stop_closes_gate_without_calling_broker(self):
        self.service.start()
        self.service.stop()
        self.assertFalse(self.service.health()["ready"])
        self.assertTrue(self.service.health()["closed"])
        self.adapter.submit.assert_not_called()
        with self.assertRaises(PaperExecutionStartupError):
            self.service.start()

    def test_factory_requires_existing_durable_journal_and_event_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "execution.sqlite3")
            events = str(Path(tmp) / "events.sqlite3")
            os.environ["ALPACA_PAPER"] = "true"
            os.environ["ALPACA_LIVE_ENABLED"] = "false"
            try:
                with self.assertRaisesRegex(PaperExecutionStartupError, "Existing durable"):
                    PaperCryptoExecutionService.from_existing_storage(
                        db_path=db, event_ledger_path=events, client=object()
                    )
                with sqlite3.connect(db) as conn:
                    conn.execute(
                        """CREATE TABLE crypto_paper_order_journal (
                        client_order_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        broker_order_id TEXT,
                        broker_status TEXT,
                        filled_qty TEXT,
                        filled_avg_price TEXT,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                    )
                with self.assertRaisesRegex(PaperExecutionStartupError, "Existing durable"):
                    PaperCryptoExecutionService.from_existing_storage(
                        db_path=db, event_ledger_path=events, client=object()
                    )
                with sqlite3.connect(events) as conn:
                    conn.executescript("""CREATE TABLE execution_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        aggregate_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    );
                    CREATE TRIGGER execution_events_no_update
                    BEFORE UPDATE ON execution_events
                    BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                    CREATE TRIGGER execution_events_no_delete
                    BEFORE DELETE ON execution_events
                    BEGIN SELECT RAISE(ABORT, 'append-only'); END;""")
                fake_adapter = Mock()
                with patch.object(
                    execution_adapter, "AlpacaCryptoPaperExecutionAdapter",
                    return_value=fake_adapter,
                ) as adapter_factory:
                    service = PaperCryptoExecutionService.from_existing_storage(
                        db_path=db, event_ledger_path=events, client=object()
                    )
                adapter_factory.assert_called_once()
                self.assertIs(service.adapter, fake_adapter)
            finally:
                os.environ.pop("ALPACA_PAPER", None)
                os.environ.pop("ALPACA_LIVE_ENABLED", None)

    def test_factory_rejects_live_and_non_paper_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "execution.sqlite3")
            events = str(Path(tmp) / "events.sqlite3")
            with sqlite3.connect(db) as conn:
                conn.execute(
                    """CREATE TABLE crypto_paper_order_journal (
                        client_order_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        broker_order_id TEXT,
                        broker_status TEXT,
                        filled_qty TEXT,
                        filled_avg_price TEXT,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )
            with sqlite3.connect(events) as conn:
                conn.executescript("""CREATE TABLE execution_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        aggregate_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    );
                    CREATE TRIGGER execution_events_no_update
                    BEFORE UPDATE ON execution_events
                    BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                    CREATE TRIGGER execution_events_no_delete
                    BEFORE DELETE ON execution_events
                    BEGIN SELECT RAISE(ABORT, 'append-only'); END;""")
            os.environ["ALPACA_PAPER"] = "true"
            os.environ["ALPACA_LIVE_ENABLED"] = "true"
            try:
                with patch.object(execution_adapter, "AlpacaCryptoPaperExecutionAdapter") as factory:
                    with self.assertRaisesRegex(PaperExecutionStartupError, "LIVE"):
                        PaperCryptoExecutionService.from_existing_storage(
                            db_path=db, event_ledger_path=events, client=object()
                        )
                    factory.assert_not_called()
                os.environ["ALPACA_LIVE_ENABLED"] = "false"
                os.environ["ALPACA_PAPER"] = "false"
                with patch.object(execution_adapter, "AlpacaCryptoPaperExecutionAdapter") as factory:
                    with self.assertRaisesRegex(PaperExecutionStartupError, "ALPACA_PAPER"):
                        PaperCryptoExecutionService.from_existing_storage(
                            db_path=db, event_ledger_path=events, client=object()
                        )
                    factory.assert_not_called()
            finally:
                os.environ.pop("ALPACA_PAPER", None)
                os.environ.pop("ALPACA_LIVE_ENABLED", None)

    def test_start_is_idempotent_while_ready(self):
        first = self.service.start()
        second = self.service.start()
        self.assertTrue(first["ready"] and second["ready"])
        self.adapter.verify_account.assert_called_once_with()
        self.adapter.recover_journaled_orders.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
