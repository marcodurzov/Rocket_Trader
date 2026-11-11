#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Alpaca account activity and crypto fee reconciliation."""

import os
import sqlite3
import tempfile
import unittest

from rocket_trader_execution_event_ledger import ExecutionEventLedger
from rocket_trader_alpaca_activity_reconciliation import (
    AlpacaAccountActivityReader,
    AlpacaActivityReconciliationError,
)


class FakeActivityClient:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if path != "/account/activities":
            raise AssertionError("unexpected endpoint")
        token = params.get("page_token")
        return self.pages.get(token, [])


class AlpacaActivityReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ExecutionEventLedger(os.path.join(self.tmp.name, "events.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def reader(self, pages):
        return AlpacaAccountActivityReader(FakeActivityClient(pages), self.ledger)

    def fill(self, activity_id, qty, price, cum_qty, *, symbol="BTC/USD", side="buy", order_id="broker-order-1"):
        return {
            "id": activity_id,
            "activity_type": "FILL",
            "order_id": order_id,
            "order_status": "filled",
            "type": "fill",
            "symbol": symbol,
            "side": side,
            "qty": str(qty),
            "price": str(price),
            "cum_qty": str(cum_qty),
            "leaves_qty": "0",
            "transaction_time": "2026-11-11T12:00:00Z",
        }

    def test_reconciles_individual_fills_and_persists_immutable_events(self):
        activities = [
            self.fill("fill-1", "0.00004", "50000", "0.00004"),
            self.fill("fill-2", "0.00006", "50100", "0.00010"),
        ]
        result = self.reader({None: activities}).reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
        )
        self.assertEqual(result["reconciliation_status"], "MATCHED")
        self.assertEqual(result["activity_filled_qty"], "0.00010")
        self.assertEqual(result["fill_count"], 2)
        events = self.ledger.list_events(aggregate_id="rt-order-1")
        self.assertEqual(len(events), 2)
        self.assertTrue(self.ledger.verify_chain()["valid"])

    def test_duplicate_fill_ingestion_is_idempotent(self):
        reader = self.reader({None: [self.fill("fill-duplicate", "0.00010", "50000", "0.00010")]})
        for _ in range(2):
            result = reader.reconcile_order_fills(
                client_order_id="rt-order-1", broker_order_id="broker-order-1",
                expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
            )
            self.assertEqual(result["reconciliation_status"], "MATCHED")
        self.assertEqual(len(self.ledger.list_events(aggregate_id="rt-order-1")), 1)

    def test_incomplete_activity_history_is_not_reported_as_full_match(self):
        reader = self.reader({None: [self.fill("fill-part", "0.00004", "50000", "0.00004")]})
        result = reader.reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
        )
        self.assertEqual(result["reconciliation_status"], "INCOMPLETE_ACTIVITY_HISTORY")
        self.assertFalse(result["quantity_match"])

    def test_overstated_fill_activities_are_flagged(self):
        reader = self.reader({None: [self.fill("fill-over", "0.00020", "50000", "0.00020")]})
        result = reader.reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
        )
        self.assertEqual(result["reconciliation_status"], "ACTIVITY_OVERSTATES_ORDER_SNAPSHOT")

    def test_cumulative_fill_sequence_mismatch_is_flagged(self):
        activities = [
            self.fill("fill-a", "0.00004", "50000", "0.00004"),
            self.fill("fill-b", "0.00006", "50100", "0.00009"),
        ]
        result = self.reader({None: activities}).reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
        )
        self.assertEqual(result["reconciliation_status"], "CUMULATIVE_FILL_SEQUENCE_MISMATCH")
        self.assertTrue(result["quantity_match"])
        self.assertFalse(result["cumulative_consistent"])

    def test_rejects_fill_for_wrong_order_symbol_or_side(self):
        wrong_order = self.fill("wrong-order", "0.0001", "50000", "0.0001", order_id="other-order")
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "order_id"):
            self.reader({None: [wrong_order]}).reconcile_order_fills(
                client_order_id="rt-order-1", broker_order_id="broker-order-1",
                expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.0001",
            )
        wrong_symbol = self.fill("wrong-symbol", "0.0001", "50000", "0.0001", symbol="ETH/USD")
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "symbol or side"):
            self.reader({None: [wrong_symbol]}).reconcile_order_fills(
                client_order_id="rt-order-1", broker_order_id="broker-order-1",
                expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.0001",
            )

    def test_crypto_fee_records_are_kept_unallocated_with_original_currency(self):
        fee = {
            "id": "fee-1", "activity_type": "CFEE", "symbol": "BTC/USD",
            "net_amount": "-0.000000334", "currency": "BTC", "qty": "0.0001",
            "group_id": None, "created_at": "2026-11-12T00:00:00Z",
            "date": "2026-11-11T00:00:00Z",
        }
        result = self.reader({None: [fee]}).collect_crypto_fee_candidates(
            symbol="BTC/USD", after="2026-11-11T00:00:00Z", until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 1)
        self.assertEqual(result["fee_activities"][0]["currency"], "BTC")
        self.assertEqual(result["fee_activities"][0]["allocation_status"], "UNALLOCATED")
        events = self.ledger.list_events(aggregate_id="account-crypto-fees")
        self.assertEqual(events[0]["event_type"], "CRYPTO_FEE_ACTIVITY_UNALLOCATED")

    def test_fee_activity_without_amount_is_preserved_as_incomplete_not_zero(self):
        fee = {
            "id": "fee-incomplete", "activity_type": "CFEE", "symbol": "BTC/USD",
            "net_amount": None, "currency": "BTC", "created_at": "2026-11-12T00:00:00Z",
        }
        result = self.reader({None: [fee]}).collect_crypto_fee_candidates(
            symbol="BTC/USD", after="2026-11-11T00:00:00Z", until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 1)
        self.assertEqual(result["incomplete_activity_count"], 1)
        self.assertEqual(result["fee_activities"][0]["net_amount"], None)
        self.assertEqual(result["fee_activities"][0]["record_status"], "INCOMPLETE_FIELDS")

    def test_pagination_uses_activity_id_cursor_and_preserves_all_fills(self):
        page_one = [self.fill("page-1", "0.00004", "50000", "0.00004")]
        page_two = [self.fill("page-2", "0.00006", "50100", "0.00010")]
        client = FakeActivityClient({None: page_one, "page-1": page_two})
        reader = AlpacaAccountActivityReader(client, self.ledger)
        result = reader.reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
            page_size=1,
        )
        self.assertEqual(result["fill_count"], 2)
        self.assertEqual(client.calls[1][1]["page_token"], "page-1")

    def test_repeated_pagination_cursor_fails_closed(self):
        first = self.fill("same-cursor", "0.00004", "50000", "0.00004")
        second = self.fill("same-cursor", "0.00006", "50100", "0.00010")
        client = FakeActivityClient({None: [first], "same-cursor": [second]})
        reader = AlpacaAccountActivityReader(client, self.ledger, max_pages=3)
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "cursor repeated"):
            reader.reconcile_order_fills(
                client_order_id="rt-order-1", broker_order_id="broker-order-1",
                expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
                page_size=1,
            )

    def test_max_page_limit_does_not_return_a_silent_partial_result(self):
        pages = {
            None: [self.fill("max-1", "0.00004", "50000", "0.00004")],
            "max-1": [self.fill("max-2", "0.00006", "50100", "0.00010")],
        }
        reader = self.reader(pages)
        reader.max_pages = 1
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "page limit reached"):
            reader.reconcile_order_fills(
                client_order_id="rt-order-1", broker_order_id="broker-order-1",
                expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.00010",
                page_size=1,
            )

    def test_cfee_results_are_locally_filtered_by_created_at_window(self):
        fees = [
            {
                "id": "fee-old-btc", "activity_type": "CFEE", "symbol": "BTC/USD",
                "net_amount": "0", "currency": "USD", "qty": "-0.0000001",
                "created_at": "2026-11-10T19:43:25.429073Z",
            },
            {
                "id": "fee-current-btc", "activity_type": "CFEE", "symbol": "BTC/USD",
                "net_amount": "0", "currency": "USD", "qty": "-0.0000002",
                "created_at": "2026-11-11T04:57:49.080580Z",
            },
            {
                "id": "fee-old-unclassified", "activity_type": "CFEE", "symbol": None,
                "net_amount": "-0.03", "currency": "USD",
                "created_at": "2026-11-10T19:40:51.934749Z",
            },
            {
                "id": "fee-no-created-at", "activity_type": "CFEE", "symbol": "BTC/USD",
                "net_amount": "0", "currency": "USD",
                "date": "2026-11-11T04:57:49Z",
            },
        ]
        result = self.reader({None: fees}).collect_crypto_fee_candidates(
            symbol="BTC/USD",
            after="2026-11-11T04:55:00Z",
            until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 1)
        self.assertEqual(result["unclassified_activity_count"], 0)
        self.assertEqual(result["out_of_window_activity_count"], 2)
        self.assertEqual(result["window_unverified_activity_count"], 1)
        self.assertEqual(
            result["fee_activities"][0]["activity_id"], "fee-current-btc"
        )
        events = self.ledger.list_events(aggregate_id="account-crypto-fees")
        event_types = {event["event_type"] for event in events}
        self.assertIn("CRYPTO_FEE_ACTIVITY_OUT_OF_WINDOW", event_types)
        self.assertIn("CRYPTO_FEE_ACTIVITY_WINDOW_UNVERIFIED", event_types)
        self.assertTrue(self.ledger.verify_chain()["valid"])

    def test_fee_time_window_is_mandatory_and_timezone_aware(self):
        reader = self.reader({None: []})
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "timezone"):
            reader.collect_crypto_fee_candidates(
                symbol="BTC/USD", after="2026-11-11T00:00:00",
                until="2026-11-12T00:00:00Z",
            )
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "earlier"):
            reader.collect_crypto_fee_candidates(
                symbol="BTC/USD", after="2026-11-12T00:00:00Z",
                until="2026-11-11T00:00:00Z",
            )



    def test_reader_requests_paper_activity_endpoint_with_exact_fill_filter(self):
        activity = self.fill("fill-request", "0.0001", "50000", "0.0001")
        client = FakeActivityClient({None: [activity]})
        reader = AlpacaAccountActivityReader(client, self.ledger)
        reader.reconcile_order_fills(
            client_order_id="rt-order-1", broker_order_id="broker-order-1",
            expected_symbol="BTC/USD", expected_side="buy", expected_filled_qty="0.0001",
        )
        path, params = client.calls[0]
        self.assertEqual(path, "/account/activities")
        self.assertEqual(params["activity_types"], "FILL")
        self.assertEqual(params["order_id"], "broker-order-1")
        self.assertEqual(params["direction"], "asc")

    def test_reader_refuses_corrupted_event_ledger(self):
        self.ledger.append_event(
            event_id="tamper-seed", aggregate_id="seed", event_type="SEED", payload={}
        )
        with sqlite3.connect(self.ledger.db_path) as connection:
            connection.execute("DROP TRIGGER execution_events_no_update")
            connection.execute(
                "UPDATE execution_events SET payload_json='{\"tampered\":true}' "
                "WHERE event_id='tamper-seed'"
            )
        with self.assertRaisesRegex(AlpacaActivityReconciliationError, "integrity check failed"):
            AlpacaAccountActivityReader(FakeActivityClient({None: []}), self.ledger)


    def test_unclassifiable_account_wide_cfee_does_not_abort_fill_evidence(self):
        fee = {
            "id": "fee-unclassified", "activity_type": "CFEE", "symbol": "USD",
            "net_amount": "-0.25", "currency": "USD",
            "created_at": "2026-11-12T00:00:00Z",
        }
        result = self.reader({None: [fee]}).collect_crypto_fee_candidates(
            symbol="BTC/USD", after="2026-11-11T00:00:00Z", until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 0)
        self.assertEqual(result["unclassified_activity_count"], 1)
        self.assertEqual(
            result["unclassified_fee_activities"][0]["symbol_classification"],
            "UNCLASSIFIED_SYMBOL",
        )
        events = self.ledger.list_events(aggregate_id="account-crypto-fees")
        self.assertEqual(events[0]["event_type"], "CRYPTO_FEE_ACTIVITY_UNCLASSIFIED")
        self.assertTrue(self.ledger.verify_chain()["valid"])

    def test_other_crypto_pair_fee_is_preserved_but_not_misattributed(self):
        fee = {
            "id": "fee-eth", "activity_type": "CFEE", "symbol": "ETH/USD",
            "net_amount": "-0.0001", "currency": "ETH",
            "created_at": "2026-11-12T00:00:00Z",
        }
        result = self.reader({None: [fee]}).collect_crypto_fee_candidates(
            symbol="BTC/USD", after="2026-11-11T00:00:00Z", until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 0)
        self.assertEqual(result["other_symbol_activity_count"], 1)
        self.assertEqual(
            self.ledger.list_events(aggregate_id="account-crypto-fees")[0]["payload"]["symbol"],
            "ETH/USD",
        )

    def test_incomplete_cfee_is_preserved_and_explicitly_flagged(self):
        fee = {
            "id": "fee-incomplete-fields", "activity_type": "CFEE", "symbol": "BTC/USD",
            "net_amount": None, "currency": None,
        }
        result = self.reader({None: [fee]}).collect_crypto_fee_candidates(
            symbol="BTC/USD", after="2026-11-11T00:00:00Z", until="2026-11-13T00:00:00Z",
        )
        self.assertEqual(result["fee_activity_count"], 1)
        self.assertEqual(result["incomplete_activity_count"], 1)
        self.assertEqual(result["fee_activities"][0]["record_status"], "INCOMPLETE_FIELDS")

if __name__ == "__main__":
    unittest.main(verbosity=2)
