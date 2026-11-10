#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Alpaca Paper account-activity stager.

This module never submits/cancels orders and never posts fills into the P&L
ledger. It stages broker activities durably so fee matching, corporate-action
handling, corrections and account reconciliation can be completed before any
activity is allowed to affect capital accounting.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
SUPPORTED_STAGED_TYPES = {"FILL", "CFEE", "FEE", "CSD", "CSW"}


class ActivityIngestionError(RuntimeError):
    """Fail-closed activity retrieval or staging error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(raw: Dict[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AlpacaPaperActivityStager:
    """Read-only, cursor-based, idempotent account-activity ingestion."""

    def __init__(
        self,
        *,
        db_path: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        fetch_page: Optional[Callable[[Optional[str], int], List[Dict[str, Any]]]] = None,
        page_size: int = 100,
    ) -> None:
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise ActivityIngestionError("LIVE mode is prohibited.")
        mode = os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper()
        if mode != "PAPER":
            raise ActivityIngestionError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")
        if not db_path:
            raise ActivityIngestionError("A durable activity staging database path is required.")
        if not 1 <= int(page_size) <= 100:
            raise ActivityIngestionError("page_size must be between 1 and 100.")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.page_size = int(page_size)
        self._lock = threading.RLock()
        self._fetch_page_override = fetch_page
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_SECRET_KEY")
        if fetch_page is None and (not self.api_key or not self.api_secret):
            raise ActivityIngestionError("Alpaca Paper API credentials are missing.")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS staged_activities (
                    activity_id TEXT PRIMARY KEY,
                    activity_type TEXT NOT NULL,
                    occurred_at TEXT,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    staged_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_stager_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS staged_activities_no_update
                BEFORE UPDATE ON staged_activities
                BEGIN SELECT RAISE(ABORT, 'staged activities are immutable'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS staged_activities_no_delete
                BEFORE DELETE ON staged_activities
                BEGIN SELECT RAISE(ABORT, 'staged activities are immutable'); END
            """)

    def _http_fetch_page(self, page_token: Optional[str], page_size: int) -> List[Dict[str, Any]]:
        try:
            import requests
            params: Dict[str, Any] = {"page_size": page_size, "direction": "asc"}
            if page_token:
                params["page_token"] = page_token
            response = requests.get(
                f"{PAPER_BASE_URL}/v2/account/activities?{urlencode(params)}",
                headers={
                    "APCA-API-KEY-ID": str(self.api_key),
                    "APCA-API-SECRET-KEY": str(self.api_secret),
                    "Accept": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ActivityIngestionError(
                "Could not retrieve Alpaca Paper account activities; cursor was not advanced."
            ) from exc
        if not isinstance(payload, list):
            raise ActivityIngestionError("Alpaca account activities response must be a list.")
        if any(not isinstance(item, dict) for item in payload):
            raise ActivityIngestionError("Alpaca returned a malformed activity row.")
        return payload

    def fetch_page(self, page_token: Optional[str], page_size: int) -> List[Dict[str, Any]]:
        fetcher = self._fetch_page_override or self._http_fetch_page
        rows = fetcher(page_token, page_size)
        if not isinstance(rows, list):
            raise ActivityIngestionError("Activity page must be a list.")
        return rows

    @staticmethod
    def _classify(activity: Dict[str, Any]) -> str:
        activity_type = str(activity.get("activity_type", "")).strip().upper()
        status = str(activity.get("status", "executed")).strip().lower()
        if not activity.get("id"):
            raise ActivityIngestionError("Every Alpaca activity must contain an id.")
        if status not in {"executed", "correct"}:
            return "BLOCKED_NON_FINAL_STATUS"
        if activity_type not in SUPPORTED_STAGED_TYPES:
            return "BLOCKED_UNSUPPORTED_ACTIVITY_TYPE"
        if activity_type == "FILL":
            side = str(activity.get("side", "")).strip().lower()
            if side not in {"buy", "sell"}:
                return "BLOCKED_UNSUPPORTED_FILL_SIDE"
            for key in ("qty", "price", "transaction_time", "symbol", "order_id"):
                if activity.get(key) in (None, ""):
                    return "BLOCKED_INCOMPLETE_FILL"
        if activity_type == "CFEE":
            if activity.get("qty") is None or activity.get("price") is None:
                return "BLOCKED_INCOMPLETE_CRYPTO_FEE"
        if activity_type == "FEE":
            if activity.get("net_amount") is None:
                return "BLOCKED_INCOMPLETE_FEE"
        if activity_type in {"CSD", "CSW"}:
            # Cash credits/debits are staged for capital reconciliation only.
            # Alpaca documents CSD as including returned withdrawals and CSW
            # as including returned deposits, so neither event is safe to
            # book as a new external contribution/withdrawal from type alone.
            if activity.get("net_amount") is None:
                return "BLOCKED_INCOMPLETE_CASH_ACTIVITY"
            if not activity.get("currency"):
                return "BLOCKED_CASH_ACTIVITY_WITHOUT_CURRENCY"
            if not (activity.get("date") or activity.get("created_at")):
                return "BLOCKED_CASH_ACTIVITY_WITHOUT_TIMESTAMP"
            try:
                from decimal import Decimal, InvalidOperation
                amount = Decimal(str(activity["net_amount"]))
                if not amount.is_finite() or amount == 0:
                    return "BLOCKED_INVALID_CASH_AMOUNT"
            except (InvalidOperation, TypeError, ValueError):
                return "BLOCKED_INVALID_CASH_AMOUNT"
            if activity_type == "CSD" and amount < 0:
                return "BLOCKED_INVALID_CASH_CREDIT_SIGN"
            if activity_type == "CSW" and amount > 0:
                return "BLOCKED_INVALID_CASH_DEBIT_SIGN"
            return "STAGED_PENDING_CAPITAL_RECONCILIATION"
        # Staged is not the same as ledger-ready: fee matching and activity
        # completeness are intentionally a separate acceptance gate.
        return "STAGED_PENDING_RECONCILIATION"

    def stage_page(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        inserted = 0
        duplicates = 0
        blocked = 0
        last_id: Optional[str] = None
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for activity in rows:
                    if not isinstance(activity, dict):
                        raise ActivityIngestionError("Activity row must be a JSON object.")
                    activity_id = str(activity.get("id", "")).strip()
                    if not activity_id:
                        raise ActivityIngestionError("Activity row is missing id; cursor not advanced.")
                    activity_type = str(activity.get("activity_type", "UNKNOWN")).strip().upper()
                    occurred_at = (
                        activity.get("transaction_time")
                        or activity.get("date")
                        or activity.get("created_at")
                    )
                    classification = self._classify(activity)
                    raw = _canonical(activity)
                    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                    existing = conn.execute(
                        "SELECT payload_hash FROM staged_activities WHERE activity_id=?",
                        (activity_id,),
                    ).fetchone()
                    if existing:
                        if existing["payload_hash"] != digest:
                            raise ActivityIngestionError(
                                f"Activity {activity_id} was redelivered with changed content."
                            )
                        duplicates += 1
                    else:
                        conn.execute(
                            """INSERT INTO staged_activities
                               (activity_id,activity_type,occurred_at,payload_json,
                                payload_hash,classification,staged_at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (
                                activity_id, activity_type, occurred_at, raw,
                                digest, classification, _utc_now(),
                            ),
                        )
                        inserted += 1
                    if classification.startswith("BLOCKED"):
                        blocked += 1
                    last_id = activity_id
                if last_id:
                    conn.execute(
                        """INSERT INTO activity_stager_meta(key,value) VALUES('cursor',?)
                           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                        (last_id,),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "inserted": inserted,
            "duplicates": duplicates,
            "blocked": blocked,
            "last_activity_id": last_id,
        }

    def sync(self, *, max_pages: int = 10) -> Dict[str, Any]:
        if max_pages < 1:
            raise ActivityIngestionError("max_pages must be >= 1")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM activity_stager_meta WHERE key='cursor'"
            ).fetchone()
        cursor = row["value"] if row else None
        totals = Counter()
        pages = 0
        for _ in range(max_pages):
            rows = self.fetch_page(cursor, self.page_size)
            if not rows:
                break
            result = self.stage_page(rows)
            totals.update({
                "inserted": result["inserted"],
                "duplicates": result["duplicates"],
                "blocked": result["blocked"],
            })
            cursor = result["last_activity_id"] or cursor
            pages += 1
            if len(rows) < self.page_size:
                break
        report = self.report()
        report.update({
            "pages_fetched": pages,
            "inserted_this_sync": totals["inserted"],
            "duplicates_this_sync": totals["duplicates"],
            "blocked_this_sync": totals["blocked"],
            "cursor": cursor,
        })
        return report

    def report(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT activity_type,classification,COUNT(*) AS n "
                "FROM staged_activities GROUP BY activity_type,classification"
            ).fetchall()
            cursor = conn.execute(
                "SELECT value FROM activity_stager_meta WHERE key='cursor'"
            ).fetchone()
        counts: Dict[str, int] = {}
        blocked_types: List[str] = []
        total = 0
        for row in rows:
            key = f"{row['activity_type']}:{row['classification']}"
            counts[key] = int(row["n"])
            total += int(row["n"])
            if row["classification"].startswith("BLOCKED"):
                blocked_types.append(row["activity_type"])
        return {
            "environment": "PAPER",
            "total_staged": total,
            "counts": counts,
            "blocked_activity_types": sorted(set(blocked_types)),
            "cursor": cursor["value"] if cursor else None,
            "ledger_posting_enabled": False,
            "reason": (
                "Awaiting verified fee matching, corporate-action handling, "
                "correction/bust handling and broker reconciliation. CSD/CSW "
                "cash movements are staged separately and must be reconciled "
                "before any external deposit or withdrawal is posted to capital."
            ),
        }
