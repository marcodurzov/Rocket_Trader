#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for durable Paper Activity SSE staging and cursor recovery."""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from rocket_trader_alpaca_activity_sse_consumer import (
    ACTIVITY_SSE_ENDPOINT,
    ActivitySSEConsumerError,
    AlpacaPaperActivitySSEConsumer,
    DurableActivitySSEInbox,
    parse_sse,
)


def ulid(n):
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = n
    chars = []
    for _ in range(26):
        chars.append(alphabet[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def activity(n, ref=None, activity_type="TRD", previous_id=None, execution_type="fill"):
    return {
        "account_id": "00000000-0000-0000-0000-000000000001",
        "activity_type": activity_type,
        "activity_subtype": None,
        "at": "2026-11-11T04:57:48.037818Z",
        "currency": "USD",
        "event_id": ulid(n),
        "executed_at": "2026-11-11T04:57:47.996523Z",
        "net_amount": "-9.81",
        "previous_id": previous_id,
        "price": "73621.74",
        "qty": "0.000133206",
        "ref_id": ref or f"ref-{n}",
        "settle_date": "2026-11-11",
        "status": "executed",
        "details": {
            "execution_type": execution_type,
            "symbol": "BTC/USD",
            "side": "buy",
            "order_id": "broker-order-id",
            "client_order_id": "paper-client-id",
        },
    }


class Response:
    def __init__(self, status=200, lines=()):
        self.status_code = status
        self.lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)

    def close(self):
        self.closed = True


class DurableActivitySSEInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.temp.name, "activity.sqlite3")
        self.inbox = DurableActivitySSEInbox(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_sse_multiline_data_and_comments(self):
        frames = list(parse_sse([
            ":heartbeat", "",
            'data: {"event_id":', 'data: "x"}', "",
        ]))
        self.assertEqual(frames, [("comment", "heartbeat"), ("data", '{"event_id":\n"x"}')])

    def test_stage_is_atomic_and_persists_cursor(self):
        result = self.inbox.stage(activity(1))
        self.assertEqual(result["status"], "STAGED")
        self.assertEqual(self.inbox.cursor, ulid(1))
        self.assertTrue(self.inbox.verify()["valid"])
        self.assertTrue(self.inbox.verify()["cursor_has_delivery"])

    def test_replay_same_event_is_idempotent(self):
        event = activity(1)
        self.inbox.stage(event)
        result = self.inbox.stage(event)
        self.assertEqual(result["status"], "DUPLICATE_EVENT")
        self.assertEqual(self.inbox.verify()["activity_count"], 1)
        self.assertEqual(self.inbox.verify()["delivery_count"], 1)

    def test_same_ref_same_payload_new_event_id_advances_cursor_without_duplicate_activity(self):
        self.inbox.stage(activity(1, ref="stable-ref"))
        second = activity(2, ref="stable-ref")
        result = self.inbox.stage(second)
        self.assertEqual(result["status"], "DUPLICATE_REF")
        self.assertEqual(self.inbox.cursor, ulid(2))
        self.assertEqual(self.inbox.verify()["activity_count"], 1)
        self.assertEqual(self.inbox.verify()["delivery_count"], 2)

    def test_same_ref_changed_payload_fails_closed_and_does_not_advance_cursor(self):
        self.inbox.stage(activity(1, ref="stable-ref"))
        changed = activity(2, ref="stable-ref")
        changed["net_amount"] = "-9.80"
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.stage(changed)
        self.assertEqual(self.inbox.cursor, ulid(1))
        self.assertEqual(self.inbox.verify()["delivery_count"], 1)

    def test_event_id_reused_with_changed_payload_fails_closed(self):
        self.inbox.stage(activity(1))
        changed = activity(1)
        changed["net_amount"] = "-9.80"
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.stage(changed)
        self.assertEqual(self.inbox.cursor, ulid(1))

    def test_unseen_event_older_than_cursor_fails_closed(self):
        self.inbox.stage(activity(2))
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.stage(activity(1))
        self.assertEqual(self.inbox.cursor, ulid(2))

    def test_trade_correction_is_staged_as_evidence_without_reversal(self):
        self.inbox.stage(activity(1, ref="original-ref"))
        correction = activity(2, ref="correction-ref", previous_id="original-ref",
                              execution_type="trade_correct")
        result = self.inbox.stage(correction)
        self.assertEqual(result["status"], "STAGED")
        rows = self.inbox.list_events()
        self.assertEqual(rows[1]["previous_id"], "original-ref")
        self.assertEqual(rows[1]["payload"]["details"]["execution_type"], "trade_correct")
        self.assertEqual(len(rows), 2)

    def test_orphan_correction_reference_is_preserved_and_reported(self):
        self.inbox.stage(activity(2, ref="correction-ref", previous_id="not-in-window",
                                  execution_type="trade_bust"))
        report = self.inbox.verify()
        self.assertTrue(report["valid"])
        self.assertEqual(report["orphan_previous_id_count"], 1)

    def test_drop_comment_requests_reconnect_after_committed_events(self):
        lines = [
            "data: " + json.dumps(activity(1)), "",
            ": you are reading too slowly, dropped 5 messages", "",
            "data: " + json.dumps(activity(2)), "",
        ]
        report = self.inbox.process_lines(lines)
        self.assertEqual(report["staged_count"], 1)
        self.assertTrue(report["reconnect_required"])
        self.assertEqual(self.inbox.cursor, ulid(1))
        self.assertEqual(self.inbox.verify()["activity_count"], 1)

    def test_internal_server_error_comment_requests_reconnect(self):
        report = self.inbox.process_lines([": internal server error", ""])
        self.assertTrue(report["reconnect_required"])

    def test_malformed_frame_does_not_advance_cursor(self):
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.process_lines(["data: {bad-json}", ""])
        self.assertIsNone(self.inbox.cursor)

    def test_missing_required_fields_do_not_advance_cursor(self):
        event = activity(1)
        del event["ref_id"]
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.stage(event)
        self.assertIsNone(self.inbox.cursor)

    def test_credential_like_payload_is_rejected(self):
        event = activity(1)
        event["details"]["api_secret"] = "must-not-persist"
        with self.assertRaises(ActivitySSEConsumerError):
            self.inbox.stage(event)
        self.assertIsNone(self.inbox.cursor)

    def test_ledger_tables_reject_update_and_delete(self):
        self.inbox.stage(activity(1))
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE activity_sse_events SET activity_type='HACK'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM activity_sse_deliveries")

    def test_chain_and_payload_hash_tampering_is_detected(self):
        self.inbox.stage(activity(1))
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TRIGGER activity_sse_events_no_update")
            conn.execute("UPDATE activity_sse_events SET payload_json='{}'")
        self.assertEqual(self.inbox.verify()["reason"], "payload_hash_mismatch")

    def test_reopen_recovers_cursor_and_events(self):
        self.inbox.stage(activity(1))
        reopened = DurableActivitySSEInbox(self.db)
        self.assertEqual(reopened.cursor, ulid(1))
        self.assertEqual(reopened.verify()["activity_count"], 1)


class AlpacaPaperActivitySSEConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.inbox = DurableActivitySSEInbox(os.path.join(self.temp.name, "activity.sqlite3"))
        self.env = patch.dict(os.environ, {
            "ALPACA_PAPER": "true",
            "ALPACA_LIVE_ENABLED": "false",
            "ROCKET_TRADER_EXECUTION_MODE": "PAPER",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_initial_connection_uses_bounded_bootstrap_since(self):
        response = Response(lines=["data: " + json.dumps(activity(1)), ""])
        captured = {}
        def get(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return response
        consumer = AlpacaPaperActivitySSEConsumer(
            inbox=self.inbox, bootstrap_since="2026-11-11T04:55:00Z",
            api_key="fake-key", api_secret="fake-secret", request_get=get,
        )
        report = consumer.connect_once()
        self.assertEqual(captured["url"], ACTIVITY_SSE_ENDPOINT)
        self.assertEqual(captured["params"], {"since": "2026-11-11T04:55:00Z"})
        self.assertEqual(report["staged_count"], 1)
        self.assertTrue(response.closed)

    def test_reconnect_uses_durable_since_id_not_original_timestamp(self):
        self.inbox.stage(activity(1))
        response = Response(lines=["data: " + json.dumps(activity(2)), ""])
        captured = {}
        def get(url, **kwargs):
            captured.update(kwargs)
            return response
        consumer = AlpacaPaperActivitySSEConsumer(
            inbox=self.inbox, bootstrap_since="2026-11-01T00:00:00Z",
            api_key="fake-key", api_secret="fake-secret", request_get=get,
        )
        report = consumer.connect_once()
        self.assertEqual(captured["params"], {"since_id": ulid(1)})
        self.assertEqual(report["staged_count"], 1)

    def test_http_error_never_advances_cursor(self):
        consumer = AlpacaPaperActivitySSEConsumer(
            inbox=self.inbox, bootstrap_since="2026-11-11T04:55:00Z",
            api_key="fake-key", api_secret="fake-secret",
            request_get=lambda *a, **k: Response(status=403),
        )
        with self.assertRaises(ActivitySSEConsumerError):
            consumer.connect_once()
        self.assertIsNone(self.inbox.cursor)

    def test_paper_mode_is_mandatory_and_live_is_rejected(self):
        with patch.dict(os.environ, {"ALPACA_PAPER": "false"}):
            with self.assertRaises(ActivitySSEConsumerError):
                AlpacaPaperActivitySSEConsumer(
                    inbox=self.inbox, bootstrap_since="2026-11-11T04:55:00Z",
                    api_key="fake", api_secret="fake", request_get=lambda *a, **k: None,
                )
        with patch.dict(os.environ, {"ALPACA_PAPER": "true", "ALPACA_LIVE_ENABLED": "true"}):
            with self.assertRaises(ActivitySSEConsumerError):
                AlpacaPaperActivitySSEConsumer(
                    inbox=self.inbox, bootstrap_since="2026-11-11T04:55:00Z",
                    api_key="fake", api_secret="fake", request_get=lambda *a, **k: None,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
