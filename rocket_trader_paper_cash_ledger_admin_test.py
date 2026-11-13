#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger, PaperCashLedgerError
from rocket_trader_paper_cash_ledger_admin import create_paper_cash_anchor


NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
ACCOUNT = "paper-account-1"


class FakePaperClient:
    def __init__(self, account, on_get=None):
        self.account = account
        self.on_get = on_get
        self.calls = 0

    def get_account(self):
        self.calls += 1
        if self.on_get:
            self.on_get()
        return self.account


class PaperCashLedgerAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cash_db = os.path.join(self.tmp.name, "cash.sqlite3")
        self.inbox_db = os.path.join(self.tmp.name, "activity.sqlite3")
        self.inbox = DurableActivitySSEInbox(self.inbox_db)
        self.account = SimpleNamespace(
            id=ACCOUNT, status="ACTIVE", currency="USD", cash="100.25", equity="120.50"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_anchor_from_paper_get_account_and_verified_cursor(self):
        client = FakePaperClient(self.account)
        result = create_paper_cash_anchor(
            client=client,
            inbox_db_path=self.inbox_db,
            cash_db_path=self.cash_db,
            initialize_db=True,
            now=NOW,
        )
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["status"], "ANCHORED")
        self.assertEqual(result["cash_usd"], "100.25")
        self.assertEqual(result["account_id"], ACCOUNT)
        self.assertTrue(result["activity_inbox_integrity_valid"])
        self.assertFalse(result["activity_coverage_complete"])
        self.assertFalse(result["orders_enabled"])
        ledger = AlpacaPaperUSDCashLedger(
            self.cash_db, account_id=ACCOUNT, initialize=False
        )
        report = ledger.reconcile(
            broker_cash_usd="100.25", broker_account_id=ACCOUNT,
            observed_at=NOW, activity_coverage_complete=False,
        )
        self.assertEqual(report["status"], "ACTIVITY_HISTORY_INCOMPLETE")

    def test_reads_cursor_before_get_account(self):
        def stage_after_cursor():
            self.inbox.stage({
                "account_id": ACCOUNT,
                "event_id": "00000000000000000000000001",
                "ref_id": "activity-after-cursor",
                "activity_type": "DIV",
                "activity_subtype": None,
                "status": "executed",
                "at": NOW.isoformat(),
                "currency": "USD",
                "net_amount": "1",
                "details": {},
            })
        client = FakePaperClient(self.account, on_get=stage_after_cursor)
        result = create_paper_cash_anchor(
            client=client,
            inbox_db_path=self.inbox_db,
            cash_db_path=self.cash_db,
            initialize_db=True,
            now=NOW - timedelta(seconds=1),
        )
        self.assertIsNone(result["activity_cursor_before_snapshot"])

    def test_missing_database_is_not_created_without_explicit_flag(self):
        client = FakePaperClient(self.account)
        with self.assertRaisesRegex(PaperCashLedgerError, "cash ledger database is missing"):
            create_paper_cash_anchor(
                client=client,
                inbox_db_path=self.inbox_db,
                cash_db_path=self.cash_db,
                initialize_db=False,
                now=NOW,
            )
        self.assertFalse(os.path.exists(self.cash_db))
        self.assertEqual(client.calls, 0)

    def test_non_usd_account_is_rejected(self):
        client = FakePaperClient(SimpleNamespace(
            id=ACCOUNT, status="ACTIVE", currency="EUR", cash="100", equity="100"
        ))
        with self.assertRaisesRegex(PaperCashLedgerError, "USD account currency"):
            create_paper_cash_anchor(
                client=client,
                inbox_db_path=self.inbox_db,
                cash_db_path=self.cash_db,
                initialize_db=True,
                now=NOW,
            )

    def test_invalid_inbox_is_rejected_before_broker_call(self):
        client = FakePaperClient(self.account)
        corrupt_inbox = os.path.join(self.tmp.name, "corrupt-inbox.sqlite3")
        with open(corrupt_inbox, "wb") as handle:
            handle.write(b"not a sqlite database")
        with self.assertRaisesRegex(PaperCashLedgerError, "integrity"):
            create_paper_cash_anchor(
                client=client,
                inbox_db_path=corrupt_inbox,
                cash_db_path=self.cash_db,
                initialize_db=True,
                now=NOW,
            )
        self.assertEqual(client.calls, 0)


if __name__ == "__main__":
    unittest.main()
