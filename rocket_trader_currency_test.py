#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for MXN capital conversion and USD position budget guard."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rocket_trader_currency import (
    CurrencyBudgetError,
    FXQuote,
    calculate_position_budget,
)


NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


class CurrencyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fx = FXQuote(
            mxn_per_usd=Decimal("18.00"),
            observed_at=NOW - timedelta(minutes=5),
            source="test-fixture",
        )

    def test_mxn_1000_converts_to_usd_and_position_is_capped(self):
        budget = calculate_position_budget(
            capital_mxn="1000",
            available_cash_usd="100000",
            current_exposure_usd="0",
            fx_quote=self.fx,
            max_position_pct="0.10",
            max_total_exposure_pct="0.50",
            max_loss_per_trade_pct="0.01",
            stop_distance_pct="0.02",
            now=NOW,
        )
        self.assertTrue(budget.allowed)
        self.assertEqual(budget.capital_usd, Decimal("1000") / Decimal("18"))
        self.assertEqual(budget.max_notional_usd, Decimal("5.55"))
        self.assertEqual(budget.max_notional_mxn, Decimal("99.90"))

    def test_paper_buying_power_cannot_override_mxn_capital(self):
        small_cash = calculate_position_budget(
            capital_mxn="1000",
            available_cash_usd="100000",
            current_exposure_usd="0",
            fx_quote=self.fx,
            now=NOW,
        )
        huge_cash = calculate_position_budget(
            capital_mxn="1000",
            available_cash_usd="9999999",
            current_exposure_usd="0",
            fx_quote=self.fx,
            now=NOW,
        )
        self.assertEqual(small_cash.max_notional_usd, huge_cash.max_notional_usd)

    def test_existing_exposure_reduces_remaining_budget(self):
        budget = calculate_position_budget(
            capital_mxn="1000",
            available_cash_usd="100",
            current_exposure_usd="20",
            fx_quote=self.fx,
            max_position_pct="0.50",
            max_total_exposure_pct="0.50",
            now=NOW,
        )
        self.assertFalse(budget.allowed)
        self.assertEqual(budget.max_notional_usd, Decimal("0.00"))

    def test_stale_fx_fails_closed(self):
        stale = FXQuote(
            mxn_per_usd="18",
            observed_at=NOW - timedelta(hours=25),
            source="test-fixture",
        )
        with self.assertRaisesRegex(CurrencyBudgetError, "stale"):
            calculate_position_budget(
                capital_mxn="1000",
                available_cash_usd="100",
                current_exposure_usd="0",
                fx_quote=stale,
                now=NOW,
            )

    def test_future_and_naive_fx_timestamps_are_rejected(self):
        with self.assertRaisesRegex(CurrencyBudgetError, "future"):
            calculate_position_budget(
                capital_mxn="1000",
                available_cash_usd="100",
                current_exposure_usd="0",
                fx_quote=FXQuote("18", NOW + timedelta(minutes=1), "test"),
                now=NOW,
            )
        with self.assertRaisesRegex(CurrencyBudgetError, "timezone-aware"):
            FXQuote("18", datetime(2026, 11, 9), "test")

    def test_below_minimum_order_is_blocked_not_rounded_up(self):
        budget = calculate_position_budget(
            capital_mxn="100",
            available_cash_usd="100",
            current_exposure_usd="0",
            fx_quote=self.fx,
            min_order_usd="1",
            now=NOW,
        )
        self.assertFalse(budget.allowed)
        self.assertEqual(budget.max_notional_usd, Decimal("0.00"))

    def test_invalid_or_missing_fx_source_is_rejected(self):
        with self.assertRaises(CurrencyBudgetError):
            FXQuote("0", NOW, "test")
        with self.assertRaises(CurrencyBudgetError):
            FXQuote("18", NOW, " ")

    def test_cash_caps_position_budget(self):
        budget = calculate_position_budget(
            capital_mxn="1000",
            available_cash_usd="2.25",
            current_exposure_usd="0",
            fx_quote=self.fx,
            now=NOW,
        )
        self.assertTrue(budget.allowed)
        self.assertEqual(budget.max_notional_usd, Decimal("2.25"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
