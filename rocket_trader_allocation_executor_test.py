#!/usr/bin/env python3
"""Offline tests for the Paper allocation sleeve executor."""

import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import rocket_trader_allocation_executor as ex

NOW = datetime(2026, 12, 1, 15, 30, tzinfo=timezone.utc)
START = datetime(2026, 11, 26, tzinfo=timezone.utc)
SAFE = {"ALPACA_PAPER": "true", "ALPACA_LIVE_ENABLED": "false"}
W = {"DIA": 0.2, "EFA": 0.2, "IWM": 0.1, "QQQ": 0.1, "SPY": 0.2}  # 80% invested, 20% cash


def order(cid, sym, side, qty, px, status="filled"):
    return SimpleNamespace(client_order_id=cid, symbol=sym, side=side, filled_qty=str(qty),
                           filled_avg_price=str(px), status=status)


class FakeClient:
    def __init__(self, orders=(), positions=(), is_open=True):
        self.orders, self.positions, self.is_open = list(orders), list(positions), is_open
        self.submitted = []

    def get_orders(self, filter=None):
        return self.orders

    def get_all_positions(self):
        return self.positions

    def get_clock(self):
        return SimpleNamespace(is_open=self.is_open)

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return SimpleNamespace(id="x")


def run(client, mode="PAPER_EXECUTE", approval="user-approval-2026-11-26", strategy=ex.DEFAULT_STRATEGY,
        initial="54.00", weights=W):
    with patch.dict(os.environ, SAFE):
        return ex.run(client=client, weights_fn=lambda: {"target_weights": weights, "signal_session_utc": "x"},
                      fees_fn=lambda _s: Decimal("0"), mode=mode, approval_ref=approval, strategy=strategy,
                      initial_usd=Decimal(initial), sleeve_start=START, now=NOW)


class ExecutorTests(unittest.TestCase):
    def test_default_dry_run_plans_but_never_submits(self):
        c = FakeClient()
        r = run(c, mode="DRY_RUN")
        self.assertEqual(r["result"], "DRY_RUN")
        self.assertIn("MODE_NOT_PAPER_EXECUTE", r["execution_gate"]["blocked_by"])
        self.assertEqual(c.submitted, [])
        self.assertEqual(len(r["planned_orders"]), 5)
        total = sum(Decimal(o["notional_usd"]) for o in r["planned_orders"])
        self.assertLessEqual(total, Decimal("54.00"))
        self.assertAlmostEqual(float(total), 54 * 0.8, delta=0.05)

    def test_each_gate_blocks_submission(self):
        for kw in ({"approval": ""}, {"approval": "x"}, {"strategy": "sma210_trend_equal_weight"},
                   {"initial": "150"}, {"initial": "0"}):
            c = FakeClient()
            if kw.get("strategy") or kw.get("initial") == "0":
                with self.assertRaises(ex.AllocationExecutorError):
                    run(c, **kw)
            else:
                r = run(c, **kw)
                self.assertEqual(r["result"], "DRY_RUN")
            self.assertEqual(c.submitted, [])
        with patch.dict(os.environ, {"ALPACA_LIVE_ENABLED": "true"}):
            c = FakeClient()
            r = ex.run(client=c, weights_fn=lambda: {"target_weights": W}, fees_fn=lambda _s: Decimal(0),
                       mode="PAPER_EXECUTE", approval_ref="user-approval-1", strategy=ex.DEFAULT_STRATEGY,
                       initial_usd=Decimal("54"), sleeve_start=START, now=NOW)
            self.assertEqual(c.submitted, [])

    def test_market_closed_blocks(self):
        c = FakeClient(is_open=False)
        self.assertEqual(run(c)["result"], "BLOCKED_MARKET_CLOSED")
        self.assertEqual(c.submitted, [])

    def test_approved_paper_submits_notional_buys_with_idempotent_ids(self):
        c = FakeClient()
        r = run(c)
        self.assertEqual(r["result"], "SUBMITTED")
        self.assertEqual(len(c.submitted), 5)
        self.assertTrue(all(o.client_order_id.startswith("rt-alloc-20261201-") for o in c.submitted))
        self.assertTrue(all(o.notional is not None and o.qty is None for o in c.submitted))
        # Re-run the same day after those orders exist: nothing new is submitted.
        existing = [order(o.client_order_id, o.symbol, "buy", 0, 1, status="new") for o in c.submitted]
        c2 = FakeClient(orders=existing)
        self.assertEqual(run(c2)["result"], "BLOCKED_OPEN_SLEEVE_ORDERS")
        self.assertEqual(c2.submitted, [])

    def test_sleeve_state_ignores_foreign_orders_and_reconciles_cash(self):
        orders = [order("rt-alloc-20261201-SPY-buy", "SPY", "buy", "0.02", "600"),
                  order("smoke-btc", "SPY", "buy", "5", "600")]
        st = ex.sleeve_state(Decimal("54"), orders, Decimal("0.01"))
        self.assertEqual(st["qty"], {"SPY": Decimal("0.02")})
        self.assertEqual(st["cash_usd"], Decimal("54") - Decimal("12.00") - Decimal("0.01"))

    def test_trend_exit_sells_full_holding_first(self):
        orders = [order("rt-alloc-20261201-SPY-buy", "SPY", "buy", "0.02", "600")]
        pos = [SimpleNamespace(symbol="SPY", qty="0.02", current_price="610")]
        c = FakeClient(orders=orders, positions=pos)
        r = run(c, weights={"DIA": 0.5})  # SPY below trend -> target 0
        sells = [o for o in r["planned_orders"] if o["side"] == "sell"]
        self.assertEqual(sells[0]["symbol"], "SPY")
        self.assertEqual(Decimal(sells[0]["qty"]), Decimal("0.02"))
        self.assertEqual(c.submitted[0].side.value, "sell")

    def test_broker_below_sleeve_quantity_fails_closed(self):
        orders = [order("rt-alloc-20261201-SPY-buy", "SPY", "buy", "0.02", "600")]
        pos = [SimpleNamespace(symbol="SPY", qty="0.01", current_price="610")]
        with self.assertRaises(ex.AllocationExecutorError):
            run(FakeClient(orders=orders, positions=pos))
        with self.assertRaises(ex.AllocationExecutorError):
            run(FakeClient(orders=orders, positions=[]))

    def test_leverage_and_negative_weights_rejected(self):
        for w in ({"SPY": 0.7, "QQQ": 0.7}, {"SPY": -0.1}):
            with self.assertRaises(ex.AllocationExecutorError):
                ex.plan_rebalance(target_weights=w, sleeve_qty={}, prices={}, cash_usd=Decimal("54"), day_key="d")

    def test_orders_below_one_dollar_are_skipped(self):
        p = ex.plan_rebalance(target_weights={"SPY": 0.01}, sleeve_qty={}, prices={}, cash_usd=Decimal("54"), day_key="d")
        self.assertEqual(p["orders"], [])

    def test_public_summary_has_no_ids(self):
        s = ex.public_summary(run(FakeClient(), mode="DRY_RUN"))
        self.assertNotIn("client_order_id", str(s))


if __name__ == "__main__":
    unittest.main(verbosity=2)
