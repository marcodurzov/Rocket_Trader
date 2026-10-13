#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader traditional strategy research v0.4.
RESEARCH ONLY: reads Alpaca historical data; never submits or manages orders.
Adds tri-state lagged daily regime, session-level regime audit, gate impact diagnostics,
and automated no-lookahead/date-alignment tests.
"""
from __future__ import annotations
import argparse, json, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict
import numpy as np
import pandas as pd

VERSION = "0.4"
BAR_MINUTES = 5
ROUND_TRIP_TRANSACTION_COST = 0.00020
SLIPPAGE_PER_SIDE = 0.00010
NY = ZoneInfo("America/New_York")
COST_MULTIPLIERS = (1.0, 2.0, 3.0)


def _alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY.")
    return StockHistoricalDataClient(key, secret)


def fetch_bars(symbol: str, days: int, daily: bool = False, chunk_days: int = 25) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    client = _alpaca_client()
    symbol = symbol.strip().upper()
    end = datetime.now(timezone.utc)
    # Extra calendar warm-up gives the daily SMA200 enough observations.
    start = end - timedelta(days=(max(days, 500) if daily else days))
    chunks, cursor = [], start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        tf = TimeFrame.Day if daily else TimeFrame(BAR_MINUTES, TimeFrameUnit.Minute)
        request = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=cursor,
                                   end=chunk_end, limit=10000, feed=DataFeed.IEX)
        response = client.get_stock_bars(request)
        try:
            bars = response[symbol]
            records = [{"timestamp": b.timestamp, "open": b.open, "high": b.high,
                        "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
        except (KeyError, TypeError, AttributeError):
            records = []
        if records:
            chunks.append(pd.DataFrame(records))
        cursor = chunk_end
    if not chunks:
        raise RuntimeError(f"Alpaca no devolvió barras para {symbol} ({'daily' if daily else '5m'}).")
    df = pd.concat(chunks, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    if not daily:
        # Timestamp is the bar start; keep 09:30 <= start < 16:00 New York time.
        local = df["timestamp"].dt.tz_convert(NY)
        minutes = local.dt.hour * 60 + local.dt.minute
        df = df[(local.dt.dayofweek < 5) & (minutes >= 570) & (minutes < 960)].reset_index(drop=True)
    if len(df) < (200 if daily else 1000):
        raise RuntimeError(f"Histórico insuficiente para {symbol}: {len(df)} barras.")
    return df


def add_lagged_daily_regime(intraday: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Attach the latest *strictly prior* completed daily close vs its SMA200.

    Uses an as-of join on New York session dates, so a missing current-session daily
    bar does not erase the prior regime and today's close can never leak into today's
    intraday decisions. Unknown is preserved separately from bearish.
    """
    d = daily.copy()
    d["session_date"] = pd.to_datetime(d["timestamp"], utc=True).dt.tz_convert(NY).dt.date
    d = d.sort_values("timestamp").drop_duplicates("session_date", keep="last").reset_index(drop=True)
    d["daily_sma200"] = d["close"].rolling(200, min_periods=200).mean()
    d["daily_regime_valid"] = d["daily_sma200"].notna()
    d["daily_bull_regime"] = np.where(
        d["daily_regime_valid"], d["close"] > d["daily_sma200"], np.nan
    )
    d["session_key"] = pd.to_datetime(d["session_date"])
    right = d[["session_key", "daily_regime_valid", "daily_bull_regime"]].sort_values("session_key")

    x = intraday.copy()
    x["session_date"] = pd.to_datetime(x["timestamp"], utc=True).dt.tz_convert(NY).dt.date
    x["session_key"] = pd.to_datetime(x["session_date"])
    x = pd.merge_asof(
        x.sort_values("session_key"), right, on="session_key", direction="backward",
        allow_exact_matches=False
    )
    x["daily_regime_valid"] = x["daily_regime_valid"].fillna(False).astype(bool)
    x["daily_bull_regime"] = x["daily_bull_regime"].astype("boolean")
    return x.drop(columns=["session_date", "session_key"])


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def strategy_signals(df: pd.DataFrame) -> Dict[str, pd.Series]:
    c = df["close"]
    ema_fast, ema_slow = c.ewm(span=12, adjust=False, min_periods=12).mean(), c.ewm(span=48, adjust=False, min_periods=48).mean()
    sma_fast, sma_slow = c.rolling(20).mean(), c.rolling(100).mean()
    sma_regime = c.rolling(200).mean()
    donchian_high, donchian_exit = df["high"].shift(1).rolling(20).max(), df["low"].shift(1).rolling(10).min()
    momentum20, r = c.pct_change(20), rsi(c, 14)
    ema_cross = (ema_fast > ema_slow) & ema_fast.notna() & ema_slow.notna()
    sma_cross = (sma_fast > sma_slow) & sma_fast.notna() & sma_slow.notna()
    donchian = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        hi, lo, close = donchian_high.iloc[i], donchian_exit.iloc[i], c.iloc[i]
        if not (np.isfinite(hi) and np.isfinite(lo)):
            donchian.iloc[i] = False; continue
        if not in_pos and close > hi: in_pos = True
        elif in_pos and close < lo: in_pos = False
        donchian.iloc[i] = in_pos
    pullback = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        ma, rv = sma_regime.iloc[i], r.iloc[i]
        if not (np.isfinite(ma) and np.isfinite(rv)):
            pullback.iloc[i] = False; continue
        if not in_pos and c.iloc[i] > ma and rv < 30: in_pos = True
        elif in_pos and (rv > 55 or c.iloc[i] < ma): in_pos = False
        pullback.iloc[i] = in_pos
    momentum = (c > sma_regime) & (momentum20 > 0) & sma_regime.notna()
    base = {"ema_12_48_trend": ema_cross, "sma_20_100_trend": sma_cross,
            "donchian_20_10_breakout": donchian, "rsi_pullback_above_sma200_intraday": pullback,
            "momentum_20_with_sma200_intraday_filter": momentum}
    # Daily filter is a separate ablation, not a claim that this filter is profitable.
    daily_gate = df["daily_bull_regime"].fillna(False).astype(bool) if "daily_bull_regime" in df else pd.Series(False, index=df.index)
    for name, sig in list(base.items()):
        base[f"{name}_daily200_gate"] = sig.fillna(False).astype(bool) & daily_gate
    return base


def simulate(df: pd.DataFrame, signal: pd.Series, round_trip_cost: float,
            slippage_per_side: float, initial_signal: bool = False) -> Dict[str, Any]:
    """Long-only, no leverage. Signal at close i is actionable at open i+1.

    Returns are open-to-open; each position change is charged once at its execution
    open. The terminal open-to-close interval is marked and an exit cost is charged
    if still invested. initial_signal can seed a flat-start holdout from the signal
    known at the close immediately before the holdout, without carrying prior PnL.
    """
    n = len(df)
    if n < 3:
        raise ValueError("Se necesitan al menos 3 barras.")
    sig = signal.fillna(False).astype(bool).to_numpy(dtype=int)
    pos = np.zeros(n, dtype=int)
    if initial_signal:
        pos[0] = int(bool(initial_signal))
    if n > 1:
        pos[1:] = sig[:-1]
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    side_cost = round_trip_cost / 2.0 + slippage_per_side
    # open-to-open return belongs to the position held at the first open.
    interval_returns = np.zeros(n - 1, dtype=float)
    turnover_costs = np.zeros(n - 1, dtype=float)
    for i in range(n - 1):
        gross = opens[i + 1] / opens[i] - 1.0
        prev_pos = pos[i - 1] if i > 0 else 0
        turnover = abs(int(pos[i]) - int(prev_pos))
        turnover_costs[i] = turnover * side_cost
        interval_returns[i] = (1.0 + pos[i] * gross) * (1.0 - turnover_costs[i]) - 1.0
    # Last partial interval plus a terminal liquidation fee if position remains open.
    terminal_gross = closes[-1] / opens[-1] - 1.0
    terminal_transition_cost = side_cost if int(pos[-1]) != int(pos[-2]) else 0.0
    terminal_exit_cost = side_cost if pos[-1] else 0.0
    terminal_ret = (1.0 + pos[-1] * terminal_gross) * (1.0 - terminal_transition_cost) * (1.0 - terminal_exit_cost) - 1.0
    all_returns = np.concatenate([interval_returns, [terminal_ret]])
    equity = np.cumprod(1.0 + all_returns)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    dd = equity / peaks - 1.0
    transitions = np.abs(np.diff(np.concatenate([[0], pos])))
    entries = int(np.sum((transitions == 1) & (pos == 1)))
    exits = int(np.sum((transitions == 1) & (pos == 0))) + int(pos[-1] == 1)
    dates = pd.to_datetime(df["timestamp"].iloc[1:].reset_index(drop=True), utc=True).dt.tz_convert(NY).dt.date
    daily = pd.DataFrame({"date": dates, "ret": interval_returns}).groupby("date")["ret"].apply(lambda x: float(np.prod(1 + x) - 1))
    std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily.mean() / std * math.sqrt(252)) if std > 0 else 0.0
    total = float(equity[-1] - 1.0)
    # Same-window buy-and-hold with one entry and one terminal exit friction.
    bh_gross = float(closes[-1] / opens[0] - 1.0)
    bh = float((1.0 + bh_gross) * (1.0 - side_cost) ** 2 - 1.0)
    # Exposure-matched benchmark: buy-and-hold only for the fraction of intervals
    # the strategy is exposed; diagnostic benchmark, not a tradable path.
    exposure = float(np.mean(pos))
    exposure_matched = float((1.0 + bh_gross) ** exposure * (1.0 - side_cost * 2.0 * exposure) - 1.0)
    return {
        "bars": n, "trades_entered": entries, "trades_exited": exits,
        "exposure_pct": exposure * 100.0, "total_return": total,
        "buy_hold_return_same_window_after_friction": bh,
        "excess_return_vs_buy_hold": total - bh,
        "exposure_matched_buy_hold_diagnostic": exposure_matched,
        "excess_return_vs_exposure_matched_diagnostic": total - exposure_matched,
        "max_drawdown": float(np.min(dd)) if len(dd) else 0.0,
        "daily_sharpe_annualized": sharpe,
        "profitable_days_pct": float(np.mean(daily.to_numpy() > 0) * 100) if len(daily) else 0.0,
        "daily_observations": int(len(daily)),
        "round_trip_transaction_cost": float(round_trip_cost),
        "slippage_per_side": float(slippage_per_side),
        "orders_enabled": False, "orders_submitted": 0,
    }

def evaluate_symbol(symbol: str, days: int, round_trip_cost: float, slippage_per_side: float) -> Dict[str, Any]:
    intraday = fetch_bars(symbol, days, daily=False)
    daily = fetch_bars(symbol, max(days, 500), daily=True)
    df = add_lagged_daily_regime(intraday, daily)
    signals = strategy_signals(df)
    split = int(len(df) * 0.60)
    hold_df = df.iloc[split:].reset_index(drop=True)
    # Keep the signal from the final pre-holdout close as a valid entry at the
    # first holdout open; do not carry prior-period PnL or position state.
    results = {}
    regime_valid = df["daily_regime_valid"].fillna(False).astype(bool)
    regime_bull = df["daily_bull_regime"].fillna(False).astype(bool)
    regime_bear = regime_valid & ~regime_bull
    base_names = [n for n in signals if not n.endswith("_daily200_gate")]

    def regime_summary(frame: pd.DataFrame) -> Dict[str, Any]:
        valid = frame["daily_regime_valid"].fillna(False).astype(bool)
        bull = frame["daily_bull_regime"].fillna(False).astype(bool) & valid
        bear = valid & ~bull
        unclassified = ~valid
        return {
            "bars": int(len(frame)),
            "sessions": int(pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(NY).dt.date.nunique()),
            "bullish_bars": int(bull.sum()), "bearish_bars": int(bear.sum()),
            "unclassified_bars": int(unclassified.sum()),
            "bullish_bar_pct": float(bull.mean() * 100) if len(frame) else 0.0,
            "bearish_bar_pct": float(bear.mean() * 100) if len(frame) else 0.0,
            "unclassified_bar_pct": float(unclassified.mean() * 100) if len(frame) else 0.0,
            "valid_bar_pct": float(valid.mean() * 100) if len(frame) else 0.0,
        }

    # Session-by-session table makes a 100% bullish holdout auditable rather than opaque.
    session_frame = df.copy()
    session_frame["session_date"] = pd.to_datetime(session_frame["timestamp"], utc=True).dt.tz_convert(NY).dt.date.astype(str)
    session_audit = []
    for session_date, group in session_frame.groupby("session_date", sort=True):
        valid = bool(group["daily_regime_valid"].fillna(False).all())
        bull = bool(group["daily_bull_regime"].fillna(False).all()) if valid else None
        session_audit.append({
            "date": session_date, "regime": ("BULLISH" if bull else "BEARISH") if valid else "UNCLASSIFIED",
            "bars": int(len(group)), "signals_by_strategy": {
                name: int(sig.loc[group.index].fillna(False).astype(bool).sum()) for name, sig in signals.items()
                if not name.endswith("_daily200_gate")
            }
        })
    split_date = str(session_frame["session_date"].iloc[split]) if split < len(session_frame) else None
    regime_diagnostics = {
        "daily_bars_available": int(len(daily)),
        "daily_sma200_valid_pct": float(daily["close"].rolling(200, min_periods=200).mean().notna().mean() * 100),
        "full_period": regime_summary(df),
        "train_selection_60pct": regime_summary(df.iloc[:split]),
        "holdout_40pct": regime_summary(df.iloc[split:]),
        "holdout_first_session": split_date,
        "session_regime_audit": session_audit,
        "interpretation": "UNCLASSIFIED means no valid prior completed daily SMA200; it is tracked separately and the gate blocks it."
    }
    ablations = {}
    for name, sig in signals.items():
        full = simulate(df, sig, round_trip_cost, slippage_per_side)
        hold_sig = sig.iloc[split:].reset_index(drop=True)
        initial = bool(sig.iloc[split - 1]) if split > 0 else False
        base_cost = simulate(hold_df, hold_sig, round_trip_cost, slippage_per_side, initial_signal=initial)
        stress = {}
        for mult in COST_MULTIPLIERS:
            stress[f"{mult:.0f}x"] = simulate(hold_df, hold_sig, round_trip_cost * mult,
                                               slippage_per_side * mult, initial_signal=initial)
        results[name] = {"full_period": full, "final_40pct_holdout_base_cost": base_cost,
                         "holdout_cost_stress": stress,
                         "holdout_initial_position_from_pre_split_signal": initial}
    # Ensure gated entries are present before summarizing ablation (the signal order
    # naturally lists all base variants first); recompute robustly for every pair.
    for name in base_names:
        gate_name = f"{name}_daily200_gate"
        ungated, gated = signals[name], signals[gate_name]
        ungated_n = int(ungated.iloc[split:].sum())
        gated_n = int(gated.iloc[split:].sum())
        ablations[name] = {
            "ungated_signal_bars_holdout": ungated_n,
            "gated_signal_bars_holdout": gated_n,
            "signal_bars_removed_pct_holdout": float((ungated_n-gated_n)/ungated_n*100) if ungated_n else 0.0,
            "ungated_holdout_return": results[name]["final_40pct_holdout_base_cost"]["total_return"],
            "gated_holdout_return": results[gate_name]["final_40pct_holdout_base_cost"]["total_return"],
            "ungated_holdout_trades": results[name]["final_40pct_holdout_base_cost"]["trades_entered"],
            "gated_holdout_trades": results[gate_name]["final_40pct_holdout_base_cost"]["trades_entered"],
            "holdout_bars_blocked_by_gate": int((ungated.iloc[split:].fillna(False).astype(bool) & ~df["daily_bull_regime"].iloc[split:].fillna(False).astype(bool)).sum()),
            "holdout_sessions_blocked_by_gate": int(pd.DataFrame({
                "date": pd.to_datetime(df["timestamp"].iloc[split:], utc=True).dt.tz_convert(NY).dt.date,
                "valid": df["daily_regime_valid"].iloc[split:].fillna(False).astype(bool),
                "bull": df["daily_bull_regime"].iloc[split:].fillna(False).astype(bool),
                "signal": ungated.iloc[split:].fillna(False).astype(bool)
            }).groupby("date").apply(lambda g: bool(g["signal"].any() and not (g["valid"].all() and g["bull"].all())), include_groups=False).sum()),
            "gate_return_delta": results[gate_name]["final_40pct_holdout_base_cost"]["total_return"] - results[name]["final_40pct_holdout_base_cost"]["total_return"],
        }
    # Split holdout into three chronological blocks for stability diagnostics only;
    # no block is used to choose parameters.
    consistency = {}
    for name, sig in signals.items():
        blocks = []
        for j, idx in enumerate(np.array_split(np.arange(split, len(df)), 3), 1):
            if len(idx) < 3:
                continue
            bdf = df.iloc[idx].reset_index(drop=True)
            bsig = sig.iloc[idx].reset_index(drop=True)
            init = bool(sig.iloc[idx[0]-1]) if idx[0] > 0 else False
            m = simulate(bdf, bsig, round_trip_cost, slippage_per_side, initial_signal=init)
            blocks.append({"block": j, "bars": m["bars"], "return": m["total_return"],
                           "trades": m["trades_entered"], "max_drawdown": m["max_drawdown"]})
        consistency[name] = {"blocks": blocks, "positive_blocks": sum(b["return"] > 0 for b in blocks)}
    return {
        "symbol": symbol, "version": VERSION, "data_source": "Alpaca IEX 5-minute and daily bars",
        "session_filter": "US regular session 09:30-16:00 America/New_York, weekdays only",
        "daily_regime_rule": "At session t, use only prior completed daily close vs prior completed 200-session SMA",
        "days_requested": days, "intraday_bars_received": len(df), "daily_bars_received": len(daily),
        "first_bar": str(df.timestamp.iloc[0]), "last_bar": str(df.timestamp.iloc[-1]),
        "holdout_split_index": split, "regime_diagnostics": regime_diagnostics,
        "daily_gate_ablation": ablations, "holdout_subperiod_consistency": consistency,
        "strategies": results, "mode": "RESEARCH_ONLY", "orders_enabled": False, "orders_submitted": 0,
    }

def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261013)
    n = 4000
    ts = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.00003, 0.001, n)))
    open_ = np.concatenate([[close[0]], close[:-1] * (1 + rng.normal(0, 0.0001, n-1))])
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close)*1.001,
        "low": np.minimum(open_, close)*0.999, "close": close, "volume": np.ones(n),
        "daily_bull_regime": pd.Series(np.arange(n) % 2 == 0, dtype="boolean"),
        "daily_regime_valid": np.ones(n, dtype=bool)})
    signals = strategy_signals(df)
    assert len(signals) == 10 and all(len(x) == n for x in signals.values())
    test_signal = pd.Series(False, index=df.index); test_signal.iloc[10:12] = True
    result = simulate(df, test_signal, 0.0002, 0.0001)
    sig = test_signal.astype(int).to_numpy(); pos = np.zeros(n, dtype=int); pos[1:] = sig[:-1]
    assert pos[10] == 0 and pos[11] == 1 and pos[12] == 1 and pos[13] == 0
    assert result["orders_enabled"] is False and result["orders_submitted"] == 0
    gated = signals["ema_12_48_trend_daily200_gate"]
    assert not bool((gated & ~df["daily_bull_regime"].fillna(False)).any())
    r1 = simulate(df, test_signal, 0.0002, 0.0001)["total_return"]
    r3 = simulate(df, test_signal, 0.0006, 0.0003)["total_return"]
    assert r3 <= r1 + 1e-12
    seed = simulate(df.iloc[:100].reset_index(drop=True), pd.Series(False, index=range(100)),
                    0.0002, 0.0001, initial_signal=True)
    flat = simulate(df.iloc[:100].reset_index(drop=True), pd.Series(False, index=range(100)),
                    0.0002, 0.0001, initial_signal=False)
    assert seed["exposure_pct"] > flat["exposure_pct"] and seed["trades_entered"] == 1
    terminal_sig = pd.Series(False, index=range(100)); terminal_sig.iloc[-2] = True
    terminal = simulate(df.iloc[:100].reset_index(drop=True), terminal_sig, 0.0002, 0.0001)
    assert terminal["exposure_pct"] > flat["exposure_pct"] and terminal["trades_entered"] == 1

    # No-lookahead test: today's regime must not change if today's daily close changes.
    dts = pd.date_range("2024-01-01", periods=260, freq="B", tz=NY).tz_convert("UTC")
    daily_close = np.linspace(100, 150, len(dts))
    daily = pd.DataFrame({"timestamp": dts, "open": daily_close, "high": daily_close,
                          "low": daily_close, "close": daily_close, "volume": 1000})
    intrats = pd.to_datetime(["2024-12-30T15:00:00Z", "2024-12-31T15:00:00Z"], utc=True)
    intra = pd.DataFrame({"timestamp": intrats, "open":[1,1], "high":[1,1], "low":[1,1],
                          "close":[1,1], "volume":[1,1]})
    aligned1 = add_lagged_daily_regime(intra, daily)
    changed = daily.copy()
    matching_date = intrats[0].tz_convert(NY).date()
    matching = pd.to_datetime(changed["timestamp"], utc=True).dt.tz_convert(NY).dt.date == matching_date
    if matching.any():
        changed.loc[matching, "close"] = 1.0
    aligned2 = add_lagged_daily_regime(intra, changed)
    assert aligned1.loc[0, "daily_bull_regime"] == aligned2.loc[0, "daily_bull_regime"]

    # Unknown regime stays unknown and is not silently classified as bearish.
    unknown = add_lagged_daily_regime(intra.iloc[:1].copy(), daily.iloc[:100].copy())
    assert not bool(unknown.loc[0, "daily_regime_valid"])
    assert pd.isna(unknown.loc[0, "daily_bull_regime"])
    return {"ok": True, "version": VERSION, "strategies_tested": list(signals),
        "next_bar_execution_lag_test": "PASS", "holdout_boundary_seed_test": "PASS",
        "daily_filter_gate_test": "PASS", "cost_stress_monotonicity_test": "PASS",
        "daily_regime_no_lookahead_test": "PASS", "unknown_regime_preservation_test": "PASS",
        "orders_enabled": False, "orders_submitted": 0}

def main() -> int:
    p=argparse.ArgumentParser(description="Traditional strategy research v0.2; research-only")
    p.add_argument("--self-test",action="store_true"); p.add_argument("--symbols",nargs="+",default=["SPY","QQQ"])
    p.add_argument("--days",type=int,default=365); p.add_argument("--friction",type=float,default=ROUND_TRIP_TRANSACTION_COST)
    p.add_argument("--slippage-per-side",type=float,default=SLIPPAGE_PER_SIDE)
    p.add_argument("--output",default="rocket_trader_traditional_research_v0_4_results.json")
    a=p.parse_args()
    print(f"ROCKET TRADER — TRADITIONAL STRATEGY RESEARCH v{VERSION}")
    print("RESEARCH ONLY | REGULAR SESSION | LONG ONLY | NO LEVERAGE | NO ORDERS")
    if a.self_test: print(json.dumps(self_test(),indent=2)); return 0
    if a.days<90 or a.friction<0 or a.slippage_per_side<0:
        print("ERROR: days debe ser >=90 y los costes no pueden ser negativos",file=sys.stderr); return 2
    results,failures=[],[]
    for symbol in [s.upper() for s in a.symbols]:
        try:
            item=evaluate_symbol(symbol,a.days,a.friction,a.slippage_per_side); results.append(item)
            print(json.dumps(item,indent=2,ensure_ascii=False,allow_nan=False))
        except Exception as exc:
            failures.append({"symbol":symbol,"error":f"{type(exc).__name__}: {exc}"}); print(json.dumps(failures[-1],ensure_ascii=False))
    summary={"ok":bool(results) and not failures,"version":VERSION,"pipeline":"rocket_trader_traditional_research_v0_4",
        "mode":"RESEARCH_ONLY","symbols_processed":[x["symbol"] for x in results],"symbols_failed":failures,
        "orders_enabled":False,"orders_submitted":0}
    with open(a.output,"w",encoding="utf-8") as f: json.dump({"summary":summary,"results":results},f,indent=2,ensure_ascii=False,allow_nan=False)
    print(f"Reporte guardado en: {a.output}"); print(json.dumps(summary,indent=2,ensure_ascii=False))
    return 0 if summary["ok"] else 1

if __name__=="__main__": raise SystemExit(main())
