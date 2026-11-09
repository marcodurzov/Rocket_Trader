#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Alpaca Paper account/position reconciliation gate.

Broker account equity/cash remain USD. Strategy capital remains MXN and comes
only from the realized-P&L ledger. This module never infers strategy capital
from Paper buying power and never submits or modifies orders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from rocket_trader_currency import FXQuote


class PaperReconciliationError(RuntimeError):
    """A fail-closed Paper account or position reconciliation error."""


def _d(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperReconciliationError(f"{name} must be a valid decimal") from exc
    if not result.is_finite():
        raise PaperReconciliationError(f"{name} must be finite")
    return result


def _value(obj: Any, name: str, default: Any = None) -> Any:
    result = getattr(obj, name, default)
    return result.value if hasattr(result, "value") else result


def _symbol(symbol: str) -> str:
    clean = str(symbol).strip().upper().replace("-", "/")
    if "/" not in clean and clean.endswith("USD") and len(clean) > 3:
        return clean[:-3] + "/USD"
    return clean


class AlpacaPaperReconciliationGate:
    """Compare broker-reported Paper positions with the local FIFO ledger."""

    def __init__(
        self,
        client: Any,
        *,
        max_fx_age: timedelta = timedelta(hours=24),
        quantity_tolerance: Any = "0",
    ) -> None:
        if max_fx_age.total_seconds() <= 0:
            raise PaperReconciliationError("max_fx_age must be positive")
        self.client = client
        self.max_fx_age = max_fx_age
        self.quantity_tolerance = _d(quantity_tolerance, "quantity_tolerance")
        if self.quantity_tolerance < 0:
            raise PaperReconciliationError("quantity_tolerance cannot be negative")

    def reconcile(
        self,
        *,
        ledger_snapshot: Any,
        fx_quote: FXQuote,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise PaperReconciliationError("now must be timezone-aware")
        age = current - fx_quote.observed_at
        if age < timedelta(0):
            raise PaperReconciliationError("FX quote timestamp is in the future")
        if age > self.max_fx_age:
            raise PaperReconciliationError("FX quote is stale; reconciliation is blocked")

        capital_mxn = _d(
            getattr(ledger_snapshot, "operating_capital_mxn", None)
            if not isinstance(ledger_snapshot, dict)
            else ledger_snapshot.get("operating_capital_mxn"),
            "ledger operating_capital_mxn",
        )
        ledger_positions = (
            ledger_snapshot.open_positions
            if not isinstance(ledger_snapshot, dict)
            else ledger_snapshot.get("open_positions", {})
        )
        if capital_mxn < 0 or not isinstance(ledger_positions, dict):
            raise PaperReconciliationError("Invalid local ledger snapshot")

        try:
            account = self.client.get_account()
            positions = self.client.get_all_positions()
        except Exception as exc:
            raise PaperReconciliationError(
                "Could not retrieve broker account/positions; reconciliation is blocked"
            ) from exc

        status = str(_value(account, "status", "UNKNOWN")).upper()
        currency = str(_value(account, "currency", "UNKNOWN")).upper()
        trading_blocked = bool(_value(account, "trading_blocked", False))
        if status != "ACTIVE" or trading_blocked:
            raise PaperReconciliationError("Alpaca Paper account is not active/unblocked")
        if currency != "USD":
            raise PaperReconciliationError("Alpaca broker account must be denominated in USD")

        broker_positions: Dict[str, Decimal] = {}
        for position in positions:
            symbol = _symbol(_value(position, "symbol", ""))
            qty = _d(_value(position, "qty", "0"), f"broker quantity {symbol}")
            if not symbol or qty < 0:
                raise PaperReconciliationError("Invalid broker position; short/negative inventory is blocked")
            if qty > 0:
                if symbol in broker_positions:
                    raise PaperReconciliationError(f"Duplicate broker position for {symbol}")
                broker_positions[symbol] = qty

        expected_positions: Dict[str, Decimal] = {}
        for raw_symbol, row in ledger_positions.items():
            symbol = _symbol(raw_symbol)
            qty = _d(row.get("quantity"), f"ledger quantity {symbol}")
            if qty < 0:
                raise PaperReconciliationError("Ledger contains negative inventory")
            if qty > 0:
                expected_positions[symbol] = qty

        differences: Dict[str, Dict[str, str]] = {}
        for symbol in sorted(set(expected_positions) | set(broker_positions)):
            expected = expected_positions.get(symbol, Decimal("0"))
            actual = broker_positions.get(symbol, Decimal("0"))
            delta = actual - expected
            if abs(delta) > self.quantity_tolerance:
                differences[symbol] = {
                    "ledger_qty": str(expected),
                    "broker_qty": str(actual),
                    "difference": str(delta),
                }

        cash_usd = _d(_value(account, "cash", "0"), "broker cash USD")
        equity_usd = _d(_value(account, "equity", "0"), "broker equity USD")
        if cash_usd < 0 or equity_usd < 0:
            raise PaperReconciliationError("Broker cash/equity cannot be negative")

        capital_usd_reference = capital_mxn / fx_quote.mxn_per_usd
        reconciled = not differences
        return {
            "environment": "PAPER",
            "status": "RECONCILED" if reconciled else "POSITION_MISMATCH",
            "positions_match": reconciled,
            "position_differences": differences,
            "ledger_operating_capital_mxn": str(capital_mxn),
            "ledger_capital_usd_reference": str(capital_usd_reference),
            "fx_mxn_per_usd": str(fx_quote.mxn_per_usd),
            "fx_source": fx_quote.source,
            "fx_observed_at": fx_quote.observed_at.isoformat(),
            "broker_cash_usd": str(cash_usd),
            "broker_equity_usd": str(equity_usd),
            "broker_account_currency": currency,
            "paper_buying_power_used_as_capital": False,
            "orders_enabled": False,
        }
