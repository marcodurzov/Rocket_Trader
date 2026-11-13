#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative MXN strategy-equity valuation from the local FIFO ledger.

This module is diagnostic only. It never connects to a broker, places orders,
or authorizes trading. Metrics remain ineligible for risk authorization until
position, cash/equity, and fee reconciliation are all explicitly complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional

from rocket_trader_currency import FXQuote


class StrategyEquityMetricsError(RuntimeError):
    """Invalid, stale, or inconsistent strategy-equity evidence."""


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StrategyEquityMetricsError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise StrategyEquityMetricsError(f"{field} must be finite")
    return result


def _get(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper().replace("-", "/")
    if not symbol:
        raise StrategyEquityMetricsError("Position symbol is required")
    if "/" not in symbol and symbol.endswith("USD") and len(symbol) > 3:
        symbol = symbol[:-3] + "/USD"
    return symbol


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise StrategyEquityMetricsError(f"{field} must be ISO-8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StrategyEquityMetricsError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class StrategySessionBaseline:
    """Persisted opening equity for one explicitly identified strategy session.

    The caller must load this record from durable storage. This calculator does
    not invent an opening balance from the first intraday observation.
    """

    session_id: str
    equity_mxn: Decimal
    observed_at: datetime
    source: str
    net_external_flows_mxn: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not str(self.session_id).strip():
            raise StrategyEquityMetricsError("session_id is required")
        equity = _decimal(self.equity_mxn, "baseline equity_mxn")
        flows = _decimal(self.net_external_flows_mxn, "baseline net_external_flows_mxn")
        if equity <= 0:
            raise StrategyEquityMetricsError("baseline equity_mxn must be positive")
        _utc(self.observed_at, "baseline observed_at")
        if not str(self.source).strip():
            raise StrategyEquityMetricsError("baseline source is required")
        object.__setattr__(self, "equity_mxn", equity)
        object.__setattr__(self, "net_external_flows_mxn", flows)


def calculate_strategy_equity_metrics(
    *,
    ledger_snapshot: Any,
    broker_positions: Iterable[Any],
    fx_quote: FXQuote,
    session_baseline: StrategySessionBaseline,
    session_id: str,
    account_reconciliation_complete: bool,
    cash_reconciliation_status: str,
    fee_reconciliation_status: str,
    now: Optional[datetime] = None,
    max_fx_age: timedelta = timedelta(hours=24),
    quantity_tolerance: Decimal = Decimal("0.00000001"),
) -> Dict[str, Any]:
    """Value strategy equity in MXN and compute flow-adjusted session P&L.

    Equity = ledger operating capital + unrealized P&L on matched open lots.
    Unrealized P&L uses each lot's persisted MXN FIFO cost basis and the
    current broker mark converted at the current timestamped FX quote.

    This is not eligible for Core risk authorization unless all independent
    account, cash/equity, and fee reconciliation gates are explicitly clear.
    """
    current = _utc(now or datetime.now(timezone.utc), "now")
    if not isinstance(max_fx_age, timedelta) or max_fx_age <= timedelta(0):
        raise StrategyEquityMetricsError("max_fx_age must be a positive timedelta")
    if not isinstance(fx_quote, FXQuote):
        raise StrategyEquityMetricsError("A validated FXQuote is required")
    fx_time = _utc(fx_quote.observed_at, "FX observed_at")
    fx_age = current - fx_time
    if fx_age < timedelta(0) or fx_age > max_fx_age:
        raise StrategyEquityMetricsError("FX quote is future-dated or stale")
    if not isinstance(session_baseline, StrategySessionBaseline):
        raise StrategyEquityMetricsError("A durable StrategySessionBaseline is required")
    if str(session_id).strip() != session_baseline.session_id:
        raise StrategyEquityMetricsError("Session baseline does not match requested session_id")
    baseline_time = _utc(session_baseline.observed_at, "baseline observed_at")
    if baseline_time > current:
        raise StrategyEquityMetricsError("Session baseline cannot be in the future")
    tolerance = _decimal(quantity_tolerance, "quantity_tolerance")
    if tolerance < 0:
        raise StrategyEquityMetricsError("quantity_tolerance cannot be negative")

    operating = _decimal(
        _get(ledger_snapshot, "operating_capital_mxn"),
        "ledger operating_capital_mxn",
    )
    ledger_positions = _get(ledger_snapshot, "open_positions")
    if operating < 0 or not isinstance(ledger_positions, dict):
        raise StrategyEquityMetricsError("Ledger snapshot is invalid")

    expected: Dict[str, Dict[str, Decimal]] = {}
    for raw_symbol, row in ledger_positions.items():
        symbol = _symbol(raw_symbol)
        if symbol in expected or not isinstance(row, dict):
            raise StrategyEquityMetricsError("Duplicate or malformed ledger position")
        qty = _decimal(row.get("quantity"), f"{symbol} ledger quantity")
        cost = _decimal(row.get("fifo_cost_basis_mxn"), f"{symbol} MXN FIFO cost basis")
        if qty <= 0 or cost < 0:
            raise StrategyEquityMetricsError("Ledger position quantity/cost basis is invalid")
        expected[symbol] = {"quantity": qty, "cost_mxn": cost}

    observed: Dict[str, Dict[str, Decimal]] = {}
    for position in broker_positions:
        symbol = _symbol(_get(position, "symbol"))
        if symbol in observed:
            raise StrategyEquityMetricsError(f"Duplicate broker position: {symbol}")
        qty = _decimal(_get(position, "qty"), f"{symbol} broker quantity")
        price = _decimal(
            _get(position, "current_price", _get(position, "current_price_usd")),
            f"{symbol} current USD mark",
        )
        currency = str(_get(position, "currency", "USD")).strip().upper()
        mark_time = _utc(_get(position, "mark_observed_at"), f"{symbol} mark_observed_at")
        mark_age = current - mark_time
        if mark_age < timedelta(0) or mark_age > timedelta(minutes=2):
            raise StrategyEquityMetricsError(f"{symbol} market mark is future-dated or stale")
        if currency != "USD":
            raise StrategyEquityMetricsError(f"{symbol} mark currency must be USD")
        if qty <= 0 or price <= 0:
            raise StrategyEquityMetricsError("Broker position quantity and mark must be positive")
        observed[symbol] = {"quantity": qty, "price_usd": price}

    differences: Dict[str, Dict[str, str]] = {}
    for symbol in sorted(set(expected) | set(observed)):
        expected_qty = expected.get(symbol, {}).get("quantity", Decimal("0"))
        actual_qty = observed.get(symbol, {}).get("quantity", Decimal("0"))
        if abs(actual_qty - expected_qty) > tolerance:
            differences[symbol] = {
                "ledger_quantity": str(expected_qty),
                "broker_quantity": str(actual_qty),
                "difference": str(actual_qty - expected_qty),
            }
    if differences:
        raise StrategyEquityMetricsError(
            f"Broker positions do not match the FIFO ledger: {differences}"
        )

    market_value_usd = Decimal("0")
    fifo_cost_mxn = Decimal("0")
    for symbol, row in expected.items():
        mark = observed[symbol]["price_usd"]
        market_value_usd += row["quantity"] * mark
        fifo_cost_mxn += row["cost_mxn"]

    market_value_mxn = market_value_usd * fx_quote.mxn_per_usd
    unrealized_pnl_mxn = market_value_mxn - fifo_cost_mxn
    equity_mxn = operating + unrealized_pnl_mxn
    if equity_mxn <= 0:
        raise StrategyEquityMetricsError("Calculated strategy equity is at or below zero")

    flow_adjusted_change = (
        equity_mxn
        - session_baseline.equity_mxn
        - session_baseline.net_external_flows_mxn
    )
    # Core RiskConfig expresses percentage limits as fractions (0.05 = 5%).
    daily_pnl_pct = flow_adjusted_change / session_baseline.equity_mxn

    cash_status = str(cash_reconciliation_status).strip().upper()
    fee_status = str(fee_reconciliation_status).strip().upper()
    positions_match = True
    reconciliation_clear = (
        account_reconciliation_complete is True
        and cash_status == "RECONCILED"
        and fee_status == "RECONCILED"
        and positions_match
    )
    return {
        "environment": "PAPER",
        "session_id": session_baseline.session_id,
        "observed_at": current.isoformat(),
        "accounting_method": _get(ledger_snapshot, "accounting_method", "UNKNOWN"),
        "strategy_equity_mxn": float(equity_mxn),
        "strategy_equity_mxn_exact": str(equity_mxn),
        "strategy_daily_pnl_pct": float(daily_pnl_pct),
        "strategy_daily_pnl_fraction_exact": str(daily_pnl_pct),
        "operating_capital_mxn": str(operating),
        "market_value_usd": str(market_value_usd),
        "market_value_mxn": str(market_value_mxn),
        "fifo_cost_basis_mxn": str(fifo_cost_mxn),
        "unrealized_pnl_mxn": str(unrealized_pnl_mxn),
        "baseline_equity_mxn": str(session_baseline.equity_mxn),
        "baseline_net_external_flows_mxn": str(session_baseline.net_external_flows_mxn),
        "fx_mxn_per_usd": str(fx_quote.mxn_per_usd),
        "fx_source": fx_quote.source,
        "fx_observed_at": fx_time.isoformat(),
        "positions_match": positions_match,
        "cash_reconciliation_status": cash_status,
        "fee_reconciliation_status": fee_status,
        "account_reconciliation_complete": account_reconciliation_complete is True,
        "risk_metrics_eligible": reconciliation_clear,
        "status": "RISK_METRICS_ELIGIBLE" if reconciliation_clear else "OBSERVATION_ONLY_RECONCILIATION_INCOMPLETE",
        "orders_enabled": False,
    }
