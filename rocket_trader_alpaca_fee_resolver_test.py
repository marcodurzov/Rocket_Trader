#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Alpaca Paper Account Activities fee resolution."""

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_alpaca_fee_resolver import (
    AlpacaActivityFeeResolver,
    AlpacaFeeNotAvailable,
    AlpacaFeeResolutionError,
    AlpacaPaperActivitiesClient,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)


class FakeResponse:
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self):
        return b"[]"


class AlpacaActivityFeeResolverTests(unittest.TestCase):
    def test_paper_activity_client_caches_same_utc_fill_day(self):
        calls = []
        client = AlpacaPaperActivitiesClient(
            api_key="paper-key",
            secret_key="paper-secret",
            cache_seconds=900,
            opener=lambda request, timeout=None: (calls.append(request) or FakeResponse()),
        )
        first = client.list_fee_activities(NOW)
        second = client.list_fee_activities(NOW.replace(hour=22))
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(len(calls), 1)

    def test_crypto_buy_base_asset_fee_is_converted_to_usd(self):
        activities = [{
            "id": "20261109::exec-buy",
            "activity_type": "CFEE",
            "net_amount": "0",
            "qty": "-0.00000025",
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
        self.assertEqual(Decimal(result["fee_usd"]), Decimal("0.00250000"))
        self.assertEqual(Decimal(result["fee_asset_qty"]), Decimal("-0.00000025"))
        self.assertIn("exec-buy", result["fee_source"])

    def test_crypto_sell_usd_fee_uses_negative_net_amount(self):
        activities = [{
            "id": "20261109::exec-sell",
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
