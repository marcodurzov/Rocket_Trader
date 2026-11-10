#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Alpaca Paper Account Activities fee resolution."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_alpaca_fee_resolver import (
    AlpacaActivityFeeResolver,
    AlpacaFeeNotAvailable,
    AlpacaFeeResolutionError,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)


class AlpacaActivityFeeResolverTests(unittest.TestCase):
    def test_crypto_buy_base_asset_fee_is_converted_to_usd(self):
        activities = [{
            "id": "20261109::exec-buy",
            "activity_type": "CFEE",
            "net_amount": "0",
            "qty": "-0.0001",
            "price": "10000",
            "symbol": "BTCUSD",
            "status": "executed",
        }]
        resolver = AlpacaActivityFeeResolver(lambda _when: activities)
        result = resolver({
            "execution_id": "exec-buy",
            "timestamp": NOW.isoformat(),
            "symbol": "BTC/USD",
            "side": "BUY",
        })
        self.assertEqual(Decimal(result["fee_usd"]), Decimal("1.0000"))
        self.assertEqual(Decimal(result["fee_asset_qty"]), Decimal("-0.0001"))
        self.assertIn("exec-buy", result["fee_source"])

    def test_crypto_sell_usd_fee_uses_negative_net_amount(self):
        activities = [{
            "id": "fee-sell-1",
            "activity_type": "CFEE",
            "net_amount": "-0.025",
            "qty": "0",
            "price": "0",
            "symbol": "BTCUSD",
            "status": "executed",
        }]
        resolver = AlpacaActivityFeeResolver(lambda _when: activities)
        result = resolver({
            "execution_id": "exec-sell",
            "timestamp": NOW.isoformat(),
            "symbol": "BTC/USD",
            "side": "SELL",
        })
        self.assertEqual(result["fee_usd"], "0.025")
        self.assertEqual(result["fee_asset_qty"], "0")

    def test_execution_linked_usd_fee_uses_parent_id(self):
        activities = [{
            "id": "fee-equity-1",
            "activity_type": "FEE",
            "currency": "USD",
            "net_amount": "-0.01",
            "status": "executed",
            "details": {"parent_id": "exec-equity"},
        }]
        resolver = AlpacaActivityFeeResolver(lambda _when: activities)
        result = resolver({
            "execution_id": "exec-equity",
            "timestamp": NOW.isoformat(),
            "symbol": "SPY",
            "side": "SELL",
        })
        self.assertEqual(result["fee_usd"], "0.01")
        self.assertEqual(result["fee_asset_qty"], "0")

    def test_equity_buy_without_linked_fee_returns_explicit_zero(self):
        resolver = AlpacaActivityFeeResolver(lambda _when: [])
        result = resolver({
            "execution_id": "equity-buy",
            "timestamp": NOW.isoformat(),
            "symbol": "SPY",
            "side": "BUY",
        })
        self.assertEqual(result["fee_usd"], "0")
        self.assertIn("commission-free", result["fee_source"])

    def test_crypto_fee_not_yet_posted_remains_pending(self):
        resolver = AlpacaActivityFeeResolver(lambda _when: [])
        with self.assertRaises(AlpacaFeeNotAvailable):
            resolver({
                "execution_id": "crypto-pending",
                "timestamp": NOW.isoformat(),
                "symbol": "BTC/USD",
                "side": "BUY",
            })

    def test_unlinked_equity_sell_fee_is_not_guessed(self):
        resolver = AlpacaActivityFeeResolver(lambda _when: [{
            "id": "daily-taf",
            "activity_type": "FEE",
            "currency": "USD",
            "net_amount": "-0.01",
            "status": "executed",
            "details": {"system_date": "2026-11-09"},
        }])
        with self.assertRaises(AlpacaFeeNotAvailable):
            resolver({
                "execution_id": "equity-sell",
                "timestamp": NOW.isoformat(),
                "symbol": "SPY",
                "side": "SELL",
            })

    def test_fee_reversal_is_not_silently_counted_as_a_fee(self):
        resolver = AlpacaActivityFeeResolver(lambda _when: [{
            "id": "fee-reversal",
            "activity_type": "FEE",
            "currency": "USD",
            "net_amount": "0.01",
            "status": "executed",
            "details": {"parent_id": "exec-reversal"},
        }])
        with self.assertRaisesRegex(AlpacaFeeResolutionError, "credit/reversal"):
            resolver({
                "execution_id": "exec-reversal",
                "timestamp": NOW.isoformat(),
                "symbol": "SPY",
                "side": "SELL",
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
