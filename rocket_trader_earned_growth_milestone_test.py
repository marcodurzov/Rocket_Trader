#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 100k milestone must be earned through trading gains, not deposits."""

import unittest

from rocket_trader_core import build_demo_core


class EarnedGrowthMilestoneTests(unittest.TestCase):
    def test_external_deposit_does_not_trigger_payout_policy(self):
        core = build_demo_core()
        plan = core.monthly_distribution_plan(
            distributable_profit=1000.0,
            operating_capital=150000.0,
            period="2026-11",
            earned_growth_capital_mxn=1000.0,
        )
        self.assertFalse(plan.threshold_reached)
        self.assertEqual(plan.reinvestment_amount, 1000.0)
        self.assertEqual(plan.reserve_amount, 0.0)
        self.assertEqual(plan.personal_amount, 0.0)
        self.assertEqual(plan.milestone_qualifying_capital_mxn, 1000.0)

    def test_earned_growth_triggers_50_10_40_after_threshold(self):
        core = build_demo_core()
        plan = core.monthly_distribution_plan(
            distributable_profit=1000.0,
            operating_capital=150000.0,
            period="2026-11",
            earned_growth_capital_mxn=100000.0,
        )
        self.assertTrue(plan.threshold_reached)
        self.assertEqual(plan.reinvestment_amount, 500.0)
        self.assertEqual(plan.reserve_amount, 100.0)
        self.assertEqual(plan.personal_amount, 400.0)
        self.assertFalse(plan.payouts_suspended)

    def test_production_distribution_requires_ledger_growth_value(self):
        core = build_demo_core()
        core.require_persistent_milestone = True
        with self.assertRaisesRegex(RuntimeError, "earned_growth_capital_mxn"):
            core.monthly_distribution_plan(
                distributable_profit=1000.0,
                operating_capital=150000.0,
                period="2026-11",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
