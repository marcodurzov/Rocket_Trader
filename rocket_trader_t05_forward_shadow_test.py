#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the T05 forward shadow recorder."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import rocket_trader_allocation_research_t05_v0_1 as t05
import rocket_trader_t05_forward_shadow as fwd


class ForwardShadowTests(unittest.TestCase):
    def setUp(self):
        self.frames = t05.synthetic_frames(sessions=900)
        _, self.close, _ = t05.align_frames(self.frames)

    def test_completed_month_excludes_current_partial_month(self):
        last = self.close.index[-1]
        now = (last + pd.Timedelta(days=1)).to_pydatetime()
        row = fwd.latest_completed_month_end(self.close.index, now)
        ny = self.close.index.tz_convert("America/New_York").tz_localize(None)
        self.assertLess(ny[row].to_period("M"), pd.Timestamp(now).tz_convert("America/New_York").tz_localize(None).to_period("M"))
        self.assertNotEqual(ny[row].to_period("M"), ny[row + 1].to_period("M"))

    def test_record_is_written_once_and_never_overwritten(self):
        now = (self.close.index[-1] + pd.Timedelta(days=1)).to_pydatetime()
        with tempfile.TemporaryDirectory() as tmp:
            first = fwd.run(Path(tmp), now=now, frames=self.frames, source="OFFLINE")
            self.assertTrue(first["written"])
            path = Path(first["path"])
            original = path.read_text()
            second = fwd.run(Path(tmp), now=now, frames=self.frames, source="OFFLINE")
            self.assertFalse(second["written"])
            self.assertEqual(path.read_text(), original)
            record = json.loads(original)
            self.assertEqual(record["orders_submitted"], 0)
            self.assertEqual(set(record["target_weights"]), set(t05.RULES) | {t05.BENCHMARK})
            for w in record["target_weights"].values():
                self.assertLessEqual(sum(w.values()), 1.0 + 1e-9)
                self.assertGreaterEqual(min(w.values()), 0.0)

    def test_record_uses_no_data_after_signal_session(self):
        now = (self.close.index[-1] + pd.Timedelta(days=1)).to_pydatetime()
        row = fwd.latest_completed_month_end(self.close.index, now)
        a = fwd.build_record(self.close, row, source="OFFLINE", now=now)
        changed = self.close.copy()
        changed.iloc[row + 1:] *= 3.0
        b = fwd.build_record(changed, row, source="OFFLINE", now=now)
        self.assertEqual(a["target_weights"], b["target_weights"])
        self.assertEqual(a["sha256_of_record_without_hash"], b["sha256_of_record_without_hash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
