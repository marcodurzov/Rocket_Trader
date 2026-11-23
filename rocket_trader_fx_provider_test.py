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
            opener=lambda _request, timeout=None: FakeResponse(
                self.payload(effective_at=(NOW - timedelta(hours=1)).isoformat())
            )
        )
        with self.assertRaisesRegex(FXProviderError, "stale"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_future_quote_to_prevent_lookahead(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, timeout=None: FakeResponse(
                self.payload(effective_at=(NOW + timedelta(minutes=1)).isoformat())
            )
        )
        with self.assertRaisesRegex(FXProviderError, "newer than the fill"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_provider_stale_flag(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, timeout=None: FakeResponse(self.payload(stale=True))
        )
        with self.assertRaisesRegex(FXProviderError, "marked stale"):
            provider.quote_for_fill(NOW, now=NOW)

    def test_rejects_wrong_base_currency(self):
        provider = ExchangerateDevFXProvider(
            opener=lambda _request, timeout=None: FakeResponse(self.payload(base="EUR"))
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

    # --- user-approved weekend/holiday policy (2026-11-23) -----------------
    def _provider(self, payload):
        return ExchangerateDevFXProvider(opener=lambda _r, timeout=None: FakeResponse(payload))

    def test_weekend_last_close_accepted_and_tagged(self):
        payload = self.payload(effective_at=(NOW - timedelta(hours=45)).isoformat())
        payload["market_session"] = "weekend"
        quote = self._provider(payload).quote_for_fill(NOW, now=NOW)
        self.assertIn("CLOSED_MARKET_LAST_CLOSE", quote.source)

    def test_weekend_quote_older_than_72h_rejected(self):
        payload = self.payload(effective_at=(NOW - timedelta(hours=73)).isoformat())
        payload["market_session"] = "weekend"
        with self.assertRaises(FXProviderError):
            self._provider(payload).quote_for_fill(NOW, now=NOW)

    def test_old_quote_during_open_session_still_rejected(self):
        payload = self.payload(effective_at=(NOW - timedelta(hours=45)).isoformat())
        with self.assertRaises(FXProviderError):
            self._provider(payload).quote_for_fill(NOW, now=NOW)

    def test_provider_stale_flag_rejected_even_on_weekend(self):
        payload = self.payload(effective_at=(NOW - timedelta(hours=10)).isoformat(), stale=True)
        payload["market_session"] = "weekend"
        with self.assertRaises(FXProviderError):
            self._provider(payload).quote_for_fill(NOW, now=NOW)

    def test_fresh_open_quote_is_not_tagged(self):
        quote = self._provider(self.payload()).quote_for_fill(NOW, now=NOW)
        self.assertNotIn("CLOSED_MARKET_LAST_CLOSE", quote.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
