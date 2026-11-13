#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only realized-P&L ledger for Rocket Trader.

All strategy capital and realized P&L reporting are MXN. Alpaca fills and fees
are USD. Every fill requires a sourced, timezone-aware MXN-per-USD FX quote.
The ledger is accounting infrastructure, not an order router.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_FLOOR
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = 1
PNL_ACCOUNTING_METHOD = "FIFO_MXN_ENTRY_AND_EXIT_FX_V2"
PNL_ACCOUNTING_METHOD_KEY = "realized_pnl_accounting_method"
DEFAULT_MILESTONE_MXN = Decimal("100000.00")


class LedgerError(RuntimeError):
    """Invalid ledger operation or inconsistent accounting state."""


def _d(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LedgerError(f"{name} must be a valid decimal") from exc
    if not result.is_finite():
        raise LedgerError(f"{name} must be finite")
    return result


def _money(value: Decimal) -> Decimal:
    """Round non-negative monetary allocations down to cents."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _pnl_money(value: Decimal) -> Decimal:
    """Conservative cent rounding: profits down, losses away from zero."""
    mode = ROUND_FLOOR if value < 0 else ROUND_DOWN
    return value.quantize(Decimal("0.01"), rounding=mode)


def _utc(value: Optional[datetime] = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerError("Timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class LedgerFX:
    mxn_per_usd: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        rate = _d(self.mxn_per_usd, "mxn_per_usd")
        if rate <= 0:
            raise LedgerError("mxn_per_usd must be > 0")
        if not self.source or not self.source.strip():
            raise LedgerError("FX source is required")
        _utc(self.observed_at)
        object.__setattr__(self, "mxn_per_usd", rate)

    def as_dict(self) -> Dict[str, str]:
        return {
            "mxn_per_usd": str(self.mxn_per_usd),
            "observed_at": _utc(self.observed_at),
            "source": self.source.strip(),
        }


@dataclass(frozen=True)
class LedgerSnapshot:
    initial_capital_mxn: Decimal
    deposits_mxn: Decimal
    withdrawals_mxn: Decimal
    realized_net_pnl_mxn: Decimal
    operating_capital_mxn: Decimal
    earned_growth_capital_mxn: Decimal
    open_positions: Dict[str, Dict[str, str]]
    milestone_reached: bool
    milestone_reached_at: Optional[str]
    event_count: int
    accounting_method: str


class RealizedPnLLedger:
    """SQLite append-only event journal with deterministic FIFO replay."""

    def __init__(
        self,
        db_path: str,
        *,
        initial_capital_mxn: Any = "1000.00",
        milestone_mxn: Any = "100000.00",
    ) -> None:
        if not db_path:
            raise LedgerError("A durable SQLite db_path is required")
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initial_capital_mxn = _money(_d(initial_capital_mxn, "initial_capital_mxn"))
        self.milestone_mxn = _money(_d(milestone_mxn, "milestone_mxn"))
        if self.initial_capital_mxn <= 0 or self.milestone_mxn <= 0:
            raise LedgerError("Initial capital and milestone must be positive")
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS ledger_events_no_update
                BEFORE UPDATE ON ledger_events
                BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS ledger_events_no_delete
                BEFORE DELETE ON ledger_events
                BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_closes (
                    period TEXT PRIMARY KEY,
                    close_json TEXT NOT NULL,
                    close_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS monthly_closes_no_update
                BEFORE UPDATE ON monthly_closes
                BEGIN SELECT RAISE(ABORT, 'monthly closes are immutable'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS monthly_closes_no_delete
                BEFORE DELETE ON monthly_closes
                BEGIN SELECT RAISE(ABORT, 'monthly closes are immutable'); END
            """)
            existing = conn.execute(
                "SELECT value FROM ledger_meta WHERE key='schema_version'"
            ).fetchone()
            if existing and int(existing["value"]) != SCHEMA_VERSION:
                raise LedgerError("Unsupported ledger schema version")
            conn.execute(
                "INSERT OR IGNORE INTO ledger_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO ledger_meta(key,value) VALUES('initial_capital_mxn',?)",
                (str(self.initial_capital_mxn),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO ledger_meta(key,value) VALUES('milestone_mxn',?)",
                (str(self.milestone_mxn),),
            )
            stored_initial = Decimal(conn.execute(
                "SELECT value FROM ledger_meta WHERE key='initial_capital_mxn'"
            ).fetchone()["value"])
            stored_milestone = Decimal(conn.execute(
                "SELECT value FROM ledger_meta WHERE key='milestone_mxn'"
            ).fetchone()["value"])
            if stored_initial != self.initial_capital_mxn or stored_milestone != self.milestone_mxn:
                raise LedgerError("Ledger configuration differs from persisted capital policy")
            method_row = conn.execute(
                "SELECT value FROM ledger_meta WHERE key=?", (PNL_ACCOUNTING_METHOD_KEY,)
            ).fetchone()
            if method_row and method_row["value"] != PNL_ACCOUNTING_METHOD:
                raise LedgerError("Unsupported realized-P&L accounting method")
            if not method_row:
                has_fills = conn.execute(
                    "SELECT 1 FROM ledger_events WHERE event_type='FILL' LIMIT 1"
                ).fetchone()
                has_closes = conn.execute(
                    "SELECT 1 FROM monthly_closes LIMIT 1"
                ).fetchone()
                if has_fills or has_closes:
                    raise LedgerError(
                        "Legacy ledger requires explicit FX-aware accounting migration before use"
                    )
                conn.execute(
                    "INSERT INTO ledger_meta(key,value) VALUES(?,?)",
                    (PNL_ACCOUNTING_METHOD_KEY, PNL_ACCOUNTING_METHOD),
                )
            if not conn.execute("SELECT 1 FROM ledger_events LIMIT 1").fetchone():
                self._append_conn(
                    conn,
                    event_id="SYSTEM-INITIAL-CAPITAL",
                    event_type="INITIAL_CAPITAL",
                    occurred_at="1970-01-01T00:00:00+00:00",
                    payload={"amount_mxn": str(self.initial_capital_mxn), "currency": "MXN"},
                )

    @classmethod
    def migrate_legacy_accounting_method(
        cls,
        db_path: str,
        *,
        backup_path: str,
        confirm: bool = False,
        no_writers_confirmed: bool = False,
    ) -> Dict[str, Any]:
        """Explicitly migrate legacy MXN P&L semantics after a verified backup.

        Migration is blocked if immutable monthly closes already exist. Stop all
        writers first; the caller must explicitly confirm that condition.
        """
        if confirm is not True or no_writers_confirmed is not True:
            raise LedgerError("Migration requires explicit confirmation and stopped writers")
        source_path = Path(db_path).expanduser()
        backup_file = Path(backup_path).expanduser()
        if not source_path.is_file():
            raise LedgerError("Existing ledger database is missing")
        if backup_file.exists():
            raise LedgerError("Backup path already exists; refusing to overwrite it")
        if source_path.resolve() == backup_file.resolve():
            raise LedgerError("Backup path must differ from the source ledger")
        if not backup_file.parent.is_dir():
            raise LedgerError("Backup directory must already exist")

        source = sqlite3.connect(str(source_path), timeout=30)
        source.row_factory = sqlite3.Row
        try:
            tables = {r["name"] for r in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            required_tables = {"ledger_meta", "ledger_events", "monthly_closes"}
            if not required_tables.issubset(tables):
                raise LedgerError("Ledger schema is incomplete; migration refused")
            triggers = {r["name"] for r in source.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()}
            required_triggers = {
                "ledger_events_no_update", "ledger_events_no_delete",
                "monthly_closes_no_update", "monthly_closes_no_delete",
            }
            if not required_triggers.issubset(triggers):
                raise LedgerError("Append-only ledger triggers are missing; migration refused")
            meta = dict(source.execute("SELECT key,value FROM ledger_meta").fetchall())
            if meta.get("schema_version") != str(SCHEMA_VERSION):
                raise LedgerError("Unsupported ledger schema version")
            if PNL_ACCOUNTING_METHOD_KEY in meta:
                if meta[PNL_ACCOUNTING_METHOD_KEY] == PNL_ACCOUNTING_METHOD:
                    return {"status": "ALREADY_CURRENT", "accounting_method": PNL_ACCOUNTING_METHOD}
                raise LedgerError("Ledger has an unknown accounting method")
            if "initial_capital_mxn" not in meta or "milestone_mxn" not in meta:
                raise LedgerError("Persisted capital policy metadata is incomplete")
            if source.execute("SELECT 1 FROM monthly_closes LIMIT 1").fetchone():
                raise LedgerError(
                    "Legacy immutable monthly closes exist; automatic accounting migration is prohibited"
                )
            events = source.execute(
                "SELECT event_id,event_type,occurred_at,payload_json,payload_hash FROM ledger_events ORDER BY seq"
            ).fetchall()
            source_max_seq = source.execute("SELECT MAX(seq) FROM ledger_events").fetchone()[0]
            if not any(
                row["event_id"] == "SYSTEM-INITIAL-CAPITAL" and row["event_type"] == "INITIAL_CAPITAL"
                for row in events
            ):
                raise LedgerError("Initial-capital event is missing")
            fill_count = 0
            for row in events:
                payload = json.loads(row["payload_json"])
                canonical = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != row["payload_hash"]:
                    raise LedgerError("Ledger event hash mismatch; migration refused")
                if row["event_type"] != "FILL":
                    continue
                fill_count += 1
                fx = payload.get("fx")
                if not isinstance(fx, dict):
                    raise LedgerError("A legacy fill has no persisted FX quote")
                rate = _d(fx.get("mxn_per_usd"), "fill FX rate")
                if rate <= 0 or not str(fx.get("source") or "").strip():
                    raise LedgerError("A legacy fill has invalid FX metadata")
                try:
                    fill_time = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
                    fx_time = datetime.fromisoformat(str(fx.get("observed_at", "")).replace("Z", "+00:00"))
                except ValueError as exc:
                    raise LedgerError("A legacy fill has invalid FX timestamps") from exc
                if (
                    fill_time.tzinfo is None or fill_time.utcoffset() is None
                    or fx_time.tzinfo is None or fx_time.utcoffset() is None
                ):
                    raise LedgerError("A legacy fill has timezone-naive FX timestamps")
                age = fill_time.astimezone(timezone.utc) - fx_time.astimezone(timezone.utc)
                if age < timedelta(0) or age > timedelta(hours=24):
                    raise LedgerError("A legacy fill has stale or future FX evidence")

            # Create a consistent SQLite backup before changing the source.
            target = sqlite3.connect(str(backup_file), timeout=30)
            try:
                source.backup(target)
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                backup_event_count = target.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
                backup_max_seq = target.execute("SELECT MAX(seq) FROM ledger_events").fetchone()[0]
                if (
                    integrity != "ok"
                    or backup_event_count != len(events)
                    or backup_max_seq != source_max_seq
                ):
                    raise LedgerError("SQLite backup integrity or event-count verification failed")
            finally:
                target.close()
        finally:
            source.close()

        backup_digest = hashlib.sha256(backup_file.read_bytes()).hexdigest()
        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(str(source_path), timeout=30, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            current_method = conn.execute(
                "SELECT value FROM ledger_meta WHERE key=?", (PNL_ACCOUNTING_METHOD_KEY,)
            ).fetchone()
            if current_method:
                raise LedgerError("Ledger accounting method changed during migration")
            if conn.execute("SELECT 1 FROM monthly_closes LIMIT 1").fetchone():
                raise LedgerError("A monthly close appeared during migration; migration refused")
            current_event_count = conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
            current_max_seq = conn.execute("SELECT MAX(seq) FROM ledger_events").fetchone()[0]
            if current_event_count != len(events) or current_max_seq != source_max_seq:
                raise LedgerError("Ledger changed after backup; migration refused")
            conn.execute(
                "INSERT INTO ledger_meta(key,value) VALUES(?,?)",
                (PNL_ACCOUNTING_METHOD_KEY, PNL_ACCOUNTING_METHOD),
            )
            cls._append_conn(
                conn,
                event_id="MIGRATION-FX-AWARE-FIFO-V2",
                event_type="ACCOUNTING_METHOD_MIGRATION",
                occurred_at=_utc(now),
                payload={
                    "from_method": "LEGACY_USD_PNL_CONVERTED_AT_EXIT_FX",
                    "to_method": PNL_ACCOUNTING_METHOD,
                    "backup_sha256": backup_digest,
                    "legacy_fill_count": fill_count,
                    "legacy_event_count": len(events),
                    "monthly_closes_present": False,
                },
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return {
            "status": "MIGRATED",
            "accounting_method": PNL_ACCOUNTING_METHOD,
            "legacy_fill_count": fill_count,
            "backup_path": str(backup_file),
            "backup_sha256": backup_digest,
        }

    @staticmethod
    def _append_conn(
        conn: sqlite3.Connection,
        *,
        event_id: str,
        event_type: str,
        occurred_at: str,
        payload: Dict[str, Any],
    ) -> bool:
        if not event_id or len(event_id) > 128:
            raise LedgerError("event_id must contain 1 to 128 characters")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = conn.execute(
            "SELECT event_type,payload_hash FROM ledger_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row:
            if row["event_type"] != event_type or row["payload_hash"] != digest:
                raise LedgerError("event_id already exists with a different event payload")
            return False
        conn.execute(
            """INSERT INTO ledger_events
               (event_id,event_type,occurred_at,payload_json,payload_hash,created_at)
               VALUES (?,?,?,?,?,?)""",
            (event_id, event_type, occurred_at, raw, digest, _utc()),
        )
        return True

    def _append(self, event_id: str, event_type: str, occurred_at: datetime, payload: Dict[str, Any]) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                inserted = self._append_conn(
                    conn, event_id=event_id, event_type=event_type,
                    occurred_at=_utc(occurred_at), payload=payload,
                )
                conn.execute("COMMIT")
                return inserted
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def record_deposit(self, *, event_id: str, amount_mxn: Any, occurred_at: datetime) -> bool:
        amount = _money(_d(amount_mxn, "amount_mxn"))
        if amount <= 0:
            raise LedgerError("Deposit must be positive")
        return self._append(event_id, "DEPOSIT_MXN", occurred_at, {
            "amount_mxn": str(amount), "currency": "MXN"
        })

    def record_withdrawal(self, *, event_id: str, amount_mxn: Any, occurred_at: datetime) -> bool:
        amount = _money(_d(amount_mxn, "amount_mxn"))
        if amount <= 0:
            raise LedgerError("Withdrawal must be positive")
        payload = {"amount_mxn": str(amount), "currency": "MXN"}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        # Check the immutable event identity before capital guards. A retry
        # after a crash between ledger append and upstream acknowledgement must
        # be idempotent even if the original withdrawal reduced available cash.
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT event_type,payload_hash FROM ledger_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        if existing:
            if existing["event_type"] != "WITHDRAWAL_MXN" or existing["payload_hash"] != digest:
                raise LedgerError("event_id already exists with a different event payload")
            return False
        with self._lock:
            snap = self.snapshot()
            if amount > snap.operating_capital_mxn:
                raise LedgerError("Withdrawal exceeds operating capital")
            if snap.milestone_reached:
                available_above_floor = max(
                    Decimal("0"), snap.operating_capital_mxn - self.milestone_mxn
                )
                if amount > available_above_floor:
                    raise LedgerError(
                        "Withdrawal would breach the protected MXN 100,000 operating-capital floor"
                    )
            return self._append(event_id, "WITHDRAWAL_MXN", occurred_at, payload)

    def record_fill(
        self,
        *,
        fill_id: str,
        symbol: str,
        side: str,
        quantity: Any,
        price_usd: Any,
        fee_usd: Any,
        fx: LedgerFX,
        fee_asset_qty: Any = "0",
        fee_source: str = "UNSPECIFIED_LEGACY_CALLER",
        occurred_at: datetime,
        asset_class: str,
    ) -> bool:
        symbol = str(symbol).strip().upper()
        side = str(side).strip().upper()
        asset_class = str(asset_class).strip().upper()
        qty = _d(quantity, "quantity")
        price = _d(price_usd, "price_usd")
        fee = _d(fee_usd, "fee_usd")
        fee_asset = _d(fee_asset_qty, "fee_asset_qty")
        fee_source = str(fee_source).strip()
        if not fee_source:
            raise LedgerError("fee_source is required")
        if not symbol or side not in {"BUY", "SELL"}:
            raise LedgerError("Fill requires a symbol and BUY/SELL side")
        if asset_class not in {"US_EQUITY", "CRYPTO_SPOT"}:
            raise LedgerError("Only US_EQUITY and CRYPTO_SPOT are supported")
        if qty <= 0 or price <= 0 or fee < 0:
            raise LedgerError("Fill quantity/price must be positive and fee non-negative")
        if fee_asset > 0:
            raise LedgerError("fee_asset_qty must be zero or negative (asset withheld)")
        if side == "SELL" and fee_asset != 0:
            raise LedgerError("For USD-quoted spot SELLs, fee_asset_qty must be zero")
        if side == "BUY" and qty + fee_asset <= 0:
            raise LedgerError("Crypto asset fee consumes the entire acquired quantity")
        fill_time = _utc(occurred_at)
        fx_time = _utc(fx.observed_at)
        fill_dt = datetime.fromisoformat(fill_time)
        fx_dt = datetime.fromisoformat(fx_time)
        fx_age = fill_dt - fx_dt
        if fx_age < timedelta(0):
            raise LedgerError("FX quote timestamp cannot be after the fill")
        if fx_age > timedelta(hours=24):
            raise LedgerError("FX quote is stale for the fill timestamp")
        payload = {
            "fill_id": fill_id,
            "symbol": symbol,
            "side": side,
            "quantity": str(qty),
            "price_usd": str(price),
            "gross_usd": str(qty * price),
            "fee_usd": str(fee),
            "fee_asset_qty": str(fee_asset),
            "fee_source": fee_source,
            "net_acquired_quantity": str(qty + fee_asset if side == "BUY" else qty),
            "asset_class": asset_class,
            "fx": fx.as_dict(),
            "currency": "USD",
        }
        occurred_iso = fill_time
        # Idempotent replay must be checked before inventory validation: the
        # original SELL may already have consumed the position.
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT event_type,payload_hash FROM ledger_events WHERE event_id=?",
                (fill_id,),
            ).fetchone()
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if existing:
            if existing["event_type"] != "FILL" or existing["payload_hash"] != digest:
                raise LedgerError("event_id already exists with a different event payload")
            return False
        if side == "SELL":
            held = Decimal("0")
            for event in self._events():
                if event["occurred_at"] > occurred_iso:
                    break
                p = event["payload"]
                if event["event_type"] != "FILL" or p["symbol"] != symbol:
                    continue
                delta = (
                    Decimal(p.get("net_acquired_quantity", p["quantity"]))
                    if p["side"] == "BUY" else Decimal(p["quantity"])
                )
                held += delta if p["side"] == "BUY" else -delta
            if qty > held:
                raise LedgerError(
                    f"SELL fill {fill_id} exceeds FIFO inventory for {symbol}"
                )
        return self._append(fill_id, "FILL", occurred_at, payload)

    def record_strategy_equity_mark(
        self,
        *,
        equity_mxn: Any,
        occurred_at: Optional[datetime] = None,
        source: str,
        position_snapshot_hash: str,
    ) -> Dict[str, str]:
        """Persist a marked-to-market MXN strategy equity observation.

        The first valid mark on a UTC day is the daily baseline. It is refused
        if same-day FILL events already exist, because that would omit earlier
        intraday P&L. Later marks calculate daily P&L from that immutable base.
        """
        current = occurred_at or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise LedgerError("Strategy equity mark timestamp must be timezone-aware")
        equity = _money(_d(equity_mxn, "strategy_equity_mxn"))
        if equity <= 0:
            raise LedgerError("Strategy equity mark must be positive")
        source = str(source or "").strip()
        snapshot_hash = str(position_snapshot_hash or "").strip()
        if not source or not snapshot_hash:
            raise LedgerError("Strategy equity mark requires source and position snapshot hash")
        current_utc = current.astimezone(timezone.utc)
        daily_key = current_utc.date().isoformat()
        occurred_text = _utc(current_utc)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                mark_rows = conn.execute(
                    "SELECT event_id,occurred_at,payload_json,payload_hash "
                    "FROM ledger_events WHERE event_type='STRATEGY_EQUITY_MARK' ORDER BY seq"
                ).fetchall()
                marks = []
                for row in mark_rows:
                    payload = json.loads(row["payload_json"])
                    canonical = json.dumps(
                        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    )
                    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != row["payload_hash"]:
                        raise LedgerError("Strategy equity mark event hash mismatch")
                    if payload.get("daily_key") != daily_key:
                        continue
                    mark_time = datetime.fromisoformat(
                        str(payload.get("observed_at", row["occurred_at"])).replace("Z", "+00:00")
                    )
                    if mark_time.tzinfo is None or mark_time.utcoffset() is None:
                        raise LedgerError("Persisted strategy equity mark has a naive timestamp")
                    marks.append((mark_time.astimezone(timezone.utc), payload))

                baseline = next(
                    ((mark_time, payload) for mark_time, payload in marks
                     if payload.get("mark_type") == "DAY_START"),
                    None,
                )
                if baseline is None:
                    fill_rows = conn.execute(
                        "SELECT occurred_at FROM ledger_events WHERE event_type='FILL'"
                    ).fetchall()
                    for fill_row in fill_rows:
                        fill_time = datetime.fromisoformat(
                            str(fill_row["occurred_at"]).replace("Z", "+00:00")
                        )
                        if fill_time.tzinfo is None or fill_time.utcoffset() is None:
                            raise LedgerError("Persisted fill has a naive timestamp")
                        fill_utc = fill_time.astimezone(timezone.utc)
                        if fill_utc.date().isoformat() == daily_key and fill_utc <= current_utc:
                            raise LedgerError(
                                "Cannot establish daily strategy baseline after same-day fills"
                            )
                    mark_type = "DAY_START"
                    baseline_equity = equity
                    baseline_time = current_utc
                else:
                    baseline_time, baseline_payload = baseline
                    if any(
                        fill_time.date().isoformat() == daily_key and fill_time < baseline_time
                        for fill_time in (
                            datetime.fromisoformat(
                                str(row["occurred_at"]).replace("Z", "+00:00")
                            ).astimezone(timezone.utc)
                            for row in conn.execute(
                                "SELECT occurred_at FROM ledger_events WHERE event_type='FILL'"
                            ).fetchall()
                        )
                    ):
                        raise LedgerError(
                            "Same-day fills precede the persisted strategy daily baseline"
                        )
                    if marks:
                        latest_time, latest_payload = marks[-1]
                        if current_utc < latest_time:
                            raise LedgerError("Strategy equity marks cannot be appended out of order")
                        if current_utc == latest_time:
                            if (
                                _d(latest_payload.get("equity_mxn"), "persisted strategy equity")
                                != equity
                                or latest_payload.get("position_snapshot_hash") != snapshot_hash
                            ):
                                raise LedgerError(
                                    "Conflicting strategy equity marks share the same timestamp"
                                )
                    mark_type = "INTRADAY"
                    baseline_equity = _money(
                        _d(baseline_payload.get("equity_mxn"), "daily baseline equity")
                    )

                payload = {
                    "daily_key": daily_key,
                    "mark_type": mark_type,
                    "equity_mxn": str(equity),
                    "source": source,
                    "observed_at": occurred_text,
                    "position_snapshot_hash": snapshot_hash,
                    "baseline_policy": "FIRST_VALID_POSITION_RECONCILIATION_MARK_UTC_DAY",
                }
                canonical = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                event_id = "STRATEGY-EQUITY-MARK-" + hashlib.sha256(
                    canonical.encode("utf-8")
                ).hexdigest()[:24]
                self._append_conn(
                    conn,
                    event_id=event_id,
                    event_type="STRATEGY_EQUITY_MARK",
                    occurred_at=current_utc,
                    payload=payload,
                )
                conn.execute("COMMIT")
                daily_pnl_pct = (equity - baseline_equity) / baseline_equity
                return {
                    "strategy_equity_mxn": str(equity),
                    "strategy_daily_baseline_mxn": str(baseline_equity),
                    "strategy_daily_baseline_at": _utc(baseline_time),
                    "strategy_daily_pnl_pct": str(daily_pnl_pct),
                    "strategy_daily_key": daily_key,
                    "strategy_risk_metrics_status": "AVAILABLE",
                    "strategy_daily_baseline_policy": "FIRST_VALID_POSITION_RECONCILIATION_MARK_UTC_DAY",
                }
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def _events(self) -> list[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq,event_id,event_type,occurred_at,payload_json FROM ledger_events ORDER BY occurred_at,seq"
            ).fetchall()
        return [{
            "seq": row["seq"], "event_id": row["event_id"],
            "event_type": row["event_type"], "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
        } for row in rows]

    def _replay(self) -> Dict[str, Any]:
        initial = Decimal("0")
        deposits = Decimal("0")
        withdrawals = Decimal("0")
        realized_mxn = Decimal("0")
        lots: Dict[str, list[Dict[str, Decimal]]] = {}
        realized_rows: list[Dict[str, Any]] = []
        milestone_at: Optional[str] = None
        threshold_seen = False
        for event in self._events():
            typ, p = event["event_type"], event["payload"]
            if typ == "INITIAL_CAPITAL":
                initial += Decimal(p["amount_mxn"])
            elif typ == "DEPOSIT_MXN":
                deposits += Decimal(p["amount_mxn"])
            elif typ == "WITHDRAWAL_MXN":
                withdrawals += Decimal(p["amount_mxn"])
            elif typ == "FILL":
                symbol = p["symbol"]
                qty = Decimal(p["quantity"])
                gross = Decimal(p["gross_usd"])
                fee = Decimal(p["fee_usd"])
                rate = Decimal(p["fx"]["mxn_per_usd"])
                if p["side"] == "BUY":
                    net_qty = Decimal(p.get("net_acquired_quantity", p["quantity"]))
                    if net_qty <= 0:
                        raise LedgerError(f"Invalid net acquired quantity in fill {event['event_id']}")
                    entry_fx = Decimal(p["fx"]["mxn_per_usd"])
                    lots.setdefault(symbol, []).append({
                        "qty": net_qty,
                        "unit_cost_usd": (gross + fee) / net_qty,
                        "unit_cost_mxn": (gross + fee) * entry_fx / net_qty,
                    })
                else:
                    remaining = qty
                    cost_basis = Decimal("0")
                    cost_basis_mxn = Decimal("0")
                    position_lots = lots.setdefault(symbol, [])
                    while remaining > 0 and position_lots:
                        lot = position_lots[0]
                        consumed = min(remaining, lot["qty"])
                        cost_basis += consumed * lot["unit_cost_usd"]
                        cost_basis_mxn += consumed * lot["unit_cost_mxn"]
                        lot["qty"] -= consumed
                        remaining -= consumed
                        if lot["qty"] == 0:
                            position_lots.pop(0)
                    if remaining > 0:
                        raise LedgerError(
                            f"SELL fill {event['event_id']} exceeds FIFO inventory for {symbol}"
                        )
                    net_proceeds = gross - fee
                    net_proceeds_mxn = net_proceeds * rate
                    pnl_usd = net_proceeds - cost_basis
                    pnl_mxn = net_proceeds_mxn - cost_basis_mxn
                    realized_mxn += pnl_mxn
                    realized_rows.append({
                        "event_id": event["event_id"],
                        "occurred_at": event["occurred_at"],
                        "symbol": symbol,
                        "quantity": str(qty),
                        "gross_proceeds_usd": str(gross),
                        "exit_fee_usd": str(fee),
                        "net_proceeds_mxn": str(net_proceeds_mxn),
                        "fifo_cost_basis_usd": str(cost_basis),
                        "fifo_cost_basis_mxn": str(cost_basis_mxn),
                        "realized_net_pnl_usd": str(pnl_usd),
                        "entry_and_exit_fx_applied": True,
                        "fx_mxn_per_usd": str(rate),
                        "realized_net_pnl_mxn": str(pnl_mxn),
                    })
            # The 100k growth milestone must be earned through net trading
            # performance from the original seed, not inflated by later deposits.
            growth_capital = initial + realized_mxn
            if not threshold_seen and growth_capital >= self.milestone_mxn:
                threshold_seen = True
                milestone_at = event["occurred_at"]
        open_positions: Dict[str, Dict[str, str]] = {}
        for symbol, position_lots in lots.items():
            qty = sum((lot["qty"] for lot in position_lots), Decimal("0"))
            cost = sum((lot["qty"] * lot["unit_cost_usd"] for lot in position_lots), Decimal("0"))
            if qty > 0:
                open_positions[symbol] = {
                    "quantity": str(qty),
                    "fifo_cost_basis_usd": str(cost),
                    "fifo_cost_basis_mxn": str(sum(
                        (lot["qty"] * lot["unit_cost_mxn"] for lot in position_lots),
                        Decimal("0"),
                    )),
                }
        return {
            "initial": initial, "deposits": deposits, "withdrawals": withdrawals,
            "realized_mxn": realized_mxn,
            "operating_capital": initial + deposits - withdrawals + realized_mxn,
            "open_positions": open_positions,
            "realized_rows": realized_rows,
            "milestone_reached": threshold_seen,
            "milestone_reached_at": milestone_at,
            "event_count": len(self._events()),
        }

    def snapshot(self) -> LedgerSnapshot:
        state = self._replay()
        return LedgerSnapshot(
            initial_capital_mxn=_money(state["initial"]),
            deposits_mxn=_money(state["deposits"]),
            withdrawals_mxn=_money(state["withdrawals"]),
            realized_net_pnl_mxn=_pnl_money(state["realized_mxn"]),
            operating_capital_mxn=_pnl_money(state["operating_capital"]),
            earned_growth_capital_mxn=_pnl_money(
                state["initial"] + state["realized_mxn"]
            ),
            open_positions=state["open_positions"],
            milestone_reached=state["milestone_reached"],
            milestone_reached_at=state["milestone_reached_at"],
            event_count=state["event_count"],
            accounting_method=PNL_ACCOUNTING_METHOD,
        )

    def monthly_summary(self, period: str) -> Dict[str, Any]:
        if len(period) != 7 or period[4] != "-":
            raise LedgerError("period must use YYYY-MM format")
        rows = [r for r in self._replay()["realized_rows"] if r["occurred_at"][:7] == period]
        total = sum((Decimal(r["realized_net_pnl_mxn"]) for r in rows), Decimal("0"))
        return {
            "period": period,
            "accounting_method": PNL_ACCOUNTING_METHOD,
            "realized_trade_count": len(rows),
            "realized_net_pnl_mxn": str(_pnl_money(total)),
            "trades": rows,
        }

    def close_month(self, period: str) -> Dict[str, Any]:
        """Create an immutable proposed payout close; never transfers money."""
        summary = self.monthly_summary(period)
        state = self._replay()
        capital = _pnl_money(state["operating_capital"])
        threshold_reached = state["milestone_reached"] or capital >= self.milestone_mxn
        if summary["realized_trade_count"] == 0:
            reserve_pct, reinvest_pct, personal_pct = Decimal("0"), Decimal("1"), Decimal("0")
            reserve = personal = Decimal("0")
            reinvest = Decimal("0")
            policy = "NO_REALIZED_PROFIT"
            suspended = False
        elif not threshold_reached:
            reserve_pct, reinvest_pct, personal_pct = Decimal("0"), Decimal("1"), Decimal("0")
            reserve = personal = Decimal("0")
            reinvest = max(Decimal("0"), Decimal(summary["realized_net_pnl_mxn"]))
            policy = (
                "ACCUMULATION_100_PERCENT_REINVESTMENT"
                if reinvest > 0 else "ACCUMULATION_NO_POSITIVE_REALIZED_PROFIT"
            )
            suspended = False
        else:
            profit = max(Decimal("0"), Decimal(summary["realized_net_pnl_mxn"]))
            reserve_pct, reinvest_pct, personal_pct = Decimal("0.10"), Decimal("0.50"), Decimal("0.40")
            reserve = _money(profit * reserve_pct)
            personal = _money(profit * personal_pct)
            reinvest = profit - reserve - personal
            suspended = capital - reserve - personal < self.milestone_mxn
            if suspended:
                reserve_pct, reinvest_pct, personal_pct = Decimal("0"), Decimal("1"), Decimal("0")
                reserve = personal = Decimal("0")
                reinvest = profit
            policy = (
                "POST_MILESTONE_FLOOR_HOLD_100_PERCENT_REINVESTMENT"
                if suspended else "POST_MILESTONE_50_10_40"
            )
        close = {
            **summary,
            "accounting_method": PNL_ACCOUNTING_METHOD,
            "operating_capital_mxn": str(capital),
            "earned_growth_capital_mxn": str(
                _pnl_money(state["initial"] + state["realized_mxn"])
            ),
            "milestone_mxn": str(self.milestone_mxn),
            "milestone_reached": bool(threshold_reached),
            "policy": policy,
            "target_allocation_pct": {
                "reinvestment": "1.00" if not threshold_reached else "0.50",
                "reserve": "0.00" if not threshold_reached else "0.10",
                "personal": "0.00" if not threshold_reached else "0.40",
            },
            "actual_allocation_pct": {
                "reinvestment": str(reinvest_pct),
                "reserve": str(reserve_pct),
                "personal": str(personal_pct),
            },
            "reinvestment_mxn": str(_money(reinvest)),
            "reserve_mxn": str(_money(reserve)),
            "personal_distribution_mxn": str(_money(personal)),
            "payouts_suspended": suspended,
            "automatic_transfer": False,
        }
        raw = json.dumps(close, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO monthly_closes(period,close_json,close_hash,created_at) VALUES(?,?,?,?)",
                (period, raw, digest, _utc()),
            )
            row = conn.execute(
                "SELECT close_json,close_hash FROM monthly_closes WHERE period=?", (period,)
            ).fetchone()
            if row["close_hash"] != digest:
                raise LedgerError("This month already has a different immutable close")
            return json.loads(row["close_json"])

    def verify_integrity(self) -> Dict[str, Any]:
        events = self._events()
        valid = True
        for event in events:
            payload_raw = json.dumps(
                event["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            # Hash check against persisted source of truth.
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_hash FROM ledger_events WHERE event_id=?",
                    (event["event_id"],),
                ).fetchone()
            if hashlib.sha256(payload_raw.encode("utf-8")).hexdigest() != row["payload_hash"]:
                valid = False
                break
        return {
            "ok": valid,
            "event_count": len(events),
            "snapshot": asdict(self.snapshot()) if valid else None,
        }
