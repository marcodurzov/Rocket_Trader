#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for read-only Paper account/position reconciliation."""

import unittest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from rocket_trader_currency import FXQuote
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger
from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
from rocket_trader_paper_reconciliation import (
    AlpacaPaperReconciliationGate, PaperReconciliationError,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
ACCOUNT = "paper-account-1"
FX = FXQuote(Decimal("18"), NOW, "OFFLINE_TEST_FIXTURE")


class FakeBroker:
    def __init__(self, *, account=None, positions=None):
        self.account = account or SimpleNamespace(
            id=ACCOUNT, status="ACTIVE", currency="USD", trading_blocked=False,
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
        }

    def _cash_reconciliation_fixture(self, *, broker_equity="100", broker_cash="90"):
        tmp = tempfile.TemporaryDirectory()
        cash_db = os.path.join(tmp.name, "paper-cash.sqlite3")
        inbox_db = os.path.join(tmp.name, "activity-inbox.sqlite3")
        cash_ledger = AlpacaPaperUSDCashLedger(cash_db, account_id=ACCOUNT)
        cash_ledger.record_anchor(
            anchor_id="anchor-1", cash_usd="100",
            observed_at=NOW - timedelta(minutes=10),
            source_reference="offline-paper-account-snapshot",
            activity_cursor_before_snapshot=None,
        )
        inbox = DurableActivitySSEInbox(inbox_db)
        inbox.stage({
            "account_id": ACCOUNT,
            "event_id": "00000000000000000000000001",
            "ref_id": "trade-1",
            "activity_type": "TRD",
            "activity_subtype": None,
            "status": "executed",
            "at": (NOW - timedelta(minutes=5)).isoformat(),
            "executed_at": (NOW - timedelta(minutes=5)).isoformat(),
            "currency": "USD",
            "net_amount": "-10",
            "details": {"side": "buy", "execution_type": "fill"},
        })
        broker = FakeBroker(
            account=SimpleNamespace(
                id=ACCOUNT, status="ACTIVE", currency="USD", trading_blocked=False,
                cash=broker_cash, equity=broker_equity,
            ),
            positions=[SimpleNamespace(
                symbol="SPY", qty="1", current_price="10", market_value="10"
            )],
        )
        gate = AlpacaPaperReconciliationGate(
            broker, cash_ledger=cash_ledger, activity_sse_inbox_path=inbox_db,
        )
        return tmp, gate

    def test_full_position_cash_and_equity_reconciliation_passes(self):
        tmp, gate = self._cash_reconciliation_fixture()
        self.addCleanup(tmp.cleanup)
        result = gate.reconcile(
            ledger_snapshot=self.snapshot({"SPY": {"quantity": "1"}}),
            fx_quote=FX, now=NOW,
            activity_coverage_complete=True,
            activity_coverage_reference="offline-replay-catchup-1",
            activity_coverage_checked_at=NOW,
            fee_reconciliation_complete=True,
            fee_reconciliation_reference="offline-fee-audit-1",
            fee_reconciliation_checked_at=NOW,
        )
        self.assertEqual(result["status"], "RECONCILED")
        self.assertTrue(result["positions_match"])
        self.assertEqual(result["cash_reconciliation_status"], "RECONCILED")
        self.assertEqual(result["account_equity_reconciliation_status"], "RECONCILED")
        self.assertEqual(result["fee_reconciliation_status"], "RECONCILED")
        self.assertTrue(result["account_reconciliation_complete"])
        self.assertFalse(result["orders_enabled"])

    def test_equity_mismatch_blocks_full_paper_reconciliation(self):
        tmp, gate = self._cash_reconciliation_fixture(broker_equity="101")
        self.addCleanup(tmp.cleanup)
        result = gate.reconcile(
            ledger_snapshot=self.snapshot({"SPY": {"quantity": "1"}}),
            fx_quote=FX, now=NOW,
            activity_coverage_complete=True,
            activity_coverage_reference="offline-replay-catchup-1",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(result["cash_reconciliation_status"], "RECONCILED")
        self.assertEqual(result["account_equity_reconciliation_status"], "EQUITY_BALANCE_MISMATCH")
        self.assertFalse(result["account_reconciliation_complete"])

    def test_position_mismatch_blocks_full_reconciliation_even_when_cash_equity_match(self):
        tmp, gate = self._cash_reconciliation_fixture()
        self.addCleanup(tmp.cleanup)
        result = gate.reconcile(
            ledger_snapshot=self.snapshot({"SPY": {"quantity": "2"}}),
            fx_quote=FX, now=NOW,
            activity_coverage_complete=True,
            activity_coverage_reference="offline-replay-catchup-1",
            activity_coverage_checked_at=NOW,
        )
        self.assertEqual(result["cash_reconciliation_status"], "RECONCILED")
        self.assertEqual(result["account_equity_reconciliation_status"], "RECONCILED")
        self.assertFalse(result["account_reconciliation_complete"])
        self.assertEqual(result["status"], "POSITION_MISMATCH")

    def test_incomplete_activity_coverage_keeps_full_reconciliation_blocked(self):
        tmp, gate = self._cash_reconciliation_fixture()
        self.addCleanup(tmp.cleanup)
        result = gate.reconcile(
            ledger_snapshot=self.snapshot({"SPY": {"quantity": "1"}}),
            fx_quote=FX, now=NOW,
        )
        self.assertEqual(result["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")
        self.assertFalse(result["account_reconciliation_complete"])

    def test_missing_cash_anchor_keeps_integrated_gate_incomplete(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cash_ledger = AlpacaPaperUSDCashLedger(
            os.path.join(tmp.name, "cash.sqlite3"), account_id=ACCOUNT,
        )
        inbox_path = os.path.join(tmp.name, "inbox.sqlite3")
        DurableActivitySSEInbox(inbox_path)
        broker = FakeBroker(
            account=SimpleNamespace(
                id=ACCOUNT, status="ACTIVE", currency="USD", trading_blocked=False,
                cash="100", equity="110",
            ),
            positions=[SimpleNamespace(
                symbol="SPY", qty="1", current_price="10", market_value="10"
            )],
        )
        result = AlpacaPaperReconciliationGate(
            broker, cash_ledger=cash_ledger, activity_sse_inbox_path=inbox_path,
        ).reconcile(
            ledger_snapshot=self.snapshot({"SPY": {"quantity": "1"}}),
            fx_quote=FX, now=NOW,
        )
        self.assertEqual(result["cash_reconciliation_status"], "NOT_RECONCILED")
        self.assertEqual(result["account_equity_reconciliation_status"], "CASH_ANCHOR_REQUIRED")
        self.assertFalse(result["account_reconciliation_complete"])

    def test_matching_crypto_position_is_not_full_account_reconciliation(self):
        broker = FakeBroker(positions=[
            SimpleNamespace(symbol="BTCUSD", qty="0.0099")
        ])
        ledger = self.snapshot({"BTC/USD": {"quantity": "0.0099"}})
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
            SimpleNamespace(symbol="BTC/USD", qty="0.01000001")
        ])
        result = AlpacaPaperReconciliationGate(
            broker, quantity_tolerance="0.000001"
        ).reconcile(
            ledger_snapshot=self.snapshot({"BTC/USD": {"quantity": "0.01"}}),
            fx_quote=FX, now=NOW,
        )
        self.assertEqual(result["status"], "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
