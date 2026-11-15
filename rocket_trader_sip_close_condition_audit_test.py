#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the SIP daily-close trade-condition audit."""
import unittest

from rocket_trader_sip_close_condition_audit import (
    classify_close_discrepancy,
    daily_close_eligible,
)


class SipCloseConditionAuditTests(unittest.TestCase):
    def test_market_center_official_close_is_not_daily_close_eligible(self):
        self.assertFalse(daily_close_eligible(["M"]))
        self.assertTrue(daily_close_eligible(["6"]))
        self.assertTrue(daily_close_eligible(["9"]))

    def test_any_excluded_condition_uses_strictest_rule(self):
        self.assertFalse(daily_close_eligible(["@", "I"]))
        self.assertFalse(daily_close_eligible(["@", "T"]))
        self.assertTrue(daily_close_eligible(["@", "F"]))

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
        self.assertEqual(result["status"], "SIP_OFFICIAL_CLOSE_CONDITION_EXPLAINS_GAP")
        self.assertTrue(result["last_eligible_trade_matches_alpaca_daily_close"])
        self.assertEqual(
            result["official_close_trades_matching_yahoo"][0]["conditions"], ["M"]
        )

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
        )
        self.assertEqual(result["status"], "CLOSES_AGREE")
        self.assertTrue(result["last_eligible_trade_matches_alpaca_daily_close"])

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
            "ALPACA_DAILY_CLOSE_NOT_REPRODUCED_FROM_ELIGIBLE_TRADES",
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
            "UNRESOLVED_CLOSE_DEFINITION_OR_TRADE_COVERAGE",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
