#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for read-only staged FILL to ledger-inbox reconciliation."""
import json
import os
import sqlite3
import tempfile
import unittest

from rocket_trader_paper_activity_reconciliation import (
    reconcile_staged_fill_activities,
)


class PaperActivityReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.activity_db = os.path.join(self.tmp.name, "activities.sqlite3")
        self.inbox_db = os.path.join(self.tmp.name, "inbox.sqlite3")
        with sqlite3.connect(self.activity_db) as db:
            db.execute("""CREATE TABLE staged_activities (
                activity_id TEXT PRIMARY KEY, activity_type TEXT, occurred_at TEXT,
                payload_json TEXT, payload_hash TEXT, classification TEXT, staged_at TEXT
            )""")
        with sqlite3.connect(self.inbox_db) as db:
            db.execute("""CREATE TABLE paper_fill_ledger_inbox (
                execution_id TEXT PRIMARY KEY, payload_hash TEXT, payload_json TEXT,
                status TEXT, last_error TEXT, fx_json TEXT, created_at TEXT, updated_at TEXT
            )""")
        self.execution_id = "8efc7b9a-8b2b-4000-9955-d36e7db0df74"
        self.activity = {
            "id": "20261110160000000::" + self.execution_id,
            "activity_type": "FILL", "status": "executed",
            "transaction_time": "2026-11-10T16:00:00Z",
            "symbol": "BTCUSD", "side": "buy", "qty": "0.01",
            "price": "50000.00", "order_id": "order-1",
        }
        self.payload = {
            "event": "fill", "execution_id": self.execution_id,
            "timestamp": "2026-11-10T16:00:00.500Z",
            "symbol": "BTC/USD", "side": "BUY", "qty": "0.010",
            "price": "50000", "order": {
                "id": "order-1", "symbol": "BTC/USD", "side": "BUY"
            }
        }

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, status="PROCESSED", activity=None, payload=None):
        activity = activity or self.activity
        payload = payload or self.payload
        with sqlite3.connect(self.activity_db) as db:
            db.execute(
                "INSERT INTO staged_activities VALUES(?,?,?,?,?,?,?)",
                (activity["id"], "FILL", activity["transaction_time"],
                 json.dumps(activity), "hash", "STAGED_PENDING_RECONCILIATION", "now"),
            )
        with sqlite3.connect(self.inbox_db) as db:
            db.execute(
                "INSERT INTO paper_fill_ledger_inbox VALUES(?,?,?,?,?,?,?,?)",
                (self.execution_id, "hash", json.dumps(payload), status, None, None, "now", "now"),
            )

    def reconcile(self):
        return reconcile_staged_fill_activities(self.activity_db, self.inbox_db)

    def test_timestamp_tolerance_rejects_negative_nonfinite_and_non_numeric_values(self):
        for value in (-0.1, float("nan"), float("inf"), float("-inf"), True, "2"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    reconcile_staged_fill_activities(
                        self.activity_db, self.inbox_db,
                        timestamp_tolerance_seconds=value,
                    )

    def test_matching_processed_fill_reconciles(self):
        self.seed()
        report = self.reconcile()
        self.assertEqual(report["status"], "RECONCILED")
        self.assertEqual(report["staged_fill_activities"], 1)
        self.assertEqual(report["matched_fill_activities"], 1)
        self.assertEqual(report["ledger_processed_fill_activities"], 1)
        self.assertFalse(report["ledger_posting_enabled"])

    def test_missing_inbox_event_is_reported(self):
        with sqlite3.connect(self.activity_db) as db:
            db.execute(
                "INSERT INTO staged_activities VALUES(?,?,?,?,?,?,?)",
                (self.activity["id"], "FILL", self.activity["transaction_time"],
                 json.dumps(self.activity), "hash", "STAGED_PENDING_RECONCILIATION", "now"),
            )
        report = self.reconcile()
        self.assertFalse(report["healthy"])
        self.assertEqual(report["missing_inbox_fills"], 1)

    def test_fee_pending_fill_is_not_reconciled(self):
        self.seed(status="PENDING")
        report = self.reconcile()
        self.assertEqual(report["matched_fill_activities"], 1)
        self.assertEqual(report["pending_or_failed_fills"], 1)
        self.assertFalse(report["healthy"])

    def test_failed_fill_is_not_reconciled(self):
        self.seed(status="FAILED")
        report = self.reconcile()
        self.assertEqual(report["pending"][0]["inbox_status"], "FAILED")
        self.assertFalse(report["healthy"])

    def test_mismatched_price_is_quarantined(self):
        payload = dict(self.payload)
        payload["price"] = "50001"
        self.seed(payload=payload)
        report = self.reconcile()
        self.assertEqual(report["mismatched_fill_payloads"], 1)
        self.assertIn("price", report["mismatches"][0]["differences"])

    def test_mismatched_order_is_quarantined(self):
        payload = dict(self.payload)
        payload["order"] = {"id": "other-order"}
        self.seed(payload=payload)
        report = self.reconcile()
        self.assertEqual(report["mismatched_fill_payloads"], 1)
        self.assertIn("order_id", report["mismatches"][0]["differences"])

    def test_equity_symbols_match_without_crypto_suffix_normalization(self):
        activity = dict(self.activity)
        activity["symbol"] = "SPY"
        payload = dict(self.payload)
        payload["symbol"] = "SPY"
        self.seed(activity=activity, payload=payload)
        report = self.reconcile()
        self.assertEqual(report["status"], "RECONCILED")

    def test_activity_and_inbox_databases_are_opened_read_only(self):
        self.seed()
        self.reconcile()
        with sqlite3.connect(self.activity_db) as db:
            row = db.execute("SELECT COUNT(*) FROM staged_activities").fetchone()
        self.assertEqual(row[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
