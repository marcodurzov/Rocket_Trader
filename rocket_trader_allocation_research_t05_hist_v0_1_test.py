#!/usr/bin/env python3
"""Offline tests for the T05 2005-2016 independent-sample study."""

import unittest
from datetime import datetime, timezone

import rocket_trader_allocation_research_t05_v0_1 as t05
import rocket_trader_allocation_research_t05_hist_v0_1 as hist


class T05HistTests(unittest.TestCase):
    def test_window_ends_before_all_prior_study_windows(self):
        self.assertLess(hist.WINDOW_END, datetime(2016, 11, 19, tzinfo=timezone.utc))

    def test_rules_are_the_unchanged_t05_family(self):
        self.assertEqual(set(t05.RULES), set(t05.HYPOTHESES))
        self.assertTrue(set(hist.RISK_RULES) <= set(t05.RULES))

    def test_offline_run_reports_drawdown_criteria_and_no_orders(self):
        r = hist.run(frames=t05.synthetic_frames(sessions=1500))
        self.assertTrue(r["ok"])
        self.assertEqual(r["orders_submitted"], 0)
        self.assertFalse(r["candidate_promotion_allowed"])
        for name in hist.RISK_RULES:
            c = r["drawdown_control"][name]
            self.assertEqual(set(c), {"max_dd_reduction_pp", "cagr_shortfall", "sharpe_shortfall", "pass"})

    def test_drawdown_criteria_logic(self):
        fake = {"benchmark": {t05.BENCHMARK: {"full_period": {"max_drawdown": -0.40, "cagr": 0.08, "sharpe_annualized": 0.6}}},
                "hypotheses": {n: {"full_period": {"max_drawdown": -0.20, "cagr": 0.06, "sharpe_annualized": 0.58}} for n in hist.RISK_RULES}}
        self.assertTrue(all(v["pass"] for v in hist.drawdown_criteria(fake).values()))
        fake["hypotheses"][hist.RISK_RULES[0]]["full_period"]["cagr"] = 0.04
        self.assertFalse(hist.drawdown_criteria(fake)[hist.RISK_RULES[0]]["pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
