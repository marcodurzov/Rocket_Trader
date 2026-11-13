#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rocket_trader_alpaca_cash_ledger import (
    AlpacaPaperUSDCashLedger,
    PaperCashLedgerError,
)


NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
ACCOUNT = "paper-account-1"


def event(ref_id, activity_type, *, amount=None, currency="USD", at=None, details=None, previous_id=None):
    value = {
        "account_id": ACCOUNT,
        "event_id": f"01K9EXAMPLE{ref_id:0>16}"[-26:],
        "ref_id": f"activity-{ref_id}",
        "activity_type": activity_type,
        "activity_subtype": None,
        "status": "executed",
        "at": (at or NOW - timedelta(minutes=5)).isoformat(),
        "executed_at": (at or NOW - timedelta(minutes=5)).isoformat(),
        "currency": currency,
        "details": details or {},
    }
    if amount is not None:
        value["net_amount"] = str(amount)
    if previous_id is not None:
        value["previous_id"] = previous_id
    return value


class AlpacaPaperUSDCashLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cash.sqlite3")
        self.ledger = AlpacaPaperUSDCashLedger(self.db, account_id=ACCOUNT)
        self.ledger.record_anchor(
            anchor_id="anchor-1", cash_usd="1000",
            observed_at=NOW - timedelta(minutes=10),
            source_reference="paper-account-snapshot-1",
            activity_cursor_before_snapshot="01K9ANCHORCURSOR000000000000",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_reconciles_usd_cash_from_trade_fee_dividend_and_journal_events(self):
        events = [
            event(1, "TRD", amount="-100", details={"side": "buy"}),
            event(2, "TRD", amount="150", details={"side": "sell"}),
            event(3, "DIV", amount="5"),
            event(4, "JNLC", amount="-10"),
            event(5, "FEE", amount="-1", details={"parent_id": "activity-1"}),
        ]
        for item in events:
            self.ledger.ingest_activity(item)
        report = self.ledger.reconcile(
            broker_cash_usd="1044", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
            fee_reconciliation_complete=False,
        )
        self.assertEqual(report["cash_reconciliation_status"], "RECONCILED")
        self.assertTrue(report["account_cash_reconciliation_complete"])
        self.assertEqual(report["expected_cash_usd"], "1044")
        self.assertEqual(report["fee_reconciliation_status"], "UNRESOLVED")
        self.assertFalse(report["orders_enabled"])

    def test_fee_reconciliation_requires_explicit_allocation_evidence(self):
        self.ledger.ingest_activity(event(1, "FEE", amount="-2"))
        report = self.ledger.reconcile(
            broker_cash_usd="998", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
            fee_reconciliation_complete=False,
        )
        self.assertEqual(report["fee_reconciliation_status"], "UNRESOLVED")
        self.assertEqual(report["pending_fee_allocation_count"], 1)

    def test_fee_completion_requires_traceable_fee_audit_evidence(self):
        with self.assertRaisesRegex(PaperCashLedgerError, "fee reconciliation requires"):
            self.ledger.reconcile(
                broker_cash_usd="1000", broker_account_id=ACCOUNT,
                observed_at=NOW, activity_coverage_complete=True,
                activity_coverage_reference="test-catch-up-proof",
                activity_coverage_checked_at=NOW,
                fee_reconciliation_complete=True,
            )

    def test_external_fee_resolver_can_explicitly_clear_fee_allocation(self):
        self.ledger.ingest_activity(event(1, "FEE", amount="-2"))
        report = self.ledger.reconcile(
            broker_cash_usd="998", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
            fee_reconciliation_complete=True,
            fee_reconciliation_reference="test-fee-audit-1",
            fee_reconciliation_checked_at=NOW,
        )
        self.assertEqual(report["fee_reconciliation_status"], "RECONCILED")
        self.assertEqual(report["pending_fee_allocation_count"], 0)
        self.assertEqual(report["fee_candidates_without_local_parent_count"], 1)

    def test_non_usd_zero_cash_fee_does_not_change_usd_cash_but_remains_unallocated(self):
        self.ledger.ingest_activity(event(1, "CFEE", amount="0", currency="ETH"))
        report = self.ledger.reconcile(
            broker_cash_usd="1000", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
            fee_reconciliation_complete=False,
        )
        self.assertEqual(report["cash_reconciliation_status"], "RECONCILED")
        self.assertEqual(report["fee_reconciliation_status"], "UNRESOLVED")

    def test_unknown_activity_blocks_cash_reconciliation(self):
        self.ledger.ingest_activity(event(1, "NEW_CLEARING_CODE", amount="10"))
        report = self.ledger.reconcile(
            broker_cash_usd="1010", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(report["cash_reconciliation_status"], "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW")
        self.assertFalse(report["account_cash_reconciliation_complete"])

    def test_trade_correction_or_bust_blocks_reconciliation(self):
        self.ledger.ingest_activity(event(1, "TRD", amount="10", details={"side": "sell"}, previous_id="old-trade"))
        report = self.ledger.reconcile(
            broker_cash_usd="1010", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(report["cash_reconciliation_status"], "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW")

    def test_trade_cash_sign_conflict_blocks_reconciliation(self):
        self.ledger.ingest_activity(event(1, "TRD", amount="10", details={"side": "buy"}))
        report = self.ledger.reconcile(
            broker_cash_usd="1010", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(report["cash_reconciliation_status"], "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW")

    def test_incomplete_activity_history_blocks_reconciliation(self):
        report = self.ledger.reconcile(
            broker_cash_usd="1000", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=False,
        )
        self.assertEqual(report["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")

    def test_cash_mismatch_is_reported(self):
        self.ledger.ingest_activity(event(1, "DIV", amount="5"))
        report = self.ledger.reconcile(
            broker_cash_usd="1007", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(report["cash_reconciliation_status"], "CASH_BALANCE_MISMATCH")
        self.assertEqual(report["difference_usd"], "2")

    def test_duplicate_activity_is_idempotent_and_collision_is_rejected(self):
        item = event(1, "DIV", amount="5")
        self.assertEqual(self.ledger.ingest_activity(item)["status"], "STAGED")
        self.assertEqual(self.ledger.ingest_activity(item)["status"], "DUPLICATE_ACTIVITY")
        changed = dict(item, net_amount="6")
        with self.assertRaisesRegex(PaperCashLedgerError, "collision"):
            self.ledger.ingest_activity(changed)

    def test_activity_from_another_account_is_rejected(self):
        item = event(1, "DIV", amount="5")
        item["account_id"] = "other-account"
        with self.assertRaisesRegex(PaperCashLedgerError, "does not match"):
            self.ledger.ingest_activity(item)

    def test_anchor_is_immutable_and_later_anchors_must_be_later(self):
        with self.assertRaisesRegex(PaperCashLedgerError, "collision"):
            self.ledger.record_anchor(
                anchor_id="anchor-1", cash_usd="999",
                observed_at=NOW - timedelta(minutes=10),
                source_reference="changed",
            )
        with self.assertRaisesRegex(PaperCashLedgerError, "later"):
            self.ledger.record_anchor(
                anchor_id="anchor-2", cash_usd="1000",
                observed_at=NOW - timedelta(minutes=11),
                source_reference="paper-account-snapshot-2",
            )
        with self.assertRaisesRegex(PaperCashLedgerError, "explicit rebase confirmation"):
            self.ledger.record_anchor(
                anchor_id="anchor-2", cash_usd="1000",
                observed_at=NOW, source_reference="paper-account-snapshot-2",
            )
        rebased = self.ledger.record_anchor(
            anchor_id="anchor-2", cash_usd="1000", observed_at=NOW,
            source_reference="paper-account-snapshot-2",
            rebase_confirmed=True, rebase_reason="Operator-reviewed broker cash mismatch closure",
        )
        self.assertEqual(rebased["status"], "ANCHORED")
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE paper_cash_anchors SET cash_usd='0' WHERE anchor_id='anchor-1'")

    def test_missing_anchor_blocks_reconciliation(self):
        other = AlpacaPaperUSDCashLedger(
            os.path.join(self.tmp.name, "other.sqlite3"), account_id=ACCOUNT
        )
        report = other.reconcile(
            broker_cash_usd="1000", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=True,
            activity_coverage_reference="test-catch-up-proof",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(report["status"], "CASH_ANCHOR_REQUIRED")

    def test_complete_coverage_requires_traceable_replay_evidence(self):
        with self.assertRaisesRegex(PaperCashLedgerError, "traceable reference"):
            self.ledger.reconcile(
                broker_cash_usd="1000", broker_account_id=ACCOUNT,
                observed_at=NOW, activity_coverage_complete=True,
            )

    def test_ingests_verified_activity_sse_inbox_without_claiming_coverage(self):
        from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
        inbox_path = os.path.join(self.tmp.name, "activity-inbox.sqlite3")
        inbox = DurableActivitySSEInbox(inbox_path)
        payload = event(
            1, "TRD", amount="-25",
            at=NOW - timedelta(minutes=5),
            details={"side": "buy", "execution_type": "fill"},
        )
        payload["event_id"] = "00000000000000000000000001"
        inbox.stage(payload)
        report = self.ledger.ingest_from_activity_sse_inbox(
            inbox_db_path=inbox_path, page_size=1,
        )
        self.assertTrue(report["inbox_integrity_valid"])
        self.assertEqual(report["staged_count"], 1)
        self.assertFalse(report["activity_coverage_complete"])
        cash = self.ledger.reconcile(
            broker_cash_usd="975", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=False,
        )
        self.assertEqual(cash["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")

    def test_corrupt_activity_sse_inbox_is_rejected(self):
        from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
        inbox_path = os.path.join(self.tmp.name, "corrupt-inbox.sqlite3")
        inbox = DurableActivitySSEInbox(inbox_path)
        payload = event(1, "DIV", amount="5", at=NOW - timedelta(minutes=5))
        payload["event_id"] = "00000000000000000000000001"
        inbox.stage(payload)
        with sqlite3.connect(inbox_path) as conn:
            conn.execute("DROP TRIGGER activity_sse_events_no_update")
            conn.execute(
                "UPDATE activity_sse_events SET payload_json='{}' WHERE ref_id='activity-1'"
            )
        with self.assertRaisesRegex(PaperCashLedgerError, "integrity"):
            self.ledger.ingest_from_activity_sse_inbox(inbox_db_path=inbox_path)

    def test_broker_account_id_mismatch_is_rejected(self):
        with self.assertRaisesRegex(PaperCashLedgerError, "does not match"):
            self.ledger.reconcile(
                broker_cash_usd="1000", broker_account_id="wrong",
                observed_at=NOW, activity_coverage_complete=True,
                activity_coverage_reference="test-catch-up-proof",
                activity_coverage_checked_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
