#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent Alpaca Paper market-data observer.

This service records minute bars for US equities and 24/7 crypto, and listens
to Paper trade-update events. It is intentionally OBSERVE_ONLY: this module
does not import TradingClient, an execution adapter, or any order-submission
method. It is a runtime foundation, not an approved trading strategy.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple


class RuntimeConfigurationError(RuntimeError):
    pass


class RuntimeStorageError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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


@dataclass(frozen=True)
class RuntimeConfig:
    api_key: str
    secret_key: str
    db_path: str
    equity_symbols: Tuple[str, ...]
    crypto_symbols: Tuple[str, ...]
    mode: str = "OBSERVE_ONLY"
    heartbeat_seconds: int = 15
    health_max_age_seconds: int = 120

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        mode = os.getenv("ROCKET_TRADER_RUNTIME_MODE", "OBSERVE_ONLY").strip().upper()
        if mode != "OBSERVE_ONLY":
            raise RuntimeConfigurationError(
                "This runtime build is OBSERVE_ONLY. Any trading mode is rejected."
            )
        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
        db_path = os.getenv("ROCKET_TRADER_RUNTIME_DB", "").strip()
        if not api_key or not secret_key:
            raise RuntimeConfigurationError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required.")
        if not db_path:
            raise RuntimeConfigurationError("ROCKET_TRADER_RUNTIME_DB must point to durable storage.")
        equity = tuple(sorted({x.strip().upper() for x in os.getenv("ROCKET_TRADER_EQUITY_SYMBOLS", "SPY,QQQ,IWM").split(",") if x.strip()}))
        crypto = tuple(sorted({x.strip().upper().replace("-", "/") for x in os.getenv("ROCKET_TRADER_CRYPTO_SYMBOLS", "BTC/USD,ETH/USD,SOL/USD").split(",") if x.strip()}))
        if not equity and not crypto:
            raise RuntimeConfigurationError("At least one equity or crypto symbol is required.")
        if any("/" in symbol for symbol in equity):
            raise RuntimeConfigurationError("Equity symbols must be plain tickers.")
        if any("/" not in symbol or symbol.split("/", 1)[1] != "USD" for symbol in crypto):
            raise RuntimeConfigurationError("Crypto symbols must be BASE/USD pairs.")
        return cls(api_key, secret_key, db_path, equity, crypto)


class MarketRuntimeRecorder:
    """SQLite/WAL store for idempotent market bars, Paper events, and heartbeats."""

    def __init__(self, db_path: str) -> None:
        if not db_path:
            raise RuntimeStorageError("A durable SQLite path is required.")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS market_bars (
                        asset_class TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                        close REAL NOT NULL, volume REAL NOT NULL,
                        trade_count REAL, vwap REAL,
                        received_at TEXT NOT NULL,
                        PRIMARY KEY(asset_class, symbol, timestamp)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS paper_trade_updates (
                        event_hash TEXT PRIMARY KEY,
                        order_id TEXT, client_order_id TEXT,
                        event_type TEXT, event_timestamp TEXT,
                        payload_json TEXT NOT NULL,
                        received_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS runtime_heartbeat (
                        component TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        last_event_at TEXT,
                        last_error TEXT,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS paper_position_reconciliation (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        status TEXT NOT NULL,
                        reconciled_at TEXT NOT NULL,
                        report_json TEXT NOT NULL
                    )
                """)
        except Exception as exc:
            raise RuntimeStorageError("Could not initialize durable runtime database.") from exc

    def record_bar(self, asset_class: str, bar: Any) -> bool:
        asset = str(asset_class).strip().upper()
        if asset not in {"EQUITY", "CRYPTO"}:
            raise RuntimeStorageError("asset_class must be EQUITY or CRYPTO.")
        symbol = str(_field(bar, "symbol", "")).strip().upper()
        timestamp = _field(bar, "timestamp")
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        timestamp = str(timestamp or "")
        if not symbol or not timestamp:
            raise RuntimeStorageError("Bar symbol and timestamp are required.")
        try:
            values = {name: float(_field(bar, name)) for name in ("open", "high", "low", "close", "volume")}
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError("non-finite OHLCV")
            if min(values[k] for k in ("open", "high", "low", "close")) <= 0 or values["volume"] < 0:
                raise ValueError("non-positive price or negative volume")
            if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]) or values["high"] < values["low"]:
                raise ValueError("structurally invalid OHLC")
            trade_count = _field(bar, "trade_count")
            vwap = _field(bar, "vwap")
            trade_count = None if trade_count is None else float(trade_count)
            vwap = None if vwap is None else float(vwap)
        except (TypeError, ValueError) as exc:
            raise RuntimeStorageError(f"Invalid OHLCV bar for {symbol}: {exc}") from exc
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO market_bars
                (asset_class,symbol,timestamp,open,high,low,close,volume,trade_count,vwap,received_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (asset, symbol, timestamp, values["open"], values["high"], values["low"],
                  values["close"], values["volume"], trade_count, vwap, _utc_now()))
            return cursor.rowcount == 1

    def record_trade_update(self, update: Any) -> bool:
        payload = _jsonable(update)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        order = _field(update, "order", {})
        order_id = _field(order, "id") or _field(update, "order_id")
        client_id = _field(order, "client_order_id") or _field(update, "client_order_id")
        event_type = _field(update, "event") or _field(update, "event_type")
        event_timestamp = _field(update, "timestamp") or _field(update, "event_timestamp")
        if hasattr(event_timestamp, "isoformat"):
            event_timestamp = event_timestamp.isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO paper_trade_updates
                (event_hash,order_id,client_order_id,event_type,event_timestamp,payload_json,received_at)
                VALUES (?,?,?,?,?,?,?)
            """, (digest, str(order_id or ""), str(client_id or ""), str(event_type or ""),
                  str(event_timestamp or ""), encoded, _utc_now()))
            return cursor.rowcount == 1

    def record_position_reconciliation(self, report: Dict[str, Any]) -> None:
        status = str(report.get("status") or "UNKNOWN").upper()
        reconciled_at = str(report.get("reconciled_at") or _utc_now())
        payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO paper_position_reconciliation(status,reconciled_at,report_json)
                   VALUES(?,?,?)""",
                (status, reconciled_at, payload),
            )

    def latest_position_reconciliation(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT report_json FROM paper_position_reconciliation
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        return json.loads(row["report_json"]) if row else None

    def heartbeat(self, component: str, status: str, last_event_at: Optional[str] = None,
                  last_error: Optional[str] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO runtime_heartbeat(component,status,last_event_at,last_error,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(component) DO UPDATE SET
                    status=excluded.status,last_event_at=excluded.last_event_at,
                    last_error=excluded.last_error,updated_at=excluded.updated_at
            """, (component, status, last_event_at, last_error, _utc_now()))

    def health(
        self,
        max_age_seconds: int = 120,
        now: Optional[datetime] = None,
        data_freshness_thresholds: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Report process heartbeat separately from market-data freshness.

        Data freshness is diagnostic only: an equity feed is naturally quiet
        outside exchange sessions, and Paper trade updates are event-driven.
        Only components explicitly assigned a threshold receive FRESH/STALE
        classification. A stale data event never masquerades as a dead process.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runtime_heartbeat ORDER BY component").fetchall()
        if not rows:
            raise RuntimeStorageError("Runtime has not emitted a heartbeat.")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise RuntimeStorageError("Health reference time must be timezone-aware.")
        thresholds = data_freshness_thresholds or {}
        components = {}
        for row in rows:
            updated = datetime.fromisoformat(row["updated_at"])
            if updated.tzinfo is None or updated.utcoffset() is None:
                raise RuntimeStorageError("Naive heartbeat timestamp; health is unknown.")
            age = (current - updated).total_seconds()
            event_age = None
            freshness = "NOT_MONITORED"
            event_at = row["last_event_at"]
            threshold = thresholds.get(row["component"])
            if event_at:
                event_time = datetime.fromisoformat(event_at)
                if event_time.tzinfo is None or event_time.utcoffset() is None:
                    raise RuntimeStorageError("Naive last-event timestamp; freshness is unknown.")
                event_age = (current - event_time).total_seconds()
                if event_age < 0:
                    freshness = "INVALID_FUTURE_TIMESTAMP"
                elif threshold is None:
                    freshness = "OBSERVED"
                else:
                    freshness = "FRESH" if event_age <= threshold else "STALE"
            elif threshold is not None:
                freshness = "NO_DATA_YET"
            components[row["component"]] = {
                "status": row["status"], "heartbeat_age_seconds": age,
                "last_event_at": event_at, "event_age_seconds": event_age,
                "data_freshness": freshness, "freshness_threshold_seconds": threshold,
                "last_error": row["last_error"],
                "healthy": row["status"] == "HEALTHY" and 0 <= age <= max_age_seconds,
            }
        return {
            "healthy": all(x["healthy"] for x in components.values()),
            "components": components,
            "data_freshness_is_diagnostic_only": True,
        }


def reconcile_paper_positions(
    reconciliation_gate: Any,
    fill_ledger_bridge: Any,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Read-only broker position check after all fills/fees are ledgered."""
    if reconciliation_gate is None or fill_ledger_bridge is None:
        raise RuntimeStorageError("Position reconciliation requires a gate and the Paper fill ledger.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeStorageError("Position reconciliation clock must be timezone-aware.")
    ledger_status = fill_ledger_bridge.status()
    pending = int(ledger_status.get("pending_or_failed", 0))
    if pending:
        return {
            "environment": "PAPER",
            "status": "BLOCKED_PENDING_LEDGER_EVENTS",
            "positions_match": False,
            "pending_fills_or_fees": pending,
            "orders_enabled": False,
        }
    try:
        from rocket_trader_currency import FXQuote
        ledger_fx = fill_ledger_bridge.fx_resolver(current)
        fx_quote = FXQuote(
            mxn_per_usd=ledger_fx.mxn_per_usd,
            observed_at=ledger_fx.observed_at,
            source=ledger_fx.source,
        )
        report = reconciliation_gate.reconcile(
            ledger_snapshot=fill_ledger_bridge.ledger.snapshot(),
            fx_quote=fx_quote,
            now=current,
        )
        report["reconciled_at"] = current.isoformat()
        report["orders_enabled"] = False
        return report
    except Exception as exc:
        return {
            "environment": "PAPER",
            "status": "RECONCILIATION_ERROR",
            "positions_match": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "orders_enabled": False,
        }


def account_activity_reconciliation_clear(
    activity_report: Dict[str, Any],
    cash_status: Optional[Dict[str, Any]],
) -> bool:
    """Fail closed on blocked activity and unresolved cash movements."""
    if activity_report.get("blocked_activity_types"):
        return False
    pending_capital = any(
        key.endswith(":STAGED_PENDING_CAPITAL_RECONCILIATION") and int(count) > 0
        for key, count in activity_report.get("counts", {}).items()
    )
    if cash_status is None:
        return not pending_capital
    return int(cash_status.get("pending_or_failed", 0)) == 0


def sync_cash_activity_review(activity_stager: Any, cash_activity_bridge: Any):
    """Mirror already-staged cash movements before reporting reconciliation health.

    This is local SQLite work only: it performs no broker/network request and
    makes no accounting classification without an explicit operator action.
    """
    if cash_activity_bridge is None:
        return None
    if activity_stager is None or not hasattr(activity_stager, "cash_movements"):
        raise RuntimeStorageError(
            "Cash activity review requires a stager exposing durable cash movements."
        )
    for activity in activity_stager.cash_movements():
        cash_activity_bridge.process_activity(activity)
    return cash_activity_bridge.status()


class AlpacaPaperObserverRuntime:
    """Starts stock, crypto and Paper trade-update streams; never submits orders."""

    def __init__(
        self,
        config: RuntimeConfig,
        recorder: MarketRuntimeRecorder,
        fill_ledger_bridge: Any = None,
        activity_stager: Any = None,
        cash_activity_bridge: Any = None,
        position_reconciliation_gate: Any = None,
        *,
        ledger_retry_interval_seconds: int = 900,
        activity_retry_interval_seconds: int = 900,
        position_reconciliation_interval_seconds: int = 60,
    ) -> None:
        if config.mode != "OBSERVE_ONLY":
            raise RuntimeConfigurationError("Only OBSERVE_ONLY is supported.")
        self.config = config
        self.recorder = recorder
        self.streams: Dict[str, Any] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.stop_event = threading.Event()
        self.last_events: Dict[str, Optional[str]] = {"equity": None, "crypto": None, "trading": None}
        self.failed_components: set[str] = set()
        self.fill_ledger_bridge = fill_ledger_bridge
        self.activity_stager = activity_stager
        self.cash_activity_bridge = cash_activity_bridge
        self.position_reconciliation_gate = position_reconciliation_gate
        self.position_reconciliation_interval_seconds = max(
            1, int(position_reconciliation_interval_seconds)
        )
        self.last_position_reconciliation_monotonic = 0.0
        self.last_position_reconciliation: Optional[Dict[str, Any]] = None
        self.ledger_retry_interval_seconds = max(1, int(ledger_retry_interval_seconds))
        self.last_ledger_retry_monotonic = 0.0
        self.activity_retry_interval_seconds = max(1, int(activity_retry_interval_seconds))
        self.last_activity_retry_monotonic = 0.0

    def _update_ledger_health(self) -> None:
        if self.fill_ledger_bridge is None:
            return
        status = self.fill_ledger_bridge.status()
        pending = int(status.get("pending_or_failed", 0))
        if pending:
            self.recorder.heartbeat(
                "ledger", "ERROR", last_error=f"{pending} fill(s) pending, failed, or requiring manual review."
            )
        else:
            self.recorder.heartbeat("ledger", "HEALTHY")

    def _reconcile_paper_positions(self) -> Optional[Dict[str, Any]]:
        if self.position_reconciliation_gate is None:
            return None
        now = datetime.now(timezone.utc)
        report = reconcile_paper_positions(
            self.position_reconciliation_gate,
            self.fill_ledger_bridge,
            now=now,
        )
        self.last_position_reconciliation = report
        self.recorder.record_position_reconciliation(report)
        if report.get("status") == "RECONCILED" and report.get("positions_match") is True:
            self.recorder.heartbeat(
                "position_reconciliation", "HEALTHY", now.isoformat()
            )
        else:
            self.recorder.heartbeat(
                "position_reconciliation", "ERROR", now.isoformat(),
                str(report.get("status") or "position reconciliation failed"),
            )
        return report

    def _sync_account_activities(self) -> Optional[Dict[str, Any]]:
        if self.activity_stager is None:
            return None
        try:
            report = self.activity_stager.sync()
            cash_status = sync_cash_activity_review(
                self.activity_stager, self.cash_activity_bridge
            )
            if cash_status is not None:
                report["cash_activity_reconciliation"] = cash_status
            if report.get("ledger_posting_enabled") is not False:
                raise RuntimeStorageError(
                    "Activity stager must remain read-only with ledger posting disabled."
                )
            blocked = report.get("blocked_activity_types", [])
            pending_capital = {
                key: count for key, count in report.get("counts", {}).items()
                if key.endswith(":STAGED_PENDING_CAPITAL_RECONCILIATION")
                and int(count) > 0
            }
            if cash_status is not None and int(cash_status.get("pending_or_failed", 0)) == 0:
                # Every staged movement has an explicit, durable resolution.
                pending_capital = {}
            if blocked or pending_capital or (
                cash_status is not None and int(cash_status.get("pending_or_failed", 0)) > 0
            ):
                reasons = []
                if blocked:
                    reasons.append(
                        "unsupported/invalid activity types: "
                        + ", ".join(sorted({str(x) for x in blocked}))
                    )
                if cash_status is not None and int(cash_status.get("pending_or_failed", 0)) > 0:
                    reasons.append(
                        "cash movements awaiting explicit resolution: "
                        + str(cash_status.get("manual_review", []))
                    )
                elif pending_capital:
                    reasons.append(
                        "unresolved cash/journal movements: "
                        + ", ".join(
                            f"{key}={count}" for key, count in sorted(pending_capital.items())
                        )
                    )
                self.recorder.heartbeat(
                    "account_activity", "ERROR",
                    last_event_at=_utc_now(),
                    last_error="Capital activity requires reconciliation; " + "; ".join(reasons),
                )
                return report
            self.recorder.heartbeat(
                "account_activity", "HEALTHY", last_event_at=_utc_now()
            )
            return report
        except Exception as exc:
            self.recorder.heartbeat(
                "account_activity", "ERROR",
                last_error=f"Read-only account activity sync failed: {exc}",
            )
            return None

    def _bar_handler(self, asset_class: str):
        async def handler(bar: Any) -> None:
            try:
                self.recorder.record_bar(asset_class, bar)
                component = "equity" if asset_class == "EQUITY" else "crypto"
                self.last_events[component] = _utc_now()
                self.recorder.heartbeat(component, "HEALTHY", self.last_events[component])
            except Exception as exc:
                self.recorder.heartbeat(asset_class.lower(), "ERROR", self.last_events.get(asset_class.lower()), str(exc))
                raise
        return handler

    async def _trade_update_handler(self, update: Any) -> None:
        self.recorder.record_trade_update(update)
        self.last_events["trading"] = _utc_now()
        self.recorder.heartbeat("trading", "HEALTHY", self.last_events["trading"])
        if self.fill_ledger_bridge is not None:
            try:
                self.fill_ledger_bridge.process_trade_update(update)
            except Exception as exc:
                self.recorder.heartbeat("ledger", "ERROR", last_error=str(exc))
            else:
                self._update_ledger_health()

    def build_streams(self) -> Dict[str, Any]:
        try:
            from alpaca.data.enums import DataFeed, CryptoFeed
            from alpaca.data.live import StockDataStream, CryptoDataStream
            from alpaca.trading.stream import TradingStream
        except Exception as exc:
            raise RuntimeConfigurationError("alpaca-py with streaming support is required.") from exc

        streams: Dict[str, Any] = {}
        if self.config.equity_symbols:
            stock = StockDataStream(
                self.config.api_key, self.config.secret_key, feed=DataFeed.IEX
            )
            stock.subscribe_bars(self._bar_handler("EQUITY"), *self.config.equity_symbols)
            streams["equity"] = stock
        if self.config.crypto_symbols:
            crypto = CryptoDataStream(
                self.config.api_key, self.config.secret_key, feed=CryptoFeed.US,
                data_timeout=180,
            )
            crypto.subscribe_bars(self._bar_handler("CRYPTO"), *self.config.crypto_symbols)
            streams["crypto"] = crypto
        trading = TradingStream(self.config.api_key, self.config.secret_key, paper=True)
        trading.subscribe_trade_updates(self._trade_update_handler)
        streams["trading"] = trading
        return streams

    def run(self) -> None:
        self.streams = self.build_streams()
        if self.fill_ledger_bridge is not None:
            self.recorder.heartbeat("ledger", "STARTING")
            self._update_ledger_health()
        if self.activity_stager is not None:
            self.recorder.heartbeat("account_activity", "STARTING")
            self._sync_account_activities()
            self.last_activity_retry_monotonic = time.monotonic()
        if self.position_reconciliation_gate is not None:
            self.recorder.heartbeat("position_reconciliation", "STARTING")
            self._reconcile_paper_positions()
            self.last_position_reconciliation_monotonic = time.monotonic()
        for component, stream in self.streams.items():
            self.recorder.heartbeat(component, "STARTING")
            thread = threading.Thread(target=stream.run, name=f"rocket-{component}-stream", daemon=True)
            self.threads[component] = thread
            thread.start()
        try:
            while not self.stop_event.wait(self.config.heartbeat_seconds):
                for component, thread in self.threads.items():
                    if not thread.is_alive():
                        self.failed_components.add(component)
                        self.recorder.heartbeat(
                            component, "ERROR", self.last_events.get(component),
                            "Stream thread exited unexpectedly.",
                        )
                        raise RuntimeError(
                            f"{component} stream exited; refusing to continue with partial market connectivity."
                        )
                    self.recorder.heartbeat(component, "HEALTHY", self.last_events.get(component))
                if self.activity_stager is not None:
                    now_monotonic = time.monotonic()
                    if (
                        now_monotonic - self.last_activity_retry_monotonic
                        >= self.activity_retry_interval_seconds
                    ):
                        self._sync_account_activities()
                        self.last_activity_retry_monotonic = now_monotonic
                if self.fill_ledger_bridge is not None:
                    status = self.fill_ledger_bridge.status()
                    counts = status.get("counts", {})
                    retryable = int(counts.get("PENDING", 0)) + int(counts.get("FAILED", 0))
                    now_monotonic = time.monotonic()
                    if retryable and (
                        now_monotonic - self.last_ledger_retry_monotonic
                        >= self.ledger_retry_interval_seconds
                    ):
                        self.fill_ledger_bridge.retry_pending()
                        self.last_ledger_retry_monotonic = now_monotonic
                    self._update_ledger_health()
                if self.position_reconciliation_gate is not None:
                    now_monotonic = time.monotonic()
                    if (
                        now_monotonic - self.last_position_reconciliation_monotonic
                        >= self.position_reconciliation_interval_seconds
                    ):
                        self._reconcile_paper_positions()
                        self.last_position_reconciliation_monotonic = now_monotonic
        finally:
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        for stream in self.streams.values():
            try:
                stream.stop()
            except Exception:
                pass
        for thread in self.threads.values():
            thread.join(timeout=5)
        for component in self.streams:
            # Preserve the causal failure state; STOPPED is only a normal shutdown state.
            if component not in self.failed_components:
                self.recorder.heartbeat(component, "STOPPED", self.last_events.get(component))


def build_fill_ledger_bridge(config: RuntimeConfig):
    enabled = os.getenv("ROCKET_TRADER_LEDGER_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        if enabled not in {"0", "false", "no", "off", ""}:
            raise RuntimeConfigurationError("ROCKET_TRADER_LEDGER_ENABLED must be boolean.")
        return None

    try:
        from rocket_trader_realized_pnl_ledger import RealizedPnLLedger
        from rocket_trader_paper_fill_ledger_bridge import PaperFillLedgerBridge
        from rocket_trader_alpaca_fee_resolver import (
            AlpacaActivityFeeResolver, AlpacaPaperActivitiesClient,
        )
        from rocket_trader_fx_provider import ExchangerateDevFXProvider
        initial_capital = os.getenv("ROCKET_TRADER_INITIAL_CAPITAL_MXN", "1000.00")
        milestone = os.getenv("ROCKET_TRADER_MILESTONE_MXN", "100000.00")
        parent = Path(config.db_path).resolve().parent
        ledger_path = os.getenv(
            "ROCKET_TRADER_LEDGER_DB", str(parent / "rocket_trader_ledger.sqlite3")
        )
        inbox_path = os.getenv(
            "ROCKET_TRADER_LEDGER_INBOX_DB", str(parent / "rocket_trader_fill_inbox.sqlite3")
        )
        ledger = RealizedPnLLedger(
            ledger_path,
            initial_capital_mxn=initial_capital,
            milestone_mxn=milestone,
        )
        fee_client = AlpacaPaperActivitiesClient(
            api_key=config.api_key, secret_key=config.secret_key
        )
        fee_resolver = AlpacaActivityFeeResolver(fee_client.list_fee_activities)
        fx_provider = ExchangerateDevFXProvider()
        return PaperFillLedgerBridge(
            db_path=inbox_path,
            ledger=ledger,
            fx_resolver=fx_provider.quote_for_fill,
            fee_resolver=fee_resolver,
        )
    except Exception as exc:
        raise RuntimeConfigurationError(
            f"Could not initialize Paper fill accounting; refusing partial startup: {exc}"
        ) from exc


def build_position_reconciliation_gate(config: RuntimeConfig, fill_ledger_bridge: Any):
    """Build a read-only TradingClient-backed position reconciliation gate."""
    if fill_ledger_bridge is None:
        return None
    try:
        from alpaca.trading.client import TradingClient
        from rocket_trader_paper_reconciliation import AlpacaPaperReconciliationGate
        client = TradingClient(
            api_key=config.api_key,
            secret_key=config.secret_key,
            paper=True,
        )
        return AlpacaPaperReconciliationGate(client)
    except Exception as exc:
        raise RuntimeConfigurationError(
            f"Could not initialize read-only Paper position reconciliation: {exc}"
        ) from exc


def build_cash_activity_bridge(config: RuntimeConfig, fill_ledger_bridge: Any, activity_stager: Any):
    """Attach explicit cash-movement review to the same durable Paper databases.

    Deposits are never auto-classified. The operator must confirm a staged CSD
    with a traceable external reference before it enters the capital ledger.
    """
    if fill_ledger_bridge is None or activity_stager is None:
        return None
    try:
        from rocket_trader_alpaca_cash_activity_bridge import AlpacaCashActivityBridge
        from rocket_trader_fx_provider import ExchangerateDevFXProvider
        fx_provider = ExchangerateDevFXProvider()
        return AlpacaCashActivityBridge(
            db_path=activity_stager.db_path,
            ledger=fill_ledger_bridge.ledger,
            fx_resolver=fx_provider.quote_for_fill,
        )
    except Exception as exc:
        raise RuntimeConfigurationError(
            f"Could not initialize Paper cash-activity reconciliation: {exc}"
        ) from exc


def build_activity_stager(config: RuntimeConfig):
    enabled = os.getenv("ROCKET_TRADER_ACTIVITY_STAGER_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        if enabled not in {"0", "false", "no", "off", ""}:
            raise RuntimeConfigurationError("ROCKET_TRADER_ACTIVITY_STAGER_ENABLED must be boolean.")
        return None
    try:
        from rocket_trader_alpaca_activity_stager import AlpacaPaperActivityStager
        parent = Path(config.db_path).resolve().parent
        path = os.getenv(
            "ROCKET_TRADER_ACTIVITY_STAGER_DB",
            str(parent / "rocket_trader_activity_stager.sqlite3"),
        )
        return AlpacaPaperActivityStager(
            db_path=path,
            api_key=config.api_key,
            api_secret=config.secret_key,
        )
    except Exception as exc:
        raise RuntimeConfigurationError(
            f"Could not initialize read-only Paper account activity stager: {exc}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Rocket Trader Paper observer runtime")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    config = RuntimeConfig.from_env()
    recorder = MarketRuntimeRecorder(config.db_path)
    fill_ledger_bridge = build_fill_ledger_bridge(config)
    activity_stager = build_activity_stager(config)
    cash_activity_bridge = build_cash_activity_bridge(
        config, fill_ledger_bridge, activity_stager
    )
    position_reconciliation_gate = build_position_reconciliation_gate(
        config, fill_ledger_bridge
    )
    if args.healthcheck:
        result = recorder.health(
            config.health_max_age_seconds,
            data_freshness_thresholds={"crypto": 600},
        )
        if activity_stager is not None:
            activity_status = activity_stager.report()
            result["account_activity"] = activity_status
            cash_status = sync_cash_activity_review(
                activity_stager, cash_activity_bridge
            )
            if cash_status is not None:
                result["cash_activity_reconciliation"] = cash_status
            result["account_activity_healthy"] = (
                result.get("components", {}).get("account_activity", {}).get("healthy", False)
                and account_activity_reconciliation_clear(activity_status, cash_status)
            )
            result["healthy"] = result["healthy"] and result["account_activity_healthy"]
        if fill_ledger_bridge is not None:
            ledger_status = fill_ledger_bridge.status()
            result["ledger_accounting"] = ledger_status
            result["ledger_accounting_healthy"] = ledger_status["pending_or_failed"] == 0
            result["healthy"] = result["healthy"] and result["ledger_accounting_healthy"]
        if position_reconciliation_gate is not None:
            latest_reconciliation = recorder.latest_position_reconciliation()
            result["position_reconciliation"] = latest_reconciliation
            position_component = result.get("components", {}).get("position_reconciliation", {})
            result["position_reconciliation_healthy"] = (
                position_component.get("healthy", False)
                and latest_reconciliation is not None
                and latest_reconciliation.get("status") == "RECONCILED"
                and latest_reconciliation.get("positions_match") is True
            )
            result["healthy"] = result["healthy"] and result["position_reconciliation_healthy"]
        print(json.dumps(result, indent=2))
        return 0 if result["healthy"] else 1
    runtime = AlpacaPaperObserverRuntime(
        config, recorder, fill_ledger_bridge, activity_stager, cash_activity_bridge,
        position_reconciliation_gate,
    )
    def request_stop(_signum, _frame):
        runtime.stop_event.set()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    runtime.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
