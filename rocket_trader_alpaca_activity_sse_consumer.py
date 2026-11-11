#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable, read-only Alpaca Paper Activity SSE inbox.

This consumer stages broker activities and a replay cursor atomically. It does
NOT update positions, cash, realized P&L, fees, or execution decisions. In
particular, trade_correct/trade_bust events are retained as evidence only;
accounting reversals require a separate reviewed implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional
from urllib.parse import urlencode

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ACTIVITY_SSE_ENDPOINT = f"{PAPER_BASE_URL}/v2beta1/events/activities"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_FORBIDDEN_KEYS = (
    "api_key", "secret", "password", "passwd", "token",
    "authorization", "private_key", "credential",
)


class ActivitySSEConsumerError(RuntimeError):
    """Fail-closed Activity SSE retrieval or durable-staging error."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ActivitySSEConsumerError("Activity must be finite JSON data.") from exc


def _reject_credentials(value: Any, path: str = "activity") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_KEYS):
                raise ActivitySSEConsumerError(
                    f"Credential-like field is prohibited in staged activity: {path}.{key}"
                )
            _reject_credentials(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _activity_fingerprint(event: Dict[str, Any]) -> str:
    """Hash stable activity content, excluding the replay/publication event_id."""
    stable = dict(event)
    stable.pop("event_id", None)
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()


def _event_hash(sequence: int, ref_id: str, event_id: str, payload_hash: str,
                previous_hash: str) -> str:
    material = _canonical({
        "sequence": sequence, "ref_id": ref_id, "event_id": event_id,
        "payload_hash": payload_hash, "previous_hash": previous_hash,
    }).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def parse_sse(lines: Iterable[Any]) -> Iterator[tuple[str, str]]:
    """Yield ('data', json_text) and ('comment', comment_text) SSE frames."""
    data: list[str] = []

    def flush() -> Optional[tuple[str, str]]:
        if not data:
            return None
        value = "\n".join(data)
        data.clear()
        return ("data", value)

    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        line = line.rstrip("\r\n")
        if line == "":
            frame = flush()
            if frame:
                yield frame
        elif line.startswith(":"):
            yield ("comment", line[1:].strip())
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    frame = flush()
    if frame:
        yield frame


class DurableActivitySSEInbox:
    """Append-only activity inbox with atomic replay cursor and idempotent staging."""

    GENESIS_HASH = "0" * 64

    def __init__(self, db_path: str) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise ActivitySSEConsumerError("A persistent SQLite path is required.")
        self.db_path = str(db_path)
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_sse_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_id TEXT NOT NULL UNIQUE,
                    first_event_id TEXT NOT NULL,
                    previous_id TEXT,
                    activity_type TEXT NOT NULL,
                    activity_subtype TEXT,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_sse_deliveries (
                    event_id TEXT PRIMARY KEY,
                    ref_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_sse_cursor (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    event_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            for table in ("activity_sse_events", "activity_sse_deliveries"):
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_update
                    BEFORE UPDATE ON {table}
                    BEGIN SELECT RAISE(ABORT, 'Activity SSE evidence is append-only'); END
                """)
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_delete
                    BEFORE DELETE ON {table}
                    BEGIN SELECT RAISE(ABORT, 'Activity SSE evidence is append-only'); END
                """)

    @property
    def cursor(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id FROM activity_sse_cursor WHERE singleton=1"
            ).fetchone()
        return str(row["event_id"]) if row else None

    def stage(self, event: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event, dict):
            raise ActivitySSEConsumerError("SSE data frame must decode to a JSON object.")
        event_id = event.get("event_id")
        ref_id = event.get("ref_id")
        activity_type = event.get("activity_type")
        occurred_at = event.get("at")
        details = event.get("details")
        if not isinstance(event_id, str) or not _ULID_RE.fullmatch(event_id):
            raise ActivitySSEConsumerError("Activity event_id must be a 26-character ULID.")
        if not isinstance(ref_id, str) or not ref_id.strip() or len(ref_id) > 128:
            raise ActivitySSEConsumerError("Activity ref_id must be a non-empty identifier.")
        if not isinstance(activity_type, str) or not activity_type.strip():
            raise ActivitySSEConsumerError("Activity activity_type is required.")
        if not isinstance(occurred_at, str) or not occurred_at.strip():
            raise ActivitySSEConsumerError("Activity business timestamp 'at' is required.")
        try:
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone missing")
        except ValueError as exc:
            raise ActivitySSEConsumerError("Activity 'at' must be timezone-aware ISO-8601.") from exc
        if details is not None and not isinstance(details, dict):
            raise ActivitySSEConsumerError("Activity details must be a JSON object when present.")
        _reject_credentials(event)
        payload_json = _canonical(event)
        payload_hash = _activity_fingerprint(event)
        previous_id = event.get("previous_id")
        if previous_id is not None and (not isinstance(previous_id, str) or not previous_id.strip()):
            raise ActivitySSEConsumerError("previous_id must be null or a non-empty string.")

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT event_id FROM activity_sse_cursor WHERE singleton=1"
            ).fetchone()
            cursor = str(current["event_id"]) if current else None

            delivered = conn.execute(
                "SELECT ref_id, payload_hash FROM activity_sse_deliveries WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if delivered:
                if delivered["ref_id"] != ref_id or delivered["payload_hash"] != payload_hash:
                    raise ActivitySSEConsumerError(
                        "Previously seen event_id was replayed with different immutable content."
                    )
                return {"status": "DUPLICATE_EVENT", "event_id": event_id, "ref_id": ref_id}

            if cursor is not None and event_id <= cursor:
                raise ActivitySSEConsumerError(
                    "Unseen event_id is not newer than the durable cursor; refusing cursor regression."
                )

            existing = conn.execute(
                "SELECT payload_hash FROM activity_sse_events WHERE ref_id=?", (ref_id,)
            ).fetchone()
            inserted = False
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ActivitySSEConsumerError(
                        "Stable ref_id was replayed with changed payload; manual reconciliation required."
                    )
            else:
                previous = conn.execute(
                    "SELECT sequence, event_hash FROM activity_sse_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                sequence = int(previous["sequence"]) + 1 if previous else 1
                previous_hash = str(previous["event_hash"]) if previous else self.GENESIS_HASH
                digest = _event_hash(sequence, ref_id, event_id, payload_hash, previous_hash)
                conn.execute("""
                    INSERT INTO activity_sse_events
                    (sequence, ref_id, first_event_id, previous_id, activity_type,
                     activity_subtype, occurred_at, payload_json, payload_hash,
                     previous_hash, event_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sequence, ref_id, event_id, previous_id,
                    activity_type.strip().upper(),
                    str(event.get("activity_subtype") or "").strip().upper() or None,
                    occurred_at, payload_json, payload_hash, previous_hash, digest,
                ))
                inserted = True

            conn.execute("""
                INSERT INTO activity_sse_deliveries(event_id, ref_id, payload_hash, received_at)
                VALUES (?, ?, ?, ?)
            """, (event_id, ref_id, payload_hash, _utc_now()))
            conn.execute("""
                INSERT INTO activity_sse_cursor(singleton, event_id, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    event_id=excluded.event_id, updated_at=excluded.updated_at
            """, (event_id, _utc_now()))
            return {
                "status": "STAGED" if inserted else "DUPLICATE_REF",
                "event_id": event_id, "ref_id": ref_id,
                "activity_type": activity_type.strip().upper(),
                "previous_id": previous_id, "cursor": event_id,
            }

    def process_lines(self, lines: Iterable[Any]) -> Dict[str, Any]:
        staged = duplicates = comments = malformed = 0
        reconnect = False
        for frame_type, content in parse_sse(lines):
            if frame_type == "comment":
                comments += 1
                lowered = content.lower()
                if "dropped" in lowered or "reading too slowly" in lowered or "internal server error" in lowered:
                    reconnect = True
                    break
                continue
            try:
                event = json.loads(content)
            except (TypeError, ValueError) as exc:
                malformed += 1
                raise ActivitySSEConsumerError("Malformed JSON SSE data frame; cursor was not advanced.") from exc
            result = self.stage(event)
            if result["status"] == "STAGED":
                staged += 1
            else:
                duplicates += 1
        return {
            "staged_count": staged, "duplicate_count": duplicates,
            "comment_count": comments, "malformed_frame_count": malformed,
            "reconnect_required": reconnect, "cursor": self.cursor,
        }

    def verify(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM activity_sse_events ORDER BY sequence").fetchall()
            deliveries = conn.execute("SELECT * FROM activity_sse_deliveries").fetchall()
            cursor_row = conn.execute(
                "SELECT event_id FROM activity_sse_cursor WHERE singleton=1"
            ).fetchone()
            refs = {str(row["ref_id"]) for row in rows}
            activity_hashes = {str(row["ref_id"]): str(row["payload_hash"]) for row in rows}
            latest_delivery_row = conn.execute(
                "SELECT event_id FROM activity_sse_deliveries ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        previous_hash = self.GENESIS_HASH
        expected_sequence = 1
        for row in rows:
            if int(row["sequence"]) != expected_sequence:
                return {"valid": False, "reason": "sequence_discontinuity"}
            if row["previous_hash"] != previous_hash:
                return {"valid": False, "reason": "previous_hash_mismatch"}
            expected = _event_hash(
                expected_sequence, row["ref_id"], row["first_event_id"],
                row["payload_hash"], previous_hash,
            )
            if row["event_hash"] != expected:
                return {"valid": False, "reason": "event_hash_mismatch"}
            payload = json.loads(row["payload_json"])
            if _activity_fingerprint(payload) != row["payload_hash"]:
                return {"valid": False, "reason": "payload_hash_mismatch"}
            previous_hash = row["event_hash"]
            expected_sequence += 1
        delivery_refs = {str(row["ref_id"]) for row in deliveries}
        cursor = str(cursor_row["event_id"]) if cursor_row else None
        delivery_ids = {str(row["event_id"]) for row in deliveries}
        delivery_mismatches = sum(
            1 for row in deliveries
            if activity_hashes.get(str(row["ref_id"])) != str(row["payload_hash"])
        )
        latest_delivery = str(latest_delivery_row["event_id"]) if latest_delivery_row else None
        cursor_is_latest = cursor == latest_delivery if cursor is not None else latest_delivery is None
        orphan_previous = sum(
            1 for row in rows if row["previous_id"] and row["previous_id"] not in refs
        )
        integrity_valid = (
            delivery_mismatches == 0
            and cursor_is_latest
            and (cursor is None or cursor in delivery_ids)
            and delivery_refs.issubset(refs)
        )
        return {
            "valid": integrity_valid, "activity_count": len(rows), "delivery_count": len(deliveries),
            "cursor": cursor, "cursor_has_delivery": cursor in delivery_ids if cursor else False,
            "cursor_is_latest_delivery": cursor_is_latest,
            "delivery_payload_mismatch_count": delivery_mismatches,
            "orphan_previous_id_count": orphan_previous,
            "unreferenced_delivery_count": len(delivery_refs - refs),
            "reason": None if integrity_valid else "delivery_or_cursor_integrity_failure",
        }

    def list_events(self, *, limit: int = 1000) -> list[Dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ActivitySSEConsumerError("limit must be from 1 to 10000.")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM activity_sse_events ORDER BY sequence LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result


class AlpacaPaperActivitySSEConsumer:
    """Reconnectable Paper SSE reader; all events are staged, never financially applied."""

    def __init__(
        self, *, inbox: DurableActivitySSEInbox, bootstrap_since: str,
        api_key: Optional[str] = None, api_secret: Optional[str] = None,
        request_get: Optional[Callable[..., Any]] = None,
        read_timeout: int = 60,
    ) -> None:
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise ActivitySSEConsumerError("LIVE mode is prohibited.")
        if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
            raise ActivitySSEConsumerError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")
        if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
            raise ActivitySSEConsumerError("ALPACA_PAPER must be exactly true.")
        if inbox is None:
            raise ActivitySSEConsumerError("A durable activity inbox is required.")
        try:
            parsed = datetime.fromisoformat(bootstrap_since.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone missing")
        except (AttributeError, ValueError) as exc:
            raise ActivitySSEConsumerError("bootstrap_since must be timezone-aware ISO-8601.") from exc
        self.inbox = inbox
        self.bootstrap_since = bootstrap_since
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_SECRET_KEY")
        if not self.api_key or not self.api_secret:
            raise ActivitySSEConsumerError("Alpaca Paper API credentials are required.")
        self.request_get = request_get
        self.read_timeout = max(15, int(read_timeout))

    def connect_once(self) -> Dict[str, Any]:
        getter = self.request_get
        if getter is None:
            import requests
            getter = requests.get
        cursor = self.inbox.cursor
        params = {"since_id": cursor} if cursor else {"since": self.bootstrap_since}
        response = None
        try:
            response = getter(
                ACTIVITY_SSE_ENDPOINT,
                headers={
                    "APCA-API-KEY-ID": str(self.api_key),
                    "APCA-API-SECRET-KEY": str(self.api_secret),
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
                params=params, stream=True, timeout=(10, self.read_timeout),
            )
            status = int(getattr(response, "status_code", 0))
            if status != 200:
                raise ActivitySSEConsumerError(
                    f"Alpaca Activity SSE returned HTTP {status}; durable cursor was not advanced."
                )
            result = self.inbox.process_lines(response.iter_lines(decode_unicode=True))
            result["http_status"] = status
            result["request_cursor_type"] = "since_id" if cursor else "since"
            return result
        except ActivitySSEConsumerError:
            raise
        except Exception as exc:
            raise ActivitySSEConsumerError(
                "Activity SSE connection failed; reconnect from the durable cursor."
            ) from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def run_forever(
        self, stop_event: threading.Event, *, max_backoff_seconds: int = 30,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """Run until stopped; reconnect with persisted since_id after every disconnect."""
        attempt = 0
        while not stop_event.is_set():
            try:
                report = self.connect_once()
                attempt = 0
                print(json.dumps({
                    "component": "paper_activity_sse",
                    "status": "STREAM_ENDED_OR_RECONNECTING",
                    "staged_count": report.get("staged_count", 0),
                    "duplicate_count": report.get("duplicate_count", 0),
                    "cursor": report.get("cursor"),
                }, sort_keys=True), flush=True)
            except ActivitySSEConsumerError as exc:
                attempt += 1
                print(json.dumps({
                    "component": "paper_activity_sse",
                    "status": "RECONNECTING",
                    "error_type": type(exc).__name__,
                    "cursor": self.inbox.cursor,
                }, sort_keys=True), flush=True)
            if stop_event.is_set():
                break
            delay = min(max_backoff_seconds, 2 ** min(attempt, 5))
            sleep_fn(float(delay))


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("ACTIVITY_SSE_DB", "data/paper-activity-sse.sqlite3"))
    parser.add_argument("--bootstrap-since", default=os.getenv("ACTIVITY_SSE_BOOTSTRAP_SINCE"))
    parser.add_argument("--healthcheck", action="store_true",
                        help="Verify the durable inbox hash chain and cursor without contacting Alpaca.")
    args = parser.parse_args()
    inbox = DurableActivitySSEInbox(args.db)
    if args.healthcheck:
        report = inbox.verify()
        print(json.dumps({"mode": "PAPER", "health": report}, sort_keys=True))
        return 0 if report.get("valid") else 1
    if not args.bootstrap_since:
        parser.error("--bootstrap-since or ACTIVITY_SSE_BOOTSTRAP_SINCE is required")
    consumer = AlpacaPaperActivitySSEConsumer(inbox=inbox, bootstrap_since=args.bootstrap_since)
    stop = threading.Event()
    try:
        consumer.run_forever(stop)
    except KeyboardInterrupt:
        stop.set()
    print(json.dumps({"mode": "PAPER", "inbox": inbox.verify()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
