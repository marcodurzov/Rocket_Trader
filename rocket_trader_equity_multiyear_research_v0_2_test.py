#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline regression tests for 10-year equity research v0.2."""

import unittest
from datetime import timedelta

import numpy as np
import pandas as pd

from rocket_trader_equity_multiyear_research_v0_2 import (
    bootstrap_q05_relative,
    data_quality_metrics,
    fetch_daily_bars,
    fetch_yahoo_daily_bars,
    strategy_positions,
)


def synthetic_frame(start="2016-11-09", periods=2600, seed=20261110):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods, tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, periods)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "timestamp": dates,
        "open": open_,
        "high": np.maximum(open_, close) * 1.005,
        "low": np.minimum(open_, close) * 0.995,
        "close": close,
        "volume": rng.lognormal(12, 0.3, periods),
    })


class FakeResponse:
    def __init__(self, frame):
        self.df = frame


class FakeStockClient:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def get_stock_bars(self, request):
        self.calls += 1
        return FakeResponse(self.frame)


class FakeYahooTicker:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


class EquityResearchV02Tests(unittest.TestCase):
    def test_relative_bootstrap_is_positive_for_constant_excess(self):
        strategy = np.full(250, 0.001)
        benchmark = np.zeros(250)
        self.assertGreater(bootstrap_q05_relative(strategy, benchmark), 0)

    def test_data_quality_rejects_missing_sessions(self):
        frame = synthetic_frame(periods=2000)
        incomplete = frame.drop(index=range(0, len(frame), 10)).reset_index(drop=True)
        self.assertFalse(data_quality_metrics(incomplete)["eligible_for_strategy_evidence"])

    def test_10_year_fetch_requires_requested_history(self):
        frame = synthetic_frame()
        end = frame["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        client = FakeStockClient(frame)
        result = fetch_daily_bars(
            "SPY", years=10, feed_name="IEX", client=client, end=end, chunk_days=365
        )
        self.assertGreaterEqual(len(result), 1800)
        self.assertEqual(result.iloc[0]["timestamp"], frame.iloc[0]["timestamp"])
        self.assertGreaterEqual(client.calls, 9)

    def test_short_history_cannot_pass_as_ten_year_research(self):
        frame = synthetic_frame(start="2021-11-09", periods=1250)
        end = frame["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        with self.assertRaisesRegex(Exception, "daily bars|requested 10-year") as caught:
            fetch_daily_bars(
                "SPY", years=10, client=FakeStockClient(frame),
                end=end, chunk_days=365,
            )
        self.assertIn("Returned range=", str(caught.exception))
        self.assertIn("approx_weekday_coverage=", str(caught.exception))
        self.assertIn("max_calendar_gap_days=", str(caught.exception))

    def test_yahoo_fetch_uses_adjusted_ohlc_and_requires_full_history(self):
        raw = synthetic_frame()
        yahoo_frame = raw.set_index("timestamp").rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        end = raw["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        ticker = FakeYahooTicker(yahoo_frame)
        result = fetch_yahoo_daily_bars(
            "SPY", years=10, ticker=ticker, end=end
        )
        self.assertGreaterEqual(len(result), 1800)
        self.assertEqual(result.iloc[0]["timestamp"], raw.iloc[0]["timestamp"])
        self.assertEqual(ticker.calls[0]["interval"], "1d")
        self.assertIs(ticker.calls[0]["auto_adjust"], True)
        self.assertIs(ticker.calls[0]["actions"], True)
        self.assertIs(ticker.calls[0]["repair"], True)
        self.assertEqual(ticker.calls[0]["end"], end.date().isoformat())

    def test_yahoo_short_history_fails_closed(self):
        raw = synthetic_frame(start="2021-11-09", periods=1250)
        yahoo_frame = raw.set_index("timestamp").rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        end = raw["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        with self.assertRaisesRegex(Exception, "Yahoo returned only"):
            fetch_yahoo_daily_bars(
                "SPY", years=10, ticker=FakeYahooTicker(yahoo_frame), end=end
            )

    def test_252_day_momentum_uses_one_session_lag(self):
        frame = synthetic_frame(periods=2100)
        positions = strategy_positions(frame)
        series = positions["time_series_momentum_252d"]
        # 252-day return is first known at index 252; shifted signal may first
        # become actionable on index 253, never on the same close.
        self.assertEqual(float(series.iloc[:253].sum()), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
