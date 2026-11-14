#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline end-to-end tests for the bounded Paper account evidence coordinator."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger
from rocket_trader_paper_activity_coverage_audit import AlpacaPaperActivityCoverageAuditor
from rocket_trader_paper_account_reconciliation import (
    PaperAccountEvidenceCoordinator,
    PaperAccountEvidenceError,
)
from rocket_trader_paper_fee_allocation_audit import AlpacaPaperFeeAllocationAuditor
from rocket_trader_paper_fill_ledger_bridge import PaperFillLedgerBridge
from rocket_trader_paper_reconciliation import AlpacaPaperReconciliationGate
from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger

ACCOUNT = "paper-account-evidence-test"
SINCE = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)
EVENT_AT = SINCE + timedelta(minutes=10)
SNAPSHOT_AT = SINCE + timedelta(minutes=30)


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


class FakePaperClient:
    def __init__(self, *, cash="899.99", equity="999.99"):
        self.account_calls = 0
        self.position_calls = 0
        self.account = SimpleNamespace(
            id=ACCOUNT,
            currency="USD",
            status="ACTIVE",
            trading_blocked=False,
            cash=cash,
            equity=equity,
        )
        self.positions = [
            SimpleNamespace(
                symbol="SPY",
                qty="1",
                market_value="100",
                current_price="100",
            )
        ]

    def get_all_positions(self):
        self.position_calls += 1
        return self.positions

    def get_account(self):
        self.account_calls += 1
        return self.account


class PaperAccountEvidenceCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cash_path = os.path.join(self.tmp.name, "cash.sqlite3")
        self.inbox_path = os.path.join(self.tmp.name, "activity-inbox.sqlite3")
        self.pnl_path = os.path.join(self.tmp.name, "realized-pnl.sqlite3")
        self.bridge_path = os.path.join(self.tmp.name, "fill-bridge.sqlite3")
        self.cash = AlpacaPaperUSDCashLedger(self.cash_path, account_id=ACCOUNT)
        self.cash.record_anchor(
            anchor_id="account-evidence-anchor",
            cash_usd="1000",
            observed_at=SINCE,
            source_reference="offline-paper-account-snapshot",
        )
        self.inbox = DurableActivitySSEInbox(self.inbox_path)
        self.ledger = RealizedPnLLedger(self.pnl_path)
        self.fill_activity = {
            "account_id": ACCOUNT,
            "event_id": "00000000000000000000000001",
            "ref_id": "execution-1",
            "activity_type": "TRD",
            "activity_subtype": None,
            "status": "executed",
            "at": EVENT_AT.isoformat(),
            "executed_at": EVENT_AT.isoformat(),
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
        self.fee_activity = {
            "account_id": ACCOUNT,
            "event_id": "00000000000000000000000002",
            "ref_id": "fee-ref-1",
            "activity_type": "FEE",
            "activity_subtype": "COM",
            "status": "executed",
            "at": EVENT_AT.isoformat(),
            "executed_at": EVENT_AT.isoformat(),
            "currency": "USD",
            "net_amount": "-0.01",
            "previous_id": None,
            "details": {"parent_id": "execution-1"},
        }
        self.inbox.stage(self.fill_activity)
        self.inbox.stage(self.fee_activity)
        self.bridge = PaperFillLedgerBridge(
            db_path=self.bridge_path,
            ledger=self.ledger,
            fx_resolver=lambda when: LedgerFX(Decimal("18"), EVENT_AT, "TEST_ENTRY_FX"),
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
        self.client = FakePaperClient()
        self.gate = AlpacaPaperReconciliationGate(
            self.client,
            cash_ledger=self.cash,
            activity_sse_inbox_path=self.inbox_path,
        )
        self.coverage = AlpacaPaperActivityCoverageAuditor(
            account_id=ACCOUNT,
            cash_ledger=self.cash,
            inbox_db_path=self.inbox_path,
            api_key="offline-key",
            api_secret="offline-secret",
            request_get=lambda *args, **kwargs: FakeSSEReplayResponse([
                self.fill_activity, self.fee_activity,
            ]),
        )
        self.fee_auditor = AlpacaPaperFeeAllocationAuditor(
            cash_ledger=self.cash,
            realized_pnl_db_path=self.pnl_path,
            fill_bridge_db_path=self.bridge_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self, *, cash="899.99", equity="999.99", clock=None):
        self.client.account.cash = cash
        self.client.account.equity = equity
        times = iter([
            SNAPSHOT_AT,
            SNAPSHOT_AT + timedelta(seconds=1),
            SNAPSHOT_AT + timedelta(seconds=2),
        ])
        return PaperAccountEvidenceCoordinator(
            reconciliation_gate=self.gate,
            fill_ledger_bridge=self.bridge,
            cash_ledger=self.cash,
            activity_sse_inbox_path=self.inbox_path,
            coverage_auditor=self.coverage,
            fee_allocation_auditor=self.fee_auditor,
            clock=clock or (lambda: next(times)),
        )

    def test_full_account_reconciliation_binds_both_audits_to_one_snapshot(self):
        report = self.coordinator().reconcile()
        self.assertEqual(report["account_evidence_status"], "RECONCILED")
        self.assertTrue(report["account_reconciliation_complete"])
        self.assertEqual(report["cash_reconciliation_status"], "RECONCILED")
        self.assertEqual(report["account_equity_reconciliation_status"], "RECONCILED")
        self.assertEqual(report["fee_reconciliation_status"], "RECONCILED")
        self.assertEqual(report["account_snapshot_observed_at"], SNAPSHOT_AT.isoformat())
        self.assertTrue(report["activity_coverage_audit_id"])
        self.assertTrue(report["fee_allocation_audit_id"])
        self.assertEqual(self.client.account_calls, 1)
        self.assertEqual(self.client.position_calls, 1)
        self.assertFalse(report["orders_enabled"])

    def test_cash_mismatch_blocks_full_account_reconciliation(self):
        with self.assertRaisesRegex(PaperAccountEvidenceError, "did not fully reconcile"):
            self.coordinator(cash="900.00").reconcile()

    def test_equity_mismatch_blocks_full_account_reconciliation(self):
        with self.assertRaisesRegex(PaperAccountEvidenceError, "did not fully reconcile"):
            self.coordinator(equity="1001.00").reconcile()

    def test_pending_fill_bridge_blocks_before_broker_snapshot(self):
        original_status = self.bridge.status
        self.bridge.status = lambda: {"pending_or_failed": 1, "counts": {"PENDING": 1}}
        with self.assertRaisesRegex(PaperAccountEvidenceError, "remain pending"):
            self.coordinator().reconcile()
        self.assertEqual(self.client.account_calls, 0)
        self.assertEqual(self.client.position_calls, 0)
        self.bridge.status = original_status

    def test_missing_anchor_blocks_before_broker_snapshot(self):
        self.cash.record_anchor(
            anchor_id="new-anchor",
            cash_usd="1000",
            observed_at=SNAPSHOT_AT + timedelta(minutes=1),
            source_reference="new-anchor",
        )
        with self.assertRaisesRegex(PaperAccountEvidenceError, "snapshot must be later"):
            self.coordinator().reconcile()

    def test_coverage_failure_blocks_fee_audit_and_reconciliation(self):
        class FailingCoverage:
            cash_ledger = self.cash
            inbox_db_path = self.inbox_path

            def audit(self, **_kwargs):
                raise RuntimeError("bounded replay mismatch")

        coordinator = PaperAccountEvidenceCoordinator(
            reconciliation_gate=self.gate,
            fill_ledger_bridge=self.bridge,
            cash_ledger=self.cash,
            activity_sse_inbox_path=self.inbox_path,
            coverage_auditor=FailingCoverage(),
            fee_allocation_auditor=self.fee_auditor,
            clock=lambda: SNAPSHOT_AT,
        )
        with self.assertRaisesRegex(PaperAccountEvidenceError, "coverage or fee allocation audit failed"):
            coordinator.reconcile()
        self.assertEqual(self.client.account_calls, 1)
        self.assertEqual(self.client.position_calls, 1)


if __name__ == "__main__":
    unittest.main()
