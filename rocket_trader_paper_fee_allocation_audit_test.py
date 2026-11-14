#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline end-to-end tests for durable Paper fee allocation evidence."""

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger
from rocket_trader_paper_activity_coverage_audit import AlpacaPaperActivityCoverageAuditor
from rocket_trader_paper_fee_allocation_audit import (
    AlpacaPaperFeeAllocationAuditor,
    PaperFeeAllocationAuditError,
)
from rocket_trader_paper_fill_ledger_bridge import PaperFillLedgerBridge
from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger

ACCOUNT = "paper-fee-audit-account"
SINCE = datetime(2026, 11, 13, 17, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
CHECKED = UNTIL + timedelta(seconds=1)


class FakeSSEReplayResponse:
    status_code = 200

    def __init__(self, events):
        self.events = events
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        for item in self.events:
            yield "data: " + json.dumps(item, separators=(",", ":"))
            yield ""

    def close(self):
        self.closed = True


class FeeAllocationAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cash_path = os.path.join(self.tmp.name, "cash.sqlite3")
        self.inbox_path = os.path.join(self.tmp.name, "activity-inbox.sqlite3")
        self.pnl_path = os.path.join(self.tmp.name, "realized-pnl.sqlite3")
        self.bridge_path = os.path.join(self.tmp.name, "fill-bridge.sqlite3")
        self.cash = AlpacaPaperUSDCashLedger(self.cash_path, account_id=ACCOUNT)
        self.cash.record_anchor(
            anchor_id="fee-anchor", cash_usd="1000", observed_at=SINCE,
            source_reference="offline-paper-snapshot",
        )
        self.inbox = DurableActivitySSEInbox(self.inbox_path)
        self.pnl = RealizedPnLLedger(self.pnl_path)
        self.fee_activity = {
            "account_id": ACCOUNT,
            "event_id": "00000000000000000000000002",
            "ref_id": "fee-ref-1",
            "activity_type": "FEE",
            "activity_subtype": "COM",
            "status": "executed",
            "at": (SINCE + timedelta(minutes=10)).isoformat(),
            "executed_at": (SINCE + timedelta(minutes=10)).isoformat(),
            "currency": "USD",
            "net_amount": "-0.01",
            "previous_id": None,
            "details": {"parent_id": "exec-1"},
        }
        self.fill_activity = {
            "account_id": ACCOUNT,
            "event_id": "00000000000000000000000001",
            "ref_id": "exec-1",
            "activity_type": "TRD",
            "activity_subtype": None,
            "status": "executed",
            "at": (SINCE + timedelta(minutes=10)).isoformat(),
            "executed_at": (SINCE + timedelta(minutes=10)).isoformat(),
            "currency": "USD",
            "net_amount": "-100",
            "qty": "1",
            "price": "100",
            "previous_id": None,
            "details": {
                "execution_type": "fill",
                "symbol": "SPY",
                "side": "buy",
                "order_id": "order-1",
                "client_order_id": "rocket-1",
            },
        }
        self.inbox.stage(self.fill_activity)
        self.inbox.stage(self.fee_activity)
        self.bridge = PaperFillLedgerBridge(
            db_path=self.bridge_path,
            ledger=self.pnl,
            fx_resolver=lambda _when: LedgerFX(Decimal("18"), SINCE + timedelta(minutes=10), "TEST_FX"),
            fee_resolver=lambda _payload: {
                "fee_usd": "0.01",
                "fee_asset_qty": "0",
                "fee_source": "Alpaca Paper Account Activities: fee-ref-1",
                "fee_activity_ids": ["fee-ref-1"],
                "fee_activity_refs": ["fee-ref-1"],
            },
        )
        self.bridge.process_trade_update(self.fill_activity)
        self.cash.ingest_from_activity_sse_inbox(inbox_db_path=self.inbox_path)
        self.coverage = AlpacaPaperActivityCoverageAuditor(
            account_id=ACCOUNT,
            cash_ledger=self.cash,
            inbox_db_path=self.inbox_path,
            api_key="offline-key",
            api_secret="offline-secret",
            request_get=lambda *args, **kwargs: FakeSSEReplayResponse([
                self.fill_activity, self.fee_activity,
            ]),
        ).audit(since=SINCE, until=UNTIL, checked_at=CHECKED)

    def tearDown(self):
        self.tmp.cleanup()

    def auditor(self):
        return AlpacaPaperFeeAllocationAuditor(
            cash_ledger=self.cash,
            realized_pnl_db_path=self.pnl_path,
            fill_bridge_db_path=self.bridge_path,
        )

    def test_exact_fee_activity_maps_to_one_processed_fill_and_mxn_ledger(self):
        report = self.auditor().audit(
            coverage_audit_id=self.coverage["audit_id"],
            since=SINCE, until=UNTIL, checked_at=CHECKED,
        )
        self.assertEqual(report["status"], "ATTESTED")
        self.assertEqual(report["fill_count"], 1)
        self.assertEqual(report["fee_count"], 1)
        result = self.cash.reconcile(
            broker_cash_usd="899.99",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference=self.coverage["audit_id"],
            activity_coverage_checked_at=CHECKED,
            fee_reconciliation_complete=True,
            fee_reconciliation_reference=report["audit_id"],
            fee_reconciliation_checked_at=CHECKED,
        )
        self.assertEqual(result["fee_reconciliation_status"], "RECONCILED")
        self.assertEqual(result["pending_fee_allocation_count"], 0)

    def test_unlinked_fee_blocks_allocation_audit(self):
        unlinked = dict(self.fee_activity)
        unlinked["event_id"] = "00000000000000000000000003"
        unlinked["ref_id"] = "unlinked-fee"
        unlinked["details"] = {}
        self.inbox.stage(unlinked)
        self.cash.ingest_activity(unlinked)
        with self.assertRaisesRegex(PaperFeeAllocationAuditError, "maps to 0 fills"):
            self.auditor().audit(
                coverage_audit_id=self.coverage["audit_id"],
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_missing_processed_bridge_fill_blocks_audit(self):
        with sqlite3.connect(self.bridge_path) as conn:
            conn.execute(
                "UPDATE paper_fill_ledger_inbox SET status='FAILED' WHERE execution_id='exec-1'"
            )
        with self.assertRaisesRegex(PaperFeeAllocationAuditError, "not PROCESSED"):
            self.auditor().audit(
                coverage_audit_id=self.coverage["audit_id"],
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_fee_amount_mismatch_with_mxn_ledger_blocks_audit(self):
        # Simulate a tampered persisted fee value while keeping its payload hash
        # internally consistent; the audit must catch the cross-ledger mismatch.
        with sqlite3.connect(self.pnl_path) as conn:
            conn.execute("DROP TRIGGER ledger_events_no_update")
            row = conn.execute(
                "SELECT payload_json FROM ledger_events WHERE event_id='ALPACA-FILL-exec-1'"
            ).fetchone()
            payload = json.loads(row[0])
            payload["fee_usd"] = "0.02"
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            )
            digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            conn.execute(
                "UPDATE ledger_events SET payload_json=?,payload_hash=? WHERE event_id='ALPACA-FILL-exec-1'",
                (encoded, digest),
            )
            conn.execute(
                "CREATE TRIGGER ledger_events_no_update BEFORE UPDATE ON ledger_events "
                "BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END"
            )
        with self.assertRaisesRegex(PaperFeeAllocationAuditError, "Resolved fee totals do not match"):
            self.auditor().audit(
                coverage_audit_id=self.coverage["audit_id"],
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_arbitrary_fee_reference_cannot_clear_fee_status(self):
        result = self.cash.reconcile(
            broker_cash_usd="899.99",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference=self.coverage["audit_id"],
            activity_coverage_checked_at=CHECKED,
            fee_reconciliation_complete=True,
            fee_reconciliation_reference="invented-fee-audit",
            fee_reconciliation_checked_at=CHECKED,
        )
        self.assertEqual(result["fee_reconciliation_status"], "UNRESOLVED")
