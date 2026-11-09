#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper-only Alpaca crypto order adapter.

Crypto is deliberately isolated from equity bracket orders. This first adapter
supports simple market IOC orders only, uses USD notional for BUY entries and
owned base-asset quantity for SELL exits, and persists an idempotency journal.
It does not implement strategy triggers, stop-loss automation, or LIVE trading.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from rocket_trader_core import ExecutionMode, Side


class CryptoPaperExecutionError(RuntimeError):
    """Fail-closed crypto Paper execution or reconciliation error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CryptoPaperExecutionError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise CryptoPaperExecutionError(f"{field} must be finite")
    return result


def _value(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    if hasattr(value, "value"):
        return value.value
    return value


def _not_found(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return status == 404


def normalize_crypto_symbol(symbol: str) -> str:
    clean = str(symbol).strip().upper().replace("-", "/")
    if "/" not in clean:
        raise CryptoPaperExecutionError("Crypto symbols must use BASE/USD pair notation.")
    base, quote = clean.split("/", 1)
    if not base or quote != "USD" or "/" in base:
        raise CryptoPaperExecutionError("Only crypto spot pairs quoted in USD are supported.")
    return f"{base}/USD"


@dataclass(frozen=True)
class CryptoOrderIntent:
    client_order_id: str
    symbol: str
    side: Side
    mode: ExecutionMode = ExecutionMode.PAPER
    order_type: str = "MARKET"
    time_in_force: str = "IOC"
    notional_usd: Optional[Decimal] = None
    quantity: Optional[Decimal] = None


class AlpacaCryptoPaperExecutionAdapter:
    """PAPER-only spot adapter. IOC avoids unattended resting market orders."""

    MIN_BUY_NOTIONAL_USD = Decimal("1.00")

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        db_path: Optional[str] = None,
        client: Any = None,
    ) -> None:
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise CryptoPaperExecutionError("LIVE mode is prohibited.")
        if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
            raise CryptoPaperExecutionError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")

        self.db_path = db_path or os.getenv("ROCKET_TRADER_CRYPTO_EXECUTION_DB")
        if not self.db_path:
            raise CryptoPaperExecutionError(
                "ROCKET_TRADER_CRYPTO_EXECUTION_DB must point to durable storage."
            )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize_db()

        if client is None:
            key = api_key or os.getenv("ALPACA_API_KEY")
            secret = api_secret or os.getenv("ALPACA_SECRET_KEY")
            if not key or not secret:
                raise CryptoPaperExecutionError("Alpaca Paper API credentials are missing.")
            from alpaca.trading.client import TradingClient
            client = TradingClient(key, secret, paper=True)
        self.client = client

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crypto_paper_order_journal (
                    client_order_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    broker_order_id TEXT,
                    broker_status TEXT,
                    filled_qty TEXT,
                    filled_avg_price TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _lookup(self, client_order_id: str) -> Any:
        try:
            return self.client.get_order_by_client_id(client_order_id)
        except Exception as exc:
            if _not_found(exc):
                return None
            raise

    def _validate_asset(self, symbol: str) -> None:
        asset = self.client.get_asset(symbol)
        asset_class = str(_value(asset, "asset_class", "")).lower()
        if asset_class not in {"crypto", "cryptocurrency"}:
            raise CryptoPaperExecutionError(f"{symbol} is not classified as a crypto asset.")
        if not bool(_value(asset, "tradable", False)):
            raise CryptoPaperExecutionError(f"{symbol} is not tradable on this Paper account.")

    def _available_position_qty(self, symbol: str) -> Decimal:
        positions = self.client.get_all_positions()
        for position in positions:
            if str(_value(position, "symbol", "")).upper() == symbol:
                qty = _decimal(_value(position, "qty", "0"), "broker_position_qty")
                if qty > 0:
                    return qty
        return Decimal("0")

    @staticmethod
    def _snapshot(order: Any) -> Dict[str, Any]:
        return {
            "order_id": str(_value(order, "id", "")),
            "client_order_id": str(_value(order, "client_order_id", "")),
            "symbol": str(_value(order, "symbol", "")),
            "side": str(_value(order, "side", "")).lower(),
            "status": str(_value(order, "status", "UNKNOWN")).lower(),
            "filled_qty": str(_value(order, "filled_qty", "0") or "0"),
            "filled_avg_price": (
                None if _value(order, "filled_avg_price") is None
                else str(_value(order, "filled_avg_price"))
            ),
            "notional": (
                None if _value(order, "notional") is None
                else str(_value(order, "notional"))
            ),
        }

    def _persist(
        self,
        client_order_id: str,
        state: str,
        broker: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
    ) -> None:
        broker = broker or {}
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE crypto_paper_order_journal
                SET state=?, broker_order_id=?, broker_status=?, filled_qty=?,
                    filled_avg_price=?, last_error=?, updated_at=?
                WHERE client_order_id=?
                """,
                (
                    state, broker.get("order_id"), broker.get("status"),
                    broker.get("filled_qty"), broker.get("filled_avg_price"),
                    last_error, _utc_now(), client_order_id,
                ),
            )

    def verify_account(self) -> Dict[str, Any]:
        account = self.client.get_account()
        status = str(_value(account, "status", "UNKNOWN")).upper()
        currency = str(_value(account, "currency", "UNKNOWN")).upper()
        crypto_status = str(_value(account, "crypto_status", "UNKNOWN")).upper()
        trading_blocked = bool(_value(account, "trading_blocked", False))
        if status != "ACTIVE" or trading_blocked:
            raise CryptoPaperExecutionError("Alpaca Paper account is not active for trading.")
        if currency != "USD":
            raise CryptoPaperExecutionError("Alpaca Paper account currency must be USD.")
        if crypto_status != "ACTIVE":
            raise CryptoPaperExecutionError("Alpaca Paper crypto_status is not ACTIVE.")
        return {
            "status": status,
            "currency": currency,
            "crypto_status": crypto_status,
            "trading_blocked": trading_blocked,
            "mode": "PAPER",
        }

    def submit(self, intent: CryptoOrderIntent) -> Dict[str, Any]:
        if intent.mode != ExecutionMode.PAPER:
            raise CryptoPaperExecutionError("Only PAPER crypto orders are accepted.")
        if intent.side not in {Side.BUY, Side.SELL}:
            raise CryptoPaperExecutionError("Only long-only BUY entries and owned-quantity SELL exits are supported.")
        if intent.order_type.upper() != "MARKET":
            raise CryptoPaperExecutionError("Only MARKET crypto orders are supported in this adapter version.")
        if intent.time_in_force.upper() != "IOC":
            raise CryptoPaperExecutionError("Only IOC is enabled to prevent unattended resting crypto orders.")
        if not intent.client_order_id or len(intent.client_order_id) > 48:
            raise CryptoPaperExecutionError("client_order_id must contain 1 to 48 characters.")

        symbol = normalize_crypto_symbol(intent.symbol)
        self.verify_account()
        self._validate_asset(symbol)

        if intent.side == Side.BUY:
            if intent.quantity is not None or intent.notional_usd is None:
                raise CryptoPaperExecutionError("BUY entry must specify notional_usd only.")
            notional = _decimal(intent.notional_usd, "notional_usd")
            if notional < self.MIN_BUY_NOTIONAL_USD:
                raise CryptoPaperExecutionError("BUY notional is below the USD 1 broker minimum.")
            if notional <= 0:
                raise CryptoPaperExecutionError("BUY notional must be positive.")
            quantity = None
        else:
            if intent.notional_usd is not None or intent.quantity is None:
                raise CryptoPaperExecutionError("SELL exit must specify quantity only.")
            quantity = _decimal(intent.quantity, "quantity")
            if quantity <= 0:
                raise CryptoPaperExecutionError("SELL quantity must be positive.")
            held = self._available_position_qty(symbol)
            if quantity > held:
                raise CryptoPaperExecutionError(
                    f"SELL quantity {quantity} exceeds broker-held {symbol} quantity {held}."
                )
            notional = None

        payload = {
            "client_order_id": intent.client_order_id,
            "symbol": symbol,
            "side": intent.side.value,
            "order_type": "MARKET",
            "time_in_force": "IOC",
            "notional_usd": None if notional is None else str(notional),
            "quantity": None if quantity is None else str(quantity),
            "mode": "PAPER",
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        client_id = intent.client_order_id

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM crypto_paper_order_journal WHERE client_order_id=?",
                    (client_id,),
                ).fetchone()

            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise CryptoPaperExecutionError(
                        "client_order_id already exists with a different crypto order payload."
                    )
                existing = self._lookup(client_id)
                if existing is None:
                    raise CryptoPaperExecutionError(
                        "Journaled crypto order is absent at broker; automatic resubmission is blocked."
                    )
                broker = self._snapshot(existing)
                self._persist(client_id, broker["status"], broker)
                return {"accepted": True, "mode": "PAPER", "duplicate_prevented": True, **broker}

            existing = self._lookup(client_id)
            if existing is not None:
                broker = self._snapshot(existing)
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO crypto_paper_order_journal
                        (client_order_id, fingerprint, payload_json, state, broker_order_id,
                         broker_status, filled_qty, filled_avg_price, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            client_id, fingerprint, json.dumps(payload, sort_keys=True),
                            broker["status"], broker["order_id"], broker["status"],
                            broker["filled_qty"], broker["filled_avg_price"], _utc_now(), _utc_now(),
                        ),
                    )
                return {"accepted": True, "mode": "PAPER", "duplicate_prevented": True, **broker}

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO crypto_paper_order_journal
                    (client_order_id, fingerprint, payload_json, state, created_at, updated_at)
                    VALUES (?, ?, ?, 'PREPARED', ?, ?)
                    """,
                    (client_id, fingerprint, json.dumps(payload, sort_keys=True), _utc_now(), _utc_now()),
                )

            try:
                from alpaca.trading.enums import OrderSide, TimeInForce
                from alpaca.trading.requests import MarketOrderRequest

                request_kwargs = {
                    "symbol": symbol,
                    "side": OrderSide.BUY if intent.side == Side.BUY else OrderSide.SELL,
                    "time_in_force": TimeInForce.IOC,
                    "client_order_id": client_id,
                }
                if notional is not None:
                    request_kwargs["notional"] = str(notional)
                else:
                    request_kwargs["qty"] = str(quantity)
                request = MarketOrderRequest(**request_kwargs)
                submitted = self.client.submit_order(order_data=request)
                broker = self._snapshot(submitted)
                self._persist(client_id, broker["status"], broker)
                return {"accepted": True, "mode": "PAPER", "duplicate_prevented": False, **broker}
            except Exception as exc:
                try:
                    existing = self._lookup(client_id)
                except Exception as lookup_exc:
                    self._persist(client_id, "SUBMISSION_UNKNOWN", last_error=str(lookup_exc))
                    raise CryptoPaperExecutionError(
                        "Crypto submission outcome unknown and broker lookup failed; do not retry."
                    ) from exc
                if existing is not None:
                    broker = self._snapshot(existing)
                    self._persist(client_id, broker["status"], broker, last_error=str(exc))
                    return {"accepted": True, "mode": "PAPER", "duplicate_prevented": True, **broker}
                self._persist(client_id, "SUBMISSION_UNKNOWN", last_error=str(exc))
                raise CryptoPaperExecutionError(
                    "Crypto submission outcome unknown; automatic retry is blocked."
                ) from exc

    def reconcile(self, client_order_id: str) -> Dict[str, Any]:
        broker_order = self._lookup(client_order_id)
        if broker_order is None:
            return {"found": False, "client_order_id": client_order_id}
        broker = self._snapshot(broker_order)
        self._persist(client_order_id, broker["status"], broker)
        return {"found": True, "mode": "PAPER", **broker}

    def reconcile_positions(self) -> Dict[str, Any]:
        """Read-only broker snapshot; broker holdings remain authoritative."""
        positions = self.client.get_all_positions()
        crypto_positions = []
        for position in positions:
            symbol = str(_value(position, "symbol", ""))
            if "/" not in symbol:
                continue
            crypto_positions.append(
                {
                    "symbol": symbol,
                    "qty": str(_value(position, "qty", "0")),
                    "avg_entry_price": str(_value(position, "avg_entry_price", "")),
                    "market_value": str(_value(position, "market_value", "")),
                    "unrealized_pl": str(_value(position, "unrealized_pl", "")),
                }
            )
        return {"mode": "PAPER", "positions": crypto_positions}
