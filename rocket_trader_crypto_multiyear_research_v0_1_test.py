#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline regression tests for multi-year crypto research and Holm correction."""

import unittest

import numpy as np
import pandas as pd

from rocket_trader_crypto_multiyear_research_v0_1 import (
    bootstrap_relative_pvalue,
    evaluate_cross_sectional,
    evaluate_single_asset,
    holm_adjust,
)


def synthetic_frame(periods=1500, seed=20261110):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=periods, freq="D", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, periods)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "timestamp": dates,
        "open": open_,
        "high": np.maximum(open_, close) * 1.005,
        "low": np.minimum(open_, close) * 0.995,
        "close": close,
        "volume": rng.lognormal(8, 0.3, periods),
    })


class CryptoResearchMultipleTestingTests(unittest.TestCase):
    def test_centered_bootstrap_pvalue_for_positive_and_negative_excess(self):
        positive = bootstrap_relative_pvalue(
            np.full(250, 0.001), np.zeros(250), seed=11, reps=2000
        )
        negative = bootstrap_relative_pvalue(
            np.full(250, -0.001), np.zeros(250), seed=11, reps=2000
        )
        self.assertLessEqual(positive, 0.001)
        self.assertEqual(negative, 1.0)

    def test_holm_adjustment_is_monotone_and_validates_input(self):
        adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.002})
        self.assertAlmostEqual(adjusted["d"], 0.008)
        self.assertAlmostEqual(adjusted["a"], 0.03)
        self.assertAlmostEqual(adjusted["c"], 0.06)
        self.assertAlmostEqual(adjusted["b"], 0.06)
        with self.assertRaisesRegex(Exception, "Invalid p-value"):
            holm_adjust({"bad": 1.5})

    def test_single_asset_candidates_emit_holdout_pvalues(self):
        result = evaluate_single_asset("BTC/USD", synthetic_frame())
        for name, metrics in result["strategies"].items():
            if name == "buy_and_hold":
                continue
            self.assertIn(
                "bootstrap_p_value_excess_vs_buy_hold",
                metrics["final_holdout_20pct"],
            )

    def test_cross_sectional_candidate_emits_holdout_pvalue_and_entries(self):
        frames = {
            "BTC/USD": synthetic_frame(seed=1),
            "ETH/USD": synthetic_frame(seed=2),
        }
        result = evaluate_cross_sectional(frames)
        metrics = result["top1_momentum"]["final_holdout_20pct"]
        self.assertIn("bootstrap_p_value_excess_vs_equal_weight", metrics)
        self.assertIn("entries", metrics)
        self.assertGreaterEqual(metrics["entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
