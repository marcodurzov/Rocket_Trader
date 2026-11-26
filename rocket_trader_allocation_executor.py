#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — monthly allocation sleeve executor (Paper only, dry-run by default).

Implements the candidate risk overlay `sma210_trend_inverse_vol` (T05 rule,
drawdown-control pass on 2005–2016, run 45819942795) as a small, isolated
"sleeve" in the Alpaca Paper account.

Safety contract
---------------
* Default mode is DRY_RUN: it computes and reports the orders it *would* send.
* Orders are submitted only when ALL hold: mode == PAPER_EXECUTE; a traceable
  approval reference is configured; the strategy is in the allowlist;
  ALPACA_PAPER=true and ALPACA_LIVE_ENABLED=false; the trading client is
  constructed with paper=True; sleeve capital <= USD 100; the market is open.
* Stateless and broker-sourced: the sleeve's quantities and cash are rebuilt on
  every run from its own filled orders (client_order_id prefix ``rt-alloc-``)
  and regulatory FEE activities since the sleeve start date. Broker positions
  must be at least the sleeve quantity, otherwise it fails closed.
* Long-only, no leverage: buys are limited to available sleeve cash; sells never
  exceed the sleeve's own quantity. Fractional DAY market orders, USD 1 minimum.
* Idempotent per day: client_order_id = rt-alloc-<YYYYMMDD>-<SYMBOL>-<side>.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ALLOWLIST = frozenset({"sma210_trend_inverse_vol"})
DEFAULT_STRATEGY = "sma210_trend_inverse_vol"
UNIVERSE = ("DIA", "EEM", "EFA", "GLD", "IWM", "QQQ", "SPY", "TLT")
CLIENT_ID_PREFIX = "rt-alloc-"
MIN_ORDER_USD = Decimal("1.00")
MAX_SLEEVE_USD = Decimal("100.00")
APPROVAL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{6,80}$")


class AllocationExecutorError(RuntimeError):
    """Fail closed."""


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: str  # "buy" | "sell"
    notional_usd: Optional[Decimal]
    qty: Optional[Decimal]
    client_order_id: str
    reason: str


def _d(value: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise AllocationExecutorError(f"Invalid {name}") from exc
    if not d.is_finite():
        raise AllocationExecutorError(f"Non-finite {name}")
    return d


def _val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    value = getattr(obj, key, default)
    return getattr(value, "value", value)


def sleeve_state(initial_usd: Decimal, orders: Iterable[Any], fees_usd: Decimal) -> Dict[str, Any]:
    """Rebuild sleeve quantities and cash from its own filled orders."""
    qty: Dict[str, Decimal] = {}
    cash = initial_usd - fees_usd
    for order in orders:
        cid = str(_val(order, "client_order_id", "") or "")
        if not cid.startswith(CLIENT_ID_PREFIX):
            continue
        filled = _d(_val(order, "filled_qty", "0") or "0", "filled_qty")
        if filled <= 0:
            continue
        price = _d(_val(order, "filled_avg_price"), "filled_avg_price")
        symbol = str(_val(order, "symbol", "")).upper()
        side = str(_val(order, "side", "")).lower()
        if symbol not in UNIVERSE or side not in {"buy", "sell"} or price <= 0:
            raise AllocationExecutorError(f"Unexpected sleeve order {cid}")
        sign = Decimal(1) if side == "buy" else Decimal(-1)
        qty[symbol] = qty.get(symbol, Decimal(0)) + sign * filled
        cash -= sign * filled * price
    if any(q < 0 for q in qty.values()):
        raise AllocationExecutorError("Sleeve quantity would be negative (short) — fail closed.")
    if cash < Decimal("-0.05"):
        raise AllocationExecutorError(f"Sleeve cash negative ({cash}) — fail closed.")
    return {"qty": {k: v for k, v in qty.items() if v > 0}, "cash_usd": cash}


def plan_rebalance(*, target_weights: Dict[str, float], sleeve_qty: Dict[str, Decimal],
                   prices: Dict[str, Decimal], cash_usd: Decimal, day_key: str) -> Dict[str, Any]:
    """Pure planning: sells first, then buys limited to available cash."""
    holdings_usd = {s: sleeve_qty.get(s, Decimal(0)) * prices[s] for s in sleeve_qty}
    equity = cash_usd + sum(holdings_usd.values(), Decimal(0))
    if equity <= 0:
        raise AllocationExecutorError("Non-positive sleeve equity.")
    total_w = sum(Decimal(str(w)) for w in target_weights.values())
    if total_w > Decimal("1.000001") or any(w < 0 for w in target_weights.values()):
        raise AllocationExecutorError("Invalid target weights (leverage or negative).")
    sells: List[PlannedOrder] = []
    buys: List[PlannedOrder] = []
    expected_cash = cash_usd
    for s in UNIVERSE:
        target = (Decimal(str(target_weights.get(s, 0.0))) * equity).quantize(Decimal("0.01"), ROUND_DOWN)
        current = holdings_usd.get(s, Decimal(0))
        delta = target - current
        if delta <= -MIN_ORDER_USD:
            held = sleeve_qty.get(s, Decimal(0))
            if target < MIN_ORDER_USD:
                q = held  # close fully
            else:
                q = min(held, (-delta / prices[s]).quantize(Decimal("0.000000001"), ROUND_DOWN))
            if q > 0:
                sells.append(PlannedOrder(s, "sell", None, q, f"{CLIENT_ID_PREFIX}{day_key}-{s}-sell",
                                          f"target {target} < holding {current.quantize(Decimal('0.01'))}"))
                expected_cash += q * prices[s]
        elif delta >= MIN_ORDER_USD:
            buys.append((s, delta, target, current))
    # Buys use only cash available now (sells may settle later; next daily run tops up).
    cash_now = cash_usd
    planned_buys: List[PlannedOrder] = []
    for s, delta, target, current in buys:
        notional = min(delta, cash_now).quantize(Decimal("0.01"), ROUND_DOWN)
        if notional < MIN_ORDER_USD:
            continue
        planned_buys.append(PlannedOrder(s, "buy", notional, None, f"{CLIENT_ID_PREFIX}{day_key}-{s}-buy",
                                         f"target {target} > holding {current.quantize(Decimal('0.01'))}"))
        cash_now -= notional
    return {"sleeve_equity_usd": equity, "orders": sells + planned_buys,
            "cash_after_buys_usd": cash_now, "expected_cash_after_sells_usd": expected_cash}


def execution_allowed(*, mode: str, approval_ref: str, strategy: str, initial_usd: Decimal) -> Dict[str, Any]:
    from rocket_trader_env import env_bool
    reasons = []
    if mode != "PAPER_EXECUTE":
        reasons.append("MODE_NOT_PAPER_EXECUTE")
    if not APPROVAL_PATTERN.match(approval_ref or ""):
        reasons.append("NO_VALID_APPROVAL_REFERENCE")
    if strategy not in ALLOWLIST:
        reasons.append("STRATEGY_NOT_ALLOWLISTED")
    try:
        if not env_bool("ALPACA_PAPER", default=False) or env_bool("ALPACA_LIVE_ENABLED", default=False):
            reasons.append("NOT_PAPER_ONLY")
    except ValueError:
        reasons.append("INVALID_PAPER_LIVE_FLAGS")
    if initial_usd > MAX_SLEEVE_USD or initial_usd <= 0:
        reasons.append("SLEEVE_CAPITAL_OUTSIDE_CAP")
    return {"allowed": not reasons, "blocked_by": reasons}


def run(*, client: Any, weights_fn: Callable[[], Dict[str, Any]], fees_fn: Callable[[datetime], Decimal],
        mode: str, approval_ref: str, strategy: str, initial_usd: Decimal, sleeve_start: datetime,
        now: Optional[datetime] = None) -> Dict[str, Any]:
    from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus, TimeInForce
    from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

    now = now or datetime.now(timezone.utc)
    if strategy not in ALLOWLIST:
        raise AllocationExecutorError("Strategy is not allowlisted.")
    gate = execution_allowed(mode=mode, approval_ref=approval_ref, strategy=strategy, initial_usd=initial_usd)
    signal = weights_fn()
    orders = list(client.get_orders(filter=GetOrdersRequest(
        status=QueryOrderStatus.ALL, after=sleeve_start, limit=500, symbols=list(UNIVERSE))) or [])
    open_sleeve = [o for o in orders if str(_val(o, "client_order_id", "")).startswith(CLIENT_ID_PREFIX)
                   and str(_val(o, "status", "")).lower() in {"new", "accepted", "pending_new", "partially_filled", "held"}]
    state = sleeve_state(initial_usd, orders, fees_fn(sleeve_start))
    positions = {str(_val(p, "symbol")).upper(): p for p in (client.get_all_positions() or [])}
    prices: Dict[str, Decimal] = {}
    for s in UNIVERSE:
        if s in positions:
            broker_qty = _d(_val(positions[s], "qty"), f"{s} qty")
            if broker_qty + Decimal("0.000000001") < state["qty"].get(s, Decimal(0)):
                raise AllocationExecutorError(f"Broker {s} quantity below sleeve quantity — fail closed.")
            prices[s] = _d(_val(positions[s], "current_price"), f"{s} price")
        elif state["qty"].get(s, Decimal(0)) > 0:
            raise AllocationExecutorError(f"Sleeve holds {s} but broker has no position — fail closed.")
        else:
            prices[s] = Decimal(1)  # not used for buys (notional) and no holding to value
    day_key = now.astimezone(timezone.utc).strftime("%Y%m%d")
    plan = plan_rebalance(target_weights=signal["target_weights"], sleeve_qty=state["qty"],
                          prices=prices, cash_usd=state["cash_usd"], day_key=day_key)
    report: Dict[str, Any] = {
        "strategy": strategy, "mode": mode, "signal_session_utc": signal.get("signal_session_utc"),
        "execution_gate": gate, "open_sleeve_orders": len(open_sleeve),
        "sleeve_cash_usd": str(state["cash_usd"]), "sleeve_equity_usd": str(plan["sleeve_equity_usd"]),
        "planned_orders": [o.__dict__ | {"notional_usd": str(o.notional_usd) if o.notional_usd else None,
                                         "qty": str(o.qty) if o.qty else None} for o in plan["orders"]],
        "submitted": 0, "orders_enabled": False,
    }
    if not gate["allowed"]:
        report["result"] = "DRY_RUN"
        return report
    if open_sleeve:
        report["result"] = "BLOCKED_OPEN_SLEEVE_ORDERS"
        return report
    if not bool(_val(client.get_clock(), "is_open", False)):
        report["result"] = "BLOCKED_MARKET_CLOSED"
        return report
    report["orders_enabled"] = True
    existing_ids = {str(_val(o, "client_order_id", "")) for o in orders}
    for order in plan["orders"]:
        if order.client_order_id in existing_ids:
            continue
        kwargs = dict(symbol=order.symbol, side=OrderSide.BUY if order.side == "buy" else OrderSide.SELL,
                      type=OrderType.MARKET, time_in_force=TimeInForce.DAY, client_order_id=order.client_order_id)
        if order.side == "buy":
            kwargs["notional"] = float(order.notional_usd)
        else:
            kwargs["qty"] = float(order.qty)
        client.submit_order(order_data=MarketOrderRequest(**kwargs))
        report["submitted"] += 1
    report["result"] = "SUBMITTED"
    return report


def public_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate fields only, safe for public workflow logs (no order IDs)."""
    return {
        "strategy": report.get("strategy"), "mode": report.get("mode"), "result": report.get("result"),
        "blocked_by": report.get("execution_gate", {}).get("blocked_by"),
        "signal_session_utc": report.get("signal_session_utc"),
        "sleeve_equity_usd": report.get("sleeve_equity_usd"), "sleeve_cash_usd": report.get("sleeve_cash_usd"),
        "planned": [{k: o[k] for k in ("symbol", "side", "notional_usd", "qty")} for o in report.get("planned_orders", [])],
        "submitted": report.get("submitted"),
    }


def _weights_from_market_data(strategy: str, now: datetime) -> Dict[str, Any]:
    import rocket_trader_allocation_research_t05_v0_1 as t05
    import rocket_trader_t05_forward_shadow as fwd
    from rocket_trader_equity_multiyear_research_v0_4 import (
        fetch_daily_bars, historical_request_end, require_zero_budget_feed,
    )
    feed = require_zero_budget_feed("SIP", end_time=historical_request_end(now))
    frames = {s: fetch_daily_bars(s, years=fwd.HISTORY_YEARS, feed_name=feed, now=now) for s in UNIVERSE}
    _o, close, _a = t05.align_frames(frames)
    row = fwd.latest_completed_month_end(close.index, now)
    w = t05.RULES[strategy](close, row)
    return {"target_weights": {k: float(v) for k, v in w.items()}, "signal_session_utc": close.index[row].isoformat()}


def _fees_from_broker(sleeve_start: datetime) -> Decimal:
    import requests
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    resp = requests.get("https://paper-api.alpaca.markets/v2/account/activities/FEE",
                        params={"after": sleeve_start.isoformat(), "page_size": 100},
                        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}, timeout=30)
    resp.raise_for_status()
    total = Decimal(0)
    for row in resp.json():
        amount = _d(row.get("net_amount", "0"), "fee net_amount")
        total += -amount if amount < 0 else amount
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="research_artifacts/allocation_executor_report.json")
    a = ap.parse_args()
    mode = os.getenv("ROCKET_TRADER_ALLOCATION_MODE", "DRY_RUN").strip().upper()
    approval = os.getenv("ROCKET_TRADER_ALLOCATION_APPROVAL_REF", "").strip()
    strategy = os.getenv("ROCKET_TRADER_ALLOCATION_STRATEGY", DEFAULT_STRATEGY).strip()
    initial = _d(os.getenv("ROCKET_TRADER_ALLOCATION_SLEEVE_USD", "54.00"), "sleeve USD")
    start_raw = os.getenv("ROCKET_TRADER_ALLOCATION_SLEEVE_START", "2026-11-26T00:00:00+00:00")
    start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    from alpaca.trading.client import TradingClient
    client = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
    now = datetime.now(timezone.utc)
    report = run(client=client, weights_fn=lambda: _weights_from_market_data(strategy, now),
                 fees_fn=_fees_from_broker, mode=mode, approval_ref=approval, strategy=strategy,
                 initial_usd=initial, sleeve_start=start, now=now)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("ROCKET_TRADER_ALLOCATION_EXECUTOR " + json.dumps(public_summary(report), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
