#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline regression tests for next-open equity research v0.3."""

import json
import unittest
from datetime import timedelta

import numpy as np
import pandas as pd

from rocket_trader_equity_multiyear_research_v0_4 import (
    EquityResearchError,
    bootstrap_q05_relative,
    bootstrap_relative_pvalue,
    holm_adjust,
    data_quality_metrics,
    evaluate_single_asset,
    evaluate_weights,
    strategy_positions,
    require_zero_budget_feed,
    historical_request_end,
    fetch_daily_bars,
    fetch_yahoo_daily_bars,
    fetch_tiingo_daily_bars,
    source_metadata,
    normalize_frame,
    research,
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
        self.requests = []

    def get_stock_bars(self, request):
        self.calls += 1
        self.requests.append(request)
        return FakeResponse(self.frame)


class FakeYahooTicker:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


class EquityResearchV04Tests(unittest.TestCase):

    def test_public_research_rejects_tiingo_as_primary_source(self):
        with self.assertRaisesRegex(ValueError, "Tiingo is disabled"):
            research(symbols=["SPY", "QQQ"], years=3, feed_name="IEX", source="TIINGO")

    def test_zero_budget_feed_allows_historical_sip_but_blocks_recent_sip(self):
        self.assertEqual(require_zero_budget_feed("iex"), "IEX")
        now = pd.Timestamp("2026-11-11T12:00:00Z").to_pydatetime()
        self.assertEqual(
            require_zero_budget_feed("SIP", end_time=now - timedelta(minutes=16), now=now),
            "SIP",
        )
        with self.assertRaisesRegex(EquityResearchError, "at least 15 minutes ago"):
            require_zero_budget_feed("SIP", end_time=now - timedelta(minutes=14), now=now)
        with self.assertRaisesRegex(EquityResearchError, "explicit timezone-aware"):
            require_zero_budget_feed("SIP", now=now)
    def test_normalize_frame_tolerates_only_float_precision_ohlc_differences(self):
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=2, tz="UTC"),
            "open": [100.0, 100.0],
            "high": [100.0 - 1e-12, 100.0 - 1e-5],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "volume": [1000, 1000],
        })
        normalized = normalize_frame(frame.iloc[:1], "SPY")
        self.assertEqual(len(normalized), 1)
        with self.assertRaisesRegex(Exception, "invalid OHLCV rows"):
            normalize_frame(frame.iloc[1:], "SPY")

    def test_relative_bootstrap_is_positive_for_constant_excess(self):
        strategy = np.full(250, 0.001)
        benchmark = np.zeros(250)
        self.assertGreater(bootstrap_q05_relative(strategy, benchmark), 0)

    def test_centered_block_bootstrap_pvalue_detects_constant_positive_excess(self):
        strategy = np.full(250, 0.001)
        benchmark = np.zeros(250)
        pvalue = bootstrap_relative_pvalue(strategy, benchmark, seed=7, reps=2000)
        self.assertLessEqual(pvalue, 0.001)

    def test_centered_block_bootstrap_pvalue_does_not_reward_negative_excess(self):
        strategy = np.full(250, -0.001)
        benchmark = np.zeros(250)
        pvalue = bootstrap_relative_pvalue(strategy, benchmark, seed=7, reps=2000)
        self.assertEqual(pvalue, 1.0)

    def test_holm_adjustment_controls_familywise_error_monotonically(self):
        adjusted = holm_adjust({
            "p01": 0.01,
            "p04": 0.04,
            "p03": 0.03,
            "p002": 0.002,
        })
        self.assertAlmostEqual(adjusted["p002"], 0.008)
        self.assertAlmostEqual(adjusted["p01"], 0.03)
        self.assertAlmostEqual(adjusted["p03"], 0.06)
        self.assertAlmostEqual(adjusted["p04"], 0.06)

    def test_holm_rejects_invalid_pvalues(self):
        with self.assertRaisesRegex(Exception, "Invalid p-value"):
            holm_adjust({"bad": 1.2})

    def test_single_asset_evaluation_emits_holdout_pvalues_for_candidates(self):
        frame = synthetic_frame(periods=1600, seed=71)
        result = evaluate_single_asset("SPY", frame)
        candidates = result["strategies"]
        self.assertIn("buy_and_hold", candidates)
        for name, metrics in candidates.items():
            if name == "buy_and_hold":
                continue
            self.assertIn(
                "bootstrap_p_value_excess_vs_buy_hold",
                metrics["final_holdout_20pct"],
                msg=f"Missing p-value for {name}",
            )

    def test_data_quality_rejects_missing_sessions(self):
        frame = synthetic_frame(periods=2000)
        incomplete = frame.drop(index=range(0, len(frame), 10)).reset_index(drop=True)
        self.assertFalse(data_quality_metrics(incomplete)["eligible_for_strategy_evidence"])

    def test_exchange_calendar_excludes_us_market_holidays(self):
        frame = synthetic_frame(start="2024-07-01", periods=6)
        frame = frame[frame["timestamp"].dt.day != 4].reset_index(drop=True)
        metrics = data_quality_metrics(frame)
        self.assertEqual(metrics["calendar"], "XNYS")
        self.assertEqual(metrics["expected_exchange_sessions"], 5)
        self.assertEqual(metrics["daily_bars"], 5)
        self.assertEqual(metrics["missing_exchange_sessions"], 0)
        self.assertAlmostEqual(metrics["exchange_session_coverage_pct"], 1.0)
        self.assertTrue(metrics["eligible_for_strategy_evidence"])

    def test_exchange_calendar_detects_missing_actual_session(self):
        frame = synthetic_frame(start="2024-07-01", periods=6)
        frame = frame[frame["timestamp"].dt.day != 4]
        frame = frame[frame["timestamp"].dt.day != 2].reset_index(drop=True)
        metrics = data_quality_metrics(frame)
        self.assertEqual(metrics["expected_exchange_sessions"], 5)
        self.assertEqual(metrics["daily_bars"], 4)
        self.assertEqual(metrics["missing_exchange_sessions"], 1)
        self.assertAlmostEqual(metrics["exchange_session_coverage_pct"], 0.8)
        self.assertFalse(metrics["eligible_for_strategy_evidence"])
        self.assertEqual(metrics["first_missing_exchange_session"], "2024-07-02")

    def test_10_year_fetch_requires_requested_history_and_uses_free_historical_sip(self):
        frame = synthetic_frame()
        end = frame["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        client = FakeStockClient(frame)
        result = fetch_daily_bars(
            "SPY", years=10, feed_name="SIP", client=client, end=end, chunk_days=365
        )
        self.assertGreaterEqual(len(result), 1800)
        self.assertEqual(result.iloc[0]["timestamp"], frame.iloc[0]["timestamp"])
        self.assertGreaterEqual(client.calls, 9)
        self.assertTrue(all(request.feed.value == "sip" for request in client.requests))

    def test_historical_request_end_uses_last_completed_xnys_session(self):
        before_close = pd.Timestamp("2026-11-11T20:00:00Z").to_pydatetime()
        after_close = pd.Timestamp("2026-11-11T21:20:00Z").to_pydatetime()
        self.assertEqual(
            historical_request_end(before_close),
            pd.Timestamp("2026-11-10T21:00:00Z").to_pydatetime(),
        )
        self.assertEqual(
            historical_request_end(after_close),
            pd.Timestamp("2026-11-11T21:00:00Z").to_pydatetime(),
        )

    def test_fetch_daily_bars_uses_injected_clock_for_default_historical_end(self):
        frame = synthetic_frame()
        client = FakeStockClient(frame)
        now = pd.Timestamp("2026-11-11T12:00:00Z").to_pydatetime()
        fetch_daily_bars(
            "SPY", years=10, feed_name="SIP", client=client,
            now=now, chunk_days=365,
        )
        expected_end = historical_request_end(now)
        self.assertTrue(client.requests)
        self.assertEqual(pd.Timestamp(client.requests[-1].end).tz_localize("UTC"), pd.Timestamp(expected_end))
        self.assertTrue(all(request.feed.value == "sip" for request in client.requests))

    def test_recent_sip_is_rejected_before_any_market_data_request(self):
        frame = synthetic_frame()
        client = FakeStockClient(frame)
        now = pd.Timestamp("2026-11-11T12:00:00Z").to_pydatetime()
        with self.assertRaisesRegex(EquityResearchError, "at least 15 minutes ago"):
            fetch_daily_bars(
                "SPY", years=3, feed_name="SIP", client=client,
                end=now - timedelta(minutes=14), now=now, chunk_days=365,
            )
        self.assertEqual(client.calls, 0)

    def test_short_history_cannot_pass_as_ten_year_research(self):
        frame = synthetic_frame(start="2021-11-09", periods=1250)
        end = frame["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        with self.assertRaisesRegex(Exception, "daily bars|requested 10-year") as caught:
            fetch_daily_bars(
                "SPY", years=10, client=FakeStockClient(frame),
                end=end, chunk_days=365,
            )
        self.assertIn("Returned range=", str(caught.exception))
        self.assertIn("exchange_session_coverage=", str(caught.exception))
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
        self.assertIs(ticker.calls[0]["repair"], False)
        self.assertEqual(ticker.calls[0]["end"], (end.date() + timedelta(days=1)).isoformat())

    def test_tiingo_fetch_uses_adjusted_ohlcv_and_requires_full_history(self):
        raw = synthetic_frame()
        payload = []
        for row in raw.to_dict(orient="records"):
            payload.append({
                "date": row["timestamp"].isoformat(),
                "adjOpen": row["open"], "adjHigh": row["high"],
                "adjLow": row["low"], "adjClose": row["close"],
                "adjVolume": row["volume"],
            })
        class FakeResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(payload).encode("utf-8")
        captured = {}
        def fake_opener(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse()
        end = raw["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        result = fetch_tiingo_daily_bars(
            "SPY", years=10, api_token="test-token", opener=fake_opener, end=end
        )
        self.assertGreaterEqual(len(result), 1800)
        self.assertEqual(result.iloc[0]["timestamp"], raw.iloc[0]["timestamp"])
        self.assertEqual(captured["authorization"], "Token test-token")
        self.assertEqual(captured["timeout"], 30)
        self.assertIn("startDate=", captured["url"])
        self.assertIn("endDate=", captured["url"])

    def test_tiingo_requires_token_and_fails_on_short_history(self):
        with self.assertRaisesRegex(Exception, "TIINGO_API_TOKEN is required"):
            fetch_tiingo_daily_bars("SPY", years=10, api_token="")
        raw = synthetic_frame(start="2021-11-09", periods=1250)
        payload = [{
            "date": row["timestamp"].isoformat(),
            "adjOpen": row["open"], "adjHigh": row["high"],
            "adjLow": row["low"], "adjClose": row["close"],
            "adjVolume": row["volume"],
        } for row in raw.to_dict(orient="records")]
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(payload).encode("utf-8")
        end = raw["timestamp"].iloc[-1].to_pydatetime() + timedelta(days=1)
        with self.assertRaisesRegex(Exception, "Tiingo returned only"):
            fetch_tiingo_daily_bars(
                "SPY", years=10, api_token="test-token",
                opener=lambda request, timeout: FakeResponse(), end=end,
            )

    def test_source_metadata_matches_actual_yahoo_repair_setting(self):
        yahoo = source_metadata("YAHOO")
        self.assertIn("repair=False", yahoo["data_source"])
        self.assertIn("repair=False", yahoo["price_adjustment"])
        tiingo = source_metadata("TIINGO")
        self.assertIn("Tiingo EOD", tiingo["data_source"])
        self.assertIn("CRSP", tiingo["price_adjustment"])

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

    def test_mean_reversion_variants_are_deterministic_long_only_weights(self):
        frame = synthetic_frame(periods=2600)
        positions = strategy_positions(frame)
        expected = {
            "rsi2_10_sma200_exit_sma5",
            "bollinger_20_2_exit_mid",
            "zscore_5d_2_exit_zero",
        }
        self.assertTrue(expected.issubset(positions))
        for name in expected:
            self.assertTrue(((positions[name] >= 0.0) & (positions[name] <= 1.0)).all())

    def test_rsi2_signal_is_lagged_to_next_open(self):
        close = np.linspace(100.0, 199.0, 200).tolist() + [189.0, 179.0, 178.0]
        dates = pd.bdate_range("2020-01-01", periods=len(close), tz="UTC")
        frame = pd.DataFrame({
            "timestamp": dates, "open": close, "high": np.array(close) * 1.01,
            "low": np.array(close) * 0.99, "close": close, "volume": 100000.0,
        })
        weights = strategy_positions(frame)["rsi2_10_sma200_exit_sma5"]
        self.assertEqual(float(weights.iloc[200]), 0.0)
        self.assertEqual(float(weights.iloc[201]), 1.0)

    def test_next_open_execution_excludes_unavailable_overnight_gap(self):
        open_prices = pd.Series([100.0, 200.0, 220.0, 242.0])
        weights = pd.Series([0.0, 1.0, 1.0, 1.0])
        metrics, net = evaluate_weights(
            open_prices, weights, cost_multiplier=0.0
        )
        self.assertEqual(metrics.bars, 3)
        self.assertAlmostEqual(float(net.iloc[0]), 0.0, places=12)
        self.assertAlmostEqual(float(net.iloc[1]), 0.10, places=12)
        self.assertAlmostEqual(float(net.iloc[2]), 0.10, places=12)

    def test_252_day_momentum_uses_one_session_lag(self):
        frame = synthetic_frame(periods=2100)
        positions = strategy_positions(frame)
        series = positions["time_series_momentum_252d"]
        # 252-day return is first known at index 252; shifted signal may first
        # become actionable on index 253, never on the same close.
        self.assertEqual(float(series.iloc[:253].sum()), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
