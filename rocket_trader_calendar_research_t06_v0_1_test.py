#!/usr/bin/env python3
"""Offline tests for T06 turn-of-month research."""

import unittest

import numpy as np
import pandas as pd

import rocket_trader_allocation_research_t05_v0_1 as t05
import rocket_trader_calendar_research_t06_v0_1 as t06


def ny_index(start, periods):
    return pd.bdate_range(start, periods=periods).tz_localize("America/New_York").tz_convert("UTC")


class T06Tests(unittest.TestCase):
    def test_mask_marks_last_day_and_first_three_days(self):
        idx = ny_index("2024-01-02", 70)  # Jan..early Apr
        mask, valid = t06.tom_mask(idx)
        ny = idx.tz_convert("America/New_York")
        marked = [d.strftime("%m-%d") for d, m in zip(ny, mask) if m]
        # Jan partial? Jan 2 is the first business day so January is excluded as first month in sample.
        self.assertIn("02-29", marked)           # last session of Feb
        self.assertIn("03-01", marked)
        self.assertIn("03-05", marked)           # third session of March (1, 4, 5)
        self.assertNotIn("03-06", marked)
        self.assertFalse(valid[0])               # first (partial) month excluded
        self.assertFalse(valid[-1])              # last (partial) month excluded

    def test_planted_effect_is_detected_and_null_is_not(self):
        idx = ny_index("2016-01-01", 2600)
        rng = np.random.default_rng(1)
        mask, valid = t06.tom_mask(idx)
        noise = rng.normal(0, 0.01, len(idx))
        p_null = t06.circular_shift_pvalue(noise[valid], mask[valid])["p_value"]
        planted = noise + np.where(mask, 0.003, 0.0)
        p_eff = t06.circular_shift_pvalue(planted[valid], mask[valid])["p_value"]
        self.assertLess(p_eff, 0.01)
        self.assertGreater(p_null, 0.01)

    def test_costs_charged_on_entries_and_exits(self):
        idx = ny_index("2020-01-01", 300)
        r = pd.Series(0.0, index=idx)
        mask, _ = t06.tom_mask(idx)
        m = t06.strategy_metrics(r, mask, 10.0)
        self.assertLess(m["total_return"], 0)
        self.assertGreater(m["round_trips"], 5)
        self.assertAlmostEqual(m["exposure"], mask.mean())

    def test_research_offline_is_research_only(self):
        frames = t05.synthetic_frames(sessions=1200)
        res = t06.research(source="OFFLINE", frames=frames)
        self.assertTrue(res["ok"])
        self.assertEqual(res["multiple_testing"]["family_size"], 9)
        self.assertFalse(res["multiple_testing"]["promotion_allowed"])
        self.assertEqual(res["orders_submitted"], 0)
        self.assertFalse(res["candidate_promotion_allowed"])
        s = t06.summarize(res)
        self.assertIn(t06.BASKET, s["instruments"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
