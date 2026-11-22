#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline regression tests for T05 monthly allocation research v0.1."""

import json
import unittest

import numpy as np
import pandas as pd

import rocket_trader_allocation_research_t05_v0_1 as t05


def _frames_from_closes(closes: dict, opens: dict | None = None) -> dict:
    n = len(next(iter(closes.values())))
    idx = pd.bdate_range("2019-01-01", periods=n, tz="UTC") + pd.Timedelta(hours=21)
    out = {}
    for s, c in closes.items():
        c = np.asarray(c, dtype=float)
        o = np.asarray(opens[s], dtype=float) if opens else c.copy()
        out[s] = pd.DataFrame({"timestamp": idx, "open": o, "high": np.maximum(o, c) * 1.001,
                               "low": np.minimum(o, c) * 0.999, "close": c, "volume": 1e6})
    return out


class T05Tests(unittest.TestCase):
    def test_month_end_positions_exclude_final_row(self):
        # Vendor daily bars are stamped at New York midnight (04:00/05:00 UTC).
        idx = pd.bdate_range("2024-01-02", "2024-03-29").tz_localize("America/New_York").tz_convert("UTC")
        ends = t05.month_end_positions(idx)
        self.assertEqual([idx[i].month for i in ends], [1, 2])
        self.assertNotIn(len(idx) - 1, ends)

    def test_signal_rows_without_history_fail_closed(self):
        frames = t05.synthetic_frames()
        _, close, _ = t05.align_frames(frames)
        with self.assertRaises(t05.AllocationResearchError):
            t05.target_dual_momentum(close, 100)

    def test_constant_prices_give_zero_gross_and_costs_only(self):
        n = 600
        closes = {s: np.full(n, 100.0) for s in ("AAA", "BBB")}
        open_df, close_df, _ = t05.align_frames(_frames_from_closes(closes))
        sim = t05.simulate(open_df, close_df, t05.target_equal_weight, cost_bps_side=10.0)
        net = sim["net"]
        # One full entry at the first eligible month-end and liquidation: 2 x 10 bps.
        self.assertAlmostEqual(float(net.sum()), -0.002, places=12)
        self.assertAlmostEqual(float(sim["turnover"].sum()), 2.0, places=12)

    def test_no_lookahead_future_shock_after_signal_is_not_anticipated(self):
        # A huge jump occurs at an open after the last month-end. Strategies decided
        # at that month-end cannot use the jump; equal weight earns it only via
        # its held weight, and trend weights were set before it.
        n = 700
        base = np.linspace(100, 120, n)
        jump = base.copy()
        jump[-5:] *= 2.0
        frames = _frames_from_closes({"AAA": base, "BBB": jump}, {"AAA": base, "BBB": jump})
        open_df, close_df, _ = t05.align_frames(frames)
        ends = t05.month_end_positions(open_df.index)
        last_end = ends[-1]
        w_before = t05.target_trend_equal_weight(close_df, last_end)
        mod = close_df.copy()
        mod.iloc[last_end + 1:] = mod.iloc[last_end + 1:] * 10
        w_after = t05.target_trend_equal_weight(mod, last_end)
        pd.testing.assert_series_equal(w_before, w_after)

    def test_weights_never_exceed_full_investment(self):
        frames = t05.synthetic_frames()
        open_df, close_df, _ = t05.align_frames(frames)
        for name, rule in t05.RULES.items():
            sim = t05.simulate(open_df, close_df, rule, cost_bps_side=5.0)
            self.assertTrue((sim["exposure"] <= 1.0 + 1e-9).all(), name)
            self.assertTrue((sim["exposure"] >= -1e-12).all(), name)

    def test_dual_momentum_holds_cash_when_all_scores_negative(self):
        n = 400
        falling = {s: np.linspace(200, 100, n) for s in ("AAA", "BBB", "CCC", "DDD")}
        _, close_df, _ = t05.align_frames(_frames_from_closes(falling))
        w = t05.target_dual_momentum(close_df, n - 1)
        self.assertEqual(float(w.sum()), 0.0)

    def test_drift_between_rebalances(self):
        n = 600
        closes = {"UP": np.linspace(100, 200, n), "FLAT": np.full(n, 100.0)}
        open_df, close_df, _ = t05.align_frames(_frames_from_closes(closes))
        sim = t05.simulate(open_df, close_df, t05.target_equal_weight, cost_bps_side=0.0)
        rebalance_days = sim["turnover"][sim["turnover"] > 0]
        # Monthly rebalancing back to 50/50 must trade a non-zero drift amount.
        self.assertGreater(len(rebalance_days), 5)
        self.assertGreater(float(rebalance_days.iloc[2]), 0.0)

    def test_research_offline_report_is_research_only(self):
        result = t05.research(source="OFFLINE", frames=t05.synthetic_frames())
        self.assertTrue(result["ok"], json.dumps({k: v for k, v in result.items() if k != "data_quality"}, default=str)[:500])
        self.assertFalse(result["candidate_promotion_allowed"])
        self.assertFalse(result["paper_approval"])
        self.assertFalse(result["orders_enabled"])
        self.assertEqual(result["orders_submitted"], 0)
        mt = result["multiple_testing"]
        self.assertEqual(mt["family_size"], 5)
        self.assertEqual(set(result["hypotheses"]), set(t05.HYPOTHESES))
        self.assertFalse(mt["promotion_allowed"])
        for v in mt["holm_adjusted_pvalues"].values():
            self.assertTrue(0.0 <= v <= 1.0)
        summary = t05.summarize(result)
        self.assertEqual(summary["orders_submitted"], 0)
        json.dumps(summary, default=str)

    def test_poor_common_coverage_fails_closed(self):
        frames = t05.synthetic_frames()
        frames["SPY"] = frames["SPY"].iloc[::2].reset_index(drop=True)
        with self.assertRaises(t05.AllocationResearchError):
            t05.align_frames(frames)


if __name__ == "__main__":
    unittest.main(verbosity=2)
