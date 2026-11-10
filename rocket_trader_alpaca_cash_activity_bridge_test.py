#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for external Alpaca cash-deposit classification."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger
from rocket_trader_alpaca_cash_activity_bridge import (
    AlpacaCashActivityBridge, AlpacaCashActivityError,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class AlpacaCashActivityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = RealizedPnLLedger(os.path.join(self.tmp.name, "ledger.sqlite3"))
        self.bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "cash-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda _when: LedgerFX(Decimal("18.50"), NOW, "TEST_FX"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_usd_deposit_is_converted_and_not_counted_as_profit(self):
        result = self.bridge.process_activity({
            "id": "cash-deposit-1", "activity_type": "CSD",
            "net_amount": "100", "currency": "USD",
            "transaction_time": NOW.isoformat(), "status": "executed",
        })
        snapshot = self.ledger.snapshot()
        self.assertEqual(Decimal(result["deposit_mxn"]), Decimal("1850.000"))
        self.assertFalse(result["counts_as_trading_profit"])
        self.assertEqual(snapshot.deposits_mxn, Decimal("1850.00"))
        self.assertEqual(snapshot.realized_net_pnl_mxn, Decimal("0.00"))
        self.assertEqual(snapshot.earned_growth_capital_mxn, Decimal("1000.00"))

    def test_mxn_deposit_does_not_call_fx(self):
        calls = []
        bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "mxn-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda when: (calls.append(when) or LedgerFX(Decimal("18"), NOW, "TEST")),
        )
        bridge.process_activity({
            "id": "cash-deposit-mxn", "activity_type": "CSD",
            "net_amount": "500", "currency": "MXN",
            "date": NOW.date().isoformat(), "status": "executed",
        })
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("500.00"))

    def test_duplicate_deposit_is_idempotent(self):
        event = {
            "id": "cash-deposit-dup", "activity_type": "CSD",
            "net_amount": "25", "currency": "USD",
            "date": NOW.date().isoformat(), "status": "executed",
        }
        self.assertFalse(self.bridge.process_activity(event)["duplicate"])
        self.assertTrue(self.bridge.process_activity(event)["duplicate"])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("462.50"))

    def test_withdrawal_is_quarantined_not_silently_recorded_as_payout(self):
        result = self.bridge.process_activity({
            "id": "cash-withdrawal-1", "activity_type": "CSW",
            "net_amount": "-100", "currency": "USD",
            "date": NOW.date().isoformat(), "status": "executed",
        })
        self.assertTrue(result["manual_review"])
        self.assertEqual(self.ledger.snapshot().withdrawals_mxn, Decimal("0.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 1)

    def test_missing_fx_is_persisted_and_retryable(self):
        calls = []
        bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "retry-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda when: (calls.append(when) or None),
        )
        event = {
            "id": "cash-deposit-retry", "activity_type": "CSD",
            "net_amount": "10", "currency": "USD",
            "date": NOW.date().isoformat(), "status": "executed",
        }
        with self.assertRaisesRegex(AlpacaCashActivityError, "validated timestamped LedgerFX"):
            bridge.process_activity(event)
        self.assertEqual(bridge.status()["pending_or_failed"], 1)
        bridge.fx_resolver = lambda when: LedgerFX(Decimal("18.50"), NOW, "RETRY_FX")
        result = bridge.retry_pending()
        self.assertEqual(result["processed"], 1)
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("185.00"))

    def test_non_cash_activity_is_ignored(self):
        result = self.bridge.process_activity({"activity_type": "CFEE", "id": "fee-1"})
        self.assertTrue(result["ignored"])
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_cash_deposit_requires_unique_id_and_supported_currency(self):
        with self.assertRaisesRegex(AlpacaCashActivityError, "broker activity id"):
            self.bridge.process_activity({
                "activity_type": "CSD", "net_amount": "100", "currency": "USD",
                "date": NOW.date().isoformat(),
            })
        with self.assertRaisesRegex(AlpacaCashActivityError, "Unsupported"):
            self.bridge.process_activity({
                "id": "deposit-eur", "activity_type": "CSD", "net_amount": "100",
                "currency": "EUR", "date": NOW.date().isoformat(),
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
