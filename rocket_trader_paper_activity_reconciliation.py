#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only reconciliation of legacy REST FILL activities to the durable fill inbox.

Alpaca's legacy REST FILL activity ID is `timestamp::execution_uuid`; the
Activity SSE `ref_id` is the same execution identifier. This module uses that
documented identity to detect missed or inconsistent TradingStream/Activity SSE
fill events. It never writes to the ledger or broker.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote


class PaperActivityReconciliationError(RuntimeError):
    """A source database or staged fill cannot be safely reconciled."""


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperActivityReconciliationError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise PaperActivityReconciliationError(f"{field} must be finite")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PaperActivityReconciliationError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperActivityReconciliationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("-", "/")
    if "/" not in clean and clean.endswith("USD") and len(clean) > 3:
        return clean[:-3] + "/USD"
    return clean


def _read_only(path: str) -> sqlite3.Connection:
    if not path or not Path(path).is_file():
        raise PaperActivityReconciliationError(f"Required database is missing: {path}")
    uri = "file:" + quote(str(Path(path).resolve()), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def reconcile_staged_fill_activities(
    activity_db_path: str,
    fill_inbox_db_path: str,
    *,
    timestamp_tolerance_seconds: float = 2.0,
) -> Dict[str, Any]:
    """Compare each staged REST FILL to its execution-ID inbox record.

    Every staged FILL must map to an inbox event and match quantity, price,
    symbol, side, order ID and execution timestamp. A matched fill is not
    reconciled until the fee/FX-aware ledger bridge marks it PROCESSED.
    """
    if isinstance(timestamp_tolerance_seconds, bool) or not isinstance(timestamp_tolerance_seconds, (int, float, Decimal)):
        raise ValueError("timestamp_tolerance_seconds must be a finite non-negative number")
    if not math.isfinite(float(timestamp_tolerance_seconds)) or timestamp_tolerance_seconds < 0:
        raise ValueError("timestamp_tolerance_seconds must be a finite non-negative number")
    try:
        with _read_only(activity_db_path) as activities, _read_only(fill_inbox_db_path) as inbox:
            staged = activities.execute(
                """SELECT activity_id,payload_json,classification
                   FROM staged_activities WHERE activity_type='FILL'
                   ORDER BY occurred_at,activity_id"""
            ).fetchall()
            inbox_rows = inbox.execute(
                """SELECT execution_id,payload_json,status
                   FROM paper_fill_ledger_inbox"""
            ).fetchall()
    except sqlite3.Error as exc:
        raise PaperActivityReconciliationError(
            "Could not read activity staging and fill inbox databases"
        ) from exc

    inbox_by_execution = {row["execution_id"]: row for row in inbox_rows}
    matched = 0
    processed = 0
    missing = []
    pending = []
    mismatches = []

    for activity_row in staged:
        activity_id = str(activity_row["activity_id"])
        # Alpaca legacy Account Activities: ID is timestamp::execution UUID.
        execution_id = activity_id.rsplit("::", 1)[-1]
        inbox_row = inbox_by_execution.get(execution_id)
        if inbox_row is None:
            missing.append({"activity_id": activity_id, "execution_id": execution_id})
            continue
        try:
            activity = json.loads(activity_row["payload_json"])
            payload = json.loads(inbox_row["payload_json"])
            order = payload.get("order") or {}
            expected = {
                "qty": _decimal(activity.get("qty"), "activity qty"),
                "price": _decimal(activity.get("price"), "activity price"),
                "symbol": _symbol(activity.get("symbol")),
                "side": str(activity.get("side") or "").strip().upper(),
                "order_id": str(activity.get("order_id") or "").strip(),
                "timestamp": _timestamp(activity.get("transaction_time"), "activity transaction_time"),
            }
            actual = {
                "qty": _decimal(payload.get("qty"), "inbox qty"),
                "price": _decimal(payload.get("price"), "inbox price"),
                "symbol": _symbol(payload.get("symbol") or order.get("symbol")),
                "side": str(payload.get("side") or order.get("side") or "").strip().upper(),
                "order_id": str(order.get("id") or "").strip(),
                "timestamp": _timestamp(payload.get("timestamp"), "inbox timestamp"),
            }
            differences = {}
            for key in ("qty", "price", "symbol", "side", "order_id"):
                if expected[key] != actual[key]:
                    differences[key] = {
                        "activity": str(expected[key]),
                        "inbox": str(actual[key]),
                    }
            time_delta = abs((expected["timestamp"] - actual["timestamp"]).total_seconds())
            if time_delta > timestamp_tolerance_seconds:
                differences["timestamp_delta_seconds"] = time_delta
            if differences:
                mismatches.append({
                    "activity_id": activity_id,
                    "execution_id": execution_id,
                    "differences": differences,
                })
                continue
            matched += 1
            status = str(inbox_row["status"]).upper()
            if status == "PROCESSED":
                processed += 1
            else:
                pending.append({
                    "activity_id": activity_id,
                    "execution_id": execution_id,
                    "inbox_status": status,
                })
        except (ValueError, TypeError, KeyError, PaperActivityReconciliationError) as exc:
            mismatches.append({
                "activity_id": activity_id,
                "execution_id": execution_id,
                "differences": {"invalid_or_incomplete_payload": str(exc)},
            })

    healthy = not missing and not pending and not mismatches
    return {
        "status": "RECONCILED" if healthy else "UNRESOLVED_TRADE_ACTIVITIES",
        "healthy": healthy,
        "staged_fill_activities": len(staged),
        "matched_fill_activities": matched,
        "ledger_processed_fill_activities": processed,
        "missing_inbox_fills": len(missing),
        "pending_or_failed_fills": len(pending),
        "mismatched_fill_payloads": len(mismatches),
        "missing": missing[:50],
        "pending": pending[:50],
        "mismatches": mismatches[:50],
        "ledger_posting_enabled": False,
        "orders_enabled": False,
    }
