#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — T06 turn-of-month calendar research v0.1 (pre-registered).

RESEARCH ONLY. No trading client, no orders.

Turn-of-month (TOM) effect: equity returns concentrate around month ends
(Ariel 1987; Lakonishok & Smidt 1988). The calendar is known in advance, so the
schedule involves no look-ahead. Our clock: each TOM "day" t earns the
open(t)->open(t+1) return. TOM days = the last session of each month plus the
first three sessions of the next month (i.e. held from the open of day -1 to the
open of day +4). All other days are cash at 0%.

Primary test per instrument (8 ETFs + equal-weight basket; Holm, family 9):
mean daily open-to-open return on TOM days minus mean on non-TOM days, over the
full post-publication window, with a circular-shift permutation p-value that
preserves the clustering of the calendar mask.
Pre-registration: RESEARCH_T06_TURN_OF_MONTH_PREREGISTRATION_v0_1.md
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import rocket_trader_allocation_research_t05_v0_1 as t05
from rocket_trader_equity_multiyear_research_v0_4 import (
    data_quality_metrics,
    fetch_daily_bars,
    fetch_yahoo_daily_bars,
    historical_request_end,
    holm_adjust,
    normalize_symbol,
    require_zero_budget_feed,
)

VERSION = "0.1"
EXPERIMENT_ID = "T06-TOM-v0.1"
PIPELINE = "rocket_trader_calendar_research_t06_v0_1"
DEFAULT_SYMBOLS = t05.DEFAULT_SYMBOLS
BASKET = "EQUAL_WEIGHT_BASKET"
TOM_BEFORE = 1
TOM_AFTER = 3
COST_BPS_SIDE = 5.0
STRESS = (2.0, 3.0)
ALPHA = 0.05
FOLDS = 5
MIN_POSITIVE_FOLDS = 4
MIN_SHIFT = 5


class CalendarResearchError(RuntimeError):
    pass


def tom_mask(index: pd.DatetimeIndex, before: int = TOM_BEFORE, after: int = TOM_AFTER) -> np.ndarray:
    """Boolean mask over rows: last `before` sessions of each month and first `after` of the next."""
    ny = index.tz_convert("America/New_York").tz_localize(None) if index.tz is not None else index
    month = ny.to_period("M")
    n = len(index)
    mask = np.zeros(n, dtype=bool)
    pos_in_month = np.zeros(n, dtype=int)
    from_end = np.zeros(n, dtype=int)
    start = 0
    for i in range(1, n + 1):
        if i == n or month[i] != month[start]:
            length = i - start
            pos_in_month[start:i] = np.arange(length)
            from_end[start:i] = np.arange(length)[::-1]
            start = i
    mask |= from_end < before
    mask |= pos_in_month < after
    # Partial first/last months in the sample cannot be classified reliably.
    first_month_end = np.argmax(month != month[0]) if (month != month[0]).any() else n
    last_month_start = n - int(np.argmax((month != month[-1])[::-1])) if (month != month[-1]).any() else 0
    valid = np.zeros(n, dtype=bool)
    valid[first_month_end:last_month_start] = True
    return mask & valid, valid


def forward_returns(open_df: pd.DataFrame) -> pd.DataFrame:
    return (open_df.shift(-1) / open_df - 1.0).iloc[:-1]


def circular_shift_pvalue(returns: np.ndarray, mask: np.ndarray, min_shift: int = MIN_SHIFT) -> Dict[str, float]:
    """One-sided p-value for mean(TOM) - mean(non-TOM) > 0 via all circular shifts of the mask."""
    r = np.asarray(returns, float)
    m = np.asarray(mask, bool)
    if len(r) != len(m) or m.sum() < 20 or (~m).sum() < 20 or not np.isfinite(r).all():
        raise CalendarResearchError("Insufficient or invalid observations for the TOM test.")
    def diff(mm):
        return float(r[mm].mean() - r[~mm].mean())
    observed = diff(m)
    n = len(r)
    null = [diff(np.roll(m, k)) for k in range(min_shift, n - min_shift)]
    p = (1 + sum(1 for x in null if x >= observed)) / (1 + len(null))
    return {"observed_diff_daily": observed, "p_value": p, "shifts": len(null)}


def strategy_metrics(returns: pd.Series, mask: np.ndarray, cost_bps_side: float) -> Dict[str, float]:
    """Hold on TOM days, cash otherwise; cost on every entry and exit."""
    w = pd.Series(mask.astype(float), index=returns.index)
    turnover = (w - w.shift(1).fillna(0.0)).abs()
    turnover.iloc[-1] += w.iloc[-1]
    net = w * returns - turnover * cost_bps_side / 1e4
    eq = (1 + net).cumprod()
    years = len(net) / 252.0
    sd = float(net.std(ddof=1))
    bh_eq = (1 + returns).cumprod()
    bh_sd = float(returns.std(ddof=1))
    return {
        "total_return": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1) if eq.iloc[-1] > 0 else -1.0,
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "sharpe": float(net.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
        "exposure": float(w.mean()),
        "round_trips": int((turnover > 0).sum() // 2),
        "buy_hold_total_return": float(bh_eq.iloc[-1] - 1),
        "buy_hold_max_drawdown": float((bh_eq / bh_eq.cummax() - 1).min()),
        "buy_hold_sharpe": float(returns.mean() / bh_sd * math.sqrt(252)) if bh_sd > 0 else 0.0,
        "net_mean_per_tom_day_bps": float(net[mask].mean() * 1e4),
    }


def evaluate(open_df: pd.DataFrame) -> Dict[str, Any]:
    rets = forward_returns(open_df)
    rets[BASKET] = rets[list(open_df.columns)].mean(axis=1)  # daily-rebalanced reference basket
    mask_all, valid = tom_mask(rets.index)
    rets = rets[valid]
    mask = mask_all[valid]
    n = len(rets)
    hold_lo = int(n * 0.8)
    edges = [int(round(n * k / FOLDS)) for k in range(FOLDS + 1)]
    out: Dict[str, Any] = {"instruments": {}}
    pvals: Dict[str, float] = {}
    for col in list(open_df.columns) + [BASKET]:
        r = rets[col]
        test = circular_shift_pvalue(r.to_numpy(), mask)
        pvals[col] = test["p_value"]
        folds = []
        for a, b in zip(edges[:-1], edges[1:]):
            rr, mm = r.iloc[a:b].to_numpy(), mask[a:b]
            folds.append(float(rr[mm].mean() - rr[~mm].mean()))
        hr, hm = r.iloc[hold_lo:].to_numpy(), mask[hold_lo:]
        entry = {
            "tom_days": int(mask.sum()), "non_tom_days": int((~mask).sum()),
            "tom_mean_daily_bps": float(r[mask].mean() * 1e4),
            "non_tom_mean_daily_bps": float(r[~mask].mean() * 1e4),
            "diff_daily_bps": test["observed_diff_daily"] * 1e4,
            "p_value": test["p_value"],
            "fold_diffs_bps": [x * 1e4 for x in folds],
            "positive_folds": int(sum(1 for x in folds if x > 0)),
            "holdout_diff_bps": float((hr[hm].mean() - hr[~hm].mean()) * 1e4),
            "strategy_base_cost": strategy_metrics(r, mask, COST_BPS_SIDE),
            "strategy_stress": {f"{m:g}x": strategy_metrics(r, mask, COST_BPS_SIDE * m) for m in STRESS},
        }
        out["instruments"][col] = entry
    adjusted = holm_adjust(pvals)
    passes = 0
    for col, e in out["instruments"].items():
        e["holm_p"] = adjusted[col]
        crit = {
            "holm_significant": adjusted[col] <= ALPHA,
            "positive_in_min_folds": e["positive_folds"] >= MIN_POSITIVE_FOLDS,
            "positive_holdout_diff": e["holdout_diff_bps"] > 0,
            "net_positive_per_tom_day_at_2x": e["strategy_stress"]["2x"]["net_mean_per_tom_day_bps"] > 0,
        }
        e["pre_registered_criteria"] = crit
        e["pre_screen_pass"] = all(crit.values())
        passes += int(e["pre_screen_pass"])
    out["multiple_testing"] = {"method": "HOLM_BONFERRONI", "alpha": ALPHA, "family_size": len(pvals),
                               "raw_pvalues": pvals, "holm_adjusted_pvalues": adjusted,
                               "pre_screen_pass_count": passes, "promotion_allowed": False}
    out["evaluation_sessions"] = n
    out["first_session"] = rets.index[0].isoformat()
    out["last_session"] = rets.index[-1].isoformat()
    out["holdout_first_session"] = rets.index[hold_lo].isoformat()
    return out


def research(symbols: Sequence[str] = DEFAULT_SYMBOLS, years: int = 10, source: str = "ALPACA",
             frames: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    source = source.upper()
    clean = sorted({normalize_symbol(s) for s in symbols})
    base = {"ok": False, "version": VERSION, "experiment_id": EXPERIMENT_ID, "pipeline": PIPELINE,
            "mode": "RESEARCH_ONLY", "source": source,
            "preregistration": "RESEARCH_T06_TURN_OF_MONTH_PREREGISTRATION_v0_1.md",
            "candidate_promotion_allowed": False, "paper_approval": False,
            "orders_enabled": False, "orders_submitted": 0}
    if frames is None:
        frames = {}
        feed = require_zero_budget_feed("SIP", end_time=historical_request_end()) if source == "ALPACA" else None
        for s in clean:
            frames[s] = fetch_yahoo_daily_bars(s, years=years) if source == "YAHOO" else fetch_daily_bars(s, years=years, feed_name=feed)
    quality = {s: data_quality_metrics(f) for s, f in frames.items()}
    bad = sorted(s for s, q in quality.items() if not q.get("eligible_for_strategy_evidence"))
    if bad:
        return {**base, "data_quality_pass": False, "symbols_with_data_quality_issues": bad}
    open_df, _close, alignment = t05.align_frames(frames)
    return {**base, "ok": True, "data_quality_pass": True, "alignment": alignment,
            "parameters": {"tom_before": TOM_BEFORE, "tom_after": TOM_AFTER, "cost_bps_side": COST_BPS_SIDE,
                           "stress": list(STRESS), "folds": FOLDS, "min_positive_folds": MIN_POSITIVE_FOLDS,
                           "test": "circular-shift permutation, one-sided"},
            **evaluate(open_df)}


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: result.get(k) for k in ("ok", "experiment_id", "source", "first_session", "holdout_first_session", "last_session")}
    if result.get("ok"):
        out["instruments"] = {k: {"diff_bps": round(e["diff_daily_bps"], 2), "holm_p": round(e["holm_p"], 4),
                                  "folds": e["positive_folds"], "holdout_diff_bps": round(e["holdout_diff_bps"], 2),
                                  "tom_sharpe": round(e["strategy_base_cost"]["sharpe"], 2),
                                  "bh_sharpe": round(e["strategy_base_cost"]["buy_hold_sharpe"], 2),
                                  "tom_mdd": round(e["strategy_base_cost"]["max_drawdown"], 3),
                                  "bh_mdd": round(e["strategy_base_cost"]["buy_hold_max_drawdown"], 3),
                                  "exposure": round(e["strategy_base_cost"]["exposure"], 3),
                                  "pass": e["pre_screen_pass"]}
                              for k, e in result["instruments"].items()}
        out["pre_screen_pass_count"] = result["multiple_testing"]["pre_screen_pass_count"]
    out["orders_submitted"] = 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="ALPACA", choices=["ALPACA", "YAHOO"])
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--output", default="research_artifacts/calendar_research_t06_v0_1.json")
    a = ap.parse_args()
    result = research(years=a.years, source=a.source)
    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("ROCKET_TRADER_T06_SUMMARY " + json.dumps(summarize(result), sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
