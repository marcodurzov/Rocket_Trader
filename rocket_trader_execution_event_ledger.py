#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only, hash-chained SQLite event ledger for Rocket Trader.

This module is deliberately broker-agnostic and has no network or order-submission
capabilities. It records evidence; it does not authorize or execute trades.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class ExecutionLedgerError(RuntimeError):
    """Invalid or unverifiable execution-ledger operation."""


_FORBIDDEN_KEY_PARTS = (
    "api_key", "secret", "password", "passwd", "token",
    "authorization", "private_key", "credential",
)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionLedgerError("Event payload must be finite JSON data.") from exc


def _reject_credentials(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise ExecutionLedgerError(
                    f"Credential-like field is prohibited in ledger evidence: {path}.{key}"
                )
            _reject_credentials(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")


def _normalize_timestamp(value: Optional[str]) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        if not isinstance(value, str) or not value.strip():
            raise ExecutionLedgerError("occurred_at must be an ISO-8601 timestamp.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExecutionLedgerError("occurred_at must be an ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ExecutionLedgerError("occurred_at must include a timezone offset.")
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _event_hash(
    sequence: int,
    event_id: str,
    aggregate_id: str,
    event_type: str,
    occurred_at: str,
    payload_json: str,
    previous_hash: str,
) -> str:
    material = {
        "sequence": sequence,
        "event_id": event_id,
        "aggregate_id": aggregate_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload_json": payload_json,
        "previous_hash": previous_hash,
    }
    encoded = _canonical_json(material).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExecutionEventLedger:
    """Durable append-only event store with global SHA-256 hash chaining.

    Use a persistent local volume for db_path. A temporary filesystem or a
    GitHub Actions runner is not durable across jobs/restarts.
    """

    GENESIS_HASH = "0" * 64

    def __init__(self, db_path: str) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise ExecutionLedgerError("db_path must point to persistent storage.")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS execution_events_no_update
                BEFORE UPDATE ON execution_events
                BEGIN
                    SELECT RAISE(ABORT, 'execution event ledger is append-only');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS execution_events_no_delete
                BEFORE DELETE ON execution_events
                BEGIN
                    SELECT RAISE(ABORT, 'execution event ledger is append-only');
                END
                """
            )

    def append_event(
        self,
        *,
        event_id: str,
        aggregate_id: str,
        event_type: str,
        payload: Dict[str, Any],
        occurred_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        for field_name, field_value in (
            ("event_id", event_id),
            ("aggregate_id", aggregate_id),
            ("event_type", event_type),
        ):
            if not isinstance(field_value, str) or not field_value.strip():
                raise ExecutionLedgerError(f"{field_name} must be a non-empty string.")
        if len(event_id) > 128 or len(aggregate_id) > 128 or len(event_type) > 96:
            raise ExecutionLedgerError("Event identifiers and event_type exceed supported length.")
        if not isinstance(payload, dict):
            raise ExecutionLedgerError("payload must be a JSON object.")
        _reject_credentials(payload)
        payload_json = _canonical_json(payload)
        # Keep an omitted timestamp distinguishable from an explicit one. This
        # lets a retry with the same event_id/payload remain idempotent even
        # though the first attempt generated its own ingestion timestamp.
        timestamp = None if occurred_at is None else _normalize_timestamp(occurred_at)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM execution_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing is not None:
                same_event = (
                    existing["aggregate_id"] == aggregate_id
                    and existing["event_type"] == event_type
                    and (timestamp is None or existing["occurred_at"] == timestamp)
                    and existing["payload_json"] == payload_json
                )
                if not same_event:
                    raise ExecutionLedgerError(
                        "event_id already exists with a different immutable event payload."
                    )
                result = dict(existing)
                result["payload"] = json.loads(result.pop("payload_json"))
                result["duplicate_prevented"] = True
                return result

            if timestamp is None:
                timestamp = _normalize_timestamp(None)

            previous = connection.execute(
                "SELECT sequence, event_hash FROM execution_events "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous["event_hash"] if previous else self.GENESIS_HASH
            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM execution_events"
            ).fetchone()
            sequence = int(sequence_row["next_sequence"])
            digest = _event_hash(
                sequence, event_id, aggregate_id, event_type,
                timestamp, payload_json, previous_hash,
            )
            connection.execute(
                """
                INSERT INTO execution_events
                (sequence, event_id, aggregate_id, event_type, occurred_at,
                 payload_json, previous_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence, event_id, aggregate_id, event_type, timestamp,
                    payload_json, previous_hash, digest,
                ),
            )
            return {
                "sequence": sequence,
                "event_id": event_id,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "occurred_at": timestamp,
                "payload": payload,
                "previous_hash": previous_hash,
                "event_hash": digest,
                "duplicate_prevented": False,
            }

    def list_events(
        self, *, aggregate_id: Optional[str] = None, limit: int = 1000
    ) -> list[Dict[str, Any]]:
        if not isinstance(limit, int) or limit < 1 or limit > 10000:
            raise ExecutionLedgerError("limit must be an integer from 1 to 10000.")
        with self._connect() as connection:
            if aggregate_id is None:
                rows = connection.execute(
                    "SELECT * FROM execution_events ORDER BY sequence LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM execution_events WHERE aggregate_id=? "
                    "ORDER BY sequence LIMIT ?", (aggregate_id, limit)
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            results.append(item)
        return results

    def verify_chain(self) -> Dict[str, Any]:
        """Verify sequence continuity, previous links, and every event digest."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_events ORDER BY sequence"
            ).fetchall()

        previous_hash = self.GENESIS_HASH
        expected_sequence = 1
        for row in rows:
            if int(row["sequence"]) != expected_sequence:
                return {
                    "valid": False, "event_count": len(rows),
                    "failed_sequence": int(row["sequence"]),
                    "reason": "sequence_discontinuity",
                }
            if row["previous_hash"] != previous_hash:
                return {
                    "valid": False, "event_count": len(rows),
                    "failed_sequence": expected_sequence,
                    "reason": "previous_hash_mismatch",
                }
            expected_hash = _event_hash(
                expected_sequence, row["event_id"], row["aggregate_id"],
                row["event_type"], row["occurred_at"],
                row["payload_json"], previous_hash,
            )
            if row["event_hash"] != expected_hash:
                return {
                    "valid": False, "event_count": len(rows),
                    "failed_sequence": expected_sequence,
                    "reason": "event_hash_mismatch",
                }
            previous_hash = row["event_hash"]
            expected_sequence += 1

        return {
            "valid": True,
            "event_count": len(rows),
            "last_sequence": expected_sequence - 1,
            "last_hash": previous_hash,
        }
