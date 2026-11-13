#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rocket_trader_currency import FXQuote
from rocket_trader_strategy_equity import (
    StrategyEquityMetricsError,
    StrategySessionBaseline,
    calculate_strategy_equity_metrics,
)


NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)


def fixture(**overrides):
    values = {
        "ledger_snapshot": {
            "operating_capital_mxn": "1000",
            "accounting_method": "FIFO_MXN_ENTRY_AND_EXIT_FX_V2",
            "open_positions": {
                "BTC/USD": {
                    "quantity": "0.01",
                    "fifo_cost_basis_mxn": "1500",
                }
            },
        },
        "broker_positions": [
            {"symbol": "BTC/USD", "qty": "0.01", "current_price": "10000"}
        ],
        "fx_quote": FXQuote(Decimal("18"), NOW - timedelta(minutes=1), "TEST_FX"),
        "session_baseline": StrategySessionBaseline(
            "2026-11-13", Decimal("1000"), NOW - timedelta(hours=1),
            "VERIFIED_SESSION_OPEN", Decimal("0"),
        ),
        "session_id": "2026-11-13",
        "account_reconciliation_complete": False,
        "cash_reconciliation_status": "NOT_IMPLEMENTED_NO_USD_CASH_LEDGER",
        "fee_reconciliation_status": "UNRESOLVED",
        "now": NOW,
    }
    values.update(overrides)
    return values


class StrategyEquityMetricsTests(unittest.TestCase):
    def test_calculates_mxn_equity_from_operating_capital_and_unrealized_pnl(self):
        report = calculate_strategy_equity_metrics(**fixture())
        self.assertEqual(Decimal(report["market_value_mxn"]), Decimal("1800"))
        self.assertEqual(Decimal(report["unrealized_pnl_mxn"]), Decimal("300"))
        self.assertEqual(Decimal(report["strategy_equity_mxn"]), Decimal("1300"))

    def test_flow_adjusted_daily_pnl_excludes_external_deposits(self):
        data = fixture()
        data["ledger_snapshot"] = {
            "operating_capital_mxn": "1200",
            "open_positions": {},
        }
        data["broker_positions"] = []
        data["session_baseline"] = StrategySessionBaseline(
            "2026-11-13", Decimal("1000"), NOW - timedelta(hours=1),
            "VERIFIED_SESSION_OPEN", Decimal("200"),
        )
        report = calculate_strategy_equity_metrics(**data)
        self.assertEqual(Decimal(report["strategy_equity_mxn"]), Decimal("1200"))
        self.assertEqual(Decimal(report["strategy_daily_pnl_pct"]), Decimal("0"))

    def test_position_mismatch_fails_closed(self):
        data = fixture(broker_positions=[])
        with self.assertRaisesRegex(StrategyEquityMetricsError, "do not match"):
            calculate_strategy_equity_metrics(**data)

    def test_stale_fx_fails_closed(self):
        data = fixture(fx_quote=FXQuote(
            Decimal("18"), NOW - timedelta(days=3), "STALE"
        ))
        with self.assertRaisesRegex(StrategyEquityMetricsError, "stale"):
            calculate_strategy_equity_metrics(**data)

    def test_missing_mxn_fifo_cost_basis_fails_closed(self):
        data = fixture()
        data["ledger_snapshot"]["open_positions"]["BTC/USD"].pop("fifo_cost_basis_mxn")
        with self.assertRaises(StrategyEquityMetricsError):
            calculate_strategy_equity_metrics(**data)

    def test_daily_baseline_must_match_session(self):
        data = fixture(session_id="2026-11-14")
        with self.assertRaisesRegex(StrategyEquityMetricsError, "does not match"):
            calculate_strategy_equity_metrics(**data)

    def test_metrics_remain_ineligible_until_cash_fee_and_account_parity_clear(self):
        report = calculate_strategy_equity_metrics(**fixture())
        self.assertFalse(report["risk_metrics_eligible"])
        self.assertEqual(report["status"], "OBSERVATION_ONLY_RECONCILIATION_INCOMPLETE")
        self.assertFalse(report["orders_enabled"])

    def test_all_reconciliation_gates_must_be_explicitly_clear(self):
        data = fixture(
            account_reconciliation_complete=True,
            cash_reconciliation_status="RECONCILED",
            fee_reconciliation_status="RECONCILED",
        )
        report = calculate_strategy_equity_metrics(**data)
        self.assertTrue(report["risk_metrics_eligible"])
        self.assertEqual(report["status"], "RISK_METRICS_ELIGIBLE")
        self.assertFalse(report["orders_enabled"])

    def test_negative_or_nonfinite_position_marks_are_rejected(self):
        for mark in ("0", "-1", "NaN", "Infinity"):
            data = fixture(broker_positions=[
                {"symbol": "BTC/USD", "qty": "0.01", "current_price": mark}
            ])
            with self.subTest(mark=mark), self.assertRaises(StrategyEquityMetricsError):
                calculate_strategy_equity_metrics(**data)

    def test_future_baseline_is_rejected(self):
        data = fixture(session_baseline=StrategySessionBaseline(
            "2026-11-13", Decimal("1000"), NOW + timedelta(minutes=1),
            "FUTURE", Decimal("0"),
        ))
        with self.assertRaisesRegex(StrategyEquityMetricsError, "future"):
            calculate_strategy_equity_metrics(**data)


if __name__ == "__main__":
    unittest.main()
