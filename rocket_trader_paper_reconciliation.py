#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Alpaca Paper position comparison; cash/equity are observations only.

Broker account equity/cash remain USD. Strategy capital remains MXN and comes
only from the realized-P&L ledger. This module does not reconcile broker cash
against a local USD cash ledger, does not infer strategy capital from Paper
buying power, and never submits or modifies orders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
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
    """Compare Paper positions; explicitly do not claim full account reconciliation."""

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
        broker_market_values_usd: Dict[str, Decimal] = {}
        missing_market_value_symbols = []
        invalid_market_value_symbols = []
        for position in positions:
            symbol = _symbol(_value(position, "symbol", ""))
            qty = _d(_value(position, "qty", "0"), f"broker quantity {symbol}")
            if not symbol or qty < 0:
                raise PaperReconciliationError("Invalid broker position; short/negative inventory is blocked")
            if qty > 0:
                if symbol in broker_positions:
                    raise PaperReconciliationError(f"Duplicate broker position for {symbol}")
                broker_positions[symbol] = qty
                raw_market_value = _value(position, "market_value", None)
                if raw_market_value is None:
                    missing_market_value_symbols.append(symbol)
                else:
                    try:
                        market_value = _d(raw_market_value, f"broker market value {symbol}")
                        if market_value <= 0:
                            invalid_market_value_symbols.append(symbol)
                        else:
                            broker_market_values_usd[symbol] = market_value
                    except PaperReconciliationError:
                        invalid_market_value_symbols.append(symbol)

        expected_positions: Dict[str, Decimal] = {}
        ledger_rows: Dict[str, Dict[str, Any]] = {}
        for raw_symbol, row in ledger_positions.items():
            symbol = _symbol(raw_symbol)
            qty = _d(row.get("quantity"), f"ledger quantity {symbol}")
            if qty < 0:
                raise PaperReconciliationError("Ledger contains negative inventory")
            if qty > 0:
                if symbol in ledger_rows:
                    raise PaperReconciliationError(f"Duplicate local ledger position for {symbol}")
                expected_positions[symbol] = qty
                ledger_rows[symbol] = row

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
        positions_match = not differences
        accounting_method = (
            getattr(ledger_snapshot, "accounting_method", None)
            if not isinstance(ledger_snapshot, dict)
            else ledger_snapshot.get("accounting_method")
        )
        strategy_equity_status = "AVAILABLE"
        strategy_unrealized_pnl_mxn = Decimal("0")
        strategy_equity_mxn = None
        strategy_equity_snapshot_hash = None
        if not positions_match:
            strategy_equity_status = "UNAVAILABLE_POSITION_MISMATCH"
        elif accounting_method != "FIFO_MXN_ENTRY_AND_EXIT_FX_V2":
            strategy_equity_status = "UNAVAILABLE_ACCOUNTING_METHOD"
        elif missing_market_value_symbols:
            strategy_equity_status = "UNAVAILABLE_MISSING_MARKET_VALUE"
        elif invalid_market_value_symbols:
            strategy_equity_status = "UNAVAILABLE_INVALID_MARKET_VALUE"
        else:
            for symbol in sorted(expected_positions):
                row = ledger_rows[symbol]
                raw_cost_basis = row.get("fifo_cost_basis_mxn")
                if raw_cost_basis is None:
                    strategy_equity_status = "UNAVAILABLE_MISSING_MXN_COST_BASIS"
                    break
                cost_basis_mxn = _d(raw_cost_basis, f"FIFO MXN cost basis {symbol}")
                if cost_basis_mxn < 0:
                    strategy_equity_status = "UNAVAILABLE_INVALID_MXN_COST_BASIS"
                    break
                market_value_mxn = broker_market_values_usd[symbol] * fx_quote.mxn_per_usd
                strategy_unrealized_pnl_mxn += market_value_mxn - cost_basis_mxn
            if strategy_equity_status == "AVAILABLE":
                candidate_equity = capital_mxn + strategy_unrealized_pnl_mxn
                if candidate_equity <= 0:
                    strategy_equity_status = "NONPOSITIVE_STRATEGY_EQUITY"
                else:
                    strategy_equity_mxn = candidate_equity
                    snapshot_payload = {
                        "accounting_method": accounting_method,
                        "operating_capital_mxn": str(capital_mxn),
                        "fx_mxn_per_usd": str(fx_quote.mxn_per_usd),
                        "positions": {
                            symbol: {
                                "quantity": str(expected_positions[symbol]),
                                "market_value_usd": str(broker_market_values_usd[symbol]),
                                "fifo_cost_basis_mxn": str(
                                    _d(ledger_rows[symbol]["fifo_cost_basis_mxn"], "FIFO MXN cost basis")
                                ),
                            }
                            for symbol in sorted(expected_positions)
                        },
                    }
                    strategy_equity_snapshot_hash = hashlib.sha256(
                        json.dumps(
                            snapshot_payload, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                    ).hexdigest()
        return {
            "environment": "PAPER",
            "status": (
                "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE"
                if positions_match else "POSITION_MISMATCH"
            ),
            "position_reconciliation_status": "MATCHED" if positions_match else "MISMATCH",
            "positions_match": positions_match,
            "cash_reconciliation_status": "NOT_IMPLEMENTED_NO_USD_CASH_LEDGER",
            "account_reconciliation_complete": False,
            "broker_cash_equity_observed_only": True,
            "position_differences": differences,
            "ledger_operating_capital_mxn": str(capital_mxn),
            "ledger_capital_usd_reference": str(capital_usd_reference),
            "ledger_accounting_method": accounting_method,
            "strategy_equity_status": strategy_equity_status,
            "strategy_unrealized_pnl_mxn": str(strategy_unrealized_pnl_mxn),
            "strategy_equity_mxn": str(strategy_equity_mxn) if strategy_equity_mxn is not None else None,
            "strategy_equity_snapshot_hash": strategy_equity_snapshot_hash,
            "broker_position_market_values_usd": {
                symbol: str(value) for symbol, value in sorted(broker_market_values_usd.items())
            },
            "missing_market_value_symbols": sorted(missing_market_value_symbols),
            "invalid_market_value_symbols": sorted(invalid_market_value_symbols),
            "fx_mxn_per_usd": str(fx_quote.mxn_per_usd),
            "fx_source": fx_quote.source,
            "fx_observed_at": fx_quote.observed_at.isoformat(),
            "broker_cash_usd": str(cash_usd),
            "broker_equity_usd": str(equity_usd),
            "broker_account_currency": currency,
            "paper_buying_power_used_as_capital": False,
            "orders_enabled": False,
        }
