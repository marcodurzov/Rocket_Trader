#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper-only Alpaca execution adapter with durable idempotency.

This module is deliberately equity-only. Crypto execution has a separate state
machine and must not be routed through equity bracket-order assumptions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from rocket_trader_core import ExecutionMode, ExecutionOrder, Side


class PaperExecutionError(RuntimeError):
    """A fail-closed execution or reconciliation error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    if hasattr(value, "value"):
        return value.value
    return value


def _order_payload(order: ExecutionOrder) -> Dict[str, Any]:
    return {
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": float(order.quantity),
        "order_type": order.order_type,
        "entry_price": float(order.entry_price),
        "stop_price": order.stop_price,
        "take_profit_price": order.take_profit_price,
        "mode": order.mode.value,
    }


def _fingerprint(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _not_found(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return status == 404


class AlpacaPaperExecutionAdapter:
    """Durable, idempotent, PAPER-only adapter for US-equity bracket entries."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        db_path: Optional[str] = None,
        client: Any = None,
    ) -> None:
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise PaperExecutionError("LIVE mode is prohibited by this adapter.")
        configured_mode = os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper()
        if configured_mode != "PAPER":
            raise PaperExecutionError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")

        self.db_path = db_path or os.getenv("ROCKET_TRADER_EXECUTION_DB")
        if not self.db_path:
            raise PaperExecutionError(
                "ROCKET_TRADER_EXECUTION_DB must point to durable storage."
            )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize_db()

        if client is None:
            key = api_key or os.getenv("ALPACA_API_KEY")
            secret = api_secret or os.getenv("ALPACA_SECRET_KEY")
            if not key or not secret:
                raise PaperExecutionError("Alpaca Paper API credentials are missing.")
            from alpaca.trading.client import TradingClient
            # Hard-coded True: there is no live-mode option in this adapter.
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
                CREATE TABLE IF NOT EXISTS paper_order_journal (
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

    @staticmethod
    def _broker_snapshot(order: Any) -> Dict[str, Any]:
        return {
            "order_id": str(_value(order, "id", "")),
            "client_order_id": str(_value(order, "client_order_id", "")),
            "symbol": str(_value(order, "symbol", "")),
            "status": str(_value(order, "status", "UNKNOWN")),
            "filled_qty": str(_value(order, "filled_qty", "0") or "0"),
            "filled_avg_price": (
                None if _value(order, "filled_avg_price") is None
                else str(_value(order, "filled_avg_price"))
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
                UPDATE paper_order_journal
                SET state=?, broker_order_id=?, broker_status=?,
                    filled_qty=?, filled_avg_price=?, last_error=?, updated_at=?
                WHERE client_order_id=?
                """,
                (
                    state,
                    broker.get("order_id"),
                    broker.get("status"),
                    broker.get("filled_qty"),
                    broker.get("filled_avg_price"),
                    last_error,
                    _utc_now(),
                    client_order_id,
                ),
            )

    def _result(self, broker: Dict[str, Any], duplicate: bool) -> Dict[str, Any]:
        return {
            "accepted": True,
            "mode": "PAPER",
            "duplicate_prevented": duplicate,
            **broker,
            "timestamp": _utc_now(),
        }

    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        if order.mode != ExecutionMode.PAPER:
            raise PaperExecutionError("Only PAPER orders are accepted.")
        if order.side != Side.BUY:
            raise PaperExecutionError("Only BUY/LONG entries are supported.")
        if order.quantity <= 0:
            raise PaperExecutionError("Order quantity must be positive.")
        if not float(order.quantity).is_integer():
            raise PaperExecutionError(
                "Fractional MARKET_BRACKET orders are blocked until Alpaca "
                "fractional bracket compatibility and the full fractional "
                "exit lifecycle are independently verified."
            )
        if order.entry_price <= 0 or float(order.stop_price or 0) <= 0 or float(order.take_profit_price or 0) <= 0:
            raise PaperExecutionError("Entry, stop-loss and take-profit prices must be positive.")
        if not float(order.stop_price) < float(order.take_profit_price):
            raise PaperExecutionError("For a BUY bracket, stop-loss must be below take-profit.")
        if order.order_type != "MARKET_BRACKET":
            raise PaperExecutionError("Only MARKET_BRACKET equity orders are supported.")
        if order.stop_price is None or order.take_profit_price is None:
            raise PaperExecutionError("Every entry must include stop-loss and take-profit.")
        if not order.client_order_id or len(order.client_order_id) > 48:
            raise PaperExecutionError("client_order_id must contain 1 to 48 characters.")
        if not order.symbol or "/" in order.symbol:
            raise PaperExecutionError("This adapter accepts US equity symbols only.")

        payload = _order_payload(order)
        fingerprint = _fingerprint(payload)
        client_id = order.client_order_id

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM paper_order_journal WHERE client_order_id=?",
                    (client_id,),
                ).fetchone()

            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise PaperExecutionError(
                        "client_order_id already exists with a different order payload."
                    )
                existing = self._lookup(client_id)
                if existing is not None:
                    broker = self._broker_snapshot(existing)
                    self._persist(client_id, broker["status"], broker)
                    return self._result(broker, duplicate=True)
                # Never resubmit a journaled request after an uncertain process/network
                # boundary. Human reconciliation is safer than a duplicate position.
                raise PaperExecutionError(
                    "Order exists in durable journal but is absent at broker; "
                    "automatic resubmission is blocked pending reconciliation."
                )

            # Protect against a lost local DB while the broker still has the order.
            existing = self._lookup(client_id)
            if existing is not None:
                broker = self._broker_snapshot(existing)
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO paper_order_journal
                        (client_order_id, fingerprint, payload_json, state,
                         broker_order_id, broker_status, filled_qty,
                         filled_avg_price, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            client_id, fingerprint, json.dumps(payload, sort_keys=True),
                            broker["status"], broker["order_id"], broker["status"],
                            broker["filled_qty"], broker["filled_avg_price"],
                            _utc_now(), _utc_now(),
                        ),
                    )
                return self._result(broker, duplicate=True)

            account = self.verify_account()
            estimated_cost = (
                Decimal(str(order.entry_price))
                * Decimal(str(order.quantity))
                * Decimal("1.05")
            )
            available_cash = min(
                Decimal(account["cash"]),
                Decimal(account["non_marginable_buying_power"]),
            )
            if estimated_cost > available_cash:
                raise PaperExecutionError(
                    "Order plus 5% market-price buffer exceeds available cash-only buying power."
                )

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO paper_order_journal
                    (client_order_id, fingerprint, payload_json, state, created_at, updated_at)
                    VALUES (?, ?, ?, 'PREPARED', ?, ?)
                    """,
                    (client_id, fingerprint, json.dumps(payload, sort_keys=True), _utc_now(), _utc_now()),
                )

            from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
            from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest

            request = MarketOrderRequest(
                symbol=order.symbol,
                qty=order.quantity,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=round(float(order.take_profit_price), 2)),
                stop_loss=StopLossRequest(stop_price=round(float(order.stop_price), 2)),
                client_order_id=client_id,
            )
            try:
                submitted = self.client.submit_order(order_data=request)
                broker = self._broker_snapshot(submitted)
                self._persist(client_id, broker["status"], broker)
                return self._result(broker, duplicate=False)
            except Exception as exc:
                # A timeout can occur after Alpaca accepted the order. Query by the
                # idempotency key before declaring the outcome unknown.
                try:
                    existing = self._lookup(client_id)
                except Exception as lookup_exc:
                    self._persist(client_id, "SUBMISSION_UNKNOWN", last_error=str(lookup_exc))
                    raise PaperExecutionError(
                        "Submission outcome is unknown and broker lookup failed; "
                        "do not retry with a new client_order_id."
                    ) from exc
                if existing is not None:
                    broker = self._broker_snapshot(existing)
                    self._persist(client_id, broker["status"], broker, last_error=str(exc))
                    return self._result(broker, duplicate=True)
                self._persist(client_id, "SUBMISSION_UNKNOWN", last_error=str(exc))
                raise PaperExecutionError(
                    "Submission outcome is unknown; automatic retry is blocked."
                ) from exc

    def reconcile(self, client_order_id: str) -> Dict[str, Any]:
        """Refresh one order from Alpaca without creating or modifying orders."""
        broker_order = self._lookup(client_order_id)
        if broker_order is None:
            return {"found": False, "client_order_id": client_order_id}
        broker = self._broker_snapshot(broker_order)
        self._persist(client_order_id, broker["status"], broker)
        return {"found": True, "mode": "PAPER", **broker}

    def verify_account(self) -> Dict[str, Any]:
        """Read-only Paper account check with hard cash-only/no-derivatives policy."""
        account = self.client.get_account()
        status = str(_value(account, "status", "UNKNOWN")).upper()
        currency = str(_value(account, "currency", "UNKNOWN")).upper()
        if status != "ACTIVE":
            raise PaperExecutionError(f"Paper account is not ACTIVE: {status}")
        if currency != "USD":
            raise PaperExecutionError("Paper account must be denominated in USD.")
        if bool(_value(account, "trading_blocked", False)):
            raise PaperExecutionError("Paper account reports trading_blocked=true.")
        multiplier = str(_value(account, "multiplier", "UNKNOWN"))
        if multiplier != "1":
            raise PaperExecutionError(
                f"Cash-only policy requires account multiplier 1; found {multiplier}."
            )
        if bool(_value(account, "shorting_enabled", True)):
            raise PaperExecutionError("Cash-only policy requires shorting_enabled=false.")
        try:
            config = self.client.get_account_configurations()
        except Exception as exc:
            raise PaperExecutionError(
                "Cannot verify account-level cash-only configuration; orders are blocked."
            ) from exc
        margin_cap = str(_value(config, "max_margin_multiplier", "UNKNOWN"))
        no_shorting = bool(_value(config, "no_shorting", False))
        options_level = int(_value(config, "max_options_trading_level", -1))
        if margin_cap != "1" or not no_shorting or options_level != 0:
            raise PaperExecutionError(
                "Account configuration must enforce max_margin_multiplier=1, "
                "no_shorting=true and max_options_trading_level=0."
            )
        try:
            cash = Decimal(str(_value(account, "cash", "NaN")))
            non_marginable = Decimal(str(_value(account, "non_marginable_buying_power", "NaN")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PaperExecutionError("Cash and non-marginable buying power are unavailable.") from exc
        if not cash.is_finite() or not non_marginable.is_finite() or cash < 0 or non_marginable < 0:
            raise PaperExecutionError("Cash and non-marginable buying power must be finite and non-negative.")
        return {
            "status": status, "currency": currency, "trading_blocked": False,
            "multiplier": multiplier, "max_margin_multiplier": margin_cap,
            "no_shorting": no_shorting, "max_options_trading_level": options_level,
            "cash": str(cash), "non_marginable_buying_power": str(non_marginable),
            "mode": "PAPER",
        }
