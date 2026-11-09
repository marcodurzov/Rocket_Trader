#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit MXN-to-USD capital conversion and fail-closed position budgeting.

All strategy capital inputs are MXN. Alpaca equity/crypto notionals are USD.
This module deliberately requires a timestamped FX quote; it never guesses a
rate, fetches an implicit rate, or treats the Paper account's virtual buying
power as the user's funded strategy capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Optional


class CurrencyBudgetError(ValueError):
    """Invalid, ambiguous, or stale currency/capital input."""


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CurrencyBudgetError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise CurrencyBudgetError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class FXQuote:
    """MXN per USD. Example: 18.00 means USD 1 costs MXN 18."""

    mxn_per_usd: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        rate = _decimal(self.mxn_per_usd, "mxn_per_usd")
        if rate <= 0:
            raise CurrencyBudgetError("mxn_per_usd must be > 0")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise CurrencyBudgetError("FX timestamp must be timezone-aware")
        if not self.source or not self.source.strip():
            raise CurrencyBudgetError("FX source is required")
        object.__setattr__(self, "mxn_per_usd", rate)


@dataclass(frozen=True)
class PositionBudget:
    allowed: bool
    reason: str
    capital_mxn: Decimal
    capital_usd: Decimal
    max_notional_usd: Decimal
    max_notional_mxn: Decimal
    fx_mxn_per_usd: Decimal
    fx_source: str
    fx_observed_at: str


def calculate_position_budget(
    *,
    capital_mxn: object,
    available_cash_usd: object,
    current_exposure_usd: object,
    fx_quote: FXQuote,
    max_position_pct: object = "0.10",
    max_total_exposure_pct: object = "0.50",
    max_loss_per_trade_pct: object = "0.01",
    stop_distance_pct: object = "0.02",
    min_order_usd: object = "1.00",
    now: Optional[datetime] = None,
    max_fx_age: timedelta = timedelta(hours=24),
) -> PositionBudget:
    """Calculate a conservative USD notional cap from an MXN capital ledger.

    The result is only a sizing ceiling. It is not a trade signal or an order.
    """

    capital = _decimal(capital_mxn, "capital_mxn")
    cash = _decimal(available_cash_usd, "available_cash_usd")
    exposure = _decimal(current_exposure_usd, "current_exposure_usd")
    position_pct = _decimal(max_position_pct, "max_position_pct")
    total_pct = _decimal(max_total_exposure_pct, "max_total_exposure_pct")
    loss_pct = _decimal(max_loss_per_trade_pct, "max_loss_per_trade_pct")
    stop_pct = _decimal(stop_distance_pct, "stop_distance_pct")
    minimum = _decimal(min_order_usd, "min_order_usd")

    if capital <= 0:
        raise CurrencyBudgetError("capital_mxn must be > 0")
    if cash < 0 or exposure < 0:
        raise CurrencyBudgetError("cash and exposure cannot be negative")
    if not (Decimal("0") < position_pct <= Decimal("1")):
        raise CurrencyBudgetError("max_position_pct must be in (0, 1]")
    if not (Decimal("0") < total_pct <= Decimal("1")):
        raise CurrencyBudgetError("max_total_exposure_pct must be in (0, 1]")
    if not (Decimal("0") < loss_pct <= Decimal("1")):
        raise CurrencyBudgetError("max_loss_per_trade_pct must be in (0, 1]")
    if not (Decimal("0") < stop_pct <= Decimal("1")):
        raise CurrencyBudgetError("stop_distance_pct must be in (0, 1]")
    if minimum <= 0:
        raise CurrencyBudgetError("min_order_usd must be > 0")
    if max_fx_age.total_seconds() <= 0:
        raise CurrencyBudgetError("max_fx_age must be positive")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise CurrencyBudgetError("now must be timezone-aware")
    age = current_time - fx_quote.observed_at
    if age < timedelta(0):
        raise CurrencyBudgetError("FX quote timestamp is in the future")
    if age > max_fx_age:
        raise CurrencyBudgetError("FX quote is stale; trading budget is blocked")

    capital_usd = capital / fx_quote.mxn_per_usd
    position_cap = capital_usd * position_pct
    exposure_cap_remaining = max(
        Decimal("0"),
        capital_usd * total_pct - exposure,
    )
    risk_cap = capital_usd * loss_pct / stop_pct
    notional = min(position_cap, exposure_cap_remaining, risk_cap, cash)
    notional = notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    if notional < minimum:
        return PositionBudget(
            allowed=False,
            reason="below_broker_minimum_or_no_available_risk_budget",
            capital_mxn=capital,
            capital_usd=capital_usd,
            max_notional_usd=Decimal("0.00"),
            max_notional_mxn=Decimal("0.00"),
            fx_mxn_per_usd=fx_quote.mxn_per_usd,
            fx_source=fx_quote.source,
            fx_observed_at=fx_quote.observed_at.isoformat(),
        )

    notional_mxn = (notional * fx_quote.mxn_per_usd).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    return PositionBudget(
        allowed=True,
        reason="budget_valid",
        capital_mxn=capital,
        capital_usd=capital_usd,
        max_notional_usd=notional,
        max_notional_mxn=notional_mxn,
        fx_mxn_per_usd=fx_quote.mxn_per_usd,
        fx_source=fx_quote.source,
        fx_observed_at=fx_quote.observed_at.isoformat(),
    )
