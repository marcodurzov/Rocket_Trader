#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — empirical quoted-spread study v0.1 (measurement, research only).

Measures the *quoted* bid/ask half-spread that a small marketable order would
pay relative to the midpoint, using free historical data:

* US ETFs: Alpaca historical SIP quotes (request end >= 16 minutes old), at six
  fixed New York times on each of the last N completed XNYS sessions.
* Crypto: Alpaca historical crypto quotes (Alpaca's own venue, where orders
  would execute), hourly over the last N days.

It compares the measured half-spread with the half-spread assumptions currently
used by research (ETF 2.5 bps/side, crypto 10 bps/side). It does NOT measure
slippage beyond the quote, latency, partial fills, market impact or fees; those
need real Paper fills. No orders; no trading client.
Pre-registration: COSTS_SPREAD_STUDY_PREREGISTRATION_v0_1.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
STUDY_ID = "COSTS-SPREAD-v0.1"
ETF_SYMBOLS = ("DIA", "EEM", "EFA", "GLD", "IWM", "QQQ", "SPY", "TLT")
CRYPTO_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
ETF_SAMPLE_TIMES = (time(9, 35), time(10, 30), time(12, 0), time(13, 30), time(15, 0), time(15, 55))
ETF_WINDOW_SECONDS = 60
CRYPTO_WINDOW_SECONDS = 300
ASSUMED_HALF_SPREAD_BPS = {"ETF": 2.5, "CRYPTO": 10.0}
SIP_SAFETY_MINUTES = 16
MIN_VALID_SAMPLE_SHARE = 0.80


class SpreadStudyError(RuntimeError):
    pass


def half_spread_bps(bid: Any, ask: Any) -> Optional[float]:
    """Half the quoted spread in bps of the midpoint; None for unusable quotes."""
    try:
        b, a = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(b) and math.isfinite(a)) or b <= 0 or a <= 0 or a <= b:
        return None  # missing, locked or crossed quotes are excluded, not zeroed
    mid = (a + b) / 2.0
    return (a - b) / 2.0 / mid * 1e4


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(values: Sequence[float], attempted: int, assumed: float) -> Dict[str, Any]:
    n = len(values)
    out = {
        "samples_attempted": attempted,
        "samples_valid": n,
        "valid_share": (n / attempted) if attempted else 0.0,
        "assumed_half_spread_bps": assumed,
    }
    if n:
        out.update({
            "median_bps": percentile(values, 0.5),
            "p75_bps": percentile(values, 0.75),
            "p90_bps": percentile(values, 0.90),
            "p95_bps": percentile(values, 0.95),
            "max_bps": max(values),
            "mean_bps": sum(values) / n,
        })
    if n == 0 or out["valid_share"] < MIN_VALID_SAMPLE_SHARE:
        verdict = "INSUFFICIENT_DATA"
    elif out["p90_bps"] <= assumed:
        verdict = "ASSUMPTION_COVERS_P90"
    elif out["median_bps"] <= assumed:
        verdict = "ASSUMPTION_COVERS_MEDIAN_ONLY"
    else:
        verdict = "ASSUMPTION_TOO_LOW"
    out["verdict"] = verdict
    return out


def completed_sessions(now: datetime, count: int) -> List[date]:
    """Last `count` XNYS sessions whose 16:00 close is >= SIP safety buffer old."""
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS")
    end = (now.astimezone(NY) - timedelta(minutes=SIP_SAFETY_MINUTES)).date()
    sessions = cal.sessions_in_range(end - timedelta(days=count * 2 + 20), end)
    usable = []
    for s in sessions:
        close = cal.session_close(s).to_pydatetime()
        if close <= now - timedelta(minutes=SIP_SAFETY_MINUTES):
            usable.append(s.date())
    if len(usable) < count:
        raise SpreadStudyError("Not enough completed sessions.")
    return usable[-count:]


def etf_sample_points(sessions: Iterable[date], early_close: Callable[[date], Optional[time]] = lambda d: None):
    for d in sessions:
        close_t = early_close(d)
        for t in ETF_SAMPLE_TIMES:
            if close_t is not None and t >= close_t:
                continue
            yield d, t, datetime.combine(d, t, tzinfo=NY).astimezone(timezone.utc)


def crypto_sample_points(now: datetime, days: int):
    start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    t = start
    while t <= now - timedelta(hours=1):
        yield t
        t += timedelta(hours=1)


def last_valid_quote(quotes: Sequence[Any]) -> Optional[float]:
    """Half-spread of the latest usable quote in the window (ordered by time)."""
    best = None
    best_ts = None
    for q in quotes:
        hs = half_spread_bps(getattr(q, "bid_price", None), getattr(q, "ask_price", None))
        ts = getattr(q, "timestamp", None)
        if hs is None or ts is None:
            continue
        if best_ts is None or ts >= best_ts:
            best, best_ts = hs, ts
    return best


def _quotes_by_symbol(response: Any) -> Dict[str, List[Any]]:
    data = getattr(response, "data", response) or {}
    return {str(k): list(v or []) for k, v in dict(data).items()}


def run_study(*, now: datetime, sessions: int, crypto_days: int,
              stock_fetch: Callable[[List[str], datetime, datetime], Dict[str, List[Any]]],
              crypto_fetch: Callable[[List[str], datetime, datetime], Dict[str, List[Any]]],
              session_list: Optional[List[date]] = None,
              early_close: Callable[[date], Optional[time]] = lambda d: None) -> Dict[str, Any]:
    session_list = session_list or completed_sessions(now, sessions)
    etf_vals: Dict[str, List[float]] = {s: [] for s in ETF_SYMBOLS}
    etf_by_time: Dict[str, Dict[str, List[float]]] = {s: {} for s in ETF_SYMBOLS}
    etf_attempts = 0
    for _d, t, ts in etf_sample_points(session_list, early_close):
        etf_attempts += 1
        got = stock_fetch(list(ETF_SYMBOLS), ts - timedelta(seconds=ETF_WINDOW_SECONDS), ts)
        for s in ETF_SYMBOLS:
            hs = last_valid_quote(got.get(s, []))
            if hs is not None:
                etf_vals[s].append(hs)
                etf_by_time[s].setdefault(t.strftime("%H:%M"), []).append(hs)
    crypto_vals: Dict[str, List[float]] = {s: [] for s in CRYPTO_SYMBOLS}
    crypto_attempts = 0
    for ts in crypto_sample_points(now, crypto_days):
        crypto_attempts += 1
        got = crypto_fetch(list(CRYPTO_SYMBOLS), ts - timedelta(seconds=CRYPTO_WINDOW_SECONDS), ts)
        for s in CRYPTO_SYMBOLS:
            hs = last_valid_quote(got.get(s, []))
            if hs is not None:
                crypto_vals[s].append(hs)
    etf = {s: summarize(v, etf_attempts, ASSUMED_HALF_SPREAD_BPS["ETF"]) for s, v in etf_vals.items()}
    for s in ETF_SYMBOLS:
        etf[s]["median_bps_by_new_york_time"] = {k: percentile(v, 0.5) for k, v in sorted(etf_by_time[s].items())}
    crypto = {s: summarize(v, crypto_attempts, ASSUMED_HALF_SPREAD_BPS["CRYPTO"]) for s, v in crypto_vals.items()}
    return {
        "ok": True, "study_id": STUDY_ID, "mode": "MEASUREMENT_RESEARCH_ONLY",
        "generated_at_utc": now.isoformat(),
        "etf_sessions": [d.isoformat() for d in session_list],
        "etf_sample_times_new_york": [t.strftime("%H:%M") for t in ETF_SAMPLE_TIMES],
        "crypto_days": crypto_days,
        "etf": etf, "crypto": crypto,
        "scope_note": ("Quoted half-spread only (marketable order vs midpoint at top of book). "
                       "Excludes fees, slippage beyond the quote, latency, partial fills and impact."),
        "cost_assumptions_validated": False,
        "orders_enabled": False, "orders_submitted": 0,
    }


def summary_line(result: Dict[str, Any]) -> Dict[str, Any]:
    def compact(block):
        return {s: {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in m.items() if k in ("samples_valid", "valid_share", "median_bps", "p90_bps", "p95_bps", "verdict")}
                for s, m in block.items()}
    return {"study_id": result["study_id"], "ok": result["ok"], "etf": compact(result["etf"]),
            "crypto": compact(result["crypto"]), "orders_submitted": 0}


PER_SYMBOL_QUOTE_LIMIT = 100


def _alpaca_fetchers(stocks: Any = None, crypto: Any = None):
    """One request per symbol, newest first.

    Run 45187950954 used one multi-symbol request with a 10,000-quote limit;
    liquid ETFs (SPY, QQQ, TLT) produce more quotes than that in 60 s, so their
    samples were truncated away. Newest-first per symbol avoids that bias.
    """
    from alpaca.common.enums import Sort
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import CryptoQuoteRequest, StockQuotesRequest
    if stocks is None or crypto is None:
        from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise SpreadStudyError("ALPACA_API_KEY/ALPACA_SECRET_KEY are required (read-only market data).")
        stocks = stocks or StockHistoricalDataClient(key, secret)
        crypto = crypto or CryptoHistoricalDataClient(key, secret)

    def stock_fetch(symbols, start, end):
        if end > datetime.now(timezone.utc) - timedelta(minutes=SIP_SAFETY_MINUTES):
            raise SpreadStudyError("SIP request end must be at least 16 minutes old (free plan).")
        out: Dict[str, List[Any]] = {}
        for sym in symbols:
            req = StockQuotesRequest(symbol_or_symbols=sym, start=start, end=end, feed=DataFeed.SIP,
                                     limit=PER_SYMBOL_QUOTE_LIMIT, sort=Sort.DESC)
            out.update(_quotes_by_symbol(stocks.get_stock_quotes(req)))
        return out

    def crypto_fetch(symbols, start, end):
        out: Dict[str, List[Any]] = {}
        for sym in symbols:
            req = CryptoQuoteRequest(symbol_or_symbols=sym, start=start, end=end,
                                     limit=PER_SYMBOL_QUOTE_LIMIT, sort=Sort.DESC)
            out.update(_quotes_by_symbol(crypto.get_crypto_quotes(req)))
        return out

    return stock_fetch, crypto_fetch


def _early_close_lookup():
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS")

    def early(d: date) -> Optional[time]:
        close = cal.session_close(d).tz_convert(NY)
        return close.time() if close.time() < time(16, 0) else None
    return early


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=40)
    parser.add_argument("--crypto-days", type=int, default=14)
    parser.add_argument("--output", default="research_artifacts/spread_study_v0_1.json")
    args = parser.parse_args()
    stock_fetch, crypto_fetch = _alpaca_fetchers()
    result = run_study(now=datetime.now(timezone.utc), sessions=args.sessions, crypto_days=args.crypto_days,
                       stock_fetch=stock_fetch, crypto_fetch=crypto_fetch, early_close=_early_close_lookup())
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("ROCKET_TRADER_SPREAD_STUDY " + json.dumps(summary_line(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
