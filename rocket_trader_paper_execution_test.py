#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the durable Alpaca Paper execution adapter."""

import os
import tempfile
import unittest
from types import SimpleNamespace

from rocket_trader_core import ExecutionMode, ExecutionOrder, Side
from rocket_trader_paper_execution import AlpacaPaperExecutionAdapter, PaperExecutionError


class NotFound(Exception):
    status_code = 404


class FakeClient:
    def __init__(self):
        self.orders = {}
        self.submit_count = 0
        self.fail_after_accept = False

    def get_order_by_client_id(self, client_id):
        if client_id not in self.orders:
            raise NotFound()
        return self.orders[client_id]

    def submit_order(self, order_data):
        self.submit_count += 1
        order = SimpleNamespace(
            id=f"broker-{self.submit_count}",
            client_order_id=order_data.client_order_id,
            symbol=order_data.symbol,
            status="accepted",
            filled_qty="0",
            filled_avg_price=None,
        )
        self.orders[order_data.client_order_id] = order
        if self.fail_after_accept:
            raise TimeoutError("simulated timeout after broker accepted")
        return order

    def get_account(self):
        return SimpleNamespace(status="ACTIVE", currency="USD", trading_blocked=False)


class PaperExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "execution.sqlite3")
        self.client = FakeClient()
        self.adapter = AlpacaPaperExecutionAdapter(
            db_path=self.db, client=self.client
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def order(client_id="rt-test-order-001", mode=ExecutionMode.PAPER, side=Side.BUY):
        return ExecutionOrder(
            client_order_id=client_id,
            symbol="SPY",
            side=side,
            quantity=0.1,
            order_type="MARKET_BRACKET",
            entry_price=100.0,
            stop_price=98.0,
            take_profit_price=104.0,
            mode=mode,
        )

    def test_duplicate_submission_is_idempotent(self):
        first = self.adapter.submit(self.order())
        second = self.adapter.submit(self.order())
        self.assertFalse(first["duplicate_prevented"])
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)
        self.assertEqual(first["order_id"], second["order_id"])

    def test_timeout_after_acceptance_reconciles_without_resubmit(self):
        self.client.fail_after_accept = True
        result = self.adapter.submit(self.order())
        self.assertTrue(result["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)

    def test_timeout_without_broker_order_fails_closed(self):
        class RejectingClient(FakeClient):
            def submit_order(self, order_data):
                self.submit_count += 1
                raise TimeoutError("network timeout")

        client = RejectingClient()
        adapter = AlpacaPaperExecutionAdapter(db_path=self.db, client=client)
        with self.assertRaises(PaperExecutionError):
            adapter.submit(self.order())
        with self.assertRaises(PaperExecutionError):
            adapter.submit(self.order())
        self.assertEqual(client.submit_count, 1)

    def test_rejects_non_paper_and_sell_orders(self):
        with self.assertRaises(PaperExecutionError):
            self.adapter.submit(self.order(mode=ExecutionMode.LIVE))
        with self.assertRaises(PaperExecutionError):
            self.adapter.submit(self.order(side=Side.SELL))
        self.assertEqual(self.client.submit_count, 0)

    def test_rejects_reused_client_id_with_changed_payload(self):
        self.adapter.submit(self.order())
        changed = self.order()
        changed = ExecutionOrder(
            client_order_id=changed.client_order_id,
            symbol=changed.symbol,
            side=changed.side,
            quantity=0.2,
            order_type=changed.order_type,
            entry_price=changed.entry_price,
            stop_price=changed.stop_price,
            take_profit_price=changed.take_profit_price,
            mode=changed.mode,
        )
        with self.assertRaises(PaperExecutionError):
            self.adapter.submit(changed)
        self.assertEqual(self.client.submit_count, 1)

    def test_read_only_account_verification(self):
        self.assertEqual(self.adapter.verify_account()["mode"], "PAPER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
