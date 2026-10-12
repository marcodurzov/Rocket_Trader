#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — traditional long-only strategy baseline research.

RESEARCH ONLY. Uses Alpaca historical market data only. Never imports a trading
client and never submits, modifies, or cancels orders.

Strategies are deliberately simple, interpretable benchmarks. Signals are made
from bar-close data and positions change no earlier than the next bar open.
"""
from __future__ import annotations
import argparse, json, math, os, sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import numpy as np
import pandas as pd

VERSION = "0.1"
BAR_MINUTES = 5
ROUND_TRIP_TRANSACTION_COST = 0.00020
SLIPPAGE_PER_SIDE = 0.00010


def fetch_bars(symbol: str, days: int, chunk_days: int = 25) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY.")
    symbol = symbol.strip().upper()
    client = StockHistoricalDataClient(key, secret)
    end, start = datetime.now(timezone.utc), datetime.now(timezone.utc) - timedelta(days=days)
    chunks, cursor = [], start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        request = StockBarsRequest(symbol_or_symbols=symbol,
            timeframe=TimeFrame(BAR_MINUTES, TimeFrameUnit.Minute), start=cursor,
            end=chunk_end, limit=10000, feed=DataFeed.IEX)
        response = client.get_stock_bars(request)
        try:
            bars = response[symbol]
            records = [{"timestamp": b.timestamp, "open": b.open, "high": b.high,
                        "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
        except (KeyError, TypeError, AttributeError):
            records = []
        if records: chunks.append(pd.DataFrame(records))
        cursor = chunk_end
    if not chunks: raise RuntimeError(f"Alpaca no devolvió barras para {symbol}.")
    df = pd.concat(chunks, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    if len(df) < 1000: raise RuntimeError(f"Histórico insuficiente: {len(df)} barras.")
    return df


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def strategy_signals(df: pd.DataFrame) -> Dict[str, pd.Series]:
    c = df["close"]
    # Signals are desired long exposure at each bar close. All strategies are long-only.
    ema_fast, ema_slow = c.ewm(span=12, adjust=False, min_periods=12).mean(), c.ewm(span=48, adjust=False, min_periods=48).mean()
    sma_fast, sma_slow = c.rolling(20).mean(), c.rolling(100).mean()
    sma_regime = c.rolling(200).mean()
    donchian_high = df["high"].shift(1).rolling(20).max()
    donchian_exit = df["low"].shift(1).rolling(10).min()
    momentum20 = c.pct_change(20)
    r = rsi(c, 14)

    # 1. Classic EMA trend: stay long while fast EMA is above slow EMA.
    ema_cross = (ema_fast > ema_slow) & ema_fast.notna() & ema_slow.notna()
    # 2. Slower SMA trend filter/crossover.
    sma_cross = (sma_fast > sma_slow) & sma_fast.notna() & sma_slow.notna()
    # 3. Donchian breakout: enter above prior 20-bar high, exit below prior 10-bar low.
    donchian = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        hi, lo, close = donchian_high.iloc[i], donchian_exit.iloc[i], c.iloc[i]
        if not (np.isfinite(hi) and np.isfinite(lo)):
            donchian.iloc[i] = False
            continue
        if not in_pos and close > hi: in_pos = True
        elif in_pos and close < lo: in_pos = False
        donchian.iloc[i] = in_pos
    # 4. Trend-gated RSI pullback: buy oversold pullbacks only above the 200-bar regime; exit on RSI recovery or regime break.
    pullback = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        vals = (sma_regime.iloc[i], r.iloc[i])
        if not all(np.isfinite(v) for v in vals):
            pullback.iloc[i] = False
            continue
        if not in_pos and c.iloc[i] > sma_regime.iloc[i] and r.iloc[i] < 30: in_pos = True
        elif in_pos and (r.iloc[i] > 55 or c.iloc[i] < sma_regime.iloc[i]): in_pos = False
        pullback.iloc[i] = in_pos
    # 5. Time-series momentum proxy suitable for the available 5-minute dataset.
    momentum = (c > sma_regime) & (momentum20 > 0) & sma_regime.notna()
    return {"ema_12_48_trend": ema_cross, "sma_20_100_trend": sma_cross,
            "donchian_20_10_breakout": donchian, "rsi_pullback_above_sma200": pullback,
            "momentum_20_with_sma200_filter": momentum}


def simulate(df: pd.DataFrame, signal: pd.Series, round_trip_cost: float, slippage_per_side: float) -> Dict[str, Any]:
    """Apply close signals at next open; mark open-to-open returns, long-only, no leverage."""
    n = len(df)
    if n < 3: raise ValueError("Se necesitan al menos 3 barras.")
    sig = signal.fillna(False).astype(bool).to_numpy(dtype=int)
    pos = np.zeros(n, dtype=int)
    pos[1:] = sig[:-1]  # signal at close i becomes exposure at open i+1
    opens = df["open"].to_numpy(dtype=float)
    interval_returns = np.zeros(n-1, dtype=float)
    side_cost = round_trip_cost / 2.0 + slippage_per_side
    for i in range(n-1):
        gross = opens[i+1] / opens[i] - 1.0
        turnover = abs(pos[i] - (pos[i-1] if i > 0 else 0))
        interval_returns[i] = pos[i] * gross - turnover * side_cost
    # Include final close mark-to-market for any position still open, then charge exit friction.
    last_ret = 0.0
    if pos[-1] == 1:
        last_ret = float(df["close"].iloc[-1] / opens[-1] - 1.0 - side_cost)
    all_returns = np.concatenate([interval_returns, [last_ret]])
    equity = np.cumprod(1.0 + all_returns)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    dd = equity / peaks - 1.0
    transitions = np.abs(np.diff(np.concatenate([[0], pos])))
    entries = int(np.sum((transitions == 1) & (pos == 1)))
    exits = int(np.sum((transitions == 1) & (pos == 0))) + int(pos[-1] == 1)
    # Daily compounded returns; use daily Sharpe to avoid pretending each 5-minute bar is equal-time overnight.
    dates = pd.to_datetime(df["timestamp"].iloc[1:].reset_index(drop=True), utc=True).dt.date
    daily = pd.DataFrame({"date": dates, "ret": interval_returns}).groupby("date")["ret"].apply(lambda x: float(np.prod(1+x)-1))
    daily_std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily.mean() / daily_std * math.sqrt(252)) if daily_std > 0 else 0.0
    total = float(equity[-1] - 1.0)
    # Same-window buy-and-hold, with a buy and final liquidation friction.
    bh_gross = float(df["close"].iloc[-1] / df["open"].iloc[0] - 1.0)
    bh = float((1.0 - side_cost) * (1.0 + bh_gross) * (1.0 - side_cost) - 1.0)
    return {"bars": n, "trades_entered": entries, "trades_exited": exits,
        "exposure_pct": float(np.mean(pos) * 100), "total_return": total,
        "buy_hold_return_same_window_after_friction": bh,
        "excess_return_vs_buy_hold": total - bh,
        "max_drawdown": float(np.min(dd)) if len(dd) else 0.0,
        "daily_sharpe_annualized": sharpe,
        "profitable_days_pct": float(np.mean(daily.to_numpy() > 0) * 100) if len(daily) else 0.0,
        "round_trip_transaction_cost": float(round_trip_cost),
        "slippage_per_side": float(slippage_per_side),
        "orders_enabled": False, "orders_submitted": 0}


def evaluate_symbol(symbol: str, days: int, round_trip_cost: float, slippage_per_side: float) -> Dict[str, Any]:
    df = fetch_bars(symbol, days)
    signals = strategy_signals(df)
    # Keep the final 40% untouched by any parameter selection. These strategies are fixed, not optimized.
    split = int(len(df) * 0.60)
    results = {}
    for name, sig in signals.items():
        full = simulate(df, sig, round_trip_cost, slippage_per_side)
        hold = simulate(df.iloc[split:].reset_index(drop=True), sig.iloc[split:].reset_index(drop=True), round_trip_cost, slippage_per_side)
        results[name] = {"full_period": full, "final_40pct_holdout": hold}
    return {"symbol": symbol, "version": VERSION, "data_source": "Alpaca IEX 5-minute bars",
        "days_requested": days, "bars_received": len(df), "first_bar": str(df.timestamp.iloc[0]),
        "last_bar": str(df.timestamp.iloc[-1]), "strategies": results,
        "mode": "RESEARCH_ONLY", "orders_enabled": False, "orders_submitted": 0}


def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261012)
    n = 4000
    ts = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    # Deterministic drift plus noise creates finite prices and a useful synthetic test.
    close = 100 * np.exp(np.cumsum(rng.normal(0.00003, 0.001, n)))
    open_ = np.concatenate([[close[0]], close[:-1] * (1 + rng.normal(0, 0.0001, n-1))])
    df = pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close)*1.001,
        "low": np.minimum(open_, close)*0.999, "close": close, "volume": np.ones(n)})
    signals = strategy_signals(df)
    assert len(signals) == 5 and all(len(x) == n for x in signals.values())
    test_signal = pd.Series(False, index=df.index); test_signal.iloc[10] = True; test_signal.iloc[11] = True; test_signal.iloc[12] = False
    result = simulate(df, test_signal, 0.0002, 0.0001)
    assert result["orders_enabled"] is False and result["orders_submitted"] == 0
    assert result["trades_entered"] >= 1
    # Signal at bar 10 must not create exposure at open 10; it is lagged to open 11.
    sig = test_signal.astype(int).to_numpy(); pos = np.zeros(n, dtype=int); pos[1:] = sig[:-1]
    assert pos[10] == 0 and pos[11] == 1 and pos[13] == 0
    return {"ok": True, "version": VERSION, "strategies_tested": list(signals),
        "next_bar_execution_lag_test": "PASS", "long_only_test": "PASS",
        "orders_enabled": False, "orders_submitted": 0}


def main() -> int:
    p = argparse.ArgumentParser(description="Traditional strategy baseline research; research-only")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--friction", type=float, default=ROUND_TRIP_TRANSACTION_COST)
    p.add_argument("--slippage-per-side", type=float, default=SLIPPAGE_PER_SIDE)
    p.add_argument("--output", default="rocket_trader_traditional_research_results.json")
    args = p.parse_args()
    print(f"ROCKET TRADER — TRADITIONAL STRATEGY RESEARCH v{VERSION}")
    print("RESEARCH ONLY | LONG ONLY | NO LEVERAGE | NO ORDER SUBMISSION")
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    if args.days < 90 or args.friction < 0 or args.slippage_per_side < 0:
        print("ERROR: days debe ser >=90 y los costes no pueden ser negativos", file=sys.stderr); return 2
    results, failures = [], []
    for symbol in [s.upper() for s in args.symbols]:
        try:
            item = evaluate_symbol(symbol, args.days, args.friction, args.slippage_per_side)
            results.append(item); print(json.dumps(item, indent=2, ensure_ascii=False, allow_nan=False))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            print(json.dumps(failures[-1], ensure_ascii=False))
    summary = {"ok": bool(results) and not failures, "version": VERSION,
        "pipeline": "rocket_trader_traditional_research", "mode": "RESEARCH_ONLY",
        "symbols_processed": [x["symbol"] for x in results], "symbols_failed": failures,
        "orders_enabled": False, "orders_submitted": 0}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, ensure_ascii=False, allow_nan=False)
    print(f"Reporte guardado en: {args.output}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1

if __name__ == "__main__": raise SystemExit(main())
