#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — T05 monthly allocation research v0.1 (pre-registered).

RESEARCH ONLY. No broker trading client, no orders, no account mutation.

Pre-registration: ``RESEARCH_T05_ALLOCATION_PREREGISTRATION_v0_1.md``. The
hypothesis family, parameters, costs, windows and pass criteria below are fixed
by that document and must not be tuned after seeing results. A new parameter
set is a new, separately registered experiment.

Execution clock (identical to equity research v0.4): weights are decided from
data up to the close of the last XNYS session of each month and take effect at
the next session's open; each day earns open-to-next-open returns. Between
rebalances weights drift with prices (no free daily rebalancing). Unallocated
weight is cash earning 0% (conservative: no T-bill yield is credited).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from rocket_trader_equity_multiyear_research_v0_4 import (
    bootstrap_relative_pvalue,
    data_quality_metrics,
    fetch_daily_bars,
    fetch_yahoo_daily_bars,
    historical_request_end,
    holm_adjust,
    normalize_symbol,
    require_zero_budget_feed,
)

VERSION = "0.1"
PIPELINE = "rocket_trader_allocation_research_t05_v0_1"
EXPERIMENT_ID = "T05-ALLOC-MONTHLY-v0.1"
DEFAULT_SYMBOLS = ("DIA", "EEM", "EFA", "GLD", "IWM", "QQQ", "SPY", "TLT")
DEFAULT_YEARS = 10
WARMUP_SESSIONS = 253
VOL_LOOKBACK = 63
SMA_LOOKBACK = 210
MOMENTUM_LOOKBACK = 252
MOMENTUM_SKIP = 21
DUAL_MOMENTUM_TOP_N = 3
VOL_TARGET_ANNUAL = 0.10
BASE_COST_BPS_SIDE = 5.0
STRESS_MULTIPLIERS = (2.0, 3.0)
PVALUE_REPS = 5000
PVALUE_BLOCK = 21
FAMILYWISE_ALPHA = 0.05
FOLDS = 5
MIN_POSITIVE_FOLDS = 4
MIN_COMMON_COVERAGE = 0.95
HYPOTHESES = (
    "inverse_vol_63d",
    "sma210_trend_equal_weight",
    "dual_momentum_top3_12_1",
    "vol_target_equal_weight_10pct",
    "sma210_trend_inverse_vol",
)


class AllocationResearchError(RuntimeError):
    """Fail-closed research error."""


@dataclass(frozen=True)
class PortfolioMetrics:
    sessions: int
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe_annualized: float
    volatility_annualized: float
    average_exposure: float
    turnover: float
    rebalances: int


# --------------------------------------------------------------------------
# Data alignment
# --------------------------------------------------------------------------

def align_frames(frames: Dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Inner-join open/close on exact timestamps; fail closed on poor overlap."""
    if len(frames) < 2:
        raise AllocationResearchError("At least two symbols are required.")
    opens, closes = {}, {}
    for symbol, frame in frames.items():
        f = frame.set_index("timestamp")
        if f.index.has_duplicates:
            raise AllocationResearchError(f"{symbol}: duplicate timestamps.")
        opens[symbol] = f["open"].astype(float)
        closes[symbol] = f["close"].astype(float)
    open_df = pd.DataFrame(opens).dropna().sort_index()
    close_df = pd.DataFrame(closes).reindex(open_df.index)
    if close_df.isna().any().any():
        raise AllocationResearchError("Close prices missing on common open sessions.")
    coverage = {s: len(open_df) / len(frames[s]) for s in frames}
    low = {s: c for s, c in coverage.items() if c < MIN_COMMON_COVERAGE}
    if low:
        raise AllocationResearchError(f"Common-session coverage below {MIN_COMMON_COVERAGE}: {low}")
    if (open_df <= 0).any().any() or (close_df <= 0).any().any():
        raise AllocationResearchError("Non-positive prices after alignment.")
    return open_df, close_df, {
        "common_sessions": int(len(open_df)),
        "first_common_session": open_df.index[0].isoformat(),
        "last_common_session": open_df.index[-1].isoformat(),
        "coverage_by_symbol": {s: round(c, 6) for s, c in sorted(coverage.items())},
    }


def month_end_positions(index: pd.DatetimeIndex) -> List[int]:
    """Integer positions of the last available session in each calendar month.

    The final month is excluded when it is the last row, because a signal on the
    final close cannot be executed inside the sample.
    """
    if len(index) == 0:
        return []
    ny = index.tz_convert("America/New_York").tz_localize(None) if index.tz is not None else index
    period = pd.Series(ny.to_period("M"), index=range(len(ny)))
    ends = [int(i) for i in period.index[period != period.shift(-1)]]
    return [i for i in ends if i < len(index) - 1]


# --------------------------------------------------------------------------
# Pre-registered target-weight rules (use data up to and including row i)
# --------------------------------------------------------------------------

MIN_SIGNAL_ROW = max(MOMENTUM_LOOKBACK, SMA_LOOKBACK, VOL_LOOKBACK)


def _require_history(i: int) -> None:
    # Negative iloc offsets would silently wrap to the end of the sample.
    if i < MIN_SIGNAL_ROW:
        raise AllocationResearchError(f"Signal row {i} lacks {MIN_SIGNAL_ROW} sessions of history.")


def _inverse_vol(close: pd.DataFrame, i: int) -> pd.Series:
    _require_history(i)
    rets = close.pct_change().iloc[i - VOL_LOOKBACK + 1:i + 1]
    vol = rets.std(ddof=1)
    if vol.isna().any() or (vol <= 0).any():
        raise AllocationResearchError("Invalid trailing volatility.")
    inv = 1.0 / vol
    return inv / inv.sum()


def _trend_mask(close: pd.DataFrame, i: int) -> pd.Series:
    _require_history(i)
    sma = close.iloc[i - SMA_LOOKBACK + 1:i + 1].mean()
    return (close.iloc[i] > sma).astype(float)


def target_inverse_vol(close: pd.DataFrame, i: int) -> pd.Series:
    return _inverse_vol(close, i)


def target_trend_equal_weight(close: pd.DataFrame, i: int) -> pd.Series:
    return _trend_mask(close, i) / close.shape[1]


def target_dual_momentum(close: pd.DataFrame, i: int) -> pd.Series:
    _require_history(i)
    score = close.iloc[i - MOMENTUM_SKIP] / close.iloc[i - MOMENTUM_LOOKBACK] - 1.0
    eligible = score[score > 0].sort_values(ascending=False, kind="mergesort")
    chosen = list(eligible.index[:DUAL_MOMENTUM_TOP_N])
    weights = pd.Series(0.0, index=close.columns)
    if chosen:
        weights[chosen] = 1.0 / DUAL_MOMENTUM_TOP_N
    return weights


def target_vol_target_equal_weight(close: pd.DataFrame, i: int) -> pd.Series:
    _require_history(i)
    rets = close.pct_change().iloc[i - VOL_LOOKBACK + 1:i + 1]
    ew = rets.mean(axis=1)
    vol = float(ew.std(ddof=1)) * math.sqrt(252.0)
    if not math.isfinite(vol) or vol <= 0:
        raise AllocationResearchError("Invalid portfolio volatility.")
    scale = min(1.0, VOL_TARGET_ANNUAL / vol)
    return pd.Series(scale / close.shape[1], index=close.columns)


def target_trend_inverse_vol(close: pd.DataFrame, i: int) -> pd.Series:
    return _inverse_vol(close, i) * _trend_mask(close, i)


def target_equal_weight(close: pd.DataFrame, i: int) -> pd.Series:
    return pd.Series(1.0 / close.shape[1], index=close.columns)


RULES: Dict[str, Callable[[pd.DataFrame, int], pd.Series]] = {
    "inverse_vol_63d": target_inverse_vol,
    "sma210_trend_equal_weight": target_trend_equal_weight,
    "dual_momentum_top3_12_1": target_dual_momentum,
    "vol_target_equal_weight_10pct": target_vol_target_equal_weight,
    "sma210_trend_inverse_vol": target_trend_inverse_vol,
}
BENCHMARK = "equal_weight_monthly"


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def simulate(
    open_df: pd.DataFrame,
    close_df: pd.DataFrame,
    rule: Callable[[pd.DataFrame, int], pd.Series],
    *,
    cost_bps_side: float,
    start: int = WARMUP_SESSIONS,
) -> Dict[str, pd.Series]:
    """Daily open-to-next-open simulation with month-end signals and drift.

    Returns per-day series aligned to session index positions [start, n-1):
    net return, gross exposure at the start of the day and turnover traded at
    that day's open. The last row has no forward open and is excluded.
    """
    n = len(open_df)
    if start < max(MOMENTUM_LOOKBACK, SMA_LOOKBACK, VOL_LOOKBACK) or start >= n - 2:
        raise AllocationResearchError("Invalid simulation start.")
    fwd = (open_df.shift(-1) / open_df - 1.0).to_numpy(dtype=float)
    signal_rows = set(month_end_positions(open_df.index))
    cost = cost_bps_side / 10000.0
    weights = np.zeros(open_df.shape[1])
    pending: Optional[np.ndarray] = None
    # The first allocation uses the latest month-end signal at or before start-1.
    prior_ends = [i for i in signal_rows if MIN_SIGNAL_ROW <= i < start]
    if prior_ends:
        pending = rule(close_df, max(prior_ends)).reindex(open_df.columns).to_numpy(dtype=float)
    net, exposure, turnover = [], [], []
    for t in range(start, n - 1):
        traded = 0.0
        if pending is not None:
            target = np.clip(np.nan_to_num(pending, nan=0.0), 0.0, 1.0)
            if target.sum() > 1.0 + 1e-9:
                raise AllocationResearchError("Target weights exceed 100% (no leverage).")
            traded = float(np.abs(target - weights).sum())
            weights = target
            pending = None
        r = fwd[t]
        if not np.isfinite(r).all():
            raise AllocationResearchError("Non-finite forward return.")
        gross = float(weights @ r)
        daily = gross - traded * cost
        net.append(daily)
        exposure.append(float(weights.sum()))
        turnover.append(traded)
        denom = 1.0 + gross
        if denom <= 0:
            raise AllocationResearchError("Portfolio wiped out in simulation.")
        weights = weights * (1.0 + r) / denom
        if t in signal_rows:
            pending = rule(close_df, t).reindex(open_df.columns).to_numpy(dtype=float)
    # Liquidate at the final available open (cost only; no return).
    if net:
        net[-1] -= float(weights.sum()) * cost
        turnover[-1] += float(weights.sum())
    idx = open_df.index[start:n - 1]
    return {
        "net": pd.Series(net, index=idx),
        "exposure": pd.Series(exposure, index=idx),
        "turnover": pd.Series(turnover, index=idx),
    }


def metrics(sim: Dict[str, pd.Series], lo: int, hi: int) -> PortfolioMetrics:
    x = sim["net"].iloc[lo:hi]
    n = len(x)
    if n < 2:
        raise AllocationResearchError("Window too short.")
    eq = (1.0 + x).cumprod()
    dd = eq / eq.cummax() - 1.0
    sd = float(x.std(ddof=1))
    years = n / 252.0
    return PortfolioMetrics(
        sessions=n,
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=float(eq.iloc[-1] ** (1.0 / years) - 1.0) if eq.iloc[-1] > 0 else -1.0,
        max_drawdown=float(dd.min()),
        sharpe_annualized=float(x.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0,
        volatility_annualized=sd * math.sqrt(252.0),
        average_exposure=float(sim["exposure"].iloc[lo:hi].mean()),
        turnover=float(sim["turnover"].iloc[lo:hi].sum()),
        rebalances=int((sim["turnover"].iloc[lo:hi] > 1e-12).sum()),
    )


def windows(n: int) -> Dict[str, tuple[int, int]]:
    train_end, val_end = int(n * 0.60), int(n * 0.80)
    return {
        "full_period": (0, n),
        "train_60pct": (0, train_end),
        "validation_20pct": (train_end, val_end),
        "final_holdout_20pct": (val_end, n),
    }


def fold_bounds(n: int, folds: int = FOLDS) -> List[tuple[int, int]]:
    edges = [int(round(n * k / folds)) for k in range(folds + 1)]
    return [(edges[k], edges[k + 1]) for k in range(folds)]


def evaluate(open_df: pd.DataFrame, close_df: pd.DataFrame) -> Dict[str, Any]:
    sims: Dict[float, Dict[str, Dict[str, pd.Series]]] = {}
    for mult in (1.0,) + STRESS_MULTIPLIERS:
        cost = BASE_COST_BPS_SIDE * mult
        sims[mult] = {name: simulate(open_df, close_df, rule, cost_bps_side=cost) for name, rule in RULES.items()}
        sims[mult][BENCHMARK] = simulate(open_df, close_df, target_equal_weight, cost_bps_side=cost)
    base = sims[1.0]
    n = len(base[BENCHMARK]["net"])
    win = windows(n)
    hold_lo, hold_hi = win["final_holdout_20pct"]
    folds = fold_bounds(n)
    spy = None
    if "SPY" in open_df.columns:
        spy_ret = (open_df["SPY"].shift(-1) / open_df["SPY"] - 1.0).iloc[WARMUP_SESSIONS:len(open_df) - 1]
        spy = {"net": spy_ret, "exposure": pd.Series(1.0, index=spy_ret.index),
               "turnover": pd.Series(0.0, index=spy_ret.index)}

    report: Dict[str, Any] = {"benchmark": {}, "hypotheses": {}}
    report["benchmark"][BENCHMARK] = {w: asdict(metrics(base[BENCHMARK], lo, hi)) for w, (lo, hi) in win.items()}
    if spy is not None:
        report["benchmark"]["spy_buy_and_hold_reference_no_costs"] = {
            w: asdict(metrics(spy, lo, hi)) for w, (lo, hi) in win.items()
        }
    pvalues: Dict[str, float] = {}
    for name in RULES:
        sim = base[name]
        entry: Dict[str, Any] = {w: asdict(metrics(sim, lo, hi)) for w, (lo, hi) in win.items()}
        bench_h = base[BENCHMARK]["net"].iloc[hold_lo:hold_hi].to_numpy(dtype=float)
        strat_h = sim["net"].iloc[hold_lo:hold_hi].to_numpy(dtype=float)
        seed = 20261122 + sum(ord(c) for c in name)
        p = bootstrap_relative_pvalue(strat_h, bench_h, seed=seed, reps=PVALUE_REPS, block_size=PVALUE_BLOCK)
        pvalues[name] = p
        hold = entry["final_holdout_20pct"]
        hold["excess_total_return_vs_benchmark"] = (
            hold["total_return"] - report["benchmark"][BENCHMARK]["final_holdout_20pct"]["total_return"]
        )
        hold["bootstrap_p_value_excess_vs_benchmark"] = p
        stress = {}
        for mult in STRESS_MULTIPLIERS:
            s = metrics(sims[mult][name], hold_lo, hold_hi)
            b = metrics(sims[mult][BENCHMARK], hold_lo, hold_hi)
            stress[f"{mult:g}x"] = {"strategy_total_return": s.total_return,
                                    "benchmark_total_return": b.total_return,
                                    "excess_total_return": s.total_return - b.total_return}
        hold["cost_stress"] = stress
        fold_excess = []
        for lo, hi in folds:
            fold_excess.append(metrics(sim, lo, hi).total_return - metrics(base[BENCHMARK], lo, hi).total_return)
        entry["fold_excess_total_return_vs_benchmark"] = fold_excess
        entry["positive_folds"] = int(sum(1 for x in fold_excess if x > 0))
        report["hypotheses"][name] = entry
    adjusted = holm_adjust(pvalues)
    passes = 0
    for name, entry in report["hypotheses"].items():
        hold = entry["final_holdout_20pct"]
        adj = adjusted.get(name)
        hold["holm_adjusted_p_value"] = adj
        criteria = {
            "holm_significant": adj is not None and adj <= FAMILYWISE_ALPHA,
            "positive_holdout_excess_at_2x_cost": hold["cost_stress"]["2x"]["excess_total_return"] > 0,
            "positive_in_min_folds": entry["positive_folds"] >= MIN_POSITIVE_FOLDS,
            "full_period_sharpe_not_below_benchmark": (
                entry["full_period"]["sharpe_annualized"]
                >= report["benchmark"][BENCHMARK]["full_period"]["sharpe_annualized"]
            ),
        }
        entry["pre_registered_criteria"] = criteria
        entry["pre_screen_pass"] = all(criteria.values())
        passes += int(entry["pre_screen_pass"])
    report["multiple_testing"] = {
        "method": "HOLM_BONFERRONI",
        "alpha": FAMILYWISE_ALPHA,
        "family_size": len(pvalues),
        "raw_pvalues": pvalues,
        "holm_adjusted_pvalues": adjusted,
        "familywise_significant_count": int(sum(1 for v in adjusted.values() if v <= FAMILYWISE_ALPHA)),
        "pre_screen_pass_count": passes,
        "promotion_allowed": False,
    }
    report["evaluation_sessions"] = n
    report["evaluation_first_session"] = base[BENCHMARK]["net"].index[0].isoformat()
    report["final_holdout_first_session"] = base[BENCHMARK]["net"].index[hold_lo].isoformat()
    report["evaluation_last_session"] = base[BENCHMARK]["net"].index[-1].isoformat()
    return report


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def research(
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    years: int = DEFAULT_YEARS,
    source: str = "ALPACA",
    feed_name: str = "SIP",
    frames: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Any]:
    source = str(source).strip().upper()
    if source not in {"ALPACA", "YAHOO", "OFFLINE"}:
        raise ValueError("source must be ALPACA, YAHOO or OFFLINE")
    clean = sorted({normalize_symbol(s) for s in symbols})
    common = {
        "ok": False, "version": VERSION, "pipeline": PIPELINE, "experiment_id": EXPERIMENT_ID,
        "mode": "RESEARCH_ONLY", "source": source, "symbols": clean,
        "preregistration": "RESEARCH_T05_ALLOCATION_PREREGISTRATION_v0_1.md",
        "candidate_promotion_allowed": False, "paper_approval": False,
        "orders_enabled": False, "orders_submitted": 0,
    }
    failures = []
    if frames is None:
        frames = {}
        if source == "ALPACA":
            feed_name = require_zero_budget_feed(feed_name, end_time=historical_request_end())
        for s in clean:
            try:
                frames[s] = (fetch_yahoo_daily_bars(s, years=years) if source == "YAHOO"
                             else fetch_daily_bars(s, years=years, feed_name=feed_name))
            except Exception as exc:  # fail closed, keep cause class only
                failures.append({"symbol": s, "error": f"{type(exc).__name__}: {exc}"})
    if failures:
        return {**common, "symbols_failed": failures}
    quality = {s: data_quality_metrics(f) for s, f in frames.items()}
    ineligible = sorted(s for s, q in quality.items() if not q.get("eligible_for_strategy_evidence"))
    if ineligible:
        return {**common, "data_quality_pass": False, "symbols_with_data_quality_issues": ineligible,
                "data_quality": quality}
    open_df, close_df, alignment = align_frames(frames)
    result = evaluate(open_df, close_df)
    return {
        **common, "ok": True, "data_quality_pass": True, "alignment": alignment,
        "parameters": {
            "warmup_sessions": WARMUP_SESSIONS, "vol_lookback": VOL_LOOKBACK,
            "sma_lookback": SMA_LOOKBACK, "momentum_lookback": MOMENTUM_LOOKBACK,
            "momentum_skip": MOMENTUM_SKIP, "dual_momentum_top_n": DUAL_MOMENTUM_TOP_N,
            "vol_target_annual": VOL_TARGET_ANNUAL, "base_cost_bps_side": BASE_COST_BPS_SIDE,
            "stress_multipliers": list(STRESS_MULTIPLIERS), "pvalue_reps": PVALUE_REPS,
            "pvalue_block": PVALUE_BLOCK, "folds": FOLDS, "min_positive_folds": MIN_POSITIVE_FOLDS,
            "cash_yield": 0.0, "execution": "month-end close signal -> next open; open-to-open returns; drifting weights",
        },
        "cost_note": "5 bps/side ETF friction is an unvalidated assumption; 2x/3x stress reported.",
        **result,
    }


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, log-friendly summary."""
    out = {k: result.get(k) for k in ("ok", "experiment_id", "source", "data_quality_pass",
                                      "evaluation_first_session", "final_holdout_first_session",
                                      "evaluation_last_session", "orders_submitted")}
    if result.get("ok"):
        bench = result["benchmark"][BENCHMARK]
        out["benchmark_holdout_total_return"] = bench["final_holdout_20pct"]["total_return"]
        out["benchmark_full_sharpe"] = bench["full_period"]["sharpe_annualized"]
        out["benchmark_full_max_drawdown"] = bench["full_period"]["max_drawdown"]
        out["hypotheses"] = {
            name: {
                "holdout_excess": e["final_holdout_20pct"]["excess_total_return_vs_benchmark"],
                "holm_p": e["final_holdout_20pct"]["holm_adjusted_p_value"],
                "positive_folds": e["positive_folds"],
                "full_sharpe": e["full_period"]["sharpe_annualized"],
                "full_max_drawdown": e["full_period"]["max_drawdown"],
                "full_cagr": e["full_period"]["cagr"],
                "pre_screen_pass": e["pre_screen_pass"],
            }
            for name, e in result["hypotheses"].items()
        }
        out["pre_screen_pass_count"] = result["multiple_testing"]["pre_screen_pass_count"]
    return out


def synthetic_frames(seed: int = 7, sessions: int = 900) -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=sessions, tz="UTC") + pd.Timedelta(hours=21)
    frames = {}
    for k, s in enumerate(DEFAULT_SYMBOLS):
        r = rng.normal(0.0003 + 0.0001 * k, 0.01 + 0.001 * k, sessions)
        close = 100 * np.exp(np.cumsum(r))
        open_ = close * np.exp(rng.normal(0, 0.002, sessions))
        hi = np.maximum(open_, close) * 1.001
        lo = np.minimum(open_, close) * 0.999
        frames[s] = pd.DataFrame({"timestamp": idx, "open": open_, "high": hi, "low": lo,
                                  "close": close, "volume": 1e6})
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    parser.add_argument("--source", default="ALPACA", choices=["ALPACA", "YAHOO"])
    parser.add_argument("--feed", default="SIP", choices=["IEX", "SIP"])
    parser.add_argument("--output", default="research_artifacts/allocation_research_t05_v0_1.json")
    args = parser.parse_args()
    if args.years < 3:
        parser.error("--years must be >= 3")
    result = research(args.symbols, args.years, args.source, args.feed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("ROCKET_TRADER_T05_SUMMARY " + json.dumps(summarize(result), sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
