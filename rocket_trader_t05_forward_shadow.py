#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — T05 forward shadow recorder (pre-registered forward test).

RESEARCH ONLY. No broker trading client, no orders.

Once per month this records, for the most recent *completed* calendar month,
the month-end closes and the target weights of every T05 rule plus the
equal-weight benchmark. Records are written once and never rewritten. Forward
performance is evaluated later from these records and subsequent prices, giving
genuinely out-of-sample evidence (data that did not exist when the rules were
fixed). See ``RESEARCH_T05_FORWARD_SHADOW_PREREGISTRATION_v0_1.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

import rocket_trader_allocation_research_t05_v0_1 as t05
from rocket_trader_equity_multiyear_research_v0_4 import (
    fetch_daily_bars,
    historical_request_end,
    require_zero_budget_feed,
)

RECORD_VERSION = "t05-forward-shadow-v0.1"
HISTORY_YEARS = 3


class ForwardShadowError(RuntimeError):
    """Fail-closed recorder error."""


def latest_completed_month_end(index: pd.DatetimeIndex, now: datetime) -> int:
    """Row of the last session of the most recent month that has fully ended."""
    ny_index = index.tz_convert("America/New_York").tz_localize(None)
    ny_now = pd.Timestamp(now).tz_convert("America/New_York").tz_localize(None)
    current = ny_now.to_period("M")
    periods = ny_index.to_period("M")
    rows = [i for i in range(len(index)) if periods[i] < current
            and (i == len(index) - 1 or periods[i + 1] != periods[i])]
    if not rows:
        raise ForwardShadowError("No completed month in the data.")
    row = rows[-1]
    if row < t05.MIN_SIGNAL_ROW:
        raise ForwardShadowError("Insufficient history before the completed month-end.")
    # The month must be complete in the data: a later session must exist or the
    # calendar month must have ended (guaranteed by periods[i] < current).
    return row


def build_record(close_df: pd.DataFrame, row: int, *, source: str, now: datetime) -> Dict[str, Any]:
    weights = {name: {k: round(float(v), 10) for k, v in rule(close_df, row).items()}
               for name, rule in t05.RULES.items()}
    weights[t05.BENCHMARK] = {k: round(float(v), 10) for k, v in t05.target_equal_weight(close_df, row).items()}
    for name, w in weights.items():
        total = sum(w.values())
        if total < -1e-12 or total > 1.0 + 1e-9:
            raise ForwardShadowError(f"{name}: invalid total weight {total}")
    session = close_df.index[row]
    record = {
        "record_version": RECORD_VERSION,
        "experiment_id": t05.EXPERIMENT_ID,
        "signal_month": session.tz_convert("America/New_York").strftime("%Y-%m"),
        "signal_session_utc": session.isoformat(),
        "recorded_at_utc": now.astimezone(timezone.utc).isoformat(),
        "source": source,
        "execution_rule": "weights take effect at the next session open after signal_session",
        "month_end_close": {k: float(v) for k, v in close_df.iloc[row].items()},
        "target_weights": weights,
        "orders_enabled": False,
        "orders_submitted": 0,
    }
    payload = json.dumps(record, sort_keys=True).encode()
    record["sha256_of_record_without_hash"] = hashlib.sha256(payload).hexdigest()
    return record


def record_path(root: Path, signal_month: str) -> Path:
    return root / "forward" / "t05" / f"{signal_month}.json"


def write_once(root: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    path = record_path(root, record["signal_month"])
    if path.exists():
        return {"written": False, "reason": "RECORD_ALREADY_EXISTS", "path": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"written": True, "path": str(path)}


def run(root: Path, *, now: Optional[datetime] = None, frames: Optional[Dict[str, pd.DataFrame]] = None,
        source: str = "ALPACA_SIP") -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if frames is None:
        feed = require_zero_budget_feed("SIP", end_time=historical_request_end(now))
        frames = {s: fetch_daily_bars(s, years=HISTORY_YEARS, feed_name=feed, now=now) for s in t05.DEFAULT_SYMBOLS}
    _, close_df, alignment = t05.align_frames(frames)
    row = latest_completed_month_end(close_df.index, now)
    record = build_record(close_df, row, source=source, now=now)
    outcome = write_once(root, record)
    return {"ok": True, "signal_month": record["signal_month"], "alignment": alignment,
            "orders_submitted": 0, **outcome}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Checkout of the forward-evidence branch")
    args = parser.parse_args()
    result = run(Path(args.root))
    print("ROCKET_TRADER_T05_FORWARD " + json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
