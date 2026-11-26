#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T05 independent historical sample 2005-2016 (pre-registered), research only.

Re-tests the *unchanged* T05 rules on data never used by any Rocket Trader
experiment (all earlier work used 2016-11 onward). The window includes the
2008 crisis, so it is the first real test of the trend rules as a drawdown
control. Source: Yahoo adjusted daily bars only (Alpaca SIP starts in 2016).
No orders. Pre-registration: RESEARCH_T05_HIST_2005_2016_PREREGISTRATION_v0_1.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import rocket_trader_allocation_research_t05_v0_1 as t05
from rocket_trader_equity_multiyear_research_v0_4 import fetch_yahoo_daily_bars

EXPERIMENT_ID = "T05-HIST-2005-2016-v0.1"
WINDOW_END = datetime(2016, 11, 18, 21, 0, tzinfo=timezone.utc)  # last session before any prior study window
WINDOW_YEARS = 11
RISK_RULES = ("sma210_trend_equal_weight", "sma210_trend_inverse_vol")
MIN_DD_REDUCTION_PP = 0.10
MAX_CAGR_SHORTFALL = 0.03
MAX_SHARPE_SHORTFALL = 0.05


def drawdown_criteria(result: Dict[str, Any]) -> Dict[str, Any]:
    bench = result["benchmark"][t05.BENCHMARK]["full_period"]
    out = {}
    for name in RISK_RULES:
        full = result["hypotheses"][name]["full_period"]
        crit = {
            "max_dd_reduction_pp": full["max_drawdown"] - bench["max_drawdown"],
            "cagr_shortfall": bench["cagr"] - full["cagr"],
            "sharpe_shortfall": bench["sharpe_annualized"] - full["sharpe_annualized"],
        }
        crit["pass"] = (crit["max_dd_reduction_pp"] >= MIN_DD_REDUCTION_PP
                        and crit["cagr_shortfall"] <= MAX_CAGR_SHORTFALL
                        and crit["sharpe_shortfall"] <= MAX_SHARPE_SHORTFALL)
        out[name] = crit
    return out


def run(frames: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if frames is None:
        frames = {s: fetch_yahoo_daily_bars(s, years=WINDOW_YEARS, end=WINDOW_END) for s in t05.DEFAULT_SYMBOLS}
    result = t05.research(source="YAHOO", frames=frames)
    result["experiment_id"] = EXPERIMENT_ID
    result["preregistration"] = "RESEARCH_T05_HIST_2005_2016_PREREGISTRATION_v0_1.md"
    result["window_end"] = WINDOW_END.isoformat()
    if result.get("ok"):
        result["drawdown_control"] = drawdown_criteria(result)
        result["drawdown_control_pass_count"] = sum(1 for v in result["drawdown_control"].values() if v["pass"])
    result["candidate_promotion_allowed"] = False
    result["orders_submitted"] = 0
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="research_artifacts/t05_hist_2005_2016_v0_1.json")
    a = ap.parse_args()
    result = run()
    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    summary = t05.summarize(result)
    summary["experiment_id"] = EXPERIMENT_ID
    summary["benchmark_full_cagr"] = (result.get("benchmark") or {}).get(t05.BENCHMARK, {}).get("full_period", {}).get("cagr")
    summary["drawdown_control"] = result.get("drawdown_control")
    print("ROCKET_TRADER_T05_HIST_SUMMARY " + json.dumps(summary, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
