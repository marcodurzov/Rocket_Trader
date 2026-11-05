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
