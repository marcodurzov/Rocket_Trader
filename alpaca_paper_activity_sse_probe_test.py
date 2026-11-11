#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the bounded Alpaca Paper Activity SSE probe."""

import json
import unittest
from unittest.mock import Mock

from alpaca_paper_activity_sse_probe import (
    ENDPOINT,
    parse_sse_lines,
    run_probe,
    summarize_events,
)


def event(event_id, ref_id, execution_type="fill", symbol="BTC/USD", previous_id=None):
    return {
        "event_id": event_id,
        "ref_id": ref_id,
        "activity_type": "TRD",
        "previous_id": previous_id,
        "qty": "0.01",
        "price": "50000",
        "net_amount": "-500",
        "currency": "USD",
        "at": "2026-11-11T05:00:00Z",
        "executed_at": "2026-11-11T05:00:00Z",
        "settle_date": "2026-11-11",
        "status": "executed",
        "details": {
            "execution_type": execution_type,
            "symbol": symbol,
            "side": "buy",
            "order_id": "broker-order-id",
            "client_order_id": "paper-client-id",
        },
    }


class Response:
    def __init__(self, status_code=200, lines=()):
        self.status_code = status_code
        self.lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)

    def close(self):
        self.closed = True


class PaperActivitySSEProbeTests(unittest.TestCase):
    def test_parser_reads_events_and_comments_and_flags_invalid_json(self):
        lines = [
            ": heartbeat",
            'data: {"event_id":"01ABC","ref_id":"ref-1","activity_type":"TRD","details":{}}',
            "",
            "data: not-json",
            "",
        ]
        events, comments, invalid = parse_sse_lines(lines)
        self.assertEqual(len(events), 1)
        self.assertEqual(comments, ["heartbeat"])
        self.assertEqual(invalid, 1)

    def test_summary_detects_crypto_corrections_busts_fees_and_previous_ids(self):
        events = [
            event("01A", "ref-1", "fill"),
            event("01B", "ref-2", "trade_correct", previous_id="ref-1"),
            event("01C", "ref-3", "trade_bust", previous_id="ref-2"),
            {
                "event_id": "01D", "ref_id": "fee-1", "activity_type": "CFEE",
                "details": {}, "currency": "USD",
            },
        ]
        report = summarize_events(
            events, [], 0, since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
        )
        self.assertEqual(report["status"], "CRYPTO_EVENTS_FOUND")
        self.assertEqual(report["crypto_trade_event_count"], 3)
        self.assertEqual(report["trade_correction_event_count"], 1)
        self.assertEqual(report["trade_bust_event_count"], 1)
        self.assertEqual(report["previous_id_event_count"], 2)
        self.assertEqual(report["fee_activity_counts"], {"CFEE": 1})

    def test_stock_only_activity_is_not_misreported_as_crypto_support(self):
        stock = event("01A", "stock-ref", symbol="AAPL")
        report = summarize_events(
            [stock], [], 0, since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
        )
        self.assertEqual(report["status"], "NO_CRYPTO_TRADES")
        self.assertEqual(report["crypto_trade_event_count"], 0)

    def test_correction_with_missing_prior_ref_is_flagged_as_orphan(self):
        correction = event("01B", "new-ref", "trade_correct", previous_id="not-in-window")
        report = summarize_events(
            [correction], [], 0, since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
        )
        self.assertEqual(report["orphan_previous_id_count"], 1)
        self.assertEqual(report["status"], "INCOMPLETE")

    def test_duplicate_ref_ids_and_non_monotonic_event_ids_are_reported(self):
        events = [
            event("01B", "same-ref"),
            event("01A", "same-ref"),
        ]
        report = summarize_events(
            events, [], 0, since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
        )
        self.assertEqual(report["duplicate_ref_id_count"], 1)
        self.assertEqual(report["event_ordering_anomaly_count"], 1)

    def test_dropped_message_comment_marks_probe_incomplete(self):
        report = summarize_events(
            [event("01A", "ref-1")],
            ["you are reading too slowly, dropped 20 messages"],
            0,
            since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
        )
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["dropped_message_comment_count"], 1)

    def test_http_403_is_reported_as_unavailable_without_exposing_body(self):
        response = Response(status_code=403, lines=["secret response"])
        def fake_get(url, **kwargs):
            self.assertEqual(url, ENDPOINT)
            self.assertEqual(kwargs["headers"]["Accept"], "text/event-stream")
            return response
        report = run_probe(
            api_key="fake-key", api_secret="fake-secret",
            since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
            request_get=fake_get,
        )
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(report["http_status"], 403)
        self.assertTrue(response.closed)
        self.assertNotIn("secret", json.dumps(report))

    def test_request_uses_paper_sse_endpoint_and_bounded_time_window(self):
        response = Response(lines=[
            'data: ' + json.dumps(event("01A", "ref-1")),
            "",
        ])
        captured = {}
        def fake_get(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return response
        report = run_probe(
            api_key="fake-key", api_secret="fake-secret",
            since="2026-11-11T04:55:00Z",
            until="2026-11-11T06:00:00Z",
            request_get=fake_get,
        )
        self.assertEqual(captured["url"], ENDPOINT)
        self.assertEqual(captured["params"]["since"], "2026-11-11T04:55:00Z")
        self.assertEqual(captured["params"]["until"], "2026-11-11T06:00:00Z")
        self.assertTrue(captured["stream"])
        self.assertEqual(report["status"], "CRYPTO_EVENTS_FOUND")
        self.assertTrue(response.closed)

    def test_invalid_or_reversed_window_is_rejected(self):
        with self.assertRaises(ValueError):
            run_probe(
                api_key="fake-key", api_secret="fake-secret",
                since="2026-11-11T06:00:00Z",
                until="2026-11-11T05:00:00Z",
                request_get=lambda *args, **kwargs: None,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
