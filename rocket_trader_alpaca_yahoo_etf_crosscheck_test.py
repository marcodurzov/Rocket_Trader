#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for independent adjusted-close source comparison."""
import unittest
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from rocket_trader_alpaca_yahoo_etf_crosscheck import (
    CrosscheckError,
    _close_series,
    compare_close_series,
    fetch_yahoo_history,
    fetch_yahoo_adjustment_fields,
    compare_adjustment_factors,
    fetch_tiingo_history,
    fetch_alpaca_corporate_actions,
    tiingo_audit_status,
    require_zero_budget_feed,
    historical_request_end,
    resolve_tiingo_token,
    _rename_pair_result,
)


class AlpacaYahooCrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2024-01-02", periods=8, freq="B", tz="UTC")
        self.yahoo = pd.Series(
            [100.0, 101.0, 100.5, 102.0, 103.0, 102.5, 104.0, 105.0],
            index=self.dates,
        )

    def test_historical_request_end_uses_last_completed_xnys_session(self):
        before_close = pd.Timestamp("2026-11-11T20:00:00Z").to_pydatetime()
        after_close = pd.Timestamp("2026-11-11T21:20:00Z").to_pydatetime()
        self.assertEqual(
            historical_request_end(before_close),
            pd.Timestamp("2026-11-11T00:00:00Z").to_pydatetime(),
        )
        self.assertEqual(
            historical_request_end(after_close),
            pd.Timestamp("2026-11-12T00:00:00Z").to_pydatetime(),
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


    def test_return_divergence_report_identifies_exact_sessions(self):
        alpaca = self.yahoo.copy()
        alpaca.iloc[4:] = alpaca.iloc[4:] * 1.03
        result = compare_close_series(
            "SPY", self.yahoo, alpaca,
            min_common_sessions=5,
            min_source_coverage=1.0,
            max_p95_abs_return_diff_bps=1.0,
        )
        outlier = result["largest_daily_return_divergences"][0]
        self.assertEqual(outlier["session"], str(self.dates[4].date()))
        self.assertGreater(
            abs(outlier["alpaca_minus_yahoo_return_difference_bps"]), 200.0
        )
        self.assertEqual(len(result["largest_daily_return_divergences"]), 7)
        self.assertTrue(result["largest_normalized_close_divergences"])
        self.assertIn(
            "alpaca_vs_yahoo_normalized_close_difference_pct",
            result["largest_normalized_close_divergences"][0],
        )

    def test_source_coverage_is_measured_separately(self):
        alpaca = self.yahoo.iloc[1:-1]
        result = compare_close_series(
            "IWM", self.yahoo, alpaca,
            min_common_sessions=3,
            min_source_coverage=0.95,
        )
        self.assertFalse(result["diagnostic_pass"])
        self.assertLess(result["yahoo_coverage_on_common"], 0.95)


    def test_history_start_mismatch_is_not_mislabeled_as_internal_missing_bars(self):
        extended_dates = pd.date_range("2018-01-02", periods=1500, freq="B", tz="UTC")
        yahoo = pd.Series(range(100, 1600), index=extended_dates, dtype=float)
        alpaca = yahoo.loc[yahoo.index >= pd.Timestamp("2020-07-27", tz="UTC")]
        result = compare_close_series(
            "DIA", yahoo, alpaca,
            min_common_sessions=100,
            min_source_coverage=0.95,
        )
        self.assertEqual(
            result["history_window_assessment"],
            "RIGHT_SOURCE_STARTS_LATER_THAN_LEFT",
        )
        self.assertAlmostEqual(result["alpaca_overlap_session_completeness"], 1.0)
        self.assertAlmostEqual(result["yahoo_overlap_session_completeness"], 1.0)
        self.assertFalse(result["diagnostic_gates"]["minimum_requested_history_overlap"])
        self.assertTrue(result["diagnostic_gates"]["minimum_overlap_session_completeness"])

    def test_history_end_mismatch_is_not_mislabeled_as_comparable_windows(self):
        alpaca = self.yahoo.iloc[:-1]
        result = compare_close_series(
            "DIA", self.yahoo, alpaca,
            min_common_sessions=5,
            min_source_coverage=0.95,
        )
        self.assertEqual(
            result["history_window_assessment"],
            "RIGHT_SOURCE_ENDS_EARLIER_THAN_LEFT",
        )
        self.assertEqual(result["alpaca_history_end_lag_days"], 1)
        self.assertEqual(result["overlap_session_assessment"], "OVERLAP_SESSIONS_ALIGNED")
        self.assertFalse(result["diagnostic_gates"]["minimum_requested_history_overlap"])

    def test_history_window_containment_reports_both_boundaries(self):
        alpaca = self.yahoo.iloc[1:-1]
        result = compare_close_series(
            "DIA", self.yahoo, alpaca,
            min_common_sessions=5,
            min_source_coverage=0.95,
        )
        self.assertEqual(result["history_window_assessment"], "RIGHT_SOURCE_WINDOW_INSIDE_LEFT")
        self.assertEqual(result["alpaca_history_start_lag_days"], 1)
        self.assertEqual(result["alpaca_history_end_lag_days"], 1)

    def test_internal_missing_sessions_are_reported_separately_from_start_mismatch(self):
        alpaca = self.yahoo.drop(self.yahoo.index[3])
        result = compare_close_series(
            "IWM", self.yahoo, alpaca,
            min_common_sessions=3,
            min_source_coverage=0.95,
        )
        self.assertEqual(result["history_window_assessment"], "COMPARABLE_HISTORY_WINDOWS")
        self.assertEqual(result["overlap_session_assessment"], "SESSION_GAPS_WITHIN_OVERLAP")
        self.assertFalse(result["diagnostic_gates"]["minimum_overlap_session_completeness"])

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


    def test_adjustment_factor_diagnostics_separate_raw_prices_from_adjustments(self):
        raw = self.yahoo.copy()
        yahoo_factor = pd.Series([0.90] * 8, index=self.dates)
        alpaca_factor = pd.Series([0.91] * 4 + [0.90] * 4, index=self.dates)
        yahoo_adjusted = raw * yahoo_factor
        alpaca_adjusted = raw * alpaca_factor
        dividends = pd.Series([0.0, 0.0, 0.0, 0.0, 0.51856, 0.0, 0.0, 0.0], index=self.dates)
        result = compare_adjustment_factors(
            "QQQ", raw, yahoo_adjusted, raw, alpaca_adjusted,
            min_common_sessions=5,
            yahoo_dividends=dividends,
        )
        self.assertAlmostEqual(result["max_abs_raw_normalized_close_difference_pct"], 0.0)
        self.assertAlmostEqual(result["mean_abs_raw_daily_return_difference_bps"], 0.0)
        self.assertGreater(result["max_abs_relative_adjustment_factor_divergence_pct"], 0.0)
        step = result["largest_adjustment_factor_step_changes"][0]
        self.assertEqual(step["session"], str(self.dates[4].date()))
        self.assertEqual(step["previous_session"], str(self.dates[3].date()))
        self.assertAlmostEqual(step["previous_yahoo_adjustment_factor"], 0.90)
        self.assertAlmostEqual(step["previous_alpaca_adjustment_factor"], 0.91)
        self.assertAlmostEqual(step["yahoo_adjustment_factor"], 0.90)
        self.assertAlmostEqual(step["alpaca_adjustment_factor"], 0.90)
        self.assertAlmostEqual(step["alpaca_to_yahoo_factor_ratio"], 1.0)
        self.assertAlmostEqual(step["yahoo_dividend_cash_on_session"], 0.51856)
        self.assertAlmostEqual(
            step["expected_cash_dividend_adjustment_bps_vs_previous_yahoo_raw_close"],
            0.51856 / raw.iloc[3] * 10000.0,
            places=4,
        )

    def test_missing_yahoo_dividend_is_compared_with_alpaca_issuer_event(self):
        raw = self.yahoo.copy()
        yahoo_factor = pd.Series([1.0] * 8, index=self.dates)
        alpaca_factor = pd.Series([0.995] * 4 + [1.0] * 4, index=self.dates)
        yahoo_dividends = pd.Series([0.0] * 8, index=self.dates)
        result = compare_adjustment_factors(
            "TLT", raw, raw * yahoo_factor, raw, raw * alpaca_factor,
            min_common_sessions=5,
            yahoo_dividends=yahoo_dividends,
            alpaca_corporate_actions=[{
                "action_type": "cash_dividend", "symbol": "TLT",
                "ex_date": str(self.dates[4].date()), "rate": "0.343177",
                "process_date": str(self.dates[4].date()),
            }],
        )
        step = result["largest_adjustment_factor_step_changes"][0]
        self.assertEqual(step["yahoo_dividend_cash_on_session"], 0.0)
        self.assertAlmostEqual(step["alpaca_cash_dividend_total_on_session"], 0.343177)
        self.assertEqual(step["alpaca_cash_dividend_event_count"], 1)
        self.assertEqual(step["alpaca_cash_dividend_total_status"], "SINGLE_EVENT")
        self.assertAlmostEqual(
            step["yahoo_minus_alpaca_cash_dividend_on_session"], -0.343177
        )

    def test_alpaca_corporate_actions_fetches_and_paginates_cash_dividends(self):
        calls = []
        payloads = [
            {
                "corporate_actions": {
                    "cash_dividends": [{
                        "id": "ca-1", "symbol": "QQQ", "ex_date": "2022-09-19",
                        "rate": "0.51856", "special": False, "process_date": "2022-09-19",
                    }],
                },
                "next_page_token": "page-2",
            },
            {
                "corporate_actions": {
                    "cash_dividends": [{
                        "id": "ca-2", "symbol": "TLT", "ex_date": "2026-11-02",
                        "rate": "0.343177", "special": False, "process_date": "2026-11-02",
                    }],
                },
                "next_page_token": None,
            },
        ]
        class FakeResponse:
            status = 200
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.payload).encode("utf-8")
        def fake_opener(request, timeout):
            calls.append(request)
            return FakeResponse(payloads[len(calls) - 1])
        start = pd.Timestamp("2016-11-10", tz="UTC").to_pydatetime()
        end = pd.Timestamp("2026-11-10", tz="UTC").to_pydatetime()
        events = fetch_alpaca_corporate_actions(
            ["QQQ", "TLT"], start, end, "key", "secret", opener=fake_opener
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["action_type"], "cash_dividend")
        self.assertEqual(events[0]["rate"], "0.51856")
        self.assertIn("symbols=QQQ%2CTLT", calls[0].full_url)
        self.assertIn("page_token=page-2", calls[1].full_url)
        self.assertEqual(calls[0].get_header("Apca-api-key-id"), "key")
        self.assertEqual(calls[0].get_header("Apca-api-secret-key"), "secret")

    def test_alpaca_corporate_actions_rejects_missing_response_envelope(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({
                    "cash_dividends": [{
                        "symbol": "TLT", "ex_date": "2026-11-02", "rate": "0.343177"
                    }],
                    "next_page_token": None,
                }).encode("utf-8")
        start = pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime()
        end = pd.Timestamp("2026-11-10", tz="UTC").to_pydatetime()
        with self.assertRaisesRegex(CrosscheckError, "corporate_actions object"):
            fetch_alpaca_corporate_actions(
                ["TLT"], start, end, "key", "secret",
                opener=lambda request, timeout: FakeResponse(),
            )

    def test_multiple_alpaca_cash_dividend_records_are_not_summed_without_review(self):
        raw = self.yahoo.copy()
        yahoo_factor = pd.Series([1.0] * 8, index=self.dates)
        alpaca_factor = pd.Series([0.995] * 4 + [1.0] * 4, index=self.dates)
        result = compare_adjustment_factors(
            "QQQ", raw, raw * yahoo_factor, raw, raw * alpaca_factor,
            min_common_sessions=5,
            yahoo_dividends=pd.Series([0.0] * 8, index=self.dates),
            alpaca_corporate_actions=[
                {
                    "id": "ca-1", "action_type": "cash_dividend", "symbol": "QQQ",
                    "ex_date": str(self.dates[4].date()), "rate": "0.51856",
                    "process_date": "2022-09-23",
                },
                {
                    "id": "ca-2", "action_type": "cash_dividend", "symbol": "QQQ",
                    "ex_date": str(self.dates[4].date()), "rate": "0.51856",
                    "process_date": "2022-10-31",
                },
            ],
        )
        step = result["largest_adjustment_factor_step_changes"][0]
        self.assertEqual(step["alpaca_cash_dividend_event_count"], 2)
        self.assertEqual(step["alpaca_cash_dividend_event_ids"], ["ca-1", "ca-2"])
        self.assertEqual(
            step["alpaca_cash_dividend_total_status"],
            "MULTIPLE_RECORDS_REQUIRES_REVIEW",
        )
        self.assertIsNone(step["alpaca_cash_dividend_total_on_session"])
        self.assertIsNone(step["yahoo_minus_alpaca_cash_dividend_on_session"])

    def test_yahoo_adjustment_fields_fetch_raw_and_adjusted_close_separately(self):
        calls = {}
        class FakeTicker:
            def history(self, **kwargs):
                calls.update(kwargs)
                return pd.DataFrame(
                    {"Close": [100.0, 101.0, 102.0], "Adj Close": [99.0, 100.0, 101.0],
                     "Dividends": [0.0, 0.25, 0.0], "Stock Splits": [0.0, 0.0, 2.0]},
                    index=pd.date_range("2024-01-02", periods=3, freq="B", tz="UTC"),
                )
        fake_yfinance = SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
            result = fetch_yahoo_adjustment_fields(
                "SPY",
                pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                pd.Timestamp("2024-01-10", tz="UTC").to_pydatetime(),
            )
        self.assertEqual(result["raw_close"].iloc[0], 100.0)
        self.assertEqual(result["adjusted_close"].iloc[0], 99.0)
        self.assertEqual(result["dividends"].iloc[1], 0.25)
        self.assertEqual(result["splits"].iloc[2], 2.0)
        self.assertFalse(calls["auto_adjust"])
        self.assertFalse(calls["repair"])
        self.assertTrue(calls["actions"])

    def test_tiingo_token_is_ignored_without_explicit_opt_in(self):
        self.assertEqual(resolve_tiingo_token(False, "secret-token"), "")

    def test_tiingo_token_requires_explicit_opt_in_and_token(self):
        with self.assertRaisesRegex(CrosscheckError, "explicitly requested"):
            resolve_tiingo_token(True, None)
        self.assertEqual(resolve_tiingo_token(True, "starter-token"), "starter-token")

    def test_historical_request_end_is_a_completed_safe_utc_boundary(self):
        for now in (
            pd.Timestamp("2026-11-11T00:05:00Z").to_pydatetime(),
            pd.Timestamp("2026-11-11T12:00:00Z").to_pydatetime(),
        ):
            end = historical_request_end(now)
            self.assertEqual(end.hour, 0)
            self.assertEqual(end.minute, 0)
            self.assertLessEqual(end, now - pd.Timedelta(minutes=15))

    def test_zero_budget_feed_allows_historical_sip_but_blocks_recent_sip(self):
        self.assertEqual(require_zero_budget_feed("iex"), "IEX")
        now = pd.Timestamp("2026-11-11T12:00:00Z").to_pydatetime()
        self.assertEqual(
            require_zero_budget_feed("SIP", end_time=now - pd.Timedelta(minutes=16), now=now),
            "SIP",
        )
        with self.assertRaisesRegex(CrosscheckError, "at least 15 minutes ago"):
            require_zero_budget_feed("SIP", end_time=now - pd.Timedelta(minutes=14), now=now)
        with self.assertRaisesRegex(CrosscheckError, "explicit timezone-aware"):
            require_zero_budget_feed("SIP", now=now)

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

    def test_tiingo_audit_is_not_requested_not_a_false_pass(self):
        status = tiingo_audit_status(None, [], [], expected_symbols=8)
        self.assertFalse(status["requested"])
        self.assertEqual(status["status"], "NOT_REQUESTED")
        self.assertIsNone(status["all_diagnostic_gates_pass"])

    def test_tiingo_audit_fails_when_requested_but_incomplete(self):
        status = tiingo_audit_status(
            "configured-token", [], [], expected_symbols=8
        )
        self.assertTrue(status["requested"])
        self.assertEqual(status["status"], "FAILED")
        self.assertFalse(status["all_diagnostic_gates_pass"])

    def test_tiingo_audit_passes_only_when_all_symbols_pass_both_pairs(self):
        item = {
            "tiingo_vs_yahoo": {"diagnostic_pass": True},
            "tiingo_vs_alpaca": {"diagnostic_pass": True},
        }
        status = tiingo_audit_status(
            "configured-token", [item] * 8, [], expected_symbols=8
        )
        self.assertTrue(status["requested"])
        self.assertEqual(status["status"], "PASSED")
        self.assertTrue(status["all_diagnostic_gates_pass"])

    def test_tiingo_pair_report_uses_true_provider_names_and_direction(self):
        raw = compare_close_series("SPY", self.yahoo, self.yahoo * 1.01)
        named = _rename_pair_result(raw, "YAHOO", "TIINGO")
        self.assertEqual(named["comparison"], "TIINGO_VS_YAHOO")
        self.assertIn("yahoo_sessions", named)
        self.assertIn("tiingo_sessions", named)
        self.assertIn("tiingo_coverage_on_common", named)
        self.assertIn("tiingo_first_session", named)
        self.assertIn("tiingo_history_start_lag_days", named)
        self.assertIn("tiingo_history_end_lag_days", named)
        self.assertIn("tiingo_overlap_session_completeness", named)
        self.assertIn("overlap_session_assessment", named)
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
