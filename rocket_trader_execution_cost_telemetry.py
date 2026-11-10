#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Paper fill-versus-quote execution cost telemetry."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Deque, Dict, List, Optional, Tuple


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


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


def _timestamp(value: Any) -> Optional[datetime]:
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite.")
    return result


def _percentile90(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.90 * len(ordered)) - 1)
    return ordered[index]


class ExecutionCostTelemetry:
    """Captures a bounded in-memory quote window and persists only fill snapshots.

    Quotes are never used if they occur after the fill. Stale/missing quote
    observations are retained but excluded from empirical cost aggregates.
    """

    MAX_QUOTES_PER_SYMBOL = 5000
    MAX_QUOTE_AGE_SECONDS = {"EQUITY": 5.0, "CRYPTO": 10.0}

    def __init__(self, db_path: str) -> None:
        if not db_path:
            raise ValueError("A durable runtime database path is required.")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._quotes: Dict[str, Deque[Dict[str, Any]]] = {}
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS paper_fill_cost_observations (
                event_hash TEXT PRIMARY KEY,
                order_id TEXT NOT NULL, client_order_id TEXT NOT NULL,
                event_type TEXT NOT NULL, asset_class TEXT NOT NULL,
                symbol TEXT NOT NULL, side TEXT NOT NULL,
                fill_qty REAL, fill_price REAL, price_source TEXT NOT NULL,
                fill_timestamp TEXT, quote_timestamp TEXT, quote_feed TEXT,
                quote_age_seconds REAL, bid_price REAL, ask_price REAL,
                bid_size REAL, ask_size REAL, mid_price REAL,
                spread_bps REAL, slippage_bps REAL,
                status TEXT NOT NULL, eligible_for_aggregation INTEGER NOT NULL,
                reason TEXT NOT NULL, received_at TEXT NOT NULL
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_fill_cost_symbol_time
                ON paper_fill_cost_observations(symbol,fill_timestamp)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_fill_cost_order
                ON paper_fill_cost_observations(order_id,event_type)""")
            db.execute("""CREATE TABLE IF NOT EXISTS paper_quote_telemetry_errors (
                error_id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_class TEXT NOT NULL, error TEXT NOT NULL,
                observed_at TEXT NOT NULL
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def record_quote(self, asset_class: str, quote: Any, feed: str) -> bool:
        asset = str(asset_class).strip().upper()
        if asset not in {"EQUITY", "CRYPTO"}:
            raise ValueError("asset_class must be EQUITY or CRYPTO.")
        symbol = str(_field(quote, "symbol", "")).strip().upper()
        timestamp = _timestamp(_field(quote, "timestamp"))
        if not symbol or timestamp is None:
            raise ValueError("Quote symbol and timezone-aware timestamp are required.")
        bid = _number(_field(quote, "bid_price"), "bid_price")
        ask = _number(_field(quote, "ask_price"), "ask_price")
        bid_size = _number(_field(quote, "bid_size", 0), "bid_size")
        ask_size = _number(_field(quote, "ask_size", 0), "ask_size")
        if bid <= 0 or ask < bid or bid_size < 0 or ask_size < 0:
            raise ValueError("Quote must have positive, non-crossed prices and non-negative sizes.")
        record = {
            "asset_class": asset, "symbol": symbol, "timestamp": timestamp,
            "bid_price": bid, "ask_price": ask, "bid_size": bid_size,
            "ask_size": ask_size, "feed": str(feed or "UNKNOWN").upper(),
        }
        with self._lock:
            queue = self._quotes.setdefault(
                symbol, deque(maxlen=self.MAX_QUOTES_PER_SYMBOL)
            )
            queue.append(record)
        return True

    def record_quote_error(self, asset_class: str, error: str) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO paper_quote_telemetry_errors
                (asset_class,error,observed_at) VALUES(?,?,?)""",
                (str(asset_class).upper(), str(error)[:500],
                 datetime.now(timezone.utc).isoformat()))

    def _select_quote(self, symbol: str, fill_time: Optional[datetime]
                      ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if fill_time is None:
            return None, "MISSING_FILL_TIMESTAMP"
        with self._lock:
            quotes = list(self._quotes.get(symbol, ()))
        if not quotes:
            return None, "NO_PRIOR_QUOTE"
        prior = [quote for quote in quotes if quote["timestamp"] <= fill_time]
        if not prior:
            return None, "FUTURE_QUOTE_ONLY"
        quote = max(prior, key=lambda item: item["timestamp"])
        age = (fill_time - quote["timestamp"]).total_seconds()
        max_age = self.MAX_QUOTE_AGE_SECONDS[quote["asset_class"]]
        if age < 0 or age > max_age:
            return quote, "STALE_QUOTE"
        return quote, None

    def record_fill_update(self, update: Any) -> Optional[Dict[str, Any]]:
        event_type = str(_value(
            _field(update, "event") or _field(update, "event_type") or ""
        )).strip().lower()
        if event_type not in {"fill", "partial_fill"}:
            return None
        order = _field(update, "order", {}) or {}
        symbol = str(_field(update, "symbol") or _field(order, "symbol") or "").strip().upper()
        side = str(_value(_field(update, "side") or _field(order, "side") or "")).upper()
        order_id = str(_field(order, "id") or _field(update, "order_id") or "")
        client_id = str(_field(order, "client_order_id") or _field(update, "client_order_id") or "")
        fill_time_raw = _field(update, "timestamp") or _field(order, "filled_at")
        fill_time = _timestamp(fill_time_raw)
        fill_timestamp = fill_time.isoformat() if fill_time else None
        asset_class = "CRYPTO" if "/" in symbol else "EQUITY"
        raw_price = _field(update, "price")
        raw_qty = _field(update, "qty")
        price_source = "EXECUTION"
        if raw_price is None or raw_qty is None:
            if event_type == "fill":
                raw_price = _field(order, "filled_avg_price") if raw_price is None else raw_price
                raw_qty = _field(order, "filled_qty") if raw_qty is None else raw_qty
                price_source = "ORDER_AVERAGE"
            else:
                price_source = "PARTIAL_FILL_PRICE_UNAVAILABLE"
        try:
            fill_price = _number(raw_price, "fill_price") if raw_price is not None else None
            fill_qty = _number(raw_qty, "fill_qty") if raw_qty is not None else None
            if fill_price is not None and fill_price <= 0:
                raise ValueError("fill_price must be positive.")
            if fill_qty is not None and fill_qty <= 0:
                raise ValueError("fill_qty must be positive.")
        except ValueError as exc:
            fill_price, fill_qty = None, None
            price_source = "INVALID_FILL_DATA"
            invalid_reason = str(exc)
        else:
            invalid_reason = ""
        payload = json.dumps(_jsonable(update), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False)
        event_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        quote, quote_error = self._select_quote(symbol, fill_time)
        status = quote_error or "MEASURED"
        reason = invalid_reason
        if not symbol or side not in {"BUY", "SELL"} or fill_price is None or fill_qty is None:
            status = "INVALID_FILL_DATA"
            reason = reason or "Fill symbol, side, price and quantity are required."
        if quote_error and not reason:
            reason = quote_error
        bid = ask = bid_size = ask_size = mid = spread = slippage = age = None
        quote_time = quote_feed = None
        if quote is not None:
            quote_time = quote["timestamp"].isoformat()
            quote_feed = quote["feed"]
            bid, ask = quote["bid_price"], quote["ask_price"]
            bid_size, ask_size = quote["bid_size"], quote["ask_size"]
            age = (fill_time - quote["timestamp"]).total_seconds() if fill_time else None
            mid = (bid + ask) / 2.0
            spread = (ask - bid) / mid * 10000.0
            if status == "MEASURED" and fill_price is not None and mid > 0:
                direction = 1.0 if side == "BUY" else -1.0
                slippage = direction * (fill_price - mid) / mid * 10000.0

        eligible = status == "MEASURED" and fill_price is not None and fill_qty is not None
        if price_source == "ORDER_AVERAGE" and event_type == "fill" and order_id:
            with self._connect() as db:
                prior_partial = db.execute("""SELECT 1 FROM paper_fill_cost_observations
                    WHERE order_id=? AND event_type='partial_fill' LIMIT 1""",
                    (order_id,)).fetchone()
            if prior_partial:
                eligible = False
                status = "CUMULATIVE_AVERAGE_AFTER_PARTIALS"
                reason = "Final order average overlaps prior partial-fill events; excluded from aggregation."
        with self._lock, self._connect() as db:
            db.execute("""INSERT OR IGNORE INTO paper_fill_cost_observations (
                event_hash,order_id,client_order_id,event_type,asset_class,symbol,side,
                fill_qty,fill_price,price_source,fill_timestamp,quote_timestamp,quote_feed,
                quote_age_seconds,bid_price,ask_price,bid_size,ask_size,mid_price,
                spread_bps,slippage_bps,status,eligible_for_aggregation,reason,received_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_hash, order_id, client_id, event_type, asset_class, symbol, side,
             fill_qty, fill_price, price_source, fill_timestamp, quote_time, quote_feed,
             age, bid, ask, bid_size, ask_size, mid, spread, slippage, status,
             int(eligible), reason, datetime.now(timezone.utc).isoformat()))
        return {
            "event_hash": event_hash, "status": status,
            "eligible_for_aggregation": eligible, "spread_bps": spread,
            "slippage_bps": slippage, "quote_age_seconds": age,
            "price_source": price_source, "reason": reason,
        }

    def summary(self) -> Dict[str, Any]:
        with self._connect() as db:
            rows = db.execute("""SELECT asset_class,symbol,side,spread_bps,slippage_bps,
                status,eligible_for_aggregation FROM paper_fill_cost_observations
                ORDER BY received_at""").fetchall()
        total = len(rows)
        eligible_rows = [row for row in rows if row["eligible_for_aggregation"] and row["status"] == "MEASURED"]
        groups: Dict[Tuple[str, str, str], List[sqlite3.Row]] = {}
        for row in eligible_rows:
            groups.setdefault((row["asset_class"], row["symbol"], row["side"]), []).append(row)
        results = []
        for (asset_class, symbol, side), values in sorted(groups.items()):
            spreads = [float(row["spread_bps"]) for row in values if row["spread_bps"] is not None]
            slippage = [float(row["slippage_bps"]) for row in values if row["slippage_bps"] is not None]
            adverse = [max(0.0, value) for value in slippage]
            results.append({
                "asset_class": asset_class, "symbol": symbol, "side": side,
                "measured_fills": len(values),
                "median_spread_bps": median(spreads) if spreads else None,
                "p90_spread_bps": _percentile90(spreads),
                "median_slippage_bps": median(slippage) if slippage else None,
                "p90_adverse_slippage_bps": _percentile90(adverse),
            })
        measured = len(eligible_rows)
        with self._connect() as db:
            quote_errors = db.execute(
                "SELECT COUNT(*) FROM paper_quote_telemetry_errors"
            ).fetchone()[0]
            last_quote_error = db.execute("""SELECT asset_class,error,observed_at
                FROM paper_quote_telemetry_errors ORDER BY error_id DESC LIMIT 1"""
            ).fetchone()
        return {
            "status": "DESCRIPTIVE_ONLY_NOT_VALIDATED",
            "quote_ingestion_errors": int(quote_errors),
            "last_quote_error": dict(last_quote_error) if last_quote_error else None,
            "fill_events_total": total, "measured_fill_events": measured,
            "unmeasured_fill_events": total - measured,
            "unmeasured_rate": (total - measured) / total if total else None,
            "groups": results,
            "costs_empirically_validated": False,
            "strategy_promotion_enabled": False,
            "orders_enabled": False,
            "limitations": [
                "Quotes are feed-specific: equities use IEX, not SIP/NBBO.",
                "A quote is eligible only when its timestamp is at or before the fill and within the freshness limit.",
                "Paper fills do not guarantee live-market execution quality.",
                "This report excludes exchange/regulatory fees; use the separate fee ledger for actual charges.",
                "A descriptive sample does not automatically approve estimated transaction costs.",
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Paper execution cost telemetry.")
    parser.add_argument("--db-path", default="/app/data/runtime.sqlite3")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    telemetry = ExecutionCostTelemetry(args.db_path)
    if args.summary:
        print(json.dumps(telemetry.summary(), indent=2, sort_keys=True))
        return 0
    parser.error("Specify --summary.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
