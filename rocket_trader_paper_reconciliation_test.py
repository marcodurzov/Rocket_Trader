#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for read-only Paper account/position reconciliation."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from rocket_trader_currency import FXQuote
from rocket_trader_paper_reconciliation import (
    AlpacaPaperReconciliationGate, PaperReconciliationError,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
FX = FXQuote(Decimal("18"), NOW, "OFFLINE_TEST_FIXTURE")


class FakeBroker:
    def __init__(self, *, account=None, positions=None):
        self.account = account or SimpleNamespace(
            status="ACTIVE", currency="USD", trading_blocked=False,
            cash="100", equity="120",
        )
        self.positions = positions or []

    def get_account(self):
        return self.account

    def get_all_positions(self):
        return self.positions


class PaperReconciliationTests(unittest.TestCase):
    def snapshot(self, positions=None, capital="1000"):
        return {
            "operating_capital_mxn": capital,
            "open_positions": positions or {},
            "accounting_method": "FIFO_MXN_ENTRY_AND_EXIT_FX_V2",
        }

    def test_matching_crypto_position_is_not_full_account_reconciliation(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTCUSD", qty="0.0099", market_value="1000")
        ])
        ledger = self.snapshot({"BTC/USD": {"quantity": "0.0099", "fifo_cost_basis_mxn": "18000"}})
        result = AlpacaPaperReconciliationGate(broker).reconcile(
            ledger_snapshot=ledger, fx_quote=FX, now=NOW
        )
        self.assertEqual(result["status"], "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE")
        self.assertFalse(result["orders_enabled"])
        self.assertFalse(result["paper_buying_power_used_as_capital"])
        self.assertFalse(result["account_reconciliation_complete"])
        self.assertEqual(result["position_reconciliation_status"], "MATCHED")
        self.assertEqual(
            result["cash_reconciliation_status"],
            "NOT_IMPLEMENTED_NO_USD_CASH_LEDGER",
        )
        self.assertTrue(result["broker_cash_equity_observed_only"])
        self.assertEqual(result["ledger_operating_capital_mxn"], "1000")
        self.assertEqual(result["strategy_equity_status"], "AVAILABLE")
        self.assertEqual(result["strategy_equity_mxn"], "1000")
        self.assertEqual(result["strategy_unrealized_pnl_mxn"], "0")
        self.assertTrue(result["strategy_equity_snapshot_hash"])

    def test_position_mismatch_blocks_reconciliation(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTC/USD", qty="0.01")
        ])
        result = AlpacaPaperReconciliationGate(broker).reconcile(
            ledger_snapshot=self.snapshot({"BTC/USD": {"quantity": "0.0099"}}),
            fx_quote=FX, now=NOW,
        )
        self.assertEqual(result["status"], "POSITION_MISMATCH")
        self.assertIn("BTC/USD", result["position_differences"])

    def test_broker_only_external_position_is_detected(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="SPY", qty="1")
        ])
        result = AlpacaPaperReconciliationGate(broker).reconcile(
            ledger_snapshot=self.snapshot(), fx_quote=FX, now=NOW
        )
        self.assertEqual(result["status"], "POSITION_MISMATCH")
        self.assertEqual(result["position_differences"]["SPY"]["ledger_qty"], "0")

    def test_strategy_equity_includes_unrealized_mxn_from_broker_market_value(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTC/USD", qty="0.01", market_value="1100")
        ])
        result = AlpacaPaperReconciliationGate(broker).reconcile(
            ledger_snapshot=self.snapshot({
                "BTC/USD": {
                    "quantity": "0.01",
                    "fifo_cost_basis_mxn": "18000",
                }
            }),
            fx_quote=FX,
            now=NOW,
        )
        self.assertEqual(result["strategy_equity_status"], "AVAILABLE")
        self.assertEqual(result["strategy_unrealized_pnl_mxn"], "1800")
        self.assertEqual(result["strategy_equity_mxn"], "2800")

    def test_missing_broker_market_value_blocks_strategy_equity_only(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTC/USD", qty="0.01")
        ])
        result = AlpacaPaperReconciliationGate(broker).reconcile(
            ledger_snapshot=self.snapshot({
                "BTC/USD": {
                    "quantity": "0.01",
                    "fifo_cost_basis_mxn": "18000",
                }
            }),
            fx_quote=FX,
            now=NOW,
        )
        self.assertTrue(result["positions_match"])
        self.assertEqual(
            result["strategy_equity_status"],
            "UNAVAILABLE_MISSING_MARKET_VALUE",
        )
        self.assertIsNone(result["strategy_equity_mxn"])

    def test_missing_fx_aware_accounting_method_blocks_strategy_equity(self):
        ledger = self.snapshot()
        ledger["accounting_method"] = "LEGACY"
        result = AlpacaPaperReconciliationGate(FakeBroker()).reconcile(
            ledger_snapshot=ledger,
            fx_quote=FX,
            now=NOW,
        )
        self.assertEqual(
            result["strategy_equity_status"],
            "UNAVAILABLE_ACCOUNTING_METHOD",
        )
        self.assertIsNone(result["strategy_equity_mxn"])

    def test_stale_or_future_fx_fails_closed(self):
        stale = FXQuote(
            Decimal("18"), NOW - timedelta(hours=25), "STALE_FIXTURE"
        )
        with self.assertRaisesRegex(PaperReconciliationError, "stale"):
            AlpacaPaperReconciliationGate(FakeBroker()).reconcile(
                ledger_snapshot=self.snapshot(), fx_quote=stale, now=NOW
            )
        future = FXQuote(
            Decimal("18"), NOW + timedelta(minutes=1), "FUTURE_FIXTURE"
        )
        with self.assertRaisesRegex(PaperReconciliationError, "future"):
            AlpacaPaperReconciliationGate(FakeBroker()).reconcile(
                ledger_snapshot=self.snapshot(), fx_quote=future, now=NOW
            )

    def test_non_usd_or_inactive_account_is_rejected(self):
        for account in [
            SimpleNamespace(status="ACTIVE", currency="MXN", trading_blocked=False),
            SimpleNamespace(status="INACTIVE", currency="USD", trading_blocked=False),
            SimpleNamespace(status="ACTIVE", currency="USD", trading_blocked=True),
        ]:
            with self.subTest(account=account):
                with self.assertRaises(PaperReconciliationError):
                    AlpacaPaperReconciliationGate(
                        FakeBroker(account=account)
                    ).reconcile(
                        ledger_snapshot=self.snapshot(), fx_quote=FX, now=NOW
                    )

    def test_negative_broker_quantity_is_rejected(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTC/USD", qty="-0.01")
        ])
        with self.assertRaisesRegex(PaperReconciliationError, "negative inventory"):
            AlpacaPaperReconciliationGate(broker).reconcile(
                ledger_snapshot=self.snapshot(), fx_quote=FX, now=NOW
            )

    def test_configured_quantity_tolerance(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTC/USD", qty="0.01000001", market_value="1000")
        ])
        result = AlpacaPaperReconciliationGate(
            broker, quantity_tolerance="0.000001"
        ).reconcile(
            ledger_snapshot=self.snapshot({"BTC/USD": {"quantity": "0.01", "fifo_cost_basis_mxn": "18000"}}),
            fx_quote=FX, now=NOW,
        )
        self.assertEqual(result["status"], "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
