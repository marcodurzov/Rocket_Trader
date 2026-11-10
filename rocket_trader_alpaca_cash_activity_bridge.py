#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative Alpaca cash-activity staging and explicitly confirmed deposits.

CSD/CSW can include returned transfers, and JNLC is a cash journal. Activity
type alone is not sufficient evidence of a new external contribution. All cash
movements are quarantined until an operator explicitly confirms a CSD as a new
external deposit with a traceable confirmation reference.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
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
        if len(raw) == 10:
            try:
                # Alpaca cash activity dates may be date-only. Normalize to UTC
                # midnight as a date key; the FX resolver must use a daily rate
                # for that date, not pretend this is an intraday execution time.
                result = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise AlpacaCashActivityError("Cash activity date is invalid") from exc
        else:
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
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    resolution_reference TEXT,
                    resolved_at TEXT
                )
            """)
            review_columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(alpaca_cash_activity_review)"
                ).fetchall()
            }
            if "status" not in review_columns:
                conn.execute(
                    "ALTER TABLE alpaca_cash_activity_review "
                    "ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'"
                )
            if "resolution_reference" not in review_columns:
                conn.execute(
                    "ALTER TABLE alpaca_cash_activity_review ADD COLUMN resolution_reference TEXT"
                )
            if "resolved_at" not in review_columns:
                conn.execute(
                    "ALTER TABLE alpaca_cash_activity_review ADD COLUMN resolved_at TEXT"
                )

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
                "SELECT payload_hash,status FROM alpaca_cash_activity_review WHERE activity_id=?",
                (activity_id,),
            ).fetchone()
            if existing and existing["payload_hash"] != digest:
                raise AlpacaCashActivityError("Cash activity ID collision with different payload")
            if existing and existing["status"] == "RESOLVED_EXTERNAL_DEPOSIT":
                return {
                    "processed": True, "duplicate": True, "activity_id": activity_id,
                    "reason": "already_confirmed_external_deposit",
                }
            conn.execute("""
                INSERT OR IGNORE INTO alpaca_cash_activity_review
                (activity_id,payload_hash,payload_json,reason,created_at,status)
                VALUES (?,?,?,?,?,'PENDING')
            """, (activity_id, digest, raw, reason, datetime.now(timezone.utc).isoformat()))
        return {"processed": False, "manual_review": True, "activity_id": activity_id, "reason": reason}

    def process_activity(self, activity: Any) -> Dict[str, Any]:
        payload = activity if isinstance(activity, dict) else {
            key: _value(activity, key) for key in (
                "id", "ref_id", "activity_type", "activity_sub_type",
                "net_amount", "currency", "date", "transaction_time",
                "created_at", "status", "description",
            ) if _value(activity, key) is not None
        }
        if not isinstance(payload, dict):
            raise AlpacaCashActivityError("Activity must be an object")
        activity_type = str(payload.get("activity_type") or "").upper()
        if activity_type not in {"CSD", "CSW", "JNLC"}:
            return {"processed": False, "ignored": True, "reason": "not_a_supported_cash_movement"}

        activity_id = str(payload.get("id") or payload.get("ref_id") or "").strip()
        if not activity_id:
            raise AlpacaCashActivityError("Cash activity requires broker activity id")
        reasons = {
            "CSD": (
                "CSD may be a new cash deposit or a returned withdrawal. "
                "Activity type alone cannot prove an external contribution."
            ),
            "CSW": (
                "CSW may be a withdrawal or a returned deposit. "
                "Explicit accounting review is required."
            ),
            "JNLC": (
                "JNLC is a cash journal and may represent an internal journal "
                "or the Paper simulator seed; it is not automatically user funding."
            ),
        }
        return self._review(activity_id, payload, reasons[activity_type])

    def confirm_external_deposit(
        self,
        activity_id: str,
        *,
        confirmation_reference: str,
    ) -> Dict[str, Any]:
        """Post a CSD only after explicit external-deposit confirmation."""
        activity_id = str(activity_id or "").strip()
        reference = str(confirmation_reference or "").strip()
        if not activity_id:
            raise AlpacaCashActivityError("broker activity id is required")
        if not reference:
            raise AlpacaCashActivityError(
                "A traceable confirmation_reference is required to classify CSD as a new deposit"
            )
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json,status,resolution_reference FROM alpaca_cash_activity_review WHERE activity_id=?",
                    (activity_id,),
                ).fetchone()
            if row is None:
                raise AlpacaCashActivityError("Cash activity must be staged for review before confirmation")
            if row["status"] == "RESOLVED_EXTERNAL_DEPOSIT":
                return {
                    "processed": True, "duplicate": True, "activity_id": activity_id,
                    "confirmation_reference": row["resolution_reference"],
                    "counts_as_trading_profit": False,
                }
            if row["status"] != "PENDING":
                raise AlpacaCashActivityError("Cash activity is not in a confirmable review state")
            payload = json.loads(row["payload_json"])
            if str(payload.get("activity_type") or "").upper() != "CSD":
                raise AlpacaCashActivityError("Only CSD cash credits can be confirmed as external deposits")
            description = str(payload.get("description") or "").lower()
            return_markers = (
                "return", "returned", "reversal", "reversed", "rejected",
                "failed", "chargeback",
            )
            if any(marker in description for marker in return_markers):
                raise AlpacaCashActivityError(
                    "Activity description indicates a return/reversal; it cannot be confirmed as a new deposit"
                )
            status = str(payload.get("status") or "executed").lower()
            if status not in {"executed", "complete", "completed"}:
                raise AlpacaCashActivityError(f"CSD activity is not final: {status}")
            amount = _decimal(payload.get("net_amount"), "net_amount")
            if amount <= 0:
                raise AlpacaCashActivityError("CSD net_amount must be positive")
            currency = str(payload.get("currency") or "").upper()
            occurred_at = _timestamp(
                payload.get("transaction_time") or payload.get("created_at") or payload.get("date")
            )
            if currency == "USD":
                fx = self.fx_resolver(occurred_at)
                if not isinstance(fx, LedgerFX):
                    raise AlpacaCashActivityError(
                        "USD deposit requires a validated timestamped LedgerFX"
                    )
                fx_time = fx.observed_at.astimezone(timezone.utc)
                fx_age = occurred_at - fx_time
                if fx_age < timedelta(0) or fx_age > timedelta(hours=24):
                    raise AlpacaCashActivityError(
                        "USD deposit FX must be at or before the activity and no more than 24 hours old"
                    )
                amount_mxn = amount * fx.mxn_per_usd
                fx_data = fx.as_dict()
            elif currency == "MXN":
                amount_mxn = amount
                fx_data = {
                    "source": "native_MXN_activity",
                    "mxn_per_usd": None,
                    "observed_at": None,
                }
            else:
                raise AlpacaCashActivityError(
                    f"Unsupported cash deposit currency: {currency or 'missing'}"
                )

            event_id = f"ALPACA-CASH-DEPOSIT-{activity_id}"
            inserted = self.ledger.record_deposit(
                event_id=event_id, amount_mxn=amount_mxn, occurred_at=occurred_at,
            )
            resolved_at = datetime.now(timezone.utc).isoformat()
            with self._connect() as conn:
                conn.execute("""
                    UPDATE alpaca_cash_activity_review
                    SET status='RESOLVED_EXTERNAL_DEPOSIT',
                        resolution_reference=?,resolved_at=?,reason=?
                    WHERE activity_id=?
                """, (
                    reference, resolved_at,
                    "Explicitly confirmed as a new external deposit; excluded from trading profit.",
                    activity_id,
                ))
            return {
                "processed": True, "duplicate": not inserted,
                "activity_id": activity_id, "ledger_event_id": event_id,
                "deposit_mxn": str(amount_mxn), "fx": fx_data,
                "confirmation_reference": reference,
                "counts_as_trading_profit": False,
            }

    def confirm_external_withdrawal(
        self,
        activity_id: str,
        *,
        confirmation_reference: str,
    ) -> Dict[str, Any]:
        """Post a CSW only after explicit confirmation of an external withdrawal."""
        activity_id = str(activity_id or "").strip()
        reference = str(confirmation_reference or "").strip()
        if not activity_id or not reference:
            raise AlpacaCashActivityError("activity_id and traceable confirmation_reference are required")
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json,status,resolution_reference FROM alpaca_cash_activity_review WHERE activity_id=?",
                    (activity_id,),
                ).fetchone()
            if row is None:
                raise AlpacaCashActivityError("Cash activity must be staged for review before confirmation")
            if row["status"] == "RESOLVED_EXTERNAL_WITHDRAWAL":
                return {
                    "processed": True, "duplicate": True, "activity_id": activity_id,
                    "confirmation_reference": row["resolution_reference"],
                    "counts_as_trading_profit": False,
                }
            if row["status"] != "PENDING":
                raise AlpacaCashActivityError("Cash activity is not in a confirmable review state")
            payload = json.loads(row["payload_json"])
            if str(payload.get("activity_type") or "").upper() != "CSW":
                raise AlpacaCashActivityError("Only CSW cash debits can be confirmed as external withdrawals")
            status = str(payload.get("status") or "executed").lower()
            if status not in {"executed", "complete", "completed"}:
                raise AlpacaCashActivityError(f"CSW activity is not final: {status}")
            amount = _decimal(payload.get("net_amount"), "net_amount")
            if amount >= 0:
                raise AlpacaCashActivityError("CSW net_amount must be negative")
            currency = str(payload.get("currency") or "").upper()
            occurred_at = _timestamp(
                payload.get("transaction_time") or payload.get("created_at") or payload.get("date")
            )
            if currency == "USD":
                fx = self.fx_resolver(occurred_at)
                if not isinstance(fx, LedgerFX):
                    raise AlpacaCashActivityError("USD withdrawal requires a validated timestamped LedgerFX")
                fx_time = fx.observed_at.astimezone(timezone.utc)
                fx_age = occurred_at - fx_time
                if fx_age < timedelta(0) or fx_age > timedelta(hours=24):
                    raise AlpacaCashActivityError(
                        "USD withdrawal FX must be at or before the activity and no more than 24 hours old"
                    )
                amount_mxn = abs(amount) * fx.mxn_per_usd
                fx_data = fx.as_dict()
            elif currency == "MXN":
                amount_mxn = abs(amount)
                fx_data = {"source": "native_MXN_activity", "mxn_per_usd": None, "observed_at": None}
            else:
                raise AlpacaCashActivityError(f"Unsupported cash withdrawal currency: {currency or 'missing'}")
            event_id = f"ALPACA-CASH-WITHDRAWAL-{activity_id}"
            inserted = self.ledger.record_withdrawal(
                event_id=event_id, amount_mxn=amount_mxn, occurred_at=occurred_at,
            )
            with self._connect() as conn:
                conn.execute("""
                    UPDATE alpaca_cash_activity_review
                    SET status='RESOLVED_EXTERNAL_WITHDRAWAL',
                        resolution_reference=?,resolved_at=?,reason=?
                    WHERE activity_id=?
                """, (
                    reference, datetime.now(timezone.utc).isoformat(),
                    "Explicitly confirmed as an external withdrawal; excluded from trading profit.",
                    activity_id,
                ))
            return {
                "processed": True, "duplicate": not inserted,
                "activity_id": activity_id, "ledger_event_id": event_id,
                "withdrawal_mxn": str(amount_mxn), "fx": fx_data,
                "confirmation_reference": reference,
                "counts_as_trading_profit": False,
            }

    def resolve_journal_as_non_user_capital(
        self,
        activity_id: str,
        *,
        resolution_reference: str,
        rationale: str,
    ) -> Dict[str, Any]:
        """Resolve a JNLC only when evidence shows it is not user funding."""
        activity_id = str(activity_id or "").strip()
        reference = str(resolution_reference or "").strip()
        explanation = str(rationale or "").strip()
        if not activity_id or not reference or not explanation:
            raise AlpacaCashActivityError(
                "activity_id, traceable resolution_reference, and rationale are required"
            )
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json,status,resolution_reference FROM alpaca_cash_activity_review WHERE activity_id=?",
                (activity_id,),
            ).fetchone()
            if row is None:
                raise AlpacaCashActivityError("Cash activity must be staged for review before resolution")
            if row["status"] == "RESOLVED_NON_USER_CAPITAL":
                return {
                    "processed": True, "duplicate": True, "activity_id": activity_id,
                    "resolution_reference": row["resolution_reference"],
                    "ledger_effect": "NONE",
                }
            if row["status"] != "PENDING":
                raise AlpacaCashActivityError("Cash activity is not in a resolvable review state")
            payload = json.loads(row["payload_json"])
            if str(payload.get("activity_type") or "").upper() != "JNLC":
                raise AlpacaCashActivityError("Only JNLC journals can use non-user-capital resolution")
            conn.execute("""
                UPDATE alpaca_cash_activity_review
                SET status='RESOLVED_NON_USER_CAPITAL',
                    resolution_reference=?,resolved_at=?,reason=?
                WHERE activity_id=?
            """, (
                reference, datetime.now(timezone.utc).isoformat(),
                explanation, activity_id,
            ))
        return {
            "processed": True, "duplicate": False, "activity_id": activity_id,
            "resolution_reference": reference, "ledger_effect": "NONE",
        }

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
                "SELECT activity_id,reason,status FROM alpaca_cash_activity_review "
                "WHERE status='PENDING' ORDER BY created_at"
            ).fetchall()
        return {
            "counts": counts,
            "pending_or_failed": counts.get("PENDING", 0) + counts.get("FAILED", 0) + len(review),
            "manual_review": [
                {"activity_id": row["activity_id"], "reason": row["reason"], "status": row["status"]}
                for row in review
            ],
        }
