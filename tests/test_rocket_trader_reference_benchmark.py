import csv
import os
import tempfile
import unittest
from datetime import date, timedelta

from rocket_trader_reference_benchmark import (
    BenchmarkInputError, compare, load_candidate, load_prices,
)


class ReferenceBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prices_path = os.path.join(self.tmp.name, "prices.csv")
        self.candidate_path = os.path.join(self.tmp.name, "candidate.csv")
        self.output_dir = self.tmp.name
        self.dates = [(date(2025, 1, 1) + timedelta(days=i)).isoformat()
                      for i in range(300)]
        with open(self.prices_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "symbol", "close"])
            for i, day in enumerate(self.dates):
                writer.writerow([day, "SPY", 100.0 * (1.001 ** i)])
        with open(self.candidate_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "symbol", "gross_return", "turnover"])
            for i, day in enumerate(self.dates):
                gross = 0.0 if i == 0 else 0.001001
                turnover = 1.0 if i in (0, len(self.dates) - 1) else 0.0
                writer.writerow([day, "SPY", gross, turnover])

    def tearDown(self):
        self.tmp.cleanup()

    def test_compares_candidate_to_all_reference_families(self):
        result = compare(load_prices(self.prices_path),
                         load_candidate(self.candidate_path), 5.0)
        self.assertEqual(result["status"], "COMPARISON_ONLY")
        self.assertFalse(result["research_approval"])
        self.assertFalse(result["orders_enabled"])
        names = set(result["results"][0]["benchmarks"])
        self.assertEqual(names, {
            "cash", "buy_and_hold", "time_series_momentum_252d",
            "momentum_63d_skip_21d", "sma_50_200_trend",
        })
        self.assertEqual(result["results"][0]["observations"], 300)

    def test_costs_are_applied_to_one_way_turnover(self):
        result = compare(load_prices(self.prices_path),
                         load_candidate(self.candidate_path), 5.0)
        candidate = result["results"][0]["candidate"]
        self.assertAlmostEqual(candidate["estimated_cost_bps"], 10.0, places=6)
        self.assertAlmostEqual(candidate["one_way_turnover"], 2.0, places=6)

    def test_different_dates_are_rejected_not_silently_intersected(self):
        with open(self.candidate_path, "r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        with open(self.candidate_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "symbol", "gross_return", "turnover"])
            writer.writeheader()
            for row in rows[1:]:
                writer.writerow(row)
        with self.assertRaisesRegex(BenchmarkInputError, "dates must match exactly"):
            compare(load_prices(self.prices_path), load_candidate(self.candidate_path), 5.0)

    def test_duplicate_candidate_dates_are_rejected(self):
        with open(self.candidate_path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([self.dates[0], "SPY", 0, 0])
        with self.assertRaisesRegex(BenchmarkInputError, "Duplicate candidate dates"):
            load_candidate(self.candidate_path)

    def test_insufficient_history_for_12_month_reference_is_rejected(self):
        prices = {"SPY": load_prices(self.prices_path)["SPY"][:100]}
        candidates = {"SPY": load_candidate(self.candidate_path)["SPY"][:100]}
        with self.assertRaisesRegex(BenchmarkInputError, "at least 253 daily prices"):
            compare(prices, candidates, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
