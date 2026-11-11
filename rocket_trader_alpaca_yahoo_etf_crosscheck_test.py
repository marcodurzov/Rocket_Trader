#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for independent adjusted-close source comparison."""
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from rocket_trader_alpaca_yahoo_etf_crosscheck import (
    CrosscheckError,
    _close_series,
    compare_close_series,
    fetch_yahoo_history,
    fetch_tiingo_history,
    _rename_pair_result,
)


class AlpacaYahooCrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2024-01-02", periods=8, freq="B", tz="UTC")
        self.yahoo = pd.Series(
            [100.0, 101.0, 100.5, 102.0, 103.0, 102.5, 104.0, 105.0],
            index=self.dates,
        )

    def test_identical_series_pass_diagnostic_gates(self):
        result = compare_close_series(
            "SPY", self.yahoo, self.yahoo,
            min_common_sessions=5,
            min_source_coverage=1.0,
        )
        self.assertTrue(result["diagnostic_pass"])
        self.assertEqual(result["common_sessions"], 8)
        self.assertAlmostEqual(result["daily_return_correlation"], 1.0)
        self.assertAlmostEqual(result["p95_abs_daily_return_difference_bps"], 0.0)

    def test_return_divergence_fails_diagnostic_gate(self):
        alpaca = self.yahoo.copy()
        alpaca.iloc[4:] = alpaca.iloc[4:] * 1.03
        result = compare_close_series(
            "QQQ", self.yahoo, alpaca,
            min_common_sessions=5,
            min_source_coverage=1.0,
            max_p95_abs_return_diff_bps=1.0,
        )
        self.assertFalse(result["diagnostic_pass"])
        self.assertFalse(result["diagnostic_gates"]["maximum_p95_abs_return_difference"])

    def test_source_coverage_is_measured_separately(self):
        alpaca = self.yahoo.iloc[1:-1]
        result = compare_close_series(
            "IWM", self.yahoo, alpaca,
            min_common_sessions=3,
            min_source_coverage=0.95,
        )
        self.assertFalse(result["diagnostic_pass"])
        self.assertLess(result["yahoo_coverage_on_common"], 0.95)

    def test_close_series_rejects_nonpositive_or_invalid_data(self):
        bad = self.yahoo.copy()
        bad.iloc[2] = 0
        with self.assertRaisesRegex(CrosscheckError, "positive"):
            _close_series(bad, "fixture")
        invalid = pd.Series([1.0, 2.0], index=["not-a-date", "2024-01-03"])
        with self.assertRaisesRegex(CrosscheckError, "timestamps"):
            _close_series(invalid, "fixture")

    def test_yahoo_history_disables_repair_workaround(self):
        calls = {}
        class FakeTicker:
            def history(self, **kwargs):
                calls.update(kwargs)
                return pd.DataFrame(
                    {"Close": [100.0, 101.0, 102.0]},
                    index=pd.date_range("2024-01-02", periods=3, freq="B", tz="UTC"),
                )
        fake_yfinance = SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
            result = fetch_yahoo_history(
                "SPY",
                pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                pd.Timestamp("2024-01-10", tz="UTC").to_pydatetime(),
            )
        self.assertEqual(len(result), 3)
        self.assertFalse(calls["repair"])
        self.assertTrue(calls["auto_adjust"])
        self.assertTrue(calls["actions"])

    def test_tiingo_history_uses_adjusted_close_and_token_header(self):
        calls = {}
        payload = [
            {"date": date.isoformat(), "adjClose": value, "close": value + 99}
            for date, value in zip(self.dates, [100, 101, 102, 103, 104, 105, 106, 107])
        ]
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                import json
                return json.dumps(payload).encode("utf-8")
        def fake_opener(request, timeout):
            calls["authorization"] = request.get_header("Authorization")
            calls["url"] = request.full_url
            calls["timeout"] = timeout
            return FakeResponse()
        result = fetch_tiingo_history(
            "SPY",
            pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
            pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime(),
            "fixture-token",
            opener=fake_opener,
        )
        self.assertEqual(len(result), 8)
        self.assertEqual(result.iloc[0], 100.0)
        self.assertEqual(calls["authorization"], "Token fixture-token")
        self.assertEqual(calls["timeout"], 30)
        self.assertIn("startDate=", calls["url"])
        self.assertIn("endDate=", calls["url"])

    def test_tiingo_history_requires_token_and_valid_adjusted_close(self):
        with self.assertRaisesRegex(CrosscheckError, "TIINGO_API_TOKEN"):
            fetch_tiingo_history(
                "SPY",
                pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime(),
                "",
            )
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'[{"date":"2024-01-02","close":100}]'
        with self.assertRaisesRegex(CrosscheckError, "malformed adjusted close"):
            fetch_tiingo_history(
                "SPY",
                pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime(),
                "fixture-token",
                opener=lambda request, timeout: FakeResponse(),
            )

    def test_tiingo_pair_report_uses_true_provider_names_and_direction(self):
        raw = compare_close_series("SPY", self.yahoo, self.yahoo * 1.01)
        named = _rename_pair_result(raw, "YAHOO", "TIINGO")
        self.assertEqual(named["comparison"], "TIINGO_VS_YAHOO")
        self.assertIn("yahoo_sessions", named)
        self.assertIn("tiingo_sessions", named)
        self.assertIn("tiingo_coverage_on_common", named)
        self.assertAlmostEqual(
            named["right_minus_left_cumulative_return_difference_bps"],
            raw["cumulative_return_difference_bps"],
        )

    def test_duplicate_session_keeps_last_observation(self):
        idx = [self.dates[0], self.dates[0], self.dates[1]]
        series = pd.Series([100.0, 101.0, 102.0], index=idx)
        normalized = _close_series(series, "fixture")
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized.iloc[0], 101.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
