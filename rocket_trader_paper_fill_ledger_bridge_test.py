#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for durable Paper fill ingestion; no broker or network calls."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger
from rocket_trader_paper_fill_ledger_bridge import (
    PaperFillLedgerBridge,
    PaperFillLedgerBridgeError,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)


class PaperFillLedgerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = RealizedPnLLedger(os.path.join(self.tmp.name, "ledger.sqlite3"))
        self.fee_ready = True

        def fee_resolver(_payload):
            if not self.fee_ready:
                return {"fee_usd": "0.0025"}
            return {"fee_usd": "0.0025", "fee_asset_qty": "0", "fee_source": "TEST_FEE_SCHEDULE"}

        self.bridge = PaperFillLedgerBridge(
            db_path=os.path.join(self.tmp.name, "inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda _when: LedgerFX(
                Decimal("18"), NOW, "TEST_FIXTURE"
            ),
            fee_resolver=fee_resolver,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, **overrides):
        payload = {
            "event": "partial_fill",
            "execution_id": "exec-001",
            "timestamp": NOW.isoformat(),
            "qty": "0.0001",
            "price": "10000",
            "order": {"symbol": "BTC/USD", "side": "buy"},
        }
        payload.update(overrides)
        return payload

    def test_partial_fill_is_recorded_in_mxn_ledger(self):
        result = self.bridge.process_trade_update(self.event())
        self.assertTrue(result["processed"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(
            self.ledger.snapshot().open_positions["BTC/USD"]["quantity"],
            "0.0001",
        )
        self.assertEqual(self.bridge.status()["pending_or_failed"], 0)
        fill = next(
            row for row in self.ledger._events()
            if row["event_type"] == "FILL"
        )
        self.assertEqual(fill["payload"]["fee_source"], "TEST_FEE_SCHEDULE")

    def test_replayed_execution_id_is_idempotent(self):
        event = self.event()
        self.bridge.process_trade_update(event)
        replay = self.bridge.process_trade_update(event)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(self.ledger.snapshot().event_count, 2)

    def test_missing_fee_is_retained_and_can_be_retried(self):
        self.fee_ready = False
        with self.assertRaisesRegex(PaperFillLedgerBridgeError, "fee_asset_qty"):
            self.bridge.process_trade_update(self.event())
        self.assertEqual(self.bridge.status()["pending_or_failed"], 1)

        self.fee_ready = True
        result = self.bridge.retry_pending()
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(self.bridge.status()["pending_or_failed"], 0)
        self.assertEqual(self.ledger.snapshot().event_count, 2)

    def test_execution_id_payload_collision_is_rejected(self):
        self.bridge.process_trade_update(self.event())
        changed = self.event(qty="0.0002")
        with self.assertRaisesRegex(PaperFillLedgerBridgeError, "different fill payload"):
            self.bridge.process_trade_update(changed)

    def test_non_fill_updates_are_ignored(self):
        result = self.bridge.process_trade_update({"event": "new", "order": {"id": "o1"}})
        self.assertTrue(result["ignored"])
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_fill_requires_execution_id_and_timestamp(self):
        with self.assertRaisesRegex(PaperFillLedgerBridgeError, "execution_id"):
            self.bridge.process_trade_update(self.event(execution_id=None))
        with self.assertRaisesRegex(PaperFillLedgerBridgeError, "timestamp"):
            self.bridge.process_trade_update(self.event(execution_id="exec-2", timestamp="invalid"))

    def test_alpaca_activity_sse_trd_event_is_normalized_and_ingested(self):
        activity = {
            "event_id": "01ACTIVITYEVENT",
            "ref_id": "activity-exec-001",
            "activity_type": "TRD",
            "qty": "0.0001",
            "price": "10000",
            "currency": "USD",
            "status": "executed",
            "executed_at": NOW.isoformat(),
            "details": {
                "execution_type": "fill",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "order-001",
                "client_order_id": "rocket-001",
            },
        }
        result = self.bridge.process_trade_update(activity)
        self.assertTrue(result["processed"])
        self.assertEqual(result["execution_id"], "activity-exec-001")
        self.assertEqual(
            self.ledger.snapshot().open_positions["BTC/USD"]["quantity"],
            "0.0001",
        )

    def test_activity_sse_trade_bust_is_quarantined_for_manual_review(self):
        activity = {
            "event_id": "01BUSTEVENT",
            "ref_id": "replacement-exec",
            "previous_id": "original-exec",
            "activity_type": "TRD",
            "qty": "0.0001",
            "price": "10000",
            "executed_at": NOW.isoformat(),
            "details": {
                "execution_type": "trade_bust",
                "symbol": "BTC/USD",
                "side": "buy",
            },
        }
        result = self.bridge.process_trade_update(activity)
        self.assertTrue(result["manual_review"])
        status = self.bridge.status()
        self.assertEqual(status["pending_or_failed"], 1)
        self.assertEqual(len(status["manual_review"]), 1)
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_activity_sse_fee_event_is_not_misread_as_a_fill(self):
        result = self.bridge.process_trade_update({
            "activity_type": "CFEE",
            "ref_id": "fee-001",
            "net_amount": "-0.01",
        })
        self.assertTrue(result["ignored"])
        self.assertIn("fee_provider", result["reason"])
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_missing_fx_is_retained_for_retry(self):
        bridge = PaperFillLedgerBridge(
            db_path=os.path.join(self.tmp.name, "fx-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda _when: None,
            fee_resolver=lambda _payload: {"fee_usd": "0", "fee_asset_qty": "0", "fee_source": "TEST_FEE_SCHEDULE"},
        )
        with self.assertRaisesRegex(PaperFillLedgerBridgeError, "validated LedgerFX"):
            bridge.process_trade_update(self.event(execution_id="exec-fx"))
        self.assertEqual(bridge.status()["pending_or_failed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
