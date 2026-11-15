#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the SIP daily-close trade-condition audit."""
import unittest

from rocket_trader_sip_close_condition_audit import (
    classify_close_discrepancy,
    daily_close_eligible,
    select_last_eligible_postmarket_trade,
    run_audit,
)


class SipCloseConditionAuditTests(unittest.TestCase):
    def test_identical_sip_trade_id_records_are_collapsed_but_trade_corrections_are_not(self):
        trades = [
            {
                "timestamp": "2020-03-16T20:00:00.100000Z",
                "price": 202.49, "size": 500000, "conditions": ["6"],
                "trade_id": 11, "exchange": "P", "tape": "C",
            },
            {
                "timestamp": "2020-03-16T20:00:00.110000Z",
                "price": 202.49, "size": 500000, "conditions": ["6"],
                "trade_id": 11, "exchange": "P", "tape": "C",
            },
            {
                "timestamp": "2020-03-16T20:00:00.120000Z",
                "price": 202.50, "size": 500000, "conditions": ["6"],
                "trade_id": 11, "exchange": "P", "tape": "C",
            },
        ]
        result = classify_close_discrepancy(
            symbol="DIA", session="2020-03-16",
            alpaca_daily_close=202.49, yahoo_close=202.49, trades=trades,
        )
        self.assertEqual(result["trade_record_count_in_window"], 3)
        self.assertEqual(result["unique_trade_count_in_window"], 2)
        self.assertEqual(result["duplicate_trade_records_collapsed"], 1)

    def test_daily_close_can_match_last_eligible_trade_later_in_postmarket(self):
        trades = [
            {
                "timestamp": "2020-03-16T20:00:00.100000Z",
                "price": 202.49, "size": 500000, "conditions": ["6"],
                "trade_id": 11, "exchange": "P", "tape": "B",
            }
        ]
        postmarket = {
            "timestamp": "2020-03-16T20:30:00.000000Z",
            "price": 207.11, "size": 100, "conditions": ["@"],
            "trade_id": 12, "exchange": "P", "tape": "B",
        }
        result = classify_close_discrepancy(
            symbol="DIA", session="2020-03-16",
            alpaca_daily_close=207.11, yahoo_close=202.49,
            trades=trades, postmarket_last_eligible_trade=postmarket,
        )
        self.assertEqual(result["status"], "POSTMARKET_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED")
        self.assertTrue(result["alpaca_daily_close_matches_postmarket_last_eligible_trade"])

    def test_select_last_eligible_postmarket_trade_skips_extended_hours_condition(self):
        rows = [
            {"t": "2020-03-16T20:30:00Z", "p": 207.11, "s": 100, "c": ["@", "T"], "i": 1, "x": "P", "z": "B"},
            {"t": "2020-03-16T20:29:00Z", "p": 207.10, "s": 100, "c": ["@"], "i": 2, "x": "P", "z": "B"},
        ]
        selected = select_last_eligible_postmarket_trade(rows)
        self.assertEqual(selected["trade_id"], 2)
        self.assertEqual(selected["price"], 207.10)

    def test_condition_b_is_tape_specific(self):
        self.assertFalse(daily_close_eligible(["B"], tape="A"))
        self.assertFalse(daily_close_eligible(["B"], tape="B"))
        self.assertTrue(daily_close_eligible(["B"], tape="C"))
        self.assertFalse(daily_close_eligible(["B"], tape=None))

    def test_run_audit_rejects_duplicate_targets_before_network(self):
        with self.assertRaisesRegex(Exception, "Duplicate symbol/session"):
            run_audit(targets=[
                {"symbol": "SPY", "session": "2020-03-12"},
                {"symbol": "spy", "session": "2020-03-12"},
            ])

    def test_market_center_official_close_is_not_daily_close_eligible(self):
        self.assertFalse(daily_close_eligible(["M"]))
        self.assertTrue(daily_close_eligible(["6"]))
        self.assertTrue(daily_close_eligible(["9"]))

    def test_any_excluded_condition_uses_strictest_rule(self):
        self.assertFalse(daily_close_eligible(["@", "I"]))
        self.assertFalse(daily_close_eligible(["@", "T"]))
        self.assertTrue(daily_close_eligible(["@", "F"], tape="B"))

    def test_official_market_center_close_explains_vendor_difference(self):
        trades = [
            {
                "timestamp": "2020-03-16T19:59:59.900000Z",
                "price": 207.11,
                "size": 100,
                "conditions": ["@"],
                "trade_id": 10,
                "exchange": "P",
                "tape": "C",
            },
            {
                "timestamp": "2020-03-16T20:00:00.100000Z",
                "price": 202.49,
                "size": 500000,
                "conditions": ["M"],
                "trade_id": 11,
                "exchange": "P",
                "tape": "C",
            },
            {
                "timestamp": "2020-03-16T20:00:00.200000Z",
                "price": 202.48,
                "size": 1,
                "conditions": ["@", "T"],
                "trade_id": 12,
                "exchange": "P",
                "tape": "C",
            },
        ]
        result = classify_close_discrepancy(
            symbol="DIA",
            session="2020-03-16",
            alpaca_daily_close=207.11,
            yahoo_close=202.49,
            trades=trades,
        )
        self.assertEqual(result["status"], "PRE_CLOSE_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED")
        self.assertTrue(result["alpaca_daily_close_matches_pre_close_trade"])
        self.assertFalse(result["alpaca_daily_close_matches_postmarket_last_eligible_trade"])
        self.assertEqual(
            result["official_close_trades_matching_yahoo"][0]["conditions"], ["M"]
        )

    def test_condition_six_before_1600_is_not_mislabelled_as_auction_close(self):
        result = classify_close_discrepancy(
            symbol="DIA",
            session="2020-03-16",
            alpaca_daily_close=202.49,
            yahoo_close=202.49,
            trades=[{
                "timestamp": "2020-03-16T19:59:59.900000Z",
                "price": 202.49,
                "size": 500000,
                "conditions": ["6"],
            }],
        )
        self.assertEqual(result["status"], "CLOSES_AGREE")
        self.assertEqual(result["official_close_condition_trades"], [])
        self.assertTrue(result["alpaca_daily_close_matches_pre_close_trade"])

    def test_closing_trade_condition_six_is_eligible_and_reproduces_daily_close(self):
        trades = [
            {
                "timestamp": "2020-03-16T20:00:00.100000Z",
                "price": 202.49,
                "size": 500000,
                "conditions": ["6"],
            }
        ]
        result = classify_close_discrepancy(
            symbol="DIA",
            session="2020-03-16",
            alpaca_daily_close=202.49,
            yahoo_close=202.49,
            trades=trades,
            postmarket_last_eligible_trade=trades[0],
        )
        self.assertEqual(result["status"], "CLOSES_AGREE")
        self.assertTrue(result["alpaca_daily_close_matches_postmarket_last_eligible_trade"])

    def test_daily_bar_not_reproduced_from_eligible_trades_stays_unresolved(self):
        trades = [
            {
                "timestamp": "2020-03-16T19:59:59.900000Z",
                "price": 207.11,
                "size": 100,
                "conditions": ["@"],
            }
        ]
        result = classify_close_discrepancy(
            symbol="DIA",
            session="2020-03-16",
            alpaca_daily_close=206.00,
            yahoo_close=202.49,
            trades=trades,
        )
        self.assertEqual(
            result["status"],
            "ALPACA_DAILY_CLOSE_NOT_REPRODUCED_FROM_WINDOW_TRADES",
        )

    def test_no_official_close_trade_match_remains_unresolved(self):
        trades = [
            {
                "timestamp": "2020-03-16T19:59:59.900000Z",
                "price": 207.11,
                "size": 100,
                "conditions": ["@"],
            }
        ]
        result = classify_close_discrepancy(
            symbol="DIA",
            session="2020-03-16",
            alpaca_daily_close=207.11,
            yahoo_close=202.49,
            trades=trades,
        )
        self.assertEqual(
            result["status"],
            "ALPACA_DAILY_CLOSE_MATCHES_PRE_CLOSE_TRADE_ONLY",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
