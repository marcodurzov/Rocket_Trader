#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for persistent drawdown protection; no broker access."""
import os, tempfile, unittest
from rocket_trader_drawdown_guard import DrawdownGuardError, PersistentDrawdownGuard

class PersistentDrawdownGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "risk", "drawdown.json")
    def tearDown(self):
        self.tmp.cleanup()
    def test_initializes_and_tracks_new_high_water_mark(self):
        guard = PersistentDrawdownGuard(self.path, 0.10)
        self.assertTrue(guard.evaluate(1000).allowed)
        self.assertEqual(guard.evaluate(1100).high_water_mark, 1100)
        result = guard.evaluate(1050)
        self.assertTrue(result.allowed)
        self.assertAlmostEqual(result.drawdown_pct, 50 / 1100)
    def test_locks_at_limit_and_stays_locked_after_recovery(self):
        guard = PersistentDrawdownGuard(self.path, 0.10)
        guard.evaluate(1000)
        breach = guard.evaluate(900)
        self.assertFalse(breach.allowed)
        self.assertTrue(breach.locked)
        self.assertEqual(breach.reason, "MAX_DRAWDOWN_LIMIT_REACHED")
        recovered = guard.evaluate(1200)
        self.assertFalse(recovered.allowed)
    def test_lock_survives_restart(self):
        PersistentDrawdownGuard(self.path, 0.10).evaluate(1000)
        PersistentDrawdownGuard(self.path, 0.10).evaluate(890)
        result = PersistentDrawdownGuard(self.path, 0.10).evaluate(950)
        self.assertFalse(result.allowed)
        self.assertEqual(result.high_water_mark, 1000)
    def test_corrupt_state_fails_closed(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle: handle.write("{not-json")
        with self.assertRaises(DrawdownGuardError):
            PersistentDrawdownGuard(self.path, 0.10).evaluate(1000)
    def test_configuration_change_fails_closed(self):
        PersistentDrawdownGuard(self.path, 0.10).evaluate(1000)
        with self.assertRaises(DrawdownGuardError):
            PersistentDrawdownGuard(self.path, 0.15).evaluate(1000)
    def test_invalid_equity_fails_closed(self):
        guard = PersistentDrawdownGuard(self.path, 0.10)
        for value in (0, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                with self.assertRaises(DrawdownGuardError): guard.evaluate(value)
    def test_uninitialized_status_fails_closed(self):
        with self.assertRaises(DrawdownGuardError):
            PersistentDrawdownGuard(self.path, 0.10).status()

if __name__ == "__main__":
    unittest.main(verbosity=2)
