#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for strict timestamped USD/MXN quote ingestion."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rocket_trader_fx_provider import ExchangerateDevFXProvider, FXProviderError


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ExchangerateDevFXProviderTests(unittest.TestCase):
    def payload(self, *, effective_at=None, stale=False, base="USD"):
        return {
            "result": "success",
            "base": base,
            "source": "live",
            "market_session": "open",
            "effective_at": {
                "MXN": (effective_at or (NOW - timedelta(minutes=15)).isoformat())
            },
            "rates": {"MXN": 18.123456},
            "stale": {"MXN": stale},
        }

    def test_accepts_recent_quote_using_effective_at(self):
        calls = []
        provider = ExchangerateDevFXProvider(
            opener=lambda request, timeout: (calls.append(request) or FakeResponse(self.payload())),
        )
        quote = provider.quote_for_fill(NOW, now=NOW)
        self.assertEqual(quote.mxn_per_usd, Decimal("18.123456"))
        self.assertEqual(quote.observed_at, NOW - timedelta(minutes=15))
        self.assertIn("indicative_not_settlement", quote.source)
        self.assertEqual(len(calls), 1)

    def test_rejects_stale_quote(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, _timeout: FakeResponse(
                self.payload(effective_at=(NOW - timedelta(hours=1)).isoformat())
            )
        )
        with self.assertRaisesRegex(FXProviderError, "stale"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_future_quote_to_prevent_lookahead(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, _timeout: FakeResponse(
                self.payload(effective_at=(NOW + timedelta(minutes=1)).isoformat())
            )
        )
        with self.assertRaisesRegex(FXProviderError, "newer than the fill"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_provider_stale_flag(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, _timeout: FakeResponse(self.payload(stale=True))
        )
        with self.assertRaisesRegex(FXProviderError, "marked stale"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_wrong_base_currency(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, _timeout: FakeResponse(self.payload(base="EUR"))
        )
        with self.assertRaisesRegex(FXProviderError, "non-USD"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_cache_respects_provider_call_budget(self):
        calls = []
        provider = ExchangerateDevFXProvider(
            cache_seconds=900,
            opener=lambda request, timeout: (calls.append(request) or FakeResponse(self.payload())),
        )
        provider.quote_for_fill(NOW, now=NOW)
        provider.quote_for_fill(NOW + timedelta(minutes=1), now=NOW + timedelta(minutes=1))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
