import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from rocket_trader_execution_cost_telemetry import ExecutionCostTelemetry


class ExecutionCostTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "runtime.sqlite3")
        self.telemetry = ExecutionCostTelemetry(self.db)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def quote(self, symbol="SPY", at=None, bid=100.0, ask=100.2, asset_class="EQUITY"):
        return {
            "symbol": symbol,
            "timestamp": (at or self.now - timedelta(seconds=1)).isoformat(),
            "bid_price": bid, "ask_price": ask,
            "bid_size": 10, "ask_size": 12,
        }

    def fill(self, symbol="SPY", side="buy", price=100.2, qty=5,
             at=None, event="fill", order_id="order-1", order=None):
        return {
            "event": event,
            "timestamp": (at or self.now).isoformat(),
            "symbol": symbol, "side": side,
            "price": price, "qty": qty,
            "order": {"id": order_id, **(order or {})},
        }

    def test_buy_fill_measures_spread_and_adverse_slippage_from_prior_quote(self):
        self.telemetry.record_quote("EQUITY", self.quote(), "IEX")
        result = self.telemetry.record_fill_update(self.fill())
        self.assertEqual(result["status"], "MEASURED")
        self.assertTrue(result["eligible_for_aggregation"])
        self.assertAlmostEqual(result["spread_bps"], 19.98001998, places=5)
        self.assertAlmostEqual(result["slippage_bps"], 9.99000999, places=5)
        with sqlite3.connect(self.db) as db:
            row = db.execute("""SELECT quote_feed,status,eligible_for_aggregation
                FROM paper_fill_cost_observations""").fetchone()
        self.assertEqual(row, ("IEX", "MEASURED", 1))

    def test_sell_slippage_uses_opposite_sign(self):
        self.telemetry.record_quote("EQUITY", self.quote(), "IEX")
        result = self.telemetry.record_fill_update(
            self.fill(side="sell", price=100.0, order_id="order-sell")
        )
        self.assertAlmostEqual(result["slippage_bps"], 9.99000999, places=5)

    def test_future_quote_is_never_used(self):
        self.telemetry.record_quote(
            "EQUITY", self.quote(at=self.now + timedelta(seconds=1)), "IEX"
        )
        result = self.telemetry.record_fill_update(self.fill())
        self.assertEqual(result["status"], "FUTURE_QUOTE_ONLY")
        self.assertFalse(result["eligible_for_aggregation"])
        self.assertIsNone(result["slippage_bps"])

    def test_stale_quote_is_excluded(self):
        self.telemetry.record_quote(
            "EQUITY", self.quote(at=self.now - timedelta(seconds=8)), "IEX"
        )
        result = self.telemetry.record_fill_update(self.fill())
        self.assertEqual(result["status"], "STALE_QUOTE")
        self.assertFalse(result["eligible_for_aggregation"])

    def test_crypto_quote_uses_its_own_freshness_limit(self):
        quote = self.quote("BTC/USD", self.now - timedelta(seconds=8))
        self.telemetry.record_quote("CRYPTO", quote, "CRYPTO_US")
        result = self.telemetry.record_fill_update(
            self.fill("BTC/USD", at=self.now, order_id="crypto-order")
        )
        self.assertEqual(result["status"], "MEASURED")
        self.assertLessEqual(result["quote_age_seconds"], 10)

    def test_missing_quote_is_retained_but_not_aggregated(self):
        result = self.telemetry.record_fill_update(self.fill())
        self.assertEqual(result["status"], "NO_PRIOR_QUOTE")
        self.assertFalse(result["eligible_for_aggregation"])
        self.assertIsNone(result["spread_bps"])

    def test_partial_fill_cumulative_order_average_is_not_double_counted(self):
        self.telemetry.record_quote("EQUITY", self.quote(), "IEX")
        partial = self.telemetry.record_fill_update(
            self.fill(event="partial_fill", price=100.2, qty=2, order_id="order-partial")
        )
        self.assertTrue(partial["eligible_for_aggregation"])
        final = self.telemetry.record_fill_update(self.fill(
            price=None, qty=None, order_id="order-partial",
            order={"filled_avg_price": 100.15, "filled_qty": 5},
        ))
        self.assertEqual(final["status"], "CUMULATIVE_AVERAGE_AFTER_PARTIALS")
        self.assertFalse(final["eligible_for_aggregation"])
        summary = self.telemetry.summary()
        self.assertEqual(summary["measured_fill_events"], 1)
        self.assertFalse(summary["costs_empirically_validated"])

    def test_summary_is_descriptive_and_never_approves_costs(self):
        self.telemetry.record_quote("EQUITY", self.quote(), "IEX")
        self.telemetry.record_fill_update(self.fill())
        summary = self.telemetry.summary()
        self.assertEqual(summary["status"], "DESCRIPTIVE_ONLY_NOT_VALIDATED")
        self.assertFalse(summary["costs_empirically_validated"])
        self.assertFalse(summary["orders_enabled"])
        self.assertEqual(summary["groups"][0]["measured_fills"], 1)

    def test_crossed_quote_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-crossed"):
            self.telemetry.record_quote(
                "EQUITY", self.quote(bid=100.2, ask=100.1), "IEX"
            )

    def test_non_fill_trade_update_is_ignored(self):
        result = self.telemetry.record_fill_update({"event": "new", "order": {"id": "x"}})
        self.assertIsNone(result)
        self.assertEqual(self.telemetry.summary()["fill_events_total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
