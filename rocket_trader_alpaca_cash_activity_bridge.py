#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotent Alpaca cash-deposit ingestion into Rocket Trader's MXN capital ledger.

Only broker-recorded CSD cash deposits are treated as external contributions.
They increase operating capital but are excluded from trading-earned growth.
Cash withdrawals are quarantined for explicit review; they are never silently
misclassified as strategy payouts or allowed to bypass the ledger's floor rules.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger


class AlpacaCashActivityError(RuntimeError):
    """Invalid, unsupported, or unprocessable Alpaca cash activity."""


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    return value.value if hasattr(value, "value") else value


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaCashActivityError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise AlpacaCashActivityError(f"{field} must be finite")
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise AlpacaCashActivityError("Cash activity timestamp is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise AlpacaCashActivityError("Cash activity timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


class AlpacaCashActivityBridge:
    """Track third-party deposits separately from trading-generated profit."""

    def __init__(
        self,
        *,
        db_path: str,
        ledger: RealizedPnLLedger,
        fx_resolver: Callable[[datetime], LedgerFX],
    ) -> None:
        if not db_path:
            raise AlpacaCashActivityError("A durable SQLite inbox path is required")
        if not callable(fx_resolver):
            raise AlpacaCashActivityError("A timestamped FX resolver is required")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.fx_resolver = fx_resolver
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alpaca_cash_activity_inbox (
                    activity_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alpaca_cash_activity_review (
                    activity_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _review(self, activity_id: str, payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT payload_hash FROM alpaca_cash_activity_review WHERE activity_id=?",
                (activity_id,),
            ).fetchone()
            if existing and existing["payload_hash"] != digest:
                raise AlpacaCashActivityError("Cash activity ID collision with different payload")
            conn.execute("""
                INSERT OR IGNORE INTO alpaca_cash_activity_review
                (activity_id,payload_hash,payload_json,reason,created_at)
                VALUES (?,?,?,?,?)
            """, (activity_id, digest, raw, reason, datetime.now(timezone.utc).isoformat()))
        return {"processed": False, "manual_review": True, "activity_id": activity_id, "reason": reason}

    def process_activity(self, activity: Any) -> Dict[str, Any]:
        payload = activity if isinstance(activity, dict) else {
            key: _value(activity, key) for key in (
                "id", "ref_id", "activity_type", "net_amount", "currency",
                "date", "transaction_time", "status", "description",
            ) if _value(activity, key) is not None
        }
        if not isinstance(payload, dict):
            raise AlpacaCashActivityError("Activity must be an object")
        activity_type = str(payload.get("activity_type") or "").upper()
        if activity_type not in {"CSD", "CSW"}:
            return {"processed": False, "ignored": True, "reason": "not_a_cash_deposit_or_withdrawal"}

        activity_id = str(payload.get("id") or payload.get("ref_id") or "").strip()
        if not activity_id:
            raise AlpacaCashActivityError("Cash activity requires broker activity id")
        if activity_type == "CSW":
            return self._review(
                activity_id, payload,
                "External cash withdrawal requires explicit accounting and floor review; no automatic ledger mutation.",
            )

        status = str(payload.get("status") or "executed").lower()
        if status not in {"executed", "complete", "completed"}:
            return {"processed": False, "ignored": True, "reason": f"deposit_status_{status}"}
        amount = _decimal(payload.get("net_amount"), "net_amount")
        if amount <= 0:
            raise AlpacaCashActivityError("CSD deposit net_amount must be positive")
        currency = str(payload.get("currency") or "").upper()
        occurred_at = _timestamp(payload.get("transaction_time") or payload.get("date"))

        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_hash,status FROM alpaca_cash_activity_inbox WHERE activity_id=?",
                    (activity_id,),
                ).fetchone()
                if row:
                    if row["payload_hash"] != digest:
                        raise AlpacaCashActivityError("Cash activity ID already exists with a different payload")
                    if row["status"] == "PROCESSED":
                        return {"processed": True, "duplicate": True, "activity_id": activity_id}
                else:
                    conn.execute("""
                        INSERT INTO alpaca_cash_activity_inbox
                        (activity_id,payload_hash,payload_json,status,last_error,created_at,updated_at)
                        VALUES (?,?,?,'PENDING',NULL,?,?)
                    """, (activity_id, digest, raw, now, now))
            try:
                if currency == "USD":
                    fx = self.fx_resolver(occurred_at)
                    if not isinstance(fx, LedgerFX):
                        raise AlpacaCashActivityError("USD deposit requires a validated timestamped LedgerFX")
                    amount_mxn = amount * fx.mxn_per_usd
                    fx_data = fx.as_dict()
                elif currency == "MXN":
                    amount_mxn = amount
                    fx_data = {"source": "native_MXN_activity", "mxn_per_usd": None, "observed_at": None}
                else:
                    raise AlpacaCashActivityError(f"Unsupported cash deposit currency: {currency or 'missing'}")

                event_id = f"ALPACA-CASH-DEPOSIT-{activity_id}"
                inserted = self.ledger.record_deposit(
                    event_id=event_id, amount_mxn=amount_mxn, occurred_at=occurred_at,
                )
                with self._connect() as conn:
                    conn.execute("""
                        UPDATE alpaca_cash_activity_inbox
                        SET status='PROCESSED',last_error=NULL,updated_at=?
                        WHERE activity_id=?
                    """, (datetime.now(timezone.utc).isoformat(), activity_id))
                return {
                    "processed": True, "duplicate": not inserted,
                    "activity_id": activity_id, "ledger_event_id": event_id,
                    "deposit_mxn": str(amount_mxn),
                    "fx": fx_data,
                    "counts_as_trading_profit": False,
                }
            except Exception as exc:
                with self._connect() as conn:
                    conn.execute("""
                        UPDATE alpaca_cash_activity_inbox
                        SET status='FAILED',last_error=?,updated_at=?
                        WHERE activity_id=?
                    """, (str(exc), datetime.now(timezone.utc).isoformat(), activity_id))
                if isinstance(exc, AlpacaCashActivityError):
                    raise
                raise AlpacaCashActivityError(
                    f"Deposit {activity_id} retained for retry: {exc}"
                ) from exc

    def retry_pending(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT payload_json FROM alpaca_cash_activity_inbox
                WHERE status!='PROCESSED' ORDER BY created_at,activity_id
            """).fetchall()
        processed, failed = 0, []
        for row in rows:
            payload = json.loads(row["payload_json"])
            try:
                result = self.process_activity(payload)
                processed += int(bool(result.get("processed")))
            except Exception as exc:
                failed.append({"activity_id": payload.get("id") or payload.get("ref_id"), "error": str(exc)})
        return {"attempted": len(rows), "processed": processed, "failed": failed}

    def status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            counts = {
                row["status"]: row["count"] for row in conn.execute(
                    "SELECT status,COUNT(*) AS count FROM alpaca_cash_activity_inbox GROUP BY status"
                ).fetchall()
            }
            review = conn.execute(
                "SELECT activity_id,reason FROM alpaca_cash_activity_review ORDER BY created_at"
            ).fetchall()
        return {
            "counts": counts,
            "pending_or_failed": counts.get("PENDING", 0) + counts.get("FAILED", 0) + len(review),
            "manual_review": [{"activity_id": row["activity_id"], "reason": row["reason"]} for row in review],
        }
