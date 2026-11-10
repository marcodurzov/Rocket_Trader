#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Same-market, same-date, same-cost benchmark harness for Rocket Trader.

Reads daily close prices and a candidate's gross daily returns/one-way turnover.
Builds cash, buy-and-hold, time-series momentum, skip-month momentum and
50/200-day trend references. It is research-only and never promotes a strategy.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, List, Sequence, Tuple


class BenchmarkInputError(ValueError):
    pass


@dataclass(frozen=True)
class DailyPrice:
    date: str
    close: float


@dataclass(frozen=True)
class CandidateDay:
    date: str
    gross_return: float
    turnover: float


def _finite(value: str, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkInputError(f"{field} must be numeric.") from exc
    if not math.isfinite(result):
        raise BenchmarkInputError(f"{field} must be finite.")
    return result


def load_prices(path: str) -> Dict[str, List[DailyPrice]]:
    result: Dict[str, List[DailyPrice]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "symbol", "close"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise BenchmarkInputError("Price CSV requires date,symbol,close columns.")
        for row in reader:
            symbol = str(row["symbol"]).strip().upper()
            date = str(row["date"]).strip()
            close = _finite(row["close"], "close")
            if not symbol or not date or close <= 0:
                raise BenchmarkInputError("Price rows require symbol/date and positive close.")
            result.setdefault(symbol, []).append(DailyPrice(date, close))
    if not result:
        raise BenchmarkInputError("Price file contains no rows.")
    for symbol, rows in result.items():
        rows.sort(key=lambda item: item.date)
        dates = [row.date for row in rows]
        if len(dates) != len(set(dates)):
            raise BenchmarkInputError(f"Duplicate price dates for {symbol}.")
        if len(rows) < 3:
            raise BenchmarkInputError(f"At least three prices are required for {symbol}.")
    return result


def load_candidate(path: str) -> Dict[str, List[CandidateDay]]:
    result: Dict[str, List[CandidateDay]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "symbol", "gross_return", "turnover"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise BenchmarkInputError(
                "Candidate CSV requires date,symbol,gross_return,turnover columns."
            )
        for row in reader:
            symbol = str(row["symbol"]).strip().upper()
            date = str(row["date"]).strip()
            gross = _finite(row["gross_return"], "gross_return")
            turnover = _finite(row["turnover"], "turnover")
            if not symbol or not date or gross <= -1 or turnover < 0 or turnover > 1:
                raise BenchmarkInputError("Candidate row has invalid symbol/date/return/turnover.")
            result.setdefault(symbol, []).append(CandidateDay(date, gross, turnover))
    if not result:
        raise BenchmarkInputError("Candidate file contains no rows.")
    for symbol, rows in result.items():
        rows.sort(key=lambda item: item.date)
        dates = [row.date for row in rows]
        if len(dates) != len(set(dates)):
            raise BenchmarkInputError(f"Duplicate candidate dates for {symbol}.")
    return result


def _compound(returns: Sequence[float]) -> float:
    value = 1.0
    for item in returns:
        if not math.isfinite(item) or item <= -1:
            raise BenchmarkInputError("A net daily return is invalid.")
        value *= 1.0 + item
    return value - 1.0


def metrics(returns: Sequence[float], turnover: Sequence[float],
            cost_bps: Sequence[float]) -> Dict[str, float]:
    if not returns:
        raise BenchmarkInputError("Cannot calculate metrics for an empty return series.")
    equity = [1.0]
    for item in returns:
        if item <= -1 or not math.isfinite(item):
            raise BenchmarkInputError("Net returns must be finite and greater than -100%.")
        equity.append(equity[-1] * (1.0 + item))
    peak = equity[0]
    max_drawdown = 0.0
    for value in equity[1:]:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    daily_vol = pstdev(returns) if len(returns) > 1 else 0.0
    total = equity[-1] - 1.0
    years = len(returns) / 252.0
    cagr = equity[-1] ** (1.0 / years) - 1.0 if years > 0 and equity[-1] > 0 else -1.0
    return {
        "observations": len(returns),
        "total_return": total,
        "cagr": cagr,
        "annualized_volatility": daily_vol * math.sqrt(252.0),
        "sharpe_zero_rf": mean(returns) / daily_vol * math.sqrt(252.0) if daily_vol > 0 else 0.0,
        "max_drawdown": max_drawdown,
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "average_daily_return": mean(returns),
        "one_way_turnover": sum(turnover),
        "estimated_cost_bps": sum(cost_bps),
    }


def _net(gross: Sequence[float], turnover: Sequence[float],
         cost_bps_per_side: float) -> Tuple[List[float], List[float]]:
    costs = [float(t) * cost_bps_per_side / 10000.0 for t in turnover]
    return [float(r) - cost for r, cost in zip(gross, costs)], costs


def build_references(prices: Sequence[DailyPrice], cost_bps_per_side: float
                     ) -> Dict[str, Tuple[List[float], List[float], List[float]]]:
    closes = [row.close for row in prices]
    daily = [0.0] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    n = len(closes)
    output = {}

    # Cash has no turnover and no modeled market cost.
    zero = [0.0] * n
    output["cash"] = (zero, zero, zero)

    # Buy-and-hold includes one full entry and one full terminal liquidation.
    bh_turnover = [0.0] * n
    bh_turnover[0] = 1.0
    bh_turnover[-1] += 1.0
    bh_net, bh_cost = _net(daily, bh_turnover, cost_bps_per_side)
    output["buy_and_hold"] = (bh_net, bh_turnover, [x * 10000 for x in bh_cost])

    strategies = {
        "time_series_momentum_252d": lambda i: closes[i - 1] / closes[i - 253] - 1.0
            if i >= 253 else None,
        "momentum_63d_skip_21d": lambda i: closes[i - 22] / closes[i - 85] - 1.0
            if i >= 85 else None,
        "sma_50_200_trend": lambda i: (
            mean(closes[i - 50:i]) / mean(closes[i - 200:i]) - 1.0
            if i >= 200 else None
        ),
    }
    for name, signal in strategies.items():
        position = 0.0
        gross, turnover = [], []
        for i in range(n):
            if i > 0:
                value = signal(i)
                if value is not None:
                    position = 1.0 if value > 0 else 0.0
            gross.append(position * daily[i])
            turnover.append(abs(position - (1.0 if i > 0 and gross[i - 1] != 0 else 0.0)))
        # Compute turnover from actual target-position transitions, not return sign.
        position = 0.0
        turnover = []
        for i in range(n):
            if i > 0:
                value = signal(i)
                if value is not None:
                    target = 1.0 if value > 0 else 0.0
                else:
                    target = position
            else:
                target = position
            turnover.append(abs(target - position))
            position = target
        if position > 0:
            turnover[-1] += position  # terminal liquidation
        net, cost = _net(gross, turnover, cost_bps_per_side)
        output[name] = (net, turnover, [x * 10000 for x in cost])
    return output


def compare(prices: Dict[str, List[DailyPrice]],
            candidates: Dict[str, List[CandidateDay]],
            cost_bps_per_side: float) -> Dict[str, object]:
    if not math.isfinite(cost_bps_per_side) or cost_bps_per_side < 0:
        raise BenchmarkInputError("cost_bps_per_side must be finite and non-negative.")
    missing = sorted(set(candidates) - set(prices))
    if missing:
        raise BenchmarkInputError(f"Candidate symbols have no matching price series: {missing}")
    results = []
    for symbol, candidate_rows in sorted(candidates.items()):
        price_rows = prices[symbol]
        price_dates = [row.date for row in price_rows]
        candidate_dates = [row.date for row in candidate_rows]
        if price_dates != candidate_dates:
            raise BenchmarkInputError(
                f"{symbol}: candidate and price dates must match exactly; "
                "do not compare different periods or silently intersect dates."
            )
        if len(price_rows) < 253:
            raise BenchmarkInputError(
                f"{symbol}: at least 253 daily prices are required for the 12-month trend reference."
            )
        candidate_gross = [row.gross_return for row in candidate_rows]
        candidate_turnover = [row.turnover for row in candidate_rows]
        candidate_net, candidate_cost = _net(
            candidate_gross, candidate_turnover, cost_bps_per_side
        )
        benchmark_series = build_references(price_rows, cost_bps_per_side)
        benchmark_metrics = {
            name: metrics(returns, turnover, costs)
            for name, (returns, turnover, costs) in benchmark_series.items()
        }
        candidate_metrics = metrics(
            candidate_net, candidate_turnover,
            [x * 10000 for x in candidate_cost],
        )
        comparisons = {}
        for name, values in benchmark_metrics.items():
            comparisons[name] = {
                "candidate_minus_benchmark_total_return":
                    candidate_metrics["total_return"] - values["total_return"],
                "candidate_sharpe_minus_benchmark":
                    candidate_metrics["sharpe_zero_rf"] - values["sharpe_zero_rf"],
                "candidate_max_drawdown_minus_benchmark":
                    candidate_metrics["max_drawdown"] - values["max_drawdown"],
            }
        results.append({
            "symbol": symbol,
            "start_date": price_dates[0],
            "end_date": price_dates[-1],
            "observations": len(price_dates),
            "cost_bps_per_side": cost_bps_per_side,
            "candidate": candidate_metrics,
            "benchmarks": benchmark_metrics,
            "comparisons": comparisons,
        })
    return {
        "schema_version": 1,
        "pipeline": "rocket_trader_same_market_benchmark",
        "status": "COMPARISON_ONLY",
        "research_approval": False,
        "strategy_promotion_enabled": False,
        "orders_enabled": False,
        "orders_submitted": 0,
        "comparability_policy": {
            "same_symbol": True, "same_exact_dates": True,
            "same_cost_assumption": True, "candidate_returns_are_gross": True,
            "turnover_is_one_way_fraction_of_nav": True,
        },
        "reference_families": [
            "buy_and_hold_market_baseline",
            "time_series_momentum_252d",
            "momentum_63d_skip_21d",
            "sma_50_200_trend",
            "cash",
        ],
        "results": results,
        "limitations": [
            "Reference rules are testable adaptations, not a reproduction of any trader's personal account.",
            "Published academic/institutional returns are not copied into this report.",
            "Daily close data cannot establish executable bid/ask prices or realized slippage.",
            "No statistical significance or strategy promotion is inferred from this comparison.",
            "Candidate gross returns and turnover must be generated point-in-time without look-ahead.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Same-date, same-cost strategy benchmark audit.")
    parser.add_argument("--prices", required=True, help="CSV: date,symbol,close")
    parser.add_argument("--candidate", required=True, help="CSV: date,symbol,gross_return,turnover")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cost-bps-per-side", type=float, required=True)
    args = parser.parse_args()
    try:
        result = compare(load_prices(args.prices), load_candidate(args.candidate),
                         args.cost_bps_per_side)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"ok": True, "symbols": len(result["results"]),
                          "status": result["status"], "orders_enabled": False}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "error": str(exc), "orders_enabled": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
