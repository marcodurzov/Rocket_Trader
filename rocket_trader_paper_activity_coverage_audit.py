#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Attest bounded Alpaca Paper Activity SSE history against the durable inbox.

This performs a read-only, bounded historical SSE replay. It does not place
orders, mutate the broker account, or infer completeness from the local hash
chain alone. Coverage is recorded only when the bounded broker replay and the
durable inbox contain the exact same activity references and payload hashes.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

from rocket_trader_alpaca_activity_sse_consumer import (
    ACTIVITY_SSE_ENDPOINT,
    ActivitySSEConsumerError,
    DurableActivitySSEInbox,
    _activity_fingerprint,
    parse_sse,
)
from rocket_trader_alpaca_cash_ledger import (
    AlpacaPaperUSDCashLedger,
    PaperCashLedgerError,
    _iso,
    _timestamp,
)


class ActivityCoverageAuditError(RuntimeError):
    """Bounded broker replay cannot prove complete Activity SSE coverage."""


def _as_utc(value: Any, field: str) -> datetime:
    try:
        return _timestamp(value, field)
    except PaperCashLedgerError as exc:
        raise ActivityCoverageAuditError(str(exc)) from exc


class AlpacaPaperActivityCoverageAuditor:
    """Compare a bounded historical broker replay with the immutable local inbox."""

    def __init__(
        self,
        *,
        account_id: str,
        cash_ledger: AlpacaPaperUSDCashLedger,
        inbox_db_path: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        request_get: Optional[Callable[..., Any]] = None,
        timeout_seconds: int = 60,
    ) -> None:
        if not isinstance(account_id, str) or not account_id.strip():
            raise ActivityCoverageAuditError("Paper account ID is required")
        if cash_ledger is None or cash_ledger.account_id != account_id.strip():
            raise ActivityCoverageAuditError("Cash ledger must be bound to the same Paper account")
        if not isinstance(inbox_db_path, str) or not inbox_db_path.strip():
            raise ActivityCoverageAuditError("Durable Activity SSE inbox path is required")
        self.account_id = account_id.strip()
        self.cash_ledger = cash_ledger
        self.inbox_db_path = str(Path(inbox_db_path).expanduser())
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.api_secret = api_secret or os.getenv("ALPACA_SECRET_KEY", "")
        if not self.api_key or not self.api_secret:
            raise ActivityCoverageAuditError("Alpaca Paper API credentials are required")
        if timeout_seconds < 15:
            raise ActivityCoverageAuditError("timeout_seconds must be at least 15")
        self.request_get = request_get
        self.timeout_seconds = timeout_seconds

    def _fetch_bounded_replay(self, since: datetime, until: datetime) -> list[Dict[str, Any]]:
        getter = self.request_get
        if getter is None:
            import requests
            getter = requests.get
        response = None
        replay: Dict[str, Dict[str, str]] = {}
        seen_event_ids: Dict[str, str] = {}
        last_event_id: Optional[str] = None
        try:
            response = getter(
                ACTIVITY_SSE_ENDPOINT,
                headers={
                    "APCA-API-KEY-ID": str(self.api_key),
                    "APCA-API-SECRET-KEY": str(self.api_secret),
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
                params={"since": _iso(since), "until": _iso(until + timedelta(microseconds=1))},
                stream=True,
                timeout=(10, self.timeout_seconds),
            )
            status = int(getattr(response, "status_code", 0))
            if status != 200:
                raise ActivityCoverageAuditError(
                    f"Bounded Activity SSE replay returned HTTP {status}"
                )
            try:
                frames = parse_sse(response.iter_lines(decode_unicode=True))
                for frame_type, content in frames:
                    if frame_type == "comment":
                        lowered = content.lower()
                        if "dropped" in lowered or "internal server error" in lowered:
                            raise ActivityCoverageAuditError(
                                "Bounded Activity SSE replay reported a dropped-message or server-error condition"
                            )
                        continue
                    import json
                    try:
                        event = json.loads(content)
                    except (TypeError, ValueError) as exc:
                        raise ActivityCoverageAuditError("Bounded replay contains malformed JSON") from exc
                    if not isinstance(event, dict):
                        raise ActivityCoverageAuditError("Bounded replay event must be a JSON object")
                    event_id = str(event.get("event_id") or "").strip()
                    ref_id = str(event.get("ref_id") or "").strip()
                    if not event_id or not ref_id:
                        raise ActivityCoverageAuditError("Bounded replay event is missing event_id or ref_id")
                    if last_event_id is not None and event_id <= last_event_id:
                        raise ActivityCoverageAuditError("Bounded replay event IDs are not strictly increasing")
                    last_event_id = event_id
                    if event_id in seen_event_ids and seen_event_ids[event_id] != ref_id:
                        raise ActivityCoverageAuditError("Bounded replay reused an event_id for another activity")
                    seen_event_ids[event_id] = ref_id
                    if str(event.get("account_id") or "").strip() != self.account_id:
                        raise ActivityCoverageAuditError("Bounded replay contains an unexpected Paper account ID")
                    occurred = _as_utc(event.get("at"), "Activity SSE at")
                    if not (since < occurred <= until):
                        raise ActivityCoverageAuditError("Bounded replay returned an event outside the requested business-time window")
                    digest = _activity_fingerprint(event)
                    existing = replay.get(ref_id)
                    item = {
                        "ref_id": ref_id,
                        "occurred_at": _iso(occurred),
                        "payload_hash": digest,
                    }
                    if existing and existing != item:
                        raise ActivityCoverageAuditError("Bounded replay contains a changed duplicate ref_id")
                    replay[ref_id] = item
            except ActivitySSEConsumerError as exc:
                raise ActivityCoverageAuditError("Could not parse or validate bounded Activity SSE replay") from exc
        except ActivityCoverageAuditError:
            raise
        except Exception as exc:
            raise ActivityCoverageAuditError("Bounded Activity SSE replay request failed or ended abnormally") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
        return [replay[key] for key in sorted(replay)]

    def _read_inbox_window(self, since: datetime, until: datetime) -> tuple[list[Dict[str, Any]], Optional[str]]:
        path = Path(self.inbox_db_path).expanduser().resolve()
        if not path.is_file():
            raise ActivityCoverageAuditError("Existing durable Activity SSE inbox is missing")
        try:
            inbox = DurableActivitySSEInbox(str(path), initialize=False)
            integrity = inbox.verify()
        except (ActivitySSEConsumerError, sqlite3.Error, ValueError) as exc:
            raise ActivityCoverageAuditError("Durable Activity SSE inbox integrity check failed") from exc
        if not isinstance(integrity, dict) or integrity.get("valid") is not True:
            raise ActivityCoverageAuditError("Durable Activity SSE inbox hash chain/cursor is invalid")
        uri = path.as_uri() + "?mode=ro"
        items: Dict[str, Dict[str, str]] = {}
        try:
            with sqlite3.connect(uri, uri=True, timeout=30) as conn:
                conn.execute("PRAGMA query_only=ON")
                rows = conn.execute(
                    """SELECT ref_id,occurred_at,payload_hash,payload_json
                       FROM activity_sse_events ORDER BY sequence"""
                ).fetchall()
            import json
            for ref_id, occurred_at, payload_hash, payload_json in rows:
                parsed_at = _as_utc(occurred_at, "inbox occurred_at")
                if not (since < parsed_at <= until):
                    continue
                payload = json.loads(payload_json)
                if str(payload.get("account_id") or "").strip() != self.account_id:
                    raise ActivityCoverageAuditError("Durable inbox contains an unexpected Paper account ID")
                item = {
                    "ref_id": str(ref_id),
                    "occurred_at": _iso(parsed_at),
                    "payload_hash": str(payload_hash),
                }
                if item["ref_id"] in items:
                    raise ActivityCoverageAuditError("Durable inbox contains duplicate activity references")
                items[item["ref_id"]] = item
        except (sqlite3.Error, ValueError) as exc:
            raise ActivityCoverageAuditError("Could not read durable Activity SSE inbox in read-only mode") from exc
        return [items[key] for key in sorted(items)], integrity.get("cursor")

    def audit(
        self,
        *,
        since: Any,
        until: Any,
        checked_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        start = _as_utc(since, "coverage since")
        end = _as_utc(until, "coverage until")
        if start >= end:
            raise ActivityCoverageAuditError("Coverage since must be earlier than until")
        replay = self._fetch_bounded_replay(start, end)
        inbox, cursor = self._read_inbox_window(start, end)
        replay_map = {item["ref_id"]: item for item in replay}
        inbox_map = {item["ref_id"]: item for item in inbox}
        if replay_map != inbox_map:
            missing = sorted(set(replay_map) - set(inbox_map))
            extra = sorted(set(inbox_map) - set(replay_map))
            changed = sorted(
                key for key in set(replay_map) & set(inbox_map)
                if replay_map[key] != inbox_map[key]
            )
            raise ActivityCoverageAuditError(
                "Bounded broker replay differs from durable inbox "
                f"(missing={len(missing)}, extra={len(extra)}, changed={len(changed)})"
            )
        checked = checked_at or datetime.now(timezone.utc)
        checked = _as_utc(checked, "coverage checked_at")
        if checked < end:
            raise ActivityCoverageAuditError("Coverage checked_at must be at or after the replay window end")
        try:
            report = self.cash_ledger.record_activity_coverage_audit(
                since_at=start,
                until_at=end,
                checked_at=checked,
                replay_events=replay,
                inbox_events=inbox,
                inbox_cursor=cursor,
            )
        except PaperCashLedgerError as exc:
            raise ActivityCoverageAuditError("Could not persist verified activity coverage evidence") from exc
        return {
            **report,
            "account_id": self.account_id,
            "replay_event_count": len(replay),
            "inbox_event_count": len(inbox),
            "replay_matches_inbox": True,
            "inbox_cursor": cursor,
            "orders_enabled": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cash-db",
        default=os.getenv("ROCKET_TRADER_CASH_LEDGER_DB", "/app/data/rocket_trader_paper_cash.sqlite3"),
    )
    parser.add_argument(
        "--activity-sse-db",
        default=os.getenv("ROCKET_TRADER_ACTIVITY_SSE_DB", "/app/data/rocket_trader_activity_sse.sqlite3"),
    )
    parser.add_argument(
        "--until",
        help="Inclusive business-time window end (RFC3339); defaults to current UTC time.",
    )
    args = parser.parse_args()

    if os.getenv("ALPACA_PAPER", "false").strip().lower() != "true":
        raise ActivityCoverageAuditError("ALPACA_PAPER=true is required")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise ActivityCoverageAuditError("ALPACA_LIVE_ENABLED must remain false")
    if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
        raise ActivityCoverageAuditError("ROCKET_TRADER_EXECUTION_MODE must be PAPER")

    cash_path = Path(args.cash_db).expanduser().resolve()
    if not cash_path.is_file():
        raise ActivityCoverageAuditError("Existing Paper cash ledger database is missing")
    uri = cash_path.as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=30) as conn:
            conn.execute("PRAGMA query_only=ON")
            anchor = conn.execute(
                "SELECT account_id,observed_at FROM paper_cash_anchors ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.Error as exc:
        raise ActivityCoverageAuditError("Could not read the existing Paper cash anchor") from exc
    if anchor is None:
        raise ActivityCoverageAuditError("A Paper cash anchor is required before coverage audit")
    account_id, anchor_at = str(anchor[0]), str(anchor[1])
    ledger = AlpacaPaperUSDCashLedger(
        str(cash_path), account_id=account_id, initialize=False,
    )
    until = _as_utc(args.until, "coverage until") if args.until else datetime.now(timezone.utc)
    auditor = AlpacaPaperActivityCoverageAuditor(
        account_id=account_id,
        cash_ledger=ledger,
        inbox_db_path=args.activity_sse_db,
    )
    report = auditor.audit(
        since=anchor_at,
        until=until,
        checked_at=datetime.now(timezone.utc),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
