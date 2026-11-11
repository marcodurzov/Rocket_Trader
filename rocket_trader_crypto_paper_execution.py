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
from rocket_trader_execution_event_ledger import ExecutionEventLedger
from rocket_trader_alpaca_activity_reconciliation import AlpacaAccountActivityReader


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
    if "/" not in clean and clean.endswith("USD") and len(clean) > 3:
        clean = clean[:-3] + "/USD"
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
        event_ledger: Any = None,
        event_ledger_path: Optional[str] = None,
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
        # By default, keep the immutable event chain beside the mutable order
        # journal. Both paths must live on persistent storage in deployment.
        ledger_path = (
            event_ledger_path
            or os.getenv("ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB")
            or f"{self.db_path}.events.sqlite3"
        )
        self.event_ledger = event_ledger or ExecutionEventLedger(ledger_path)
        ledger_db_path = getattr(self.event_ledger, "db_path", None)
        if ledger_db_path and os.path.abspath(ledger_db_path) == os.path.abspath(self.db_path):
            raise CryptoPaperExecutionError(
                "Execution event ledger must use a separate SQLite file from the mutable order journal."
            )
        try:
            integrity = self.event_ledger.verify_chain()
        except Exception as exc:
            raise CryptoPaperExecutionError(
                "Execution event ledger cannot be verified; crypto orders are blocked."
            ) from exc
        if not isinstance(integrity, dict) or not integrity.get("valid"):
            raise CryptoPaperExecutionError(
                "Execution event ledger integrity check failed; crypto orders are blocked."
            )

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
            try:
                position_symbol = normalize_crypto_symbol(_value(position, "symbol", ""))
            except CryptoPaperExecutionError:
                continue
            if position_symbol == symbol:
                qty = _decimal(_value(position, "qty", "0"), "broker_position_qty")
                if qty > 0:
                    return qty
        return Decimal("0")


    def _broker_open_sell_orders(self, symbol: str) -> list[Any]:
        """Read all open broker SELL orders for this symbol; fail closed on ambiguity."""
        try:
            from alpaca.trading.enums import OrderSide, QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            request = GetOrdersRequest(
                status=QueryOrderStatus.OPEN,
                side=OrderSide.SELL,
                symbols=[symbol],
                limit=500,
            )
            orders = self.client.get_orders(filter=request)
        except Exception as exc:
            raise CryptoPaperExecutionError(
                "Cannot verify open broker SELL orders; new SELL orders are blocked."
            ) from exc
        if not isinstance(orders, list):
            raise CryptoPaperExecutionError(
                "Broker open-order response is malformed; new SELL orders are blocked."
            )
        if len(orders) >= 500:
            raise CryptoPaperExecutionError(
                "Broker open-order result reached the 500-order limit; reservation state may be truncated."
            )

        normalized = []
        for order in orders:
            order_symbol = normalize_crypto_symbol(_value(order, "symbol", ""))
            side = str(_value(order, "side", "")).lower()
            if order_symbol != symbol or side != "sell":
                raise CryptoPaperExecutionError(
                    "Broker open-order response conflicts with the requested SELL symbol/side."
                )
            order_id = str(_value(order, "id", "") or "")
            if not order_id:
                raise CryptoPaperExecutionError(
                    "Open broker SELL order is missing its order ID; new SELL orders are blocked."
                )
            raw_qty = _value(order, "qty", None)
            raw_filled = _value(order, "filled_qty", None)
            if raw_qty is None or raw_filled is None:
                raise CryptoPaperExecutionError(
                    "Open broker SELL order has incomplete quantity data; new SELL orders are blocked."
                )
            qty = _decimal(raw_qty, "open_sell_order_qty")
            filled = _decimal(raw_filled, "open_sell_order_filled_qty")
            if qty <= 0 or filled < 0 or filled > qty:
                raise CryptoPaperExecutionError(
                    "Open broker SELL order has inconsistent quantity data; new SELL orders are blocked."
                )
            normalized.append(
                {
                    "order_id": order_id,
                    "client_order_id": str(_value(order, "client_order_id", "") or ""),
                    "remaining_qty": qty - filled,
                }
            )
        return normalized

    def _prepare_sell_order(
        self,
        *,
        client_id: str,
        fingerprint: str,
        payload: Dict[str, Any],
        symbol: str,
        quantity: Decimal,
    ) -> None:
        """Atomically reserve local SELL intent against broker open orders."""
        open_orders = self._broker_open_sell_orders(symbol)
        broker_reserved = sum(
            (item["remaining_qty"] for item in open_orders),
            Decimal("0"),
        )
        open_client_ids = {
            item["client_order_id"] for item in open_orders if item["client_order_id"]
        }
        open_order_ids = {item["order_id"] for item in open_orders}
        held = self._available_position_qty(symbol)

        with self._connect() as conn:
            # Serialize competing adapter processes, not just threads in one process.
            conn.execute("BEGIN IMMEDIATE")
            local_rows = conn.execute(
                """
                SELECT client_order_id, payload_json, state, broker_order_id
                FROM crypto_paper_order_journal
                """
            ).fetchall()
            terminal = {"filled", "canceled", "expired", "rejected", "replaced"}
            for row in local_rows:
                try:
                    local_payload = json.loads(row["payload_json"])
                except (TypeError, ValueError) as exc:
                    raise CryptoPaperExecutionError(
                        "Local order journal is malformed; new SELL orders are blocked."
                    ) from exc
                if (
                    str(local_payload.get("side", "")).lower() != "sell"
                    or local_payload.get("symbol") != symbol
                ):
                    continue
                state = str(row["state"] or "").lower()
                if state in terminal:
                    continue
                if (
                    row["client_order_id"] in open_client_ids
                    or row["broker_order_id"] in open_order_ids
                ):
                    # Count this order from the broker snapshot exactly once.
                    continue
                # PREPARED, unknown, stale or unfamiliar local states are not
                # assumed released just because the open-order query omitted them.
                raise CryptoPaperExecutionError(
                    "An existing local SELL order is not present in the broker open-order snapshot; "
                    "reconcile it before submitting another SELL."
                )

            available = held - broker_reserved
            if available < 0:
                raise CryptoPaperExecutionError(
                    "Broker open SELL orders reserve more quantity than the current position."
                )
            if quantity > available:
                raise CryptoPaperExecutionError(
                    f"SELL quantity {quantity} exceeds broker-held unreserved {symbol} quantity {available} after open-order reservations."
                )

            # Write-ahead evidence and the local reservation are committed before
            # any broker submission. BEGIN IMMEDIATE prevents a second process
            # from passing the same available-quantity check concurrently.
            self._record_event(client_id, "ORDER_PREPARED", {"order_intent": payload})
            conn.execute(
                """
                INSERT INTO crypto_paper_order_journal
                (client_order_id, fingerprint, payload_json, state, created_at, updated_at)
                VALUES (?, ?, ?, 'PREPARED', ?, ?)
                """,
                (client_id, fingerprint, json.dumps(payload, sort_keys=True), _utc_now(), _utc_now()),
            )

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

    def _record_event(
        self, client_order_id: str, event_type: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        material = json.dumps(
            {
                "client_order_id": client_order_id,
                "event_type": event_type,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        event_id = "rt-" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        return self.event_ledger.append_event(
            event_id=event_id,
            aggregate_id=client_order_id,
            event_type=event_type,
            payload=payload,
        )

    def order_events(self, client_order_id: str) -> list[Dict[str, Any]]:
        """Return immutable local evidence for one client order; no broker call."""
        return self.event_ledger.list_events(aggregate_id=client_order_id)

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
        # Persist broker state first. If the event write fails, the mutable
        # journal still prevents resubmission; the next reconciliation retries
        # recording the same deterministic event ID.
        self._record_event(
            client_order_id,
            "ORDER_STATE_OBSERVED",
            {
                "state": state,
                "broker_snapshot": broker,
                "error_present": last_error is not None,
            },
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
        multiplier = str(_value(account, "multiplier", "UNKNOWN"))
        if multiplier != "1":
            raise CryptoPaperExecutionError(
                f"Cash-only policy requires account multiplier 1; found {multiplier}."
            )
        if bool(_value(account, "shorting_enabled", True)):
            raise CryptoPaperExecutionError("Cash-only policy requires shorting_enabled=false.")
        try:
            config = self.client.get_account_configurations()
        except Exception as exc:
            raise CryptoPaperExecutionError(
                "Cannot verify account-level cash-only configuration; orders are blocked."
            ) from exc
        margin_cap = str(_value(config, "max_margin_multiplier", "UNKNOWN"))
        no_shorting = bool(_value(config, "no_shorting", False))
        raw_options_level = _value(config, "max_options_trading_level", None)
        try:
            options_level = int(raw_options_level) if raw_options_level is not None else -1
        except (TypeError, ValueError) as exc:
            raise CryptoPaperExecutionError("Options trading level is invalid; orders are blocked.") from exc
        if margin_cap != "1" or not no_shorting or options_level != 0:
            raise CryptoPaperExecutionError(
                "Account configuration must enforce max_margin_multiplier=1, "
                "no_shorting=true and max_options_trading_level=0."
            )
        cash = _decimal(_value(account, "cash", "NaN"), "account_cash")
        non_marginable = _decimal(
            _value(account, "non_marginable_buying_power", "NaN"),
            "non_marginable_buying_power",
        )
        if cash < 0 or non_marginable < 0:
            raise CryptoPaperExecutionError("Cash and non-marginable buying power cannot be negative.")
        return {
            "status": status, "currency": currency, "crypto_status": crypto_status,
            "trading_blocked": trading_blocked, "multiplier": multiplier,
            "max_margin_multiplier": margin_cap, "no_shorting": no_shorting,
            "max_options_trading_level": options_level, "cash": str(cash),
            "non_marginable_buying_power": str(non_marginable), "mode": "PAPER",
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
        account_snapshot = self.verify_account()
        self._validate_asset(symbol)

        if intent.side == Side.BUY:
            if intent.quantity is not None or intent.notional_usd is None:
                raise CryptoPaperExecutionError("BUY entry must specify notional_usd only.")
            notional = _decimal(intent.notional_usd, "notional_usd")
            if notional < self.MIN_BUY_NOTIONAL_USD:
                raise CryptoPaperExecutionError("BUY notional is below the USD 1 broker minimum.")
            if notional <= 0:
                raise CryptoPaperExecutionError("BUY notional must be positive.")
            available_cash = min(
                Decimal(account_snapshot["cash"]),
                Decimal(account_snapshot["non_marginable_buying_power"]),
            )
            if notional * Decimal("1.02") > available_cash:
                raise CryptoPaperExecutionError(
                    "BUY notional plus 2% fee/price buffer exceeds available cash-only buying power."
                )
            quantity = None
        else:
            if intent.notional_usd is not None or intent.quantity is None:
                raise CryptoPaperExecutionError("SELL exit must specify quantity only.")
            quantity = _decimal(intent.quantity, "quantity")
            if quantity <= 0:
                raise CryptoPaperExecutionError("SELL quantity must be positive.")
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
                self._record_event(
                    client_id, "BROKER_ORDER_DISCOVERED",
                    {"order_intent": payload, "broker_snapshot": broker},
                )
                return {"accepted": True, "mode": "PAPER", "duplicate_prevented": True, **broker}

            if intent.side == Side.SELL:
                self._prepare_sell_order(
                    client_id=client_id,
                    fingerprint=fingerprint,
                    payload=payload,
                    symbol=symbol,
                    quantity=quantity,
                )
            else:
                # Write-ahead evidence: if this fails, do not create the mutable
                # journal row and, critically, do not send an order to the broker.
                self._record_event(client_id, "ORDER_PREPARED", {"order_intent": payload})
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

    def cancel(self, client_order_id: str) -> Dict[str, Any]:
        """Request cancellation of one known Paper order and reconcile the broker result."""
        if not isinstance(client_order_id, str) or not client_order_id.strip():
            raise CryptoPaperExecutionError("client_order_id is required for cancellation.")
        broker_order = self._lookup(client_order_id)
        if broker_order is None:
            return {"found": False, "client_order_id": client_order_id, "cancel_requested": False}
        broker = self._snapshot(broker_order)
        terminal = {"filled", "canceled", "cancelled", "expired", "rejected", "done_for_day", "replaced"}
        if str(broker.get("status", "")).lower() in terminal:
            self._persist(client_order_id, broker["status"], broker)
            return {"found": True, "mode": "PAPER", "cancel_requested": False, **broker}
        order_id = broker.get("order_id")
        if not order_id:
            self._persist(client_order_id, "CANCEL_OUTCOME_UNKNOWN", broker, "Missing broker order ID.")
            raise CryptoPaperExecutionError("Cannot cancel without a broker order ID; reconcile before retrying.")
        try:
            self.client.cancel_order_by_id(order_id)
        except Exception as exc:
            try:
                latest = self._lookup(client_order_id)
            except Exception as lookup_exc:
                self._persist(client_order_id, "CANCEL_OUTCOME_UNKNOWN", broker, str(lookup_exc))
                raise CryptoPaperExecutionError(
                    "Cancellation outcome unknown; reconcile this client_order_id before any retry."
                ) from exc
            if latest is not None:
                refreshed = self._snapshot(latest)
                if str(refreshed.get("status", "")).lower() in terminal:
                    self._persist(client_order_id, refreshed["status"], refreshed, str(exc))
                    return {"found": True, "mode": "PAPER", "cancel_requested": True, **refreshed}
                self._persist(client_order_id, "CANCEL_OUTCOME_UNKNOWN", refreshed, str(exc))
            raise CryptoPaperExecutionError(
                "Cancellation outcome unknown; reconcile this client_order_id before any retry."
            ) from exc
        latest = self._lookup(client_order_id)
        if latest is None:
            self._persist(client_order_id, "CANCEL_REQUESTED", broker)
            return {"found": False, "client_order_id": client_order_id, "cancel_requested": True}
        refreshed = self._snapshot(latest)
        self._persist(client_order_id, refreshed["status"], refreshed)
        return {"found": True, "mode": "PAPER", "cancel_requested": True, **refreshed}

    def reconcile_order_activities(self, client_order_id: str) -> Dict[str, Any]:
        """Reconcile an order snapshot against individual broker FILL activities."""
        broker_order = self._lookup(client_order_id)
        if broker_order is None:
            return {"found": False, "client_order_id": client_order_id}
        broker = self._snapshot(broker_order)
        if not broker.get("order_id"):
            raise CryptoPaperExecutionError(
                "Broker order snapshot is missing its order ID; fill reconciliation is blocked."
            )
        self._persist(client_order_id, broker["status"], broker)
        try:
            activity_result = AlpacaAccountActivityReader(
                self.client, self.event_ledger
            ).reconcile_order_fills(
                client_order_id=client_order_id,
                broker_order_id=broker["order_id"],
                expected_symbol=broker["symbol"],
                expected_side=broker["side"],
                expected_filled_qty=broker["filled_qty"],
            )
        except Exception as exc:
            raise CryptoPaperExecutionError(
                "Broker order snapshot retrieved, but individual fill activity reconciliation failed."
            ) from exc
        self._record_event(
            client_order_id,
            "ORDER_FILL_RECONCILIATION",
            {
                "broker_order_id": broker["order_id"],
                "expected_filled_qty": activity_result["expected_filled_qty"],
                "activity_filled_qty": activity_result["activity_filled_qty"],
                "fill_count": activity_result["fill_count"],
                "reconciliation_status": activity_result["reconciliation_status"],
            },
        )
        return {
            "found": True,
            "mode": "PAPER",
            **broker,
            "activity_reconciliation": activity_result,
        }

    def reconcile(self, client_order_id: str) -> Dict[str, Any]:
        """Read-only broker order + individual fill-activity reconciliation."""
        return self.reconcile_order_activities(client_order_id)

    def collect_crypto_fee_activities(
        self, *, symbol: str, after: str, until: str, page_size: int = 100
    ) -> Dict[str, Any]:
        """Collect fee activities as unallocated account-level evidence."""
        try:
            return AlpacaAccountActivityReader(
                self.client, self.event_ledger
            ).collect_crypto_fee_candidates(
                symbol=symbol, after=after, until=until, page_size=page_size
            )
        except Exception as exc:
            raise CryptoPaperExecutionError(
                "Crypto fee activity collection failed; fees remain unreconciled."
            ) from exc

    def reconcile_positions(self) -> Dict[str, Any]:
        """Read-only broker snapshot; broker holdings remain authoritative."""
        positions = self.client.get_all_positions()
        crypto_positions = []
        for position in positions:
            try:
                symbol = normalize_crypto_symbol(_value(position, "symbol", ""))
            except CryptoPaperExecutionError:
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
