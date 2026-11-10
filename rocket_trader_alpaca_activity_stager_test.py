#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for read-only Alpaca Paper activity staging."""

import os
import tempfile
import unittest

from rocket_trader_alpaca_activity_stager import (
    ActivityIngestionError, AlpacaPaperActivityStager,
)


def fill(activity_id="fill-1", qty="0.01"):
    return {
        "id": activity_id,
        "activity_type": "FILL",
        "status": "executed",
        "transaction_time": "2026-11-09T16:00:00Z",
        "symbol": "BTCUSD",
        "side": "buy",
        "qty": qty,
        "price": "50000",
        "order_id": "order-1",
    }


class ActivityStagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "activities.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, pages=None, page_size=100):
        pages = list(pages or [])
        def fetch(cursor, size):
            if not pages:
                return []
            return pages.pop(0)
        return AlpacaPaperActivityStager(
            db_path=self.db, fetch_page=fetch, page_size=page_size
        )

    def test_stages_fill_but_never_marks_it_ledger_ready(self):
        stager = self.make([[fill()]])
        report = stager.sync()
        self.assertEqual(report["total_staged"], 1)
        self.assertFalse(report["ledger_posting_enabled"])
        self.assertIn("FILL:STAGED_PENDING_RECONCILIATION", report["counts"])

    def test_idempotent_redelivery(self):
        stager = self.make([[fill()], [fill()]])
        first = stager.sync(max_pages=1)
        second = stager.sync(max_pages=1)
        self.assertEqual(first["inserted_this_sync"], 1)
        self.assertEqual(second["duplicates_this_sync"], 1)
        self.assertEqual(second["total_staged"], 1)

    def test_changed_duplicate_fails_closed_without_cursor_advance(self):
        stager = self.make([[fill()]])
        stager.sync(max_pages=1)
        with self.assertRaisesRegex(ActivityIngestionError, "changed content"):
            stager.stage_page([fill(qty="0.02")])
        self.assertEqual(stager.report()["cursor"], "fill-1")

    def test_unsupported_activity_blocks_automated_reconciliation(self):
        activity = {
            "id": "split-1", "activity_type": "SPLIT",
            "status": "executed", "symbol": "SPY",
        }
        report = self.make([[activity]]).sync()
        self.assertEqual(report["blocked_activity_types"], ["SPLIT"])
        self.assertFalse(report["ledger_posting_enabled"])

    def test_missing_activity_id_does_not_advance_cursor(self):
        stager = self.make([[fill()]])
        with self.assertRaisesRegex(ActivityIngestionError, "missing id"):
            stager.stage_page([{"activity_type": "FILL"}])
        self.assertIsNone(stager.report()["cursor"])

    def test_fee_activities_are_staged_separately(self):
        cfee = {
            "id": "cfee-1", "activity_type": "CFEE", "status": "executed",
            "date": "2026-11-09", "symbol": "BTCUSD", "qty": "-0.00001",
            "price": "50000", "net_amount": "0",
        }
        fee = {
            "id": "fee-1", "activity_type": "FEE", "status": "executed",
            "date": "2026-11-09", "net_amount": "-0.01", "currency": "USD",
        }
        report = self.make([[cfee, fee]]).sync()
        self.assertIn("CFEE:STAGED_PENDING_RECONCILIATION", report["counts"])
        self.assertIn("FEE:STAGED_PENDING_RECONCILIATION", report["counts"])

    def test_non_final_fill_status_is_blocked(self):
        row = fill()
        row["status"] = "pending"
        report = self.make([[row]]).sync()
        self.assertEqual(report["blocked_activity_types"], ["FILL"])

    def test_jnlc_cash_journal_is_staged_pending_capital_reconciliation(self):
        activity = {
            "id": "paper-seed-journal-1", "activity_type": "JNLC",
            "status": "executed", "date": "2026-09-28",
            "net_amount": "100000.00", "currency": "USD",
        }
        report = self.make([[activity]]).sync()
        self.assertIn(
            "JNLC:STAGED_PENDING_CAPITAL_RECONCILIATION", report["counts"]
        )
        self.assertFalse(report["ledger_posting_enabled"])

    def test_cash_deposit_credit_is_staged_for_capital_reconciliation_only(self):
        activity = {
            "id": "cash-deposit-1", "activity_type": "CSD",
            "status": "executed", "date": "2026-11-10",
            "net_amount": "250.00", "currency": "USD",
        }
        report = self.make([[activity]]).sync()
        self.assertIn(
            "CSD:STAGED_PENDING_CAPITAL_RECONCILIATION", report["counts"]
        )
        self.assertFalse(report["ledger_posting_enabled"])

    def test_cash_withdrawal_debit_is_staged_not_counted_as_profit(self):
        activity = {
            "id": "cash-withdrawal-1", "activity_type": "CSW",
            "status": "executed", "date": "2026-11-10",
            "net_amount": "-100.00", "currency": "USD",
        }
        report = self.make([[activity]]).sync()
        self.assertIn(
            "CSW:STAGED_PENDING_CAPITAL_RECONCILIATION", report["counts"]
        )
        self.assertFalse(report["ledger_posting_enabled"])

    def test_invalid_cash_credit_sign_is_blocked(self):
        activity = {
            "id": "cash-credit-invalid", "activity_type": "CSD",
            "status": "executed", "date": "2026-11-10",
            "net_amount": "-100.00", "currency": "USD",
        }
        report = self.make([[activity]]).sync()
        self.assertIn(
            "CSD:BLOCKED_INVALID_CASH_CREDIT_SIGN", report["counts"]
        )
        self.assertFalse(report["ledger_posting_enabled"])

    def test_cash_activity_without_currency_is_blocked(self):
        activity = {
            "id": "cash-no-currency", "activity_type": "CSD",
            "status": "executed", "date": "2026-11-10",
            "net_amount": "100.00",
        }
        report = self.make([[activity]]).sync()
        self.assertIn(
            "CSD:BLOCKED_CASH_ACTIVITY_WITHOUT_CURRENCY", report["counts"]
        )

    def test_cash_movements_returns_only_durable_cash_review_rows(self):
        rows = [
            {"id": "deposit-1", "activity_type": "CSD", "status": "executed",
             "date": "2026-11-10", "net_amount": "250", "currency": "USD"},
            {"id": "seed-1", "activity_type": "JNLC", "status": "executed",
             "date": "2026-09-28", "net_amount": "100000", "currency": "USD"},
            {"id": "fill-1", **fill("fill-1")},
        ]
        stager = self.make([rows])
        stager.sync()
        movements = stager.cash_movements()
        self.assertEqual({row["id"] for row in movements}, {"deposit-1", "seed-1"})
        self.assertTrue(all(row["activity_type"] in {"CSD", "CSW", "JNLC"} for row in movements))

    def test_rejects_live_configuration(self):
        old_live = os.environ.get("ALPACA_LIVE_ENABLED")
        old_mode = os.environ.get("ROCKET_TRADER_EXECUTION_MODE")
        try:
            os.environ["ALPACA_LIVE_ENABLED"] = "true"
            with self.assertRaises(ActivityIngestionError):
                self.make()
        finally:
            if old_live is None:
                os.environ.pop("ALPACA_LIVE_ENABLED", None)
            else:
                os.environ["ALPACA_LIVE_ENABLED"] = old_live
            if old_mode is None:
                os.environ.pop("ROCKET_TRADER_EXECUTION_MODE", None)
            else:
                os.environ["ROCKET_TRADER_EXECUTION_MODE"] = old_mode


if __name__ == "__main__":
    unittest.main(verbosity=2)
