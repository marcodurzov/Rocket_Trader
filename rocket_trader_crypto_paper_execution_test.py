#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the crypto Paper adapter; no broker orders are sent."""

import os
import tempfile
import unittest
from types import SimpleNamespace

from rocket_trader_core import ExecutionMode, Side
from rocket_trader_execution_event_ledger import ExecutionEventLedger
from rocket_trader_crypto_paper_execution import (
    AlpacaCryptoPaperExecutionAdapter,
    CryptoOrderIntent,
    CryptoPaperExecutionError,
)


class NotFound(Exception):
    status_code = 404


class FakeCryptoClient:
    def __init__(self):
        self.orders = {}
        self.positions = []
        self.submit_count = 0
        self.fail_after_accept = False
        self.cancel_count = 0

    def get_account(self):
        return SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="ACTIVE",
            trading_blocked=False, multiplier="1", shorting_enabled=False,
            cash="100000", non_marginable_buying_power="100000",
        )

    def get_account_configurations(self):
        return SimpleNamespace(
            max_margin_multiplier="1", no_shorting=True,
            max_options_trading_level=0,
        )

    def cancel_order_by_id(self, order_id):
        self.cancel_count += 1
        for order in self.orders.values():
            if order.id == order_id:
                order.status = "canceled"
                return order
        raise NotFound()

    def get_asset(self, symbol):
        return SimpleNamespace(symbol=symbol, asset_class="crypto", tradable=True)

    def get_all_positions(self):
        return self.positions

    def get_order_by_client_id(self, client_id):
        if client_id not in self.orders:
            raise NotFound()
        return self.orders[client_id]

    def submit_order(self, order_data):
        self.submit_count += 1
        order = SimpleNamespace(
            id=f"crypto-broker-{self.submit_count}",
            client_order_id=order_data.client_order_id,
            symbol=order_data.symbol,
            side=order_data.side,
            status="accepted",
            filled_qty="0.0001" if getattr(order_data, "notional", None) else str(order_data.qty),
            filled_avg_price="50000",
            notional=getattr(order_data, "notional", None),
        )
        self.orders[order_data.client_order_id] = order
        if self.fail_after_accept:
            raise TimeoutError("simulated timeout after broker acceptance")
        return order


class CryptoPaperExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "crypto-execution.sqlite3")
        self.client = FakeCryptoClient()
        self.adapter = AlpacaCryptoPaperExecutionAdapter(
            db_path=self.db, client=self.client
        )

    def tearDown(self):
        self.tmp.cleanup()

    def buy(self, client_id="crypto-buy-001", notional="10.00"):
        return CryptoOrderIntent(
            client_order_id=client_id, symbol="BTC/USD", side=Side.BUY,
            notional_usd=notional,
        )

    def test_market_ioc_buy_uses_usd_notional(self):
        result = self.adapter.submit(self.buy())
        self.assertTrue(result["accepted"])
        self.assertEqual(result["mode"], "PAPER")
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.client.submit_count, 1)

    def test_duplicate_buy_is_idempotent(self):
        first = self.adapter.submit(self.buy())
        second = self.adapter.submit(self.buy())
        self.assertFalse(first["duplicate_prevented"])
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)

    def test_timeout_after_acceptance_reconciles(self):
        self.client.fail_after_accept = True
        result = self.adapter.submit(self.buy())
        self.assertTrue(result["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)

    def test_timeout_without_broker_order_fails_closed(self):
        class TimeoutClient(FakeCryptoClient):
            def submit_order(self, order_data):
                self.submit_count += 1
                raise TimeoutError("simulated network timeout")
        client = TimeoutClient()
        adapter = AlpacaCryptoPaperExecutionAdapter(db_path=self.db, client=client)
        with self.assertRaises(CryptoPaperExecutionError):
            adapter.submit(self.buy())
        with self.assertRaises(CryptoPaperExecutionError):
            adapter.submit(self.buy())
        self.assertEqual(client.submit_count, 1)

    def test_buy_minimum_and_order_type_guards(self):
        with self.assertRaisesRegex(CryptoPaperExecutionError, "USD 1"):
            self.adapter.submit(self.buy(notional="0.50"))
        invalid = CryptoOrderIntent(
            client_order_id="crypto-limit-001", symbol="BTC/USD", side=Side.BUY,
            order_type="LIMIT", notional_usd="10",
        )
        with self.assertRaises(CryptoPaperExecutionError):
            self.adapter.submit(invalid)
        self.assertEqual(self.client.submit_count, 0)

    def test_sell_requires_existing_broker_position(self):
        with self.assertRaisesRegex(CryptoPaperExecutionError, "exceeds broker-held"):
            self.adapter.submit(
                CryptoOrderIntent(
                    client_order_id="crypto-sell-001", symbol="BTC/USD",
                    side=Side.SELL, quantity="0.001",
                )
            )
        self.assertEqual(self.client.submit_count, 0)

    def test_sell_cannot_exceed_owned_quantity(self):
        self.client.positions = [
            SimpleNamespace(symbol="BTC/USD", qty="0.001")
        ]
        with self.assertRaisesRegex(CryptoPaperExecutionError, "exceeds broker-held"):
            self.adapter.submit(
                CryptoOrderIntent(
                    client_order_id="crypto-sell-002", symbol="BTC/USD",
                    side=Side.SELL, quantity="0.002",
                )
            )
        self.assertEqual(self.client.submit_count, 0)

    def test_sell_within_owned_quantity(self):
        self.client.positions = [
            SimpleNamespace(symbol="BTC/USD", qty="0.001")
        ]
        result = self.adapter.submit(
            CryptoOrderIntent(
                client_order_id="crypto-sell-003", symbol="BTC/USD",
                side=Side.SELL, quantity="0.0005",
            )
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["side"], "sell")
        self.assertEqual(self.client.submit_count, 1)

    def test_duplicate_sell_reconciles_even_after_position_is_consumed(self):
        self.client.positions = [
            SimpleNamespace(symbol="BTC/USD", qty="0.001")
        ]
        intent = CryptoOrderIntent(
            client_order_id="crypto-sell-idempotent", symbol="BTC/USD",
            side=Side.SELL, quantity="0.0005",
        )
        first = self.adapter.submit(intent)
        self.client.positions = []
        second = self.adapter.submit(intent)
        self.assertFalse(first["duplicate_prevented"])
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)

    def test_rejects_inactive_crypto_account_and_untradable_asset(self):
        self.client.get_account = lambda: SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="INACTIVE",
            trading_blocked=False,
        )
        with self.assertRaises(CryptoPaperExecutionError):
            self.adapter.submit(self.buy())
        self.client.get_account = lambda: SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="ACTIVE",
            trading_blocked=False,
        )
        self.client.get_asset = lambda symbol: SimpleNamespace(
            symbol=symbol, asset_class="crypto", tradable=False,
        )
        with self.assertRaises(CryptoPaperExecutionError):
            self.adapter.submit(self.buy())
        self.assertEqual(self.client.submit_count, 0)

    def test_blocks_margin_enabled_account(self):
        self.client.get_account = lambda: SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="ACTIVE",
            trading_blocked=False, multiplier="2", shorting_enabled=False,
            cash="100000", non_marginable_buying_power="100000",
        )
        with self.assertRaisesRegex(CryptoPaperExecutionError, "multiplier 1"):
            self.adapter.submit(self.buy())
        self.assertEqual(self.client.submit_count, 0)

    def test_blocks_unsafe_account_configuration(self):
        self.client.get_account_configurations = lambda: SimpleNamespace(
            max_margin_multiplier="1", no_shorting=False,
            max_options_trading_level=1,
        )
        with self.assertRaisesRegex(CryptoPaperExecutionError, "must enforce"):
            self.adapter.submit(self.buy())
        self.assertEqual(self.client.submit_count, 0)

    def test_blocks_unset_options_level_without_leaking_type_error(self):
        self.client.get_account_configurations = lambda: SimpleNamespace(
            max_margin_multiplier="1", no_shorting=True,
            max_options_trading_level=None,
        )
        with self.assertRaisesRegex(CryptoPaperExecutionError, "must enforce"):
            self.adapter.submit(self.buy())
        self.assertEqual(self.client.submit_count, 0)

    def test_blocks_crypto_buy_above_cash_only_budget(self):
        self.client.get_account = lambda: SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="ACTIVE",
            trading_blocked=False, multiplier="1", shorting_enabled=False,
            cash="10", non_marginable_buying_power="10",
        )
        with self.assertRaisesRegex(CryptoPaperExecutionError, "exceeds available cash"):
            self.adapter.submit(self.buy(notional="10"))
        self.assertEqual(self.client.submit_count, 0)

    def test_cancel_is_idempotent_and_persists_terminal_state(self):
        self.adapter.submit(self.buy())
        first = self.adapter.cancel("crypto-buy-001")
        second = self.adapter.cancel("crypto-buy-001")
        self.assertEqual(first["status"], "canceled")
        self.assertTrue(first["cancel_requested"])
        self.assertFalse(second["cancel_requested"])
        self.assertEqual(self.client.cancel_count, 1)
        reconciled = self.adapter.reconcile("crypto-buy-001")
        self.assertEqual(reconciled["status"], "canceled")

    def test_cancel_unknown_client_order_id_does_not_call_broker(self):
        result = self.adapter.cancel("not-found")
        self.assertFalse(result["found"])
        self.assertEqual(self.client.cancel_count, 0)

    def test_rejects_non_paper_and_non_usd_pairs(self):
        live = CryptoOrderIntent(
            client_order_id="crypto-live-001", symbol="BTC/USD",
            side=Side.BUY, mode=ExecutionMode.LIVE, notional_usd="10",
        )
        with self.assertRaises(CryptoPaperExecutionError):
            self.adapter.submit(live)
        with self.assertRaises(CryptoPaperExecutionError):
            self.adapter.submit(
                CryptoOrderIntent(
                    client_order_id="crypto-eur-001", symbol="BTC/EUR",
                    side=Side.BUY, notional_usd="10",
                )
            )
        self.assertEqual(self.client.submit_count, 0)

    def test_sell_recognizes_compact_broker_crypto_symbol(self):
        self.client.positions = [SimpleNamespace(symbol="ETHUSD", qty="0.5")]
        result = self.adapter.submit(CryptoOrderIntent(
            client_order_id="crypto-sell-compact-001", symbol="ETH/USD",
            side=Side.SELL, quantity="0.5",
        ))
        self.assertTrue(result["accepted"])
        self.assertEqual(self.client.submit_count, 1)

    def test_reconcile_positions_normalizes_compact_broker_symbol(self):
        self.client.positions = [
            SimpleNamespace(
                symbol="ETHUSD", qty="0.5", avg_entry_price="2000",
                market_value="1100", unrealized_pl="100",
            )
        ]
        result = self.adapter.reconcile_positions()
        self.assertEqual(result["positions"][0]["symbol"], "ETH/USD")

    def test_reconcile_positions_is_read_only(self):
        self.client.positions = [
            SimpleNamespace(
                symbol="ETH/USD", qty="0.5", avg_entry_price="2000",
                market_value="1100", unrealized_pl="100",
            ),
            SimpleNamespace(symbol="SPY", qty="1"),
        ]
        result = self.adapter.reconcile_positions()
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["positions"][0]["symbol"], "ETH/USD")
        self.assertEqual(self.client.submit_count, 0)



    def test_restart_reconciles_existing_order_without_resubmitting(self):
        first = self.adapter.submit(self.buy())
        restarted = AlpacaCryptoPaperExecutionAdapter(
            db_path=self.db, client=self.client
        )
        second = restarted.submit(self.buy())
        self.assertTrue(first["accepted"])
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(second["order_id"], first["order_id"])
        self.assertEqual(self.client.submit_count, 1)

    def test_unknown_broker_status_is_preserved_not_assumed_terminal(self):
        self.adapter.submit(self.buy())
        order = self.client.orders["crypto-buy-001"]
        order.status = "suspended"
        order.filled_qty = "0.00004"
        order.filled_avg_price = "50000"
        result = self.adapter.reconcile("crypto-buy-001")
        self.assertEqual(result["status"], "suspended")
        self.assertEqual(result["filled_qty"], "0.00004")
        self.assertEqual(self.client.submit_count, 1)

    def test_partial_fill_is_preserved_when_remainder_is_canceled(self):
        self.adapter.submit(self.buy())
        order = self.client.orders["crypto-buy-001"]
        order.status = "partially_filled"
        order.filled_qty = "0.00004"
        order.filled_avg_price = "50000"
        result = self.adapter.cancel("crypto-buy-001")
        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["filled_qty"], "0.00004")
        self.assertEqual(self.client.cancel_count, 1)
        self.assertEqual(self.client.submit_count, 1)

    def test_fill_during_cancel_race_is_reconciled_as_filled(self):
        self.adapter.submit(self.buy())
        order = self.client.orders["crypto-buy-001"]
        order.status = "partially_filled"
        order.filled_qty = "0.00004"
        order.filled_avg_price = "50000"

        def fill_on_cancel(order_id):
            self.client.cancel_count += 1
            order.status = "filled"
            order.filled_qty = "0.0001"
            return order

        self.client.cancel_order_by_id = fill_on_cancel
        result = self.adapter.cancel("crypto-buy-001")
        self.assertEqual(result["status"], "filled")
        self.assertEqual(result["filled_qty"], "0.0001")
        self.assertEqual(self.client.submit_count, 1)

    def test_unknown_submission_result_blocks_retry_after_adapter_restart(self):
        class TimeoutClient(FakeCryptoClient):
            def submit_order(self, order_data):
                self.submit_count += 1
                raise TimeoutError("simulated network timeout without broker acceptance")

        client = TimeoutClient()
        first_adapter = AlpacaCryptoPaperExecutionAdapter(db_path=self.db, client=client)
        with self.assertRaises(CryptoPaperExecutionError):
            first_adapter.submit(self.buy("crypto-restart-unknown"))
        restarted = AlpacaCryptoPaperExecutionAdapter(db_path=self.db, client=client)
        with self.assertRaisesRegex(CryptoPaperExecutionError, "absent at broker"):
            restarted.submit(self.buy("crypto-restart-unknown"))
        self.assertEqual(client.submit_count, 1)


    def test_adapter_writes_prepared_and_broker_state_events(self):
        result = self.adapter.submit(self.buy())
        self.assertTrue(result["accepted"])
        events = self.adapter.order_events("crypto-buy-001")
        self.assertEqual(
            [event["event_type"] for event in events],
            ["ORDER_PREPARED", "ORDER_STATE_OBSERVED"],
        )
        self.assertTrue(self.adapter.event_ledger.verify_chain()["valid"])

    def test_event_ledger_failure_before_submit_fails_closed(self):
        class BrokenLedger:
            def append_event(self, **kwargs):
                raise RuntimeError("simulated durable ledger write failure")

        adapter = AlpacaCryptoPaperExecutionAdapter(
            db_path=self.db, client=self.client, event_ledger=BrokenLedger()
        )
        with self.assertRaisesRegex(RuntimeError, "ledger write failure"):
            adapter.submit(self.buy("crypto-ledger-fail-closed"))
        self.assertEqual(self.client.submit_count, 0)
        with sqlite3.connect(self.db) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM crypto_paper_order_journal"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_event_write_failure_after_broker_acceptance_reconciles_without_resubmit(self):
        real_ledger = ExecutionEventLedger(self.db + ".events.sqlite3")

        class FailOnceLedger:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.calls = 0

            def append_event(self, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("simulated event write failure after broker acceptance")
                return self.wrapped.append_event(**kwargs)

            def list_events(self, **kwargs):
                return self.wrapped.list_events(**kwargs)

            def verify_chain(self):
                return self.wrapped.verify_chain()

        flaky_ledger = FailOnceLedger(real_ledger)
        adapter = AlpacaCryptoPaperExecutionAdapter(
            db_path=self.db, client=self.client, event_ledger=flaky_ledger
        )
        result = adapter.submit(self.buy("crypto-ledger-after-accept"))
        self.assertTrue(result["accepted"])
        self.assertTrue(result["duplicate_prevented"])
        self.assertEqual(self.client.submit_count, 1)
        events = adapter.order_events("crypto-ledger-after-accept")
        self.assertEqual(
            [event["event_type"] for event in events],
            ["ORDER_PREPARED", "ORDER_STATE_OBSERVED"],
        )
        self.assertTrue(flaky_ledger.verify_chain()["valid"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
