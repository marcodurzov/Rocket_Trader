#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Rocket Trader's append-only execution evidence ledger."""

import os
import sqlite3
import tempfile
import unittest

from rocket_trader_execution_event_ledger import (
    ExecutionEventLedger,
    ExecutionLedgerError,
)


class ExecutionEventLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "execution-events.sqlite3")
        self.ledger = ExecutionEventLedger(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def append(self, event_id, event_type="ORDER_SUBMITTED", payload=None, **kwargs):
        return self.ledger.append_event(
            event_id=event_id,
            aggregate_id="paper-run-001",
            event_type=event_type,
            payload=payload or {"symbol": "BTC/USD", "side": "buy"},
            occurred_at="2026-11-11T12:00:00Z",
            **kwargs,
        )

    def test_append_and_verify_hash_chain(self):
        first = self.append("evt-1")
        second = self.append("evt-2", "ORDER_FILLED", {"filled_qty": "0.001"})
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["previous_hash"], first["event_hash"])
        self.assertTrue(self.ledger.verify_chain()["valid"])

    def test_duplicate_event_is_idempotent(self):
        first = self.append("evt-duplicate")
        second = self.append("evt-duplicate")
        self.assertFalse(first["duplicate_prevented"])
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(first["event_hash"], second["event_hash"])
        self.assertEqual(self.ledger.verify_chain()["event_count"], 1)


    def test_default_timestamp_retry_remains_idempotent(self):
        first = self.ledger.append_event(
            event_id="evt-default-time", aggregate_id="run", event_type="STARTED",
            payload={"source": "test"},
        )
        second = self.ledger.append_event(
            event_id="evt-default-time", aggregate_id="run", event_type="STARTED",
            payload={"source": "test"},
        )
        self.assertTrue(second["duplicate_prevented"])
        self.assertEqual(first["occurred_at"], second["occurred_at"])
        self.assertEqual(self.ledger.verify_chain()["event_count"], 1)

    def test_concurrent_duplicate_appends_create_one_event(self):
        from concurrent.futures import ThreadPoolExecutor

        def write_event(_):
            return self.ledger.append_event(
                event_id="evt-concurrent", aggregate_id="run", event_type="STARTED",
                payload={"source": "parallel"},
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write_event, range(8)))
        self.assertEqual(sum(not item["duplicate_prevented"] for item in results), 1)
        self.assertEqual(self.ledger.verify_chain()["event_count"], 1)

    def test_same_event_id_with_different_payload_is_rejected(self):
        self.append("evt-conflict")
        with self.assertRaisesRegex(ExecutionLedgerError, "different immutable"):
            self.append("evt-conflict", payload={"filled_qty": "9"})
        self.assertEqual(self.ledger.verify_chain()["event_count"], 1)

    def test_reopen_preserves_events_and_chain(self):
        self.append("evt-persist")
        reopened = ExecutionEventLedger(self.db_path)
        events = reopened.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], "evt-persist")
        self.assertTrue(reopened.verify_chain()["valid"])

    def test_update_and_delete_are_blocked(self):
        self.append("evt-immutable")
        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE execution_events SET event_type='ALTERED' WHERE event_id='evt-immutable'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM execution_events WHERE event_id='evt-immutable'")

    def test_hash_chain_detects_tampering_if_trigger_is_bypassed(self):
        self.append("evt-tamper")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DROP TRIGGER execution_events_no_update")
            connection.execute(
                "UPDATE execution_events SET payload_json='{\"tampered\":true}' "
                "WHERE event_id='evt-tamper'"
            )
        result = self.ledger.verify_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "event_hash_mismatch")

    def test_rejects_credential_like_payload_fields(self):
        with self.assertRaisesRegex(ExecutionLedgerError, "Credential-like"):
            self.append("evt-secret", payload={"broker": {"api_secret": "do-not-store"}})

    def test_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(ExecutionLedgerError, "timezone"):
            self.ledger.append_event(
                event_id="evt-naive", aggregate_id="run", event_type="STARTED",
                payload={}, occurred_at="2026-11-11T12:00:00",
            )

    def test_normalizes_timestamps_to_utc(self):
        result = self.ledger.append_event(
            event_id="evt-offset", aggregate_id="run", event_type="STARTED",
            payload={}, occurred_at="2026-11-11T13:00:00+01:00",
        )
        self.assertEqual(result["occurred_at"], "2026-11-11T12:00:00.000000Z")

    def test_filters_by_aggregate_without_losing_global_sequence(self):
        self.ledger.append_event(
            event_id="evt-a", aggregate_id="run-a", event_type="STARTED", payload={}
        )
        self.ledger.append_event(
            event_id="evt-b", aggregate_id="run-b", event_type="STARTED", payload={}
        )
        events = self.ledger.list_events(aggregate_id="run-b")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["sequence"], 2)

    def test_rejects_invalid_payload_and_limits(self):
        with self.assertRaises(ExecutionLedgerError):
            self.ledger.append_event(
                event_id="evt-list", aggregate_id="run", event_type="STARTED", payload=[]
            )
        with self.assertRaises(ExecutionLedgerError):
            self.ledger.list_events(limit=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
