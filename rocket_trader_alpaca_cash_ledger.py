#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only USD cash mirror for the Alpaca Paper Activity SSE.

Only explicitly understood USD cash events are applied. Unknown activity
codes, corrections/busts, non-USD cash effects, and incomplete activity history
block reconciliation. This module is read-only with respect to Alpaca and
never authorizes or submits orders.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional


class PaperCashLedgerError(RuntimeError):
    """Invalid cash evidence or append-only ledger state."""


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperCashLedgerError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise PaperCashLedgerError(f"{field} must be finite")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise PaperCashLedgerError(f"{field} must be ISO-8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PaperCashLedgerError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _timestamp(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PaperCashLedgerError("Cash activity must be finite JSON data") from exc


class AlpacaPaperUSDCashLedger:
    """Mirror USD cash from a verified account anchor and subsequent activities.

    Anchor procedure:
      1. Read the durable Activity SSE cursor.
      2. Fetch a fresh Paper account cash snapshot and timestamp it.
      3. Record that cash snapshot as an immutable anchor.
      4. Replay/stage all Activity SSE events and reconcile only business
         timestamps after the anchor and up to the current cash snapshot.

    The caller must assert complete event coverage only after a successful
    historical replay/catch-up with no dropped SSE messages.
    """

    CASH_ACTIVITY_TYPES = {
        "TRD", "DIV", "CGD", "FEE", "CFEE", "INT", "JNLC", "CSD",
        "CSW", "MEM", "ACATC", "OPCSH", "FIMAT", "PTC", "PTR",
        "WH", "FXTRD",
    }
    KNOWN_ZERO_USD_CASH_TYPES = {"SPLIT", "JNLS", "NC"}

    def __init__(self, db_path: str, *, account_id: str) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise PaperCashLedgerError("A durable USD cash ledger path is required")
        if not isinstance(account_id, str) or not account_id.strip():
            raise PaperCashLedgerError("Alpaca Paper account_id is required")
        self.db_path = str(db_path)
        self.account_id = account_id.strip()
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
                CREATE TABLE IF NOT EXISTS paper_cash_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    cash_usd TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    activity_cursor_before_snapshot TEXT,
                    source_reference TEXT NOT NULL,
                    rebase_reason TEXT,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_cash_activities (
                    ref_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    activity_subtype TEXT,
                    occurred_at TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    cash_delta_usd TEXT,
                    classification TEXT NOT NULL,
                    previous_id TEXT,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            for table in ("paper_cash_anchors", "paper_cash_activities"):
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_update
                    BEFORE UPDATE ON {table}
                    BEGIN SELECT RAISE(ABORT, 'Paper cash evidence is append-only'); END
                """)
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_delete
                    BEFORE DELETE ON {table}
                    BEGIN SELECT RAISE(ABORT, 'Paper cash evidence is append-only'); END
                """)

    def record_anchor(
        self,
        *,
        anchor_id: str,
        cash_usd: Any,
        observed_at: Any,
        source_reference: str,
        activity_cursor_before_snapshot: Optional[str] = None,
        rebase_confirmed: bool = False,
        rebase_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        anchor = str(anchor_id or "").strip()
        reference = str(source_reference or "").strip()
        amount = _decimal(cash_usd, "cash_usd")
        when = _iso(_timestamp(observed_at, "anchor observed_at"))
        cursor = None if activity_cursor_before_snapshot is None else str(activity_cursor_before_snapshot).strip()
        if not anchor or not reference or amount < 0:
            raise PaperCashLedgerError("Anchor ID/reference are required and cash cannot be negative")
        if cursor == "":
            raise PaperCashLedgerError("Activity cursor must be null or non-empty")
        if not isinstance(rebase_confirmed, bool):
            raise PaperCashLedgerError("rebase_confirmed must be a boolean")
        reason = str(rebase_reason or "").strip()
        payload = {
            "anchor_id": anchor, "account_id": self.account_id,
            "cash_usd": str(amount), "observed_at": when,
            "activity_cursor_before_snapshot": cursor,
            "source_reference": reference,
            "rebase_confirmed": rebase_confirmed,
            "rebase_reason": reason or None,
        }
        raw = _canonical(payload)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT payload_hash FROM paper_cash_anchors WHERE anchor_id=?", (anchor,)
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise PaperCashLedgerError("Anchor ID collision with different cash evidence")
                return {"status": "DUPLICATE_ANCHOR", "anchor_id": anchor}
            latest = conn.execute(
                "SELECT observed_at FROM paper_cash_anchors ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
            if latest and when <= latest["observed_at"]:
                raise PaperCashLedgerError("A new cash anchor must be later than the prior anchor")
            if latest and (not rebase_confirmed or not reason):
                raise PaperCashLedgerError(
                    "A later cash anchor requires explicit rebase confirmation and a reason"
                )
            conn.execute("""
                INSERT INTO paper_cash_anchors
                (anchor_id,account_id,cash_usd,observed_at,
                 activity_cursor_before_snapshot,source_reference,rebase_reason,payload_hash,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                anchor, self.account_id, str(amount), when, cursor,
                reference, reason or None, digest, _iso(datetime.now(timezone.utc)),
            ))
        return {"status": "ANCHORED", "anchor_id": anchor, "cash_usd": str(amount), "observed_at": when}

    def ingest_activity(self, event: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event, dict):
            raise PaperCashLedgerError("Activity event must be an object")
        ref_id = str(event.get("ref_id") or "").strip()
        event_id = str(event.get("event_id") or "").strip()
        account_id = str(event.get("account_id") or "").strip()
        activity_type = str(event.get("activity_type") or "").strip().upper()
        currency = str(event.get("currency") or "").strip().upper()
        if not ref_id or not event_id or not activity_type or not currency:
            raise PaperCashLedgerError("Activity ref_id, event_id, activity_type and currency are required")
        if account_id != self.account_id:
            raise PaperCashLedgerError("Activity account_id does not match the configured Paper account")
        occurred_at = _iso(_timestamp(event.get("at"), "activity at"))
        details = event.get("details") or {}
        if not isinstance(details, dict):
            raise PaperCashLedgerError("Activity details must be an object")
        previous_id = event.get("previous_id")
        if previous_id is not None and not str(previous_id).strip():
            raise PaperCashLedgerError("previous_id must be null or non-empty")
        status = str(event.get("status") or "").strip().lower()
        net_amount_raw = event.get("net_amount")
        cash_delta: Optional[Decimal] = None
        classification = "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW"

        if previous_id:
            classification = "CORRECTION_OR_BUST_REQUIRES_RESTATEMENT"
        elif status != "executed":
            classification = "NON_FINAL_ACTIVITY_REQUIRES_REVIEW"
        elif activity_type in self.KNOWN_ZERO_USD_CASH_TYPES and currency == "USD":
            cash_delta = Decimal("0")
            classification = "KNOWN_ZERO_USD_CASH_EFFECT"
        elif activity_type in self.CASH_ACTIVITY_TYPES and currency == "USD":
            if net_amount_raw in (None, ""):
                classification = "MISSING_NET_AMOUNT_REQUIRES_REVIEW"
            else:
                cash_delta = _decimal(net_amount_raw, "activity net_amount")
                if activity_type == "TRD":
                    side = str(details.get("side") or "").strip().lower()
                    execution_type = str(details.get("execution_type") or "fill").strip().lower()
                    if execution_type != "fill" or side not in {"buy", "sell"}:
                        cash_delta = None
                        classification = "TRADE_CORRECTION_OR_UNSUPPORTED_SIDE"
                    elif (side == "buy" and cash_delta > 0) or (side == "sell" and cash_delta < 0):
                        cash_delta = None
                        classification = "TRADE_CASH_SIGN_CONFLICT"
                    else:
                        classification = "APPLIED_USD_CASH_ACTIVITY"
                elif activity_type in {"FEE", "CFEE"}:
                    if cash_delta > 0:
                        cash_delta = None
                        classification = "FEE_CREDIT_REQUIRES_REVIEW"
                    else:
                        classification = "APPLIED_USD_FEE_UNALLOCATED"
                else:
                    classification = "APPLIED_USD_CASH_ACTIVITY"
        elif activity_type in {"FEE", "CFEE"} and currency != "USD" and net_amount_raw not in (None, ""):
            non_usd_amount = _decimal(net_amount_raw, "non-USD fee net_amount")
            if non_usd_amount == 0:
                cash_delta = Decimal("0")
                classification = "NON_USD_FEE_ZERO_USD_CASH_UNALLOCATED"
        else:
            classification = "UNSUPPORTED_CURRENCY_OR_ACTIVITY_TYPE"

        raw = _canonical(event)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT payload_hash FROM paper_cash_activities WHERE ref_id=?", (ref_id,)
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise PaperCashLedgerError("Activity ref_id collision with different immutable content")
                return {"status": "DUPLICATE_ACTIVITY", "ref_id": ref_id}
            conn.execute("""
                INSERT INTO paper_cash_activities
                (ref_id,event_id,account_id,activity_type,activity_subtype,occurred_at,
                 currency,cash_delta_usd,classification,previous_id,payload_json,
                 payload_hash,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ref_id, event_id, account_id, activity_type,
                str(event.get("activity_subtype") or "").strip().upper() or None,
                occurred_at, currency,
                None if cash_delta is None else str(cash_delta),
                classification, previous_id, raw, digest,
                _iso(datetime.now(timezone.utc)),
            ))
        return {
            "status": "STAGED",
            "ref_id": ref_id,
            "classification": classification,
            "cash_delta_usd": None if cash_delta is None else str(cash_delta),
        }

    def ingest_from_activity_sse_inbox(
        self,
        *,
        inbox_db_path: str,
        page_size: int = 1000,
    ) -> Dict[str, Any]:
        """Verify and idempotently ingest every staged Activity SSE payload.

        Inbox hash-chain validity proves local integrity, not completeness of
        the broker stream. This method therefore never sets the coverage flag;
        a separate successful replay/catch-up attestation is required by
        reconcile().
        """
        if not isinstance(inbox_db_path, str) or not inbox_db_path.strip():
            raise PaperCashLedgerError("A durable Activity SSE inbox path is required")
        if not isinstance(page_size, int) or not 1 <= page_size <= 10000:
            raise PaperCashLedgerError("page_size must be from 1 to 10000")
        from rocket_trader_alpaca_activity_sse_consumer import (
            ActivitySSEConsumerError, DurableActivitySSEInbox,
        )

        inbox_path = Path(inbox_db_path).expanduser().resolve()
        if not inbox_path.is_file():
            raise PaperCashLedgerError("Activity SSE inbox database does not exist")
        try:
            inbox = DurableActivitySSEInbox(str(inbox_path), initialize=False)
            integrity = inbox.verify()
        except (ActivitySSEConsumerError, sqlite3.Error, ValueError) as exc:
            raise PaperCashLedgerError("Activity SSE inbox integrity verification failed") from exc
        if not isinstance(integrity, dict) or integrity.get("valid") is not True:
            raise PaperCashLedgerError("Activity SSE inbox integrity check failed: hash chain/cursor is invalid")

        uri = f"file:{inbox_path.as_posix()}?mode=ro"
        staged = duplicates = 0
        last_sequence = 0
        try:
            with sqlite3.connect(uri, uri=True, timeout=30) as conn:
                conn.execute("PRAGMA query_only=ON")
                while True:
                    rows = conn.execute(
                        """SELECT sequence,payload_json FROM activity_sse_events
                           WHERE sequence>? ORDER BY sequence LIMIT ?""",
                        (last_sequence, page_size),
                    ).fetchall()
                    if not rows:
                        break
                    for sequence, payload_json in rows:
                        try:
                            payload = json.loads(payload_json)
                        except (TypeError, ValueError) as exc:
                            raise PaperCashLedgerError(
                                "Verified Activity SSE payload could not be decoded"
                            ) from exc
                        result = self.ingest_activity(payload)
                        if result["status"] == "STAGED":
                            staged += 1
                        else:
                            duplicates += 1
                        last_sequence = int(sequence)
        except sqlite3.Error as exc:
            raise PaperCashLedgerError("Could not read Activity SSE inbox in read-only mode") from exc
        return {
            "status": "INBOX_INGESTED_COVERAGE_NOT_ATTESTED",
            "staged_count": staged,
            "duplicate_count": duplicates,
            "last_sequence": last_sequence,
            "activity_cursor": integrity.get("cursor"),
            "inbox_integrity_valid": True,
            "activity_coverage_complete": False,
            "orders_enabled": False,
        }

    def reconcile(
        self,
        *,
        broker_cash_usd: Any,
        broker_account_id: str,
        observed_at: Any,
        activity_coverage_complete: bool,
        activity_coverage_reference: Optional[str] = None,
        activity_coverage_checked_at: Optional[Any] = None,
        fee_reconciliation_complete: bool = False,
        fee_reconciliation_reference: Optional[str] = None,
        fee_reconciliation_checked_at: Optional[Any] = None,
        tolerance_usd: Any = "0.01",
    ) -> Dict[str, Any]:
        current_cash = _decimal(broker_cash_usd, "broker_cash_usd")
        current_time = _timestamp(observed_at, "broker cash observed_at")
        tolerance = _decimal(tolerance_usd, "tolerance_usd")
        if current_cash < 0 or tolerance < 0:
            raise PaperCashLedgerError("Broker cash and tolerance cannot be negative")
        if not isinstance(activity_coverage_complete, bool) or not isinstance(fee_reconciliation_complete, bool):
            raise PaperCashLedgerError("Reconciliation completeness flags must be booleans")
        coverage_reference = str(activity_coverage_reference or "").strip()
        coverage_checked_at = None
        fee_reference = str(fee_reconciliation_reference or "").strip()
        fee_checked_at = None
        if activity_coverage_complete:
            if not coverage_reference or activity_coverage_checked_at is None:
                raise PaperCashLedgerError(
                    "Complete activity coverage requires a traceable reference and checked_at timestamp"
                )
            coverage_checked_at = _iso(_timestamp(activity_coverage_checked_at, "activity coverage checked_at"))
        if fee_reconciliation_complete:
            if not activity_coverage_complete or not fee_reference or fee_reconciliation_checked_at is None:
                raise PaperCashLedgerError(
                    "Complete fee reconciliation requires complete activity coverage, a reference and checked_at"
                )
            fee_checked_at = _iso(_timestamp(fee_reconciliation_checked_at, "fee reconciliation checked_at"))
        if str(broker_account_id).strip() != self.account_id:
            raise PaperCashLedgerError("Broker account ID does not match cash ledger")

        with self._connect() as conn:
            anchor = conn.execute(
                "SELECT * FROM paper_cash_anchors WHERE account_id=? ORDER BY observed_at DESC LIMIT 1",
                (self.account_id,),
            ).fetchone()
            if anchor is None:
                return {
                    "status": "CASH_ANCHOR_REQUIRED",
                    "cash_reconciliation_status": "NOT_RECONCILED",
                    "fee_reconciliation_status": "UNRESOLVED",
                    "account_cash_reconciliation_complete": False,
                    "orders_enabled": False,
                }
            anchor_time = _timestamp(anchor["observed_at"], "anchor observed_at")
            if current_time < anchor_time:
                raise PaperCashLedgerError("Broker cash snapshot predates the active cash anchor")
            rows = conn.execute(
                """SELECT * FROM paper_cash_activities
                   WHERE account_id=? AND occurred_at>? AND occurred_at<=?
                   ORDER BY occurred_at,event_id""",
                (self.account_id, _iso(anchor_time), _iso(current_time)),
            ).fetchall()

        unsupported = [
            row for row in rows
            if row["cash_delta_usd"] is None
            or row["classification"] in {
                "CORRECTION_OR_BUST_REQUIRES_RESTATEMENT",
                "NON_FINAL_ACTIVITY_REQUIRES_REVIEW",
                "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW",
                "MISSING_NET_AMOUNT_REQUIRES_REVIEW",
                "TRADE_CORRECTION_OR_UNSUPPORTED_SIDE",
                "TRADE_CASH_SIGN_CONFLICT",
                "FEE_CREDIT_REQUIRES_REVIEW",
                "UNSUPPORTED_CURRENCY_OR_ACTIVITY_TYPE",
            }
        ]
        fee_rows = [row for row in rows if row["activity_type"] in {"FEE", "CFEE"}]
        pending_fees = [
            row for row in fee_rows
            if "UNALLOCATED" in row["classification"]
        ]
        expected_cash = _decimal(anchor["cash_usd"], "anchor cash_usd")
        for row in rows:
            if row["cash_delta_usd"] is not None:
                expected_cash += _decimal(row["cash_delta_usd"], "cash_delta_usd")
        difference = current_cash - expected_cash

        if unsupported:
            status = "UNSUPPORTED_ACTIVITY_REQUIRES_REVIEW"
        elif not activity_coverage_complete:
            status = "ACTIVITY_HISTORY_INCOMPLETE"
        elif abs(difference) > tolerance:
            status = "CASH_BALANCE_MISMATCH"
        else:
            status = "RECONCILED"

        # The independent fee resolver owns allocation evidence. Its explicit
        # completion flag may clear candidates that this cash mirror cannot
        # allocate by itself (e.g. volume fees without parent_id).
        fee_status = (
            "RECONCILED"
            if fee_reconciliation_complete is True and activity_coverage_complete and not unsupported
            else "UNRESOLVED"
        )
        return {
            "environment": "PAPER",
            "status": status,
            "cash_reconciliation_status": status,
            "account_cash_reconciliation_complete": status == "RECONCILED",
            "fee_reconciliation_status": fee_status,
            "fee_activity_count": len(fee_rows),
            "pending_fee_allocation_count": 0 if fee_status == "RECONCILED" else len(pending_fees),
            "fee_candidates_without_local_parent_count": len(pending_fees),
            "anchor_id": anchor["anchor_id"],
            "anchor_cash_usd": anchor["cash_usd"],
            "anchor_observed_at": anchor["observed_at"],
            "activity_count_since_anchor": len(rows),
            "unsupported_activity_count": len(unsupported),
            "expected_cash_usd": str(expected_cash),
            "broker_cash_usd": str(current_cash),
            "difference_usd": str(difference),
            "tolerance_usd": str(tolerance),
            "activity_coverage_complete": activity_coverage_complete,
            "activity_coverage_reference": coverage_reference or None,
            "activity_coverage_checked_at": coverage_checked_at,
            "fee_reconciliation_reference": fee_reference or None,
            "fee_reconciliation_checked_at": fee_checked_at,
            "orders_enabled": False,
        }
