#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for bounded Paper Activity SSE coverage attestations."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger, PaperCashLedgerError
from rocket_trader_paper_activity_coverage_audit import (
    ActivityCoverageAuditError,
    AlpacaPaperActivityCoverageAuditor,
)

ACCOUNT = "paper-account-coverage"
SINCE = datetime(2026, 11, 13, 17, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
CHECKED = UNTIL + timedelta(seconds=1)


def event(event_id, ref_id, amount="5"):
    return {
        "account_id": ACCOUNT,
        "activity_type": "DIV",
        "activity_subtype": None,
        "at": (SINCE + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "currency": "USD",
        "event_id": event_id,
        "executed_at": (SINCE + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "net_amount": amount,
        "previous_id": None,
        "ref_id": ref_id,
        "status": "executed",
        "details": {},
    }


class FakeResponse:
    status_code = 200

    def __init__(self, events=(), comments=()):
        self.events = list(events)
        self.comments = list(comments)
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        for comment in self.comments:
            yield f":{comment}"
            yield ""
        for item in self.events:
            yield "data: " + json.dumps(item, separators=(",", ":"))
            yield ""

    def close(self):
        self.closed = True


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox_path = os.path.join(self.tmp.name, "inbox.sqlite3")
        self.cash_path = os.path.join(self.tmp.name, "cash.sqlite3")
        self.inbox = DurableActivitySSEInbox(self.inbox_path)
        self.ledger = AlpacaPaperUSDCashLedger(self.cash_path, account_id=ACCOUNT)
        self.ledger.record_anchor(
            anchor_id="coverage-anchor",
            cash_usd="1000",
            observed_at=SINCE,
            source_reference="paper-account-snapshot",
            activity_cursor_before_snapshot=None,
        )
        self.activity = event("00000000000000000000000001", "coverage-ref-1")
        self.inbox.stage(self.activity)
        self.ledger.ingest_from_activity_sse_inbox(inbox_db_path=self.inbox_path)

    def tearDown(self):
        self.tmp.cleanup()

    def auditor(self, response):
        return AlpacaPaperActivityCoverageAuditor(
            account_id=ACCOUNT,
            cash_ledger=self.ledger,
            inbox_db_path=self.inbox_path,
            api_key="paper-key",
            api_secret="paper-secret",
            request_get=lambda *args, **kwargs: response,
        )

    def test_exact_bounded_replay_creates_durable_attestation(self):
        response = FakeResponse([self.activity])
        report = self.auditor(response).audit(since=SINCE, until=UNTIL, checked_at=CHECKED)
        self.assertEqual(report["status"], "ATTESTED")
        self.assertEqual(report["replay_event_count"], 1)
        self.assertTrue(report["replay_matches_inbox"])
        self.assertTrue(response.closed)
        result = self.ledger.reconcile(
            broker_cash_usd="1005",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference=report["audit_id"],
            activity_coverage_checked_at=CHECKED,
        )
        self.assertEqual(result["cash_reconciliation_status"], "RECONCILED")
        self.assertTrue(result["activity_coverage_complete"])

    def test_missing_inbox_event_blocks_attestation(self):
        other = event("00000000000000000000000002", "missing-ref")
        with self.assertRaisesRegex(ActivityCoverageAuditError, "differs from durable inbox"):
            self.auditor(FakeResponse([self.activity, other])).audit(
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_extra_inbox_event_blocks_attestation(self):
        self.inbox.stage(event("00000000000000000000000002", "extra-ref"))
        self.ledger.ingest_from_activity_sse_inbox(inbox_db_path=self.inbox_path)
        with self.assertRaisesRegex(ActivityCoverageAuditError, "differs from durable inbox"):
            self.auditor(FakeResponse([self.activity])).audit(
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_dropped_message_comment_blocks_attestation(self):
        response = FakeResponse([self.activity], comments=["you are reading too slowly, dropped 4 messages"])
        with self.assertRaisesRegex(ActivityCoverageAuditError, "dropped-message"):
            self.auditor(response).audit(since=SINCE, until=UNTIL, checked_at=CHECKED)
        self.assertTrue(response.closed)

    def test_internal_server_error_comment_blocks_attestation(self):
        with self.assertRaisesRegex(ActivityCoverageAuditError, "dropped-message"):
            self.auditor(FakeResponse([self.activity], comments=["internal server error"])).audit(
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_changed_payload_for_same_reference_blocks_attestation(self):
        changed = dict(self.activity, net_amount="6")
        with self.assertRaisesRegex(ActivityCoverageAuditError, "differs from durable inbox"):
            self.auditor(FakeResponse([changed])).audit(
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_nonmatching_account_is_rejected(self):
        wrong = dict(self.activity, account_id="other-account")
        with self.assertRaisesRegex(ActivityCoverageAuditError, "unexpected Paper account"):
            self.auditor(FakeResponse([wrong])).audit(
                since=SINCE, until=UNTIL, checked_at=CHECKED,
            )

    def test_unbounded_or_invalid_time_window_is_rejected(self):
        with self.assertRaisesRegex(ActivityCoverageAuditError, "earlier than until"):
            self.auditor(FakeResponse([])).audit(since=UNTIL, until=SINCE, checked_at=CHECKED)

    def test_coverage_attestation_is_required_for_cash_reconciliation(self):
        report = self.ledger.reconcile(
            broker_cash_usd="1005",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference="invented-reference",
            activity_coverage_checked_at=CHECKED,
        )
        self.assertEqual(report["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")
        self.assertFalse(report["activity_coverage_complete"])

    def test_attestation_must_cover_the_snapshot_time(self):
        response = FakeResponse([self.activity])
        report = self.auditor(response).audit(
            since=SINCE, until=UNTIL - timedelta(seconds=1),
            checked_at=CHECKED,
        )
        result = self.ledger.reconcile(
            broker_cash_usd="1005",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference=report["audit_id"],
            activity_coverage_checked_at=CHECKED,
        )
        self.assertEqual(result["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")

    def test_coverage_manifest_must_match_cash_ledger_events(self):
        response = FakeResponse([self.activity])
        report = self.auditor(response).audit(since=SINCE, until=UNTIL, checked_at=CHECKED)
        # Tamper with the local cash ledger only after the audit. Append-only
        # triggers are removed solely to simulate damaged storage.
        import sqlite3
        with sqlite3.connect(self.cash_path) as conn:
            conn.execute("DROP TRIGGER paper_cash_activities_no_update")
            row = conn.execute(
                "SELECT payload_json FROM paper_cash_activities WHERE ref_id=?",
                ("coverage-ref-1",),
            ).fetchone()
            changed = json.loads(row[0])
            changed["net_amount"] = "6"
            conn.execute(
                "UPDATE paper_cash_activities SET payload_json=? WHERE ref_id=?",
                (json.dumps(changed, sort_keys=True, separators=(",", ":")), "coverage-ref-1"),
            )
            conn.execute("CREATE TRIGGER paper_cash_activities_no_update BEFORE UPDATE ON paper_cash_activities "
                         "BEGIN SELECT RAISE(ABORT, 'Paper cash evidence is append-only'); END")
        result = self.ledger.reconcile(
            broker_cash_usd="1005",
            broker_account_id=ACCOUNT,
            observed_at=UNTIL,
            activity_coverage_complete=True,
            activity_coverage_reference=report["audit_id"],
            activity_coverage_checked_at=CHECKED,
        )
        self.assertEqual(result["cash_reconciliation_status"], "ACTIVITY_HISTORY_INCOMPLETE")
