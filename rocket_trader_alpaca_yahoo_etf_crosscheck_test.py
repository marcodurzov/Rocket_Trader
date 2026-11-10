#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for independent adjusted-close source comparison."""
import unittest

import pandas as pd

from rocket_trader_alpaca_yahoo_etf_crosscheck import (
    CrosscheckError,
    _close_series,
    compare_close_series,
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

    def test_duplicate_session_keeps_last_observation(self):
        idx = [self.dates[0], self.dates[0], self.dates[1]]
        series = pd.Series([100.0, 101.0, 102.0], index=idx)
        normalized = _close_series(series, "fixture")
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized.iloc[0], 101.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
