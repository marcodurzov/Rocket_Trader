#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable, retryable bridge from Alpaca Paper fill updates to the MXN ledger.

This module never submits, cancels, or modifies orders. Every fill requires
an explicit fee resolver and a timestamped LedgerFX resolver; missing costs or
FX are retained in a retryable inbox instead of being silently assumed zero.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger


class PaperFillLedgerBridgeError(RuntimeError):
    """Invalid or unprocessable broker fill update."""


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    return value.value if hasattr(value, "value") else value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {str(k): _jsonable(v) for k, v in vars(value).items()}
    return str(value)


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
            raise PaperFillLedgerBridgeError("Fill update timestamp is invalid.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PaperFillLedgerBridgeError("Fill update timestamp must be timezone-aware.")
    return result


class PaperFillLedgerBridge:
    """Idempotently ingest partial/full fills with durable retry on missing inputs."""

    FILL_EVENTS = {"partial_fill", "fill"}

    def __init__(
        self,
        *,
        db_path: str,
        ledger: RealizedPnLLedger,
        fx_resolver: Callable[[datetime], LedgerFX],
        fee_resolver: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        if not db_path:
            raise PaperFillLedgerBridgeError("A durable inbox db_path is required.")
        if not callable(fx_resolver) or not callable(fee_resolver):
            raise PaperFillLedgerBridgeError("Explicit FX and fee resolvers are required.")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.fx_resolver = fx_resolver
        self.fee_resolver = fee_resolver
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_fill_ledger_inbox (
                    execution_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _ingest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_type = str(payload.get("event", "")).lower()
        if event_type not in self.FILL_EVENTS:
            return {"processed": False, "ignored": True, "reason": "not_a_fill_event"}

        execution_id = str(payload.get("execution_id") or "").strip()
        if not execution_id:
            raise PaperFillLedgerBridgeError("Fill update requires a broker execution_id.")
        order = payload.get("order") or {}
        symbol = str(payload.get("symbol") or _value(order, "symbol", "")).strip().upper()
        side = str(payload.get("side") or _value(order, "side", "")).strip().upper()
        quantity = payload.get("qty")
        price = payload.get("price")
        occurred_at = _timestamp(payload.get("timestamp"))
        if not symbol or side not in {"BUY", "SELL"}:
            raise PaperFillLedgerBridgeError("Fill update requires symbol and BUY/SELL side.")
        if quantity is None or price is None:
            raise PaperFillLedgerBridgeError("Fill update requires incremental qty and price.")
        asset_class = "CRYPTO_SPOT" if "/" in symbol else "US_EQUITY"

        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_hash,status FROM paper_fill_ledger_inbox WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    conn.execute("ROLLBACK")
                    raise PaperFillLedgerBridgeError(
                        "Broker execution_id already exists with a different fill payload."
                    )
                if row["status"] == "PROCESSED":
                    conn.execute("COMMIT")
                    return {"processed": True, "duplicate": True, "execution_id": execution_id}
            else:
                conn.execute("""
                    INSERT INTO paper_fill_ledger_inbox
                    (execution_id,payload_hash,payload_json,status,last_error,created_at,updated_at)
                    VALUES (?,?,?,'PENDING',NULL,?,?)
                """, (execution_id, digest, raw, now, now))
            conn.execute("COMMIT")

        try:
            fee = self.fee_resolver(payload)
            if (
                not isinstance(fee, dict)
                or "fee_usd" not in fee
                or "fee_asset_qty" not in fee
                or not str(fee.get("fee_source", "")).strip()
            ):
                raise PaperFillLedgerBridgeError(
                    "Fee resolver must explicitly provide fee_usd, fee_asset_qty, and fee_source."
                )
            fx = self.fx_resolver(occurred_at)
            if not isinstance(fx, LedgerFX):
                raise PaperFillLedgerBridgeError("FX resolver must return a validated LedgerFX.")
            inserted = self.ledger.record_fill(
                fill_id=f"ALPACA-FILL-{execution_id}",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price_usd=price,
                fee_usd=fee["fee_usd"],
                fee_asset_qty=fee["fee_asset_qty"],
                fee_source=fee["fee_source"],
                fx=fx,
                occurred_at=occurred_at,
                asset_class=asset_class,
            )
            with self._connect() as conn:
                conn.execute("""
                    UPDATE paper_fill_ledger_inbox
                    SET status='PROCESSED',last_error=NULL,updated_at=?
                    WHERE execution_id=?
                """, (datetime.now(timezone.utc).isoformat(), execution_id))
            return {
                "processed": True,
                "duplicate": not inserted,
                "execution_id": execution_id,
                "ledger_event_id": f"ALPACA-FILL-{execution_id}",
            }
        except Exception as exc:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE paper_fill_ledger_inbox
                    SET status='FAILED',last_error=?,updated_at=?
                    WHERE execution_id=?
                """, (str(exc), datetime.now(timezone.utc).isoformat(), execution_id))
            if isinstance(exc, PaperFillLedgerBridgeError):
                raise
            raise PaperFillLedgerBridgeError(
                f"Fill {execution_id} retained for retry: {exc}"
            ) from exc

    def process_trade_update(self, update: Any) -> Dict[str, Any]:
        payload = _jsonable(update)
        if not isinstance(payload, dict):
            raise PaperFillLedgerBridgeError("Trade update must serialize to an object.")
        with self._lock:
            return self._ingest(payload)

    def retry_pending(self) -> Dict[str, Any]:
        """Retry every non-processed inbox row; ledger fill IDs make replay safe."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT payload_json FROM paper_fill_ledger_inbox
                WHERE status != 'PROCESSED' ORDER BY created_at,execution_id
            """).fetchall()
        processed = 0
        failed = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            try:
                result = self._ingest(payload)
                processed += int(bool(result.get("processed")))
            except Exception as exc:
                failed.append({"execution_id": payload.get("execution_id"), "error": str(exc)})
        return {"attempted": len(rows), "processed": processed, "failed": failed}

    def status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT status,COUNT(*) AS count FROM paper_fill_ledger_inbox GROUP BY status
            """).fetchall()
            failures = conn.execute("""
                SELECT execution_id,last_error FROM paper_fill_ledger_inbox
                WHERE status='FAILED' ORDER BY updated_at
            """).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {
            "counts": counts,
            "pending_or_failed": counts.get("PENDING", 0) + counts.get("FAILED", 0),
            "failures": [
                {"execution_id": row["execution_id"], "error": row["last_error"]}
                for row in failures
            ],
        }
