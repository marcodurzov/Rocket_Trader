#!/usr/bin/env python3
"""Offline tests for the quoted-spread measurement study."""

import unittest
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import rocket_trader_spread_study as st

NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def q(bid, ask, ts):
    return SimpleNamespace(bid_price=bid, ask_price=ask, timestamp=ts)


class SpreadStudyTests(unittest.TestCase):
    def test_half_spread_bps(self):
        self.assertAlmostEqual(st.half_spread_bps(99.99, 100.01), 1.0, places=6)
        for bad in [(0, 1), (1, 1), (2, 1), (None, 1), ("x", 1), (float("nan"), 1)]:
            self.assertIsNone(st.half_spread_bps(*bad))

    def test_last_valid_quote_ignores_crossed_and_uses_latest(self):
        t0 = NOW
        quotes = [q(99.0, 101.0, t0), q(99.99, 100.01, t0 + timedelta(seconds=5)),
                  q(100.02, 100.00, t0 + timedelta(seconds=9))]  # crossed, ignored
        self.assertAlmostEqual(st.last_valid_quote(quotes), 1.0, places=6)
        self.assertIsNone(st.last_valid_quote([q(1, 1, t0)]))

    def test_verdicts(self):
        self.assertEqual(st.summarize([1.0] * 10, 10, 2.5)["verdict"], "ASSUMPTION_COVERS_P90")
        self.assertEqual(st.summarize([1.0] * 8 + [9.0] * 2, 10, 2.5)["verdict"], "ASSUMPTION_COVERS_MEDIAN_ONLY")
        self.assertEqual(st.summarize([5.0] * 10, 10, 2.5)["verdict"], "ASSUMPTION_TOO_LOW")
        self.assertEqual(st.summarize([1.0] * 7, 10, 2.5)["verdict"], "INSUFFICIENT_DATA")
        self.assertEqual(st.summarize([], 0, 2.5)["verdict"], "INSUFFICIENT_DATA")

    def test_sample_points_are_new_york_times_and_skip_early_close(self):
        d = date(2026, 11, 27)  # day after Thanksgiving: 13:00 close
        pts = list(st.etf_sample_points([d], early_close=lambda _d: time(13, 0)))
        self.assertEqual([p[1] for p in pts], [time(9, 35), time(10, 30), time(12, 0)])
        self.assertEqual(pts[0][2], datetime(2026, 11, 27, 14, 35, tzinfo=timezone.utc))

    def test_run_study_with_fake_fetchers_and_no_orders(self):
        def stock_fetch(symbols, start, end):
            self.assertLessEqual(end - start, timedelta(seconds=st.ETF_WINDOW_SECONDS))
            return {s: [q(99.99, 100.01, end)] for s in symbols}

        def crypto_fetch(symbols, start, end):
            return {s: [q(49990, 50010, end)] for s in symbols if s != "SOL/USD"}

        r = st.run_study(now=NOW, sessions=2, crypto_days=1, stock_fetch=stock_fetch,
                         crypto_fetch=crypto_fetch, session_list=[date(2026, 11, 19), date(2026, 11, 20)])
        self.assertEqual(r["etf"]["SPY"]["samples_valid"], 12)
        self.assertEqual(r["etf"]["SPY"]["verdict"], "ASSUMPTION_COVERS_P90")
        self.assertEqual(r["crypto"]["BTC/USD"]["verdict"], "ASSUMPTION_COVERS_P90")
        self.assertEqual(r["crypto"]["SOL/USD"]["verdict"], "INSUFFICIENT_DATA")
        self.assertFalse(r["cost_assumptions_validated"])
        self.assertEqual(r["orders_submitted"], 0)
        self.assertEqual(st.summary_line(r)["orders_submitted"], 0)

    def test_alpaca_fetch_is_per_symbol_newest_first(self):
        from alpaca.common.enums import Sort
        calls = []

        class FakeClient:
            def get_stock_quotes(self, req):
                calls.append(req)
                return SimpleNamespace(data={req.symbol_or_symbols: [q(1, 2, NOW)]})
            get_crypto_quotes = get_stock_quotes

        stock_fetch, crypto_fetch = st._alpaca_fetchers(FakeClient(), FakeClient())
        end = datetime.now(timezone.utc) - timedelta(hours=1)
        got = stock_fetch(["SPY", "QQQ"], end - timedelta(seconds=60), end)
        self.assertEqual(sorted(got), ["QQQ", "SPY"])
        self.assertEqual([c.symbol_or_symbols for c in calls], ["SPY", "QQQ"])
        self.assertTrue(all(c.sort == Sort.DESC and c.limit == st.PER_SYMBOL_QUOTE_LIMIT for c in calls))
        with self.assertRaises(st.SpreadStudyError):
            stock_fetch(["SPY"], datetime.now(timezone.utc) - timedelta(minutes=2), datetime.now(timezone.utc))
        crypto_fetch(["BTC/USD"], end - timedelta(minutes=5), end)
        self.assertEqual(calls[-1].symbol_or_symbols, "BTC/USD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
