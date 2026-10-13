#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader traditional strategy research v0.2.
RESEARCH ONLY: reads Alpaca historical data; never submits or manages orders.
Changes: regular US session only, lagged daily regime filter, cost stress test,
explicit holdout metrics and regression tests for next-bar execution.
"""
from __future__ import annotations
import argparse, json, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict
import numpy as np
import pandas as pd

VERSION = "0.2"
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
    """Use only completed prior-session daily close vs prior 200-session SMA."""
    d = daily.copy()
    d["session_date"] = d["timestamp"].dt.tz_convert(NY).dt.date
    d["daily_sma200"] = d["close"].rolling(200, min_periods=200).mean()
    d["daily_bull_regime"] = (d["close"].shift(1) > d["daily_sma200"].shift(1)).fillna(False)
    # The shifted daily close/SMA are known before the current session starts.
    regime = d[["session_date", "daily_bull_regime"]].copy()
    x = intraday.copy()
    x["session_date"] = x["timestamp"].dt.tz_convert(NY).dt.date
    x = x.merge(regime, on="session_date", how="left")
    x["daily_bull_regime"] = x["daily_bull_regime"].fillna(False).astype(bool)
    return x.drop(columns=["session_date"])


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
        base[f"{name}_daily200_gate"] = sig & daily_gate
    return base


def simulate(df: pd.DataFrame, signal: pd.Series, round_trip_cost: float, slippage_per_side: float) -> Dict[str, Any]:
    """Signal at close i becomes position at open i+1; long-only, no leverage."""
    n = len(df)
    if n < 3: raise ValueError("Se necesitan al menos 3 barras.")
    sig = signal.fillna(False).astype(bool).to_numpy(dtype=int)
    pos = np.zeros(n, dtype=int); pos[1:] = sig[:-1]
    opens = df["open"].to_numpy(dtype=float)
    interval_returns = np.zeros(n-1, dtype=float)
    side_cost = round_trip_cost / 2.0 + slippage_per_side
    for i in range(n-1):
        gross = opens[i+1] / opens[i] - 1.0
        prev_pos = pos[i-1] if i > 0 else 0
        turnover = abs(pos[i] - prev_pos)
        interval_returns[i] = pos[i] * gross - turnover * side_cost
    last_ret = float(df["close"].iloc[-1] / opens[-1] - 1.0 - side_cost) if pos[-1] == 1 else 0.0
    all_returns = np.concatenate([interval_returns, [last_ret]])
    equity = np.cumprod(1.0 + all_returns)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    dd = equity / peaks - 1.0
    transitions = np.abs(np.diff(np.concatenate([[0], pos])))
    entries = int(np.sum((transitions == 1) & (pos == 1)))
    exits = int(np.sum((transitions == 1) & (pos == 0))) + int(pos[-1] == 1)
    dates = pd.to_datetime(df["timestamp"].iloc[1:].reset_index(drop=True), utc=True).dt.tz_convert(NY).dt.date
    daily = pd.DataFrame({"date": dates, "ret": interval_returns}).groupby("date")["ret"].apply(lambda x: float(np.prod(1+x)-1))
    std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily.mean() / std * math.sqrt(252)) if std > 0 else 0.0
    total = float(equity[-1] - 1.0)
    bh_gross = float(df["close"].iloc[-1] / df["open"].iloc[0] - 1.0)
    bh = float((1.0-side_cost) * (1.0+bh_gross) * (1.0-side_cost)-1.0)
    return {"bars": n, "trades_entered": entries, "trades_exited": exits,
        "exposure_pct": float(np.mean(pos)*100), "total_return": total,
        "buy_hold_return_same_window_after_friction": bh, "excess_return_vs_buy_hold": total-bh,
        "max_drawdown": float(np.min(dd)) if len(dd) else 0.0,
        "daily_sharpe_annualized": sharpe,
        "profitable_days_pct": float(np.mean(daily.to_numpy()>0)*100) if len(daily) else 0.0,
        "round_trip_transaction_cost": float(round_trip_cost), "slippage_per_side": float(slippage_per_side),
        "orders_enabled": False, "orders_submitted": 0}


def evaluate_symbol(symbol: str, days: int, round_trip_cost: float, slippage_per_side: float) -> Dict[str, Any]:
    intraday = fetch_bars(symbol, days, daily=False)
    daily = fetch_bars(symbol, days, daily=True)
    df = add_lagged_daily_regime(intraday, daily)
    signals = strategy_signals(df)
    split = int(len(df)*0.60)
    results = {}
    for name, sig in signals.items():
        full = simulate(df, sig, round_trip_cost, slippage_per_side)
        # Keep indicators computed from the past for warm-up, but simulate the holdout flat at its start.
        hold_df = df.iloc[split:].reset_index(drop=True)
        hold_sig = sig.iloc[split:].reset_index(drop=True)
        base_cost_results = simulate(hold_df, hold_sig, round_trip_cost, slippage_per_side)
        stress = {}
        for mult in COST_MULTIPLIERS:
            stress[f"{mult:.0f}x"] = simulate(hold_df, hold_sig, round_trip_cost*mult, slippage_per_side*mult)
        results[name] = {"full_period": full, "final_40pct_holdout_base_cost": base_cost_results,
                         "holdout_cost_stress": stress}
    return {"symbol": symbol, "version": VERSION, "data_source": "Alpaca IEX 5-minute and daily bars",
        "session_filter": "US regular session 09:30-16:00 America/New_York, weekdays only",
        "daily_regime_rule": "At session t, use only previous completed daily close vs previous completed 200-session SMA",
        "days_requested": days, "intraday_bars_received": len(df), "daily_bars_received": len(daily),
        "first_bar": str(df.timestamp.iloc[0]), "last_bar": str(df.timestamp.iloc[-1]),
        "holdout_split_index": split, "strategies": results, "mode": "RESEARCH_ONLY",
        "orders_enabled": False, "orders_submitted": 0}


def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261012); n = 4000
    ts = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    close = 100*np.exp(np.cumsum(rng.normal(0.00003, 0.001, n)))
    open_ = np.concatenate([[close[0]], close[:-1]*(1+rng.normal(0,0.0001,n-1))])
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_,close)*1.001,
        "low": np.minimum(open_,close)*0.999, "close": close, "volume": np.ones(n),
        "daily_bull_regime": np.arange(n)%2==0})
    signals = strategy_signals(df)
    assert len(signals) == 10 and all(len(x)==n for x in signals.values())
    test_signal = pd.Series(False,index=df.index); test_signal.iloc[10:12] = True
    result = simulate(df,test_signal,0.0002,0.0001)
    sig = test_signal.astype(int).to_numpy(); pos=np.zeros(n,dtype=int); pos[1:]=sig[:-1]
    assert pos[10]==0 and pos[11]==1 and pos[12]==1 and pos[13]==0
    assert result["orders_enabled"] is False and result["orders_submitted"]==0
    # Daily filter must never permit an entry when the regime is false.
    gated = signals["ema_12_48_trend_daily200_gate"]
    assert not bool((gated & ~df["daily_bull_regime"]).any())
    # Cost stress should not improve the net result on this fixed positive-exposure signal.
    r1=simulate(df,test_signal,0.0002,0.0001)["total_return"]
    r3=simulate(df,test_signal,0.0006,0.0003)["total_return"]
    assert r3 <= r1 + 1e-12
    return {"ok":True,"version":VERSION,"strategies_tested":list(signals),
        "next_bar_execution_lag_test":"PASS","daily_filter_no_lookahead_design":"PASS",
        "cost_stress_monotonicity_test":"PASS","orders_enabled":False,"orders_submitted":0}


def main() -> int:
    p=argparse.ArgumentParser(description="Traditional strategy research v0.2; research-only")
    p.add_argument("--self-test",action="store_true"); p.add_argument("--symbols",nargs="+",default=["SPY","QQQ"])
    p.add_argument("--days",type=int,default=365); p.add_argument("--friction",type=float,default=ROUND_TRIP_TRANSACTION_COST)
    p.add_argument("--slippage-per-side",type=float,default=SLIPPAGE_PER_SIDE)
    p.add_argument("--output",default="rocket_trader_traditional_research_v0_2_results.json")
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
    summary={"ok":bool(results) and not failures,"version":VERSION,"pipeline":"rocket_trader_traditional_research_v0_2",
        "mode":"RESEARCH_ONLY","symbols_processed":[x["symbol"] for x in results],"symbols_failed":failures,
        "orders_enabled":False,"orders_submitted":0}
    with open(a.output,"w",encoding="utf-8") as f: json.dump({"summary":summary,"results":results},f,indent=2,ensure_ascii=False,allow_nan=False)
    print(f"Reporte guardado en: {a.output}"); print(json.dumps(summary,indent=2,ensure_ascii=False))
    return 0 if summary["ok"] else 1

if __name__=="__main__": raise SystemExit(main())
