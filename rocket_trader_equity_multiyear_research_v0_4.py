#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-year US ETF trend/momentum benchmark research with next-open execution. RESEARCH ONLY.

Uses split/dividend/spin-off adjusted daily bars. Fixed ETF universe, long-only,
unlevered strategies, next-session signal timing, chronological holdout windows.
No TradingClient, order submission or account mutation is imported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import exchange_calendars as xcals
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

VERSION = "0.4"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "EFA", "EEM")
DEFAULT_YEARS = 10
MIN_DAILY_BARS = 1800
MIN_EXCHANGE_SESSION_COVERAGE = 0.95
MAX_GAP_DAYS = 7
FEE_BPS_SIDE = 0.0
HALF_SPREAD_BPS_SIDE = 2.5
SLIPPAGE_BPS_SIDE = 2.5
BASE_COST_SIDE = (FEE_BPS_SIDE + HALF_SPREAD_BPS_SIDE + SLIPPAGE_BPS_SIDE) / 10000.0
BOOTSTRAP_REPS = 500
BOOTSTRAP_PVALUE_REPS = 5000
FAMILYWISE_ALPHA = 0.05
BOOTSTRAP_BLOCK = 5


class EquityResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Metrics:
    bars: int
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe_annualized: float
    volatility_annualized: float
    exposure_pct: float
    turnover: float
    entries: int
    profitable_days_pct: float
    bootstrap_q05_total_return: float


def normalize_symbol(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if not value or any(ch.isspace() for ch in value):
        raise EquityResearchError(f"Invalid US ETF symbol: {symbol!r}")
    return value


def normalize_frame(frame: pd.DataFrame, symbol: str, min_rows: int = 1) -> pd.DataFrame:
    symbol = normalize_symbol(symbol)
    if frame is None or frame.empty:
        raise EquityResearchError(f"{symbol}: empty daily bars.")
    df = frame.copy()
    if isinstance(df.index, pd.MultiIndex):
        level = next(
            (i for i in range(df.index.nlevels)
             if symbol in set(map(str, df.index.get_level_values(i).unique()))),
            None,
        )
        if level is not None:
            df = df.xs(symbol, level=level)
    df = df.reset_index()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "timestamp" not in df.columns and "time" in df.columns:
        df = df.rename(columns={"time": "timestamp"})
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise EquityResearchError(f"{symbol}: missing OHLCV fields {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    bad = df[required].isna().any(axis=1)
    bad |= (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    bad |= df["volume"] < 0
    # Vendor-adjusted OHLC can differ by a few floating-point ULPs.
    # Permit only a tiny relative tolerance; material candle inconsistencies
    # still fail closed.
    price_scale = df[["open", "high", "low", "close"]].abs().max(axis=1)
    tolerance = price_scale * 1e-10
    bad |= df["high"] + tolerance < df[["open", "close"]].max(axis=1)
    bad |= df["low"] - tolerance > df[["open", "close"]].min(axis=1)
    bad |= df["high"] + tolerance < df["low"]
    if bad.any():
        sample = df.loc[bad, required].head(10).copy()
        sample["timestamp"] = sample["timestamp"].astype(str)
        diagnostics = sample.to_dict(orient="records")
        reasons = {
            "null_or_non_numeric": int(df[required].isna().any(axis=1).sum()),
            "non_positive_ohlc": int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
            "negative_volume": int((df["volume"] < 0).sum()),
            "high_below_open_or_close": int((df["high"] < df[["open", "close"]].max(axis=1)).sum()),
            "low_above_open_or_close": int((df["low"] > df[["open", "close"]].min(axis=1)).sum()),
            "high_below_low": int((df["high"] < df["low"]).sum()),
        }
        raise EquityResearchError(
            f"{symbol}: {int(bad.sum())} invalid OHLCV rows; "
            f"reason_counts={json.dumps(reasons, sort_keys=True)}; "
            f"sample={json.dumps(diagnostics, default=str)}"
        )
    df = df[required].sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    df = df.reset_index(drop=True)
    if len(df) < min_rows:
        raise EquityResearchError(f"{symbol}: {len(df)} daily bars; minimum {min_rows}.")
    return df


def data_quality_metrics(frame: pd.DataFrame) -> Dict[str, Any]:
    """Measure daily-bar completeness against actual XNYS trading sessions.

    This intentionally replaces weekday counting: weekends and US exchange
    holidays are not expected sessions and must not penalize valid datasets.
    """
    dates = (
        pd.to_datetime(frame["timestamp"], utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
    )
    if dates.empty:
        raise EquityResearchError("Cannot assess empty daily history.")
    # exchange_calendars expects timezone-naive session labels (not UTC instants).
    start = pd.Timestamp(dates.iloc[0]).normalize()
    end = pd.Timestamp(dates.iloc[-1]).normalize()
    try:
        calendar = xcals.get_calendar(
            "XNYS",
            start=start - pd.Timedelta(days=14),
            end=end + pd.Timedelta(days=14),
        )
        sessions = calendar.sessions[
            (calendar.sessions >= start) & (calendar.sessions <= end)
        ]
    except Exception as exc:
        raise EquityResearchError(
            f"Unable to calculate authoritative XNYS sessions: {type(exc).__name__}: {exc}"
        ) from exc
    session_dates = pd.DatetimeIndex(sessions)
    if session_dates.tz is not None:
        session_dates = session_dates.tz_convert("UTC").tz_localize(None)
    session_dates = session_dates.normalize()
    observed = pd.DatetimeIndex(dates)
    expected_sessions = int(len(session_dates))
    bars = int(len(observed.intersection(session_dates)))
    missing = max(0, expected_sessions - bars)
    missing_dates = session_dates.difference(observed)
    observed_gaps = observed.to_series().diff().dt.days.dropna()
    max_gap = int(observed_gaps.max()) if not observed_gaps.empty else 0
    coverage = bars / expected_sessions if expected_sessions else 0.0
    eligible = coverage >= MIN_EXCHANGE_SESSION_COVERAGE and max_gap <= MAX_GAP_DAYS
    return {
        "calendar": "XNYS",
        "expected_exchange_sessions": expected_sessions,
        "daily_bars": bars,
        "missing_exchange_sessions": missing,
        "exchange_session_coverage_pct": coverage,
        "max_calendar_gap_days": max_gap,
        "minimum_exchange_session_coverage_pct": MIN_EXCHANGE_SESSION_COVERAGE,
        "maximum_allowed_gap_days": MAX_GAP_DAYS,
        "eligible_for_strategy_evidence": eligible,
        "first_missing_exchange_session": (
            missing_dates[0].date().isoformat() if len(missing_dates) else None
        ),
    }


def fetch_daily_bars(
    symbol: str,
    *,
    years: int = DEFAULT_YEARS,
    feed_name: str = "IEX",
    client: Optional[StockHistoricalDataClient] = None,
    end: Optional[datetime] = None,
    chunk_days: int = 365,
) -> pd.DataFrame:
    if years < 3 or chunk_days < 30:
        raise ValueError("years must be >=3 and chunk_days >=30.")
    clean = normalize_symbol(symbol)
    api = client
    if api is None:
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise EquityResearchError("Alpaca market-data credentials are missing.")
        api = StockHistoricalDataClient(key, secret)
    feed = DataFeed.SIP if feed_name.strip().upper() == "SIP" else DataFeed.IEX
    end_at = end or datetime.now(timezone.utc)
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    start_at = end_at - timedelta(days=365 * years)
    cursor = start_at
    chunks: List[pd.DataFrame] = []
    while cursor < end_at:
        chunk_end = min(cursor + timedelta(days=chunk_days), end_at)
        request = StockBarsRequest(
            symbol_or_symbols=[clean],
            timeframe=TimeFrame.Day,
            start=cursor,
            end=chunk_end,
            limit=10000,
            adjustment=Adjustment.ALL,
            feed=feed,
        )
        try:
            response = api.get_stock_bars(request)
            frame = response.df
            if frame is not None and not frame.empty:
                chunks.append(normalize_frame(frame, clean, min_rows=1))
        except Exception as exc:
            raise EquityResearchError(
                f"{clean}: Alpaca daily bars failed on {feed_name}: {type(exc).__name__}: {exc}"
            ) from exc
        cursor = chunk_end
    if not chunks:
        raise EquityResearchError(f"{clean}: no daily bars returned for {years} years.")
    combined = pd.concat(chunks, ignore_index=True)
    combined = combined.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    minimum_rows = max(900, int(years * 252 * 0.65))
    if len(combined) < minimum_rows:
        quality = data_quality_metrics(combined)
        first_seen = combined.iloc[0]["timestamp"].isoformat()
        last_seen = combined.iloc[-1]["timestamp"].isoformat()
        raise EquityResearchError(
            f"{clean}: only {len(combined)} daily bars; minimum {minimum_rows} "
            f"for {years} requested years. Returned range={first_seen}..{last_seen}; "
            f"exchange_session_coverage={quality['exchange_session_coverage_pct']:.2%}; "
            f"missing_exchange_sessions={quality['missing_exchange_sessions']}; "
            f"max_calendar_gap_days={quality['max_calendar_gap_days']}. "
            "Do not treat this partial history as full-period evidence."
        )
    if combined.iloc[0]["timestamp"] > start_at + timedelta(days=60):
        raise EquityResearchError(f"{clean}: returned history does not cover the requested {years}-year start date.")
    return combined



def fetch_yahoo_daily_bars(
    symbol: str,
    *,
    years: int = DEFAULT_YEARS,
    ticker: Any = None,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Fetch adjusted daily history from Yahoo Finance for research only."""
    if years < 3:
        raise ValueError("years must be >=3.")
    clean = normalize_symbol(symbol)
    end_at = end or datetime.now(timezone.utc)
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    start_at = end_at - timedelta(days=365 * years)
    # yfinance end is exclusive; excluding today avoids partial-session bars.
    end_exclusive = end_at.date().isoformat()
    try:
        if ticker is None:
            import yfinance as yf
            ticker = yf.Ticker(clean)
        history = ticker.history(
            start=start_at.date().isoformat(),
            end=end_exclusive,
            interval="1d",
            auto_adjust=True,
            actions=True,
            repair=False,
            raise_errors=True,
        )
    except Exception as exc:
        raise EquityResearchError(
            f"{clean}: Yahoo Finance history failed: {type(exc).__name__}: {exc}"
        ) from exc
    if history is None or history.empty:
        raise EquityResearchError(f"{clean}: Yahoo Finance returned empty history.")
    frame = history.copy().reset_index()
    frame.columns = [str(col).strip().lower() for col in frame.columns]
    if "timestamp" not in frame.columns:
        date_col = next((name for name in ("date", "datetime", "index") if name in frame.columns), None)
        if date_col is None:
            raise EquityResearchError(f"{clean}: Yahoo history has no Date/Datetime index.")
        frame = frame.rename(columns={date_col: "timestamp"})
    normalized = normalize_frame(frame, clean, min_rows=1)
    minimum_rows = max(900, int(years * 252 * 0.65))
    quality = data_quality_metrics(normalized)
    first_seen = normalized.iloc[0]["timestamp"]
    last_seen = normalized.iloc[-1]["timestamp"]
    if len(normalized) < minimum_rows:
        raise EquityResearchError(
            f"{clean}: Yahoo returned only {len(normalized)} daily bars; "
            f"minimum {minimum_rows} for {years} requested years. "
            f"Returned range={first_seen.isoformat()}..{last_seen.isoformat()}; "
            f"exchange_session_coverage={quality['exchange_session_coverage_pct']:.2%}; "
            f"max_calendar_gap_days={quality['max_calendar_gap_days']}."
        )
    if first_seen > pd.Timestamp(start_at).tz_convert("UTC") + pd.Timedelta(days=60):
        raise EquityResearchError(
            f"{clean}: Yahoo history does not cover the requested {years}-year start."
        )
    if last_seen.date() < end_at.date() - timedelta(days=7):
        raise EquityResearchError(
            f"{clean}: Yahoo history is stale; latest daily bar is {last_seen.date()}."
        )
    return normalized



def fetch_tiingo_daily_bars(
    symbol: str,
    *,
    years: int = DEFAULT_YEARS,
    api_token: Optional[str] = None,
    opener: Any = urlopen,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Fetch split/dividend-adjusted EOD OHLCV from Tiingo for research only."""
    if years < 3:
        raise ValueError("years must be >=3.")
    token = str(api_token or os.getenv("TIINGO_API_TOKEN", "")).strip()
    if not token:
        raise EquityResearchError("TIINGO_API_TOKEN is required for the Tiingo source.")
    clean = normalize_symbol(symbol)
    end_at = end or datetime.now(timezone.utc)
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    start_at = end_at - timedelta(days=365 * years)
    url = (
        "https://api.tiingo.com/tiingo/daily/"
        + quote(clean, safe="")
        + "?"
        + urlencode({
            "startDate": start_at.date().isoformat(),
            "endDate": end_at.date().isoformat(),
            "format": "json",
        })
    )
    request = Request(url, headers={
        "Authorization": f"Token {token}",
        "Accept": "application/json",
    })
    try:
        with opener(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise EquityResearchError(f"Tiingo returned HTTP {status}")
            payload = json.loads(response.read().decode("utf-8"))
    except EquityResearchError:
        raise
    except Exception as exc:
        raise EquityResearchError(
            f"{clean}: Tiingo EOD history failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise EquityResearchError(f"{clean}: Tiingo returned no daily history.")
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            raise EquityResearchError(f"{clean}: Tiingo returned a malformed daily row.")
        required = ("date", "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume")
        if any(item.get(key) is None for key in required):
            raise EquityResearchError(
                f"{clean}: Tiingo row is missing adjusted OHLCV fields."
            )
        rows.append({
            "timestamp": item["date"],
            "open": item["adjOpen"],
            "high": item["adjHigh"],
            "low": item["adjLow"],
            "close": item["adjClose"],
            "volume": item["adjVolume"],
        })
    normalized = normalize_frame(pd.DataFrame(rows), clean, min_rows=1)
    minimum_rows = max(900, int(years * 252 * 0.65))
    quality = data_quality_metrics(normalized)
    first_seen = normalized.iloc[0]["timestamp"]
    last_seen = normalized.iloc[-1]["timestamp"]
    if len(normalized) < minimum_rows:
        raise EquityResearchError(
            f"{clean}: Tiingo returned only {len(normalized)} daily bars; "
            f"minimum {minimum_rows} for {years} years. "
            f"Returned range={first_seen.isoformat()}..{last_seen.isoformat()}; "
            f"exchange_session_coverage={quality['exchange_session_coverage_pct']:.2%}; "
            f"max_calendar_gap_days={quality['max_calendar_gap_days']}."
        )
    if first_seen > pd.Timestamp(start_at).tz_convert("UTC") + pd.Timedelta(days=60):
        raise EquityResearchError(
            f"{clean}: Tiingo history does not cover the requested {years}-year start."
        )
    if last_seen.date() < end_at.date() - timedelta(days=7):
        raise EquityResearchError(
            f"{clean}: Tiingo history is stale; latest daily bar is {last_seen.date()}."
        )
    return normalized


def source_metadata(source: str, feed_name: str = "IEX") -> Dict[str, str]:
    clean = str(source).strip().upper()
    if clean == "YAHOO":
        return {
            "data_source": "Yahoo Finance via yfinance, daily auto_adjust=True, actions=True, repair=False (research only)",
            "price_adjustment": "Yahoo Finance yfinance history auto_adjust=True with actions=True and repair=False; research-only provider.",
        }
    if clean == "TIINGO":
        return {
            "data_source": "Tiingo EOD adjusted daily OHLCV via adjOpen/adjHigh/adjLow/adjClose/adjVolume (research only)",
            "price_adjustment": "Tiingo adjusted OHLCV fields; provider documents split/dividend adjustment following CRSP methodology.",
        }
    if clean == "ALPACA":
        return {
            "data_source": f"Alpaca US stock daily bars, {feed_name.upper()} feed, Adjustment.ALL",
            "price_adjustment": "Alpaca Adjustment.ALL (splits, dividends, spin-offs).",
        }
    raise ValueError("source must be ALPACA, YAHOO or TIINGO")


def _stateful_long_only(entry: pd.Series, exit_: pd.Series, index: pd.Index) -> pd.Series:
    """Create a close-observed state machine and shift execution to next open."""
    state = np.zeros(len(index), dtype=float)
    in_position = False
    for i in range(len(index)):
        if not in_position and bool(entry.iloc[i]):
            in_position = True
        elif in_position and bool(exit_.iloc[i]):
            in_position = False
        state[i] = 1.0 if in_position else 0.0
    return pd.Series(state, index=index).shift(1).fillna(0.0).clip(0.0, 1.0)


def _mean_reversion_positions(close: pd.Series) -> Dict[str, pd.Series]:
    # RSI(2): Wilder smoothing; oversold entry only above the 200-day trend.
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    avg_loss = losses.ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi2 = 100.0 - (100.0 / (1.0 + rs))
    rsi2 = rsi2.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    rsi2 = rsi2.mask((avg_gain == 0.0) & (avg_loss > 0.0), 0.0)
    rsi2 = rsi2.mask((avg_gain == 0.0) & (avg_loss == 0.0), 50.0)
    sma5 = close.rolling(5, min_periods=5).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    rsi_entry = (rsi2 < 10.0) & (close > sma200)
    rsi_exit = (close > sma5) | (rsi2 > 70.0)

    # Bollinger(20, 2): enter below the lower band, exit at the middle band.
    middle = close.rolling(20, min_periods=20).mean()
    sigma = close.rolling(20, min_periods=20).std(ddof=0)
    lower = middle - 2.0 * sigma
    bollinger_entry = close < lower
    bollinger_exit = close >= middle

    # Five-day downside shock normalized by trailing 20-day daily volatility.
    daily_vol = close.pct_change().rolling(20, min_periods=20).std()
    five_day_z = close.pct_change(5) / (daily_vol * math.sqrt(5.0)).replace(0.0, np.nan)
    z_entry = five_day_z < -2.0
    z_exit = five_day_z >= 0.0

    return {
        "rsi2_10_sma200_exit_sma5": _stateful_long_only(rsi_entry, rsi_exit, close.index),
        "bollinger_20_2_exit_mid": _stateful_long_only(bollinger_entry, bollinger_exit, close.index),
        "zscore_5d_2_exit_zero": _stateful_long_only(z_entry, z_exit, close.index),
    }


def strategy_positions(frame: pd.DataFrame) -> Dict[str, pd.Series]:
    close, high, low = frame["close"], frame["high"], frame["low"]
    positions: Dict[str, pd.Series] = {"buy_and_hold": pd.Series(1.0, index=frame.index)}
    for lookback in (63, 126, 252):
        positions[f"time_series_momentum_{lookback}d"] = (
            (close.pct_change(lookback) > 0).shift(1).fillna(False).astype(float)
        )
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    positions["sma_50_200_trend"] = (
        ((close > sma200) & (sma50 > sma200)).shift(1).fillna(False).astype(float)
    )
    prior_high = high.shift(1).rolling(55, min_periods=55).max()
    prior_low = low.shift(1).rolling(20, min_periods=20).min()
    state = np.zeros(len(frame), dtype=float)
    in_position = False
    for i in range(len(frame)):
        if not np.isfinite(prior_high.iloc[i]) or not np.isfinite(prior_low.iloc[i]):
            state[i] = 0.0
            continue
        if not in_position and close.iloc[i] > prior_high.iloc[i]:
            in_position = True
        elif in_position and close.iloc[i] < prior_low.iloc[i]:
            in_position = False
        state[i] = 1.0 if in_position else 0.0
    positions["donchian_55_20"] = pd.Series(state, index=frame.index).shift(1).fillna(0.0)
    vol = close.pct_change().rolling(20, min_periods=20).std() * math.sqrt(252.0)
    trend = (close.pct_change(126) > 0).astype(float)
    scale = (0.10 / vol.replace(0, np.nan)).clip(lower=0.0, upper=1.0)
    positions["vol_targeted_momentum_126d"] = (trend * scale).shift(1).fillna(0.0).clip(0.0, 1.0)
    positions.update(_mean_reversion_positions(close))
    return positions


def bootstrap_q05(returns: np.ndarray, seed: int = 20261109) -> float:
    if len(returns) < 100:
        return float("nan")
    rng = np.random.default_rng(seed)
    n = len(returns)
    blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    samples = []
    for _ in range(BOOTSTRAP_REPS):
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=blocks)
        sample = np.concatenate([returns[s:s + BOOTSTRAP_BLOCK] for s in starts])[:n]
        samples.append(float(np.prod(1.0 + sample) - 1.0))
    return float(np.quantile(samples, 0.05))


def bootstrap_q05_relative(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    seed: int = 20261110,
) -> float:
    if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 100:
        return float("nan")
    relative = (1.0 + strategy_returns) / (1.0 + benchmark_returns) - 1.0
    rng = np.random.default_rng(seed)
    n = len(relative)
    blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    samples = []
    for _ in range(BOOTSTRAP_REPS):
        starts = rng.integers(0, n - BOOTSTRAP_BLOCK + 1, size=blocks)
        sample = np.concatenate([relative[s:s + BOOTSTRAP_BLOCK] for s in starts])[:n]
        samples.append(float(np.prod(1.0 + sample) - 1.0))
    return float(np.quantile(samples, 0.05))


def bootstrap_relative_pvalue(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    seed: int = 20261110,
    reps: int = BOOTSTRAP_PVALUE_REPS,
    block_size: int = BOOTSTRAP_BLOCK,
) -> float:
    """One-sided moving-block bootstrap p-value for positive log excess return.

    The observed log-relative series is centered to construct the null of zero
    mean excess. Blocks preserve short-range serial dependence. This is a
    screening p-value, not a substitute for independent replication.
    """
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if (
        strategy.ndim != 1 or benchmark.ndim != 1
        or len(strategy) != len(benchmark) or len(strategy) < 100
        or reps < 1000 or block_size < 1 or block_size > len(strategy)
        or not np.isfinite(strategy).all() or not np.isfinite(benchmark).all()
        or (strategy <= -1).any() or (benchmark <= -1).any()
    ):
        return float("nan")
    log_relative = np.log1p(strategy) - np.log1p(benchmark)
    observed = float(log_relative.mean())
    centered = log_relative - observed
    rng = np.random.default_rng(seed)
    n = len(centered)
    blocks = int(math.ceil(n / block_size))
    starts = rng.integers(0, n - block_size + 1, size=(reps, blocks))
    offsets = np.arange(block_size, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]).reshape(reps, -1)[:, :n]
    null_means = centered[indices].mean(axis=1)
    return float((1 + np.count_nonzero(null_means >= observed)) / (reps + 1))


def holm_adjust(pvalues: Dict[str, float]) -> Dict[str, float]:
    """Holm-Bonferroni family-wise adjusted p-values, preserving input keys."""
    valid = []
    for key, value in pvalues.items():
        p = float(value)
        if math.isfinite(p):
            if not 0.0 <= p <= 1.0:
                raise EquityResearchError(f"Invalid p-value for {key}: {p}")
            valid.append((p, str(key)))
    ordered = sorted(valid)
    total = len(ordered)
    adjusted: Dict[str, float] = {}
    running = 0.0
    for rank, (p, key) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * p))
        adjusted[key] = running
    return adjusted


def evaluate_weights(
    open_prices: pd.Series,
    weights: pd.Series,
    *,
    cost_multiplier: float = 1.0,
    lo: int = 0,
    hi: Optional[int] = None,
) -> tuple[Metrics, pd.Series]:
    """Apply close-derived weights at the next open; earn open-to-next-open returns.

    The final available open is used to liquidate the last held interval. The
    final bar has no forward return and is excluded from the return series.
    Turnover at window boundaries uses the true prior-day position.
    """
    if len(open_prices) < 2:
        raise EquityResearchError("At least two open prices are required.")
    returns_all = (open_prices.shift(-1) / open_prices - 1.0).iloc[:-1]
    weights_all = (
        weights.reindex(open_prices.index).fillna(0.0).clip(0.0, 1.0).iloc[:-1]
    )
    previous_all = weights_all.shift(1).fillna(0.0)
    turnover_all = (weights_all - previous_all).abs()
    if len(turnover_all):
        # Exit the last position at the final available open.
        turnover_all.iloc[-1] += abs(float(weights_all.iloc[-1]))
    hi = len(returns_all) if hi is None else min(int(hi), len(returns_all))
    lo = int(lo)
    if lo < 0 or hi < lo:
        raise EquityResearchError("Invalid evaluation window.")
    returns = returns_all.iloc[lo:hi]
    w = weights_all.iloc[lo:hi]
    turnover = turnover_all.iloc[lo:hi]
    net = w * returns - turnover * BASE_COST_SIDE * cost_multiplier
    equity = (1.0 + net).cumprod()
    dd = equity / equity.cummax() - 1.0
    n = len(net)
    years = n / 252.0
    total = float(equity.iloc[-1] - 1.0) if n else 0.0
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else -1.0
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    metrics = Metrics(
        bars=n,
        total_return=total,
        cagr=cagr,
        max_drawdown=float(dd.min()) if n else 0.0,
        sharpe_annualized=float(net.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0,
        volatility_annualized=sd * math.sqrt(252.0),
        exposure_pct=float(w.mean()) if n else 0.0,
        turnover=float(turnover.sum()),
        entries=int(((weights_all > 0) & (previous_all <= 0)).iloc[lo:hi].sum()),
        profitable_days_pct=float((net > 0).mean()) if n else 0.0,
        bootstrap_q05_total_return=bootstrap_q05(net.to_numpy(dtype=float)),
    )
    return metrics, net

def evaluate_single_asset(
    symbol: str,
    frame: pd.DataFrame,
    cost_multiplier: float = 1.0,
    quality: Optional[Dict[str, Any]] = None,
    *,
    compute_pvalues: bool = True,
) -> Dict[str, Any]:
    frame = frame.reset_index(drop=True)
    quality = quality or data_quality_metrics(frame)
    n = len(frame) - 1
    train_end, val_end = int(n * .60), int(n * .80)
    windows = {
        "full_period": (0, n),
        "train_60pct": (0, train_end),
        "validation_20pct": (train_end, val_end),
        "final_holdout_20pct": (val_end, n),
    }
    results: Dict[str, Any] = {}
    positions = strategy_positions(frame)
    benchmark_holdout, benchmark_returns = evaluate_weights(
        frame["open"], positions["buy_and_hold"],
        cost_multiplier=cost_multiplier, lo=val_end, hi=n,
    )
    benchmark = asdict(benchmark_holdout)
    for name, weights in positions.items():
        results[name] = {
            window: asdict(evaluate_weights(
                frame["open"], weights, cost_multiplier=cost_multiplier, lo=lo, hi=hi
            )[0])
            for window, (lo, hi) in windows.items()
        }
        _, strategy_holdout_returns = evaluate_weights(
            frame["open"], weights,
            cost_multiplier=cost_multiplier, lo=val_end, hi=n,
        )
        results[name]["final_holdout_20pct"]["excess_vs_buy_hold_same_asset"] = (
            results[name]["final_holdout_20pct"]["total_return"] - benchmark["total_return"]
        )
        results[name]["final_holdout_20pct"]["bootstrap_q05_excess_vs_buy_hold"] = (
            bootstrap_q05_relative(
                strategy_holdout_returns.to_numpy(dtype=float),
                benchmark_returns.to_numpy(dtype=float),
            )
        )
        if compute_pvalues and name != "buy_and_hold":
            seed = 20261110 + sum(ord(ch) for ch in f"{symbol}:{name}")
            results[name]["final_holdout_20pct"]["bootstrap_p_value_excess_vs_buy_hold"] = (
                bootstrap_relative_pvalue(
                    strategy_holdout_returns.to_numpy(dtype=float),
                    benchmark_returns.to_numpy(dtype=float),
                    seed=seed,
                )
            )
    return {
        "symbol": symbol,
        "bars": n,
        "first_timestamp": frame.iloc[0]["timestamp"].isoformat(),
        "last_timestamp": frame.iloc[-1]["timestamp"].isoformat(),
        "cost_per_side_bps": BASE_COST_SIDE * cost_multiplier * 10000.0,
        "data_quality": quality,
        "eligible_for_strategy_evidence": quality["eligible_for_strategy_evidence"],
        "strategies": results,
    }

def cross_sectional_top1(frames: Dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.DataFrame({
        symbol: frame.set_index("timestamp")["close"]
        for symbol, frame in frames.items()
    }).dropna()
    momentum = close.pct_change(126).shift(1)
    safe = momentum.fillna(-np.inf)
    top, max_mom = safe.idxmax(axis=1), safe.max(axis=1)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for symbol in close.columns:
        weights.loc[(top == symbol) & (max_mom > 0), symbol] = 1.0
    return close, weights


def evaluate_cross_sectional(
    frames: Dict[str, pd.DataFrame],
    cost_multiplier: float = 1.0,
    *,
    compute_pvalue: bool = True,
) -> Dict[str, Any]:
    close, weights_all = cross_sectional_top1(frames)
    open_prices = pd.DataFrame({
        symbol: frame.set_index("timestamp")["open"]
        for symbol, frame in frames.items()
    }).reindex(index=close.index, columns=close.columns)
    returns = (open_prices.shift(-1) / open_prices - 1.0).iloc[:-1]
    weights = weights_all.reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    turnover = (weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[-1] += float(weights.iloc[-1].abs().sum())
    top_returns = (weights * returns).sum(axis=1) - turnover * BASE_COST_SIDE * cost_multiplier
    equal = pd.DataFrame(1.0 / len(close.columns), index=returns.index, columns=close.columns)
    eq_turnover = (equal - equal.shift(1).fillna(0.0)).abs().sum(axis=1)
    if len(eq_turnover):
        eq_turnover.iloc[-1] += float(equal.iloc[-1].abs().sum())
    equal_returns = (equal * returns).sum(axis=1) - eq_turnover * BASE_COST_SIDE * cost_multiplier
    n = len(returns)
    windows = {
        "full_period": (0, n),
        "train_60pct": (0, int(n * .60)),
        "validation_20pct": (int(n * .60), int(n * .80)),
        "final_holdout_20pct": (int(n * .80), n),
    }

    def metrics(r: pd.Series, lo: int, hi: int, exposure: pd.Series, turn: pd.Series) -> Dict[str, Any]:
        x = r.iloc[lo:hi]
        eq = (1.0 + x).cumprod()
        dd = eq / eq.cummax() - 1.0
        sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
        yrs = len(x) / 252.0
        return {
            "bars": len(x),
            "total_return": float(eq.iloc[-1] - 1.0) if len(x) else 0.0,
            "cagr": float(eq.iloc[-1] ** (1.0 / yrs) - 1.0) if yrs > 0 and eq.iloc[-1] > 0 else -1.0,
            "max_drawdown": float(dd.min()) if len(x) else 0.0,
            "sharpe_annualized": float(x.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0,
            "exposure_pct": float(exposure.iloc[lo:hi].mean()) if len(x) else 0.0,
            "turnover": float(turn.iloc[lo:hi].sum()),
            "bootstrap_q05_total_return": bootstrap_q05(x.to_numpy(dtype=float)),
        }
    top = {w: metrics(top_returns, lo, hi, weights.sum(axis=1), turnover) for w, (lo, hi) in windows.items()}
    eq = {w: metrics(equal_returns, lo, hi, equal.sum(axis=1), eq_turnover) for w, (lo, hi) in windows.items()}
    holdout_lo = int(n * .80)
    top["final_holdout_20pct"]["excess_vs_equal_weight_buy_hold"] = (
        top["final_holdout_20pct"]["total_return"] - eq["final_holdout_20pct"]["total_return"]
    )
    top["final_holdout_20pct"]["bootstrap_q05_excess_vs_equal_weight"] = (
        bootstrap_q05_relative(
            top_returns.iloc[holdout_lo:].to_numpy(dtype=float),
            equal_returns.iloc[holdout_lo:].to_numpy(dtype=float),
        )
    )
    top["final_holdout_20pct"]["entries"] = int(
        ((weights > 0) & (weights.shift(1).fillna(0.0) <= 0)).iloc[holdout_lo:].sum().sum()
    )
    if compute_pvalue:
        top["final_holdout_20pct"]["bootstrap_p_value_excess_vs_equal_weight"] = (
            bootstrap_relative_pvalue(
                top_returns.iloc[holdout_lo:].to_numpy(dtype=float),
                equal_returns.iloc[holdout_lo:].to_numpy(dtype=float),
                seed=20261110,
            )
        )
    return {
        "strategy": "cross_sectional_momentum_top1_126d",
        "symbols": list(close.columns),
        "bars": n,
        "top1_momentum": top,
        "equal_weight_buy_and_hold": eq,
    }

def research(
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    years: int = DEFAULT_YEARS,
    feed_name: str = "IEX",
    source: str = "ALPACA",
) -> Dict[str, Any]:
    clean = sorted({normalize_symbol(s) for s in symbols})
    if len(clean) < 2:
        raise EquityResearchError("Cross-sectional research requires at least two ETFs.")
    source = str(source).strip().upper()
    if source not in {"ALPACA", "YAHOO", "TIINGO"}:
        raise ValueError("source must be ALPACA, YAHOO or TIINGO")
    frames: Dict[str, pd.DataFrame] = {}
    failures = []
    for symbol in clean:
        try:
            if source == "YAHOO":
                frames[symbol] = fetch_yahoo_daily_bars(symbol, years=years)
            elif source == "TIINGO":
                frames[symbol] = fetch_tiingo_daily_bars(symbol, years=years)
            else:
                frames[symbol] = fetch_daily_bars(symbol, years=years, feed_name=feed_name)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    if failures:
        return {
            "ok": False, "version": VERSION,
            "pipeline": "rocket_trader_equity_multiyear_research_v0_4",
            "mode": "RESEARCH_ONLY", "symbols_processed": sorted(frames),
            "symbols_failed": failures, "candidate_promotion_allowed": False,
            "paper_approval": False, "orders_enabled": False, "orders_submitted": 0,
        }
    quality = {s: data_quality_metrics(f) for s, f in frames.items()}
    eligible = {s: f for s, f in frames.items() if quality[s]["eligible_for_strategy_evidence"]}
    base = {
        s: evaluate_single_asset(s, f, quality=quality[s], compute_pvalues=(s in eligible))
        for s, f in frames.items()
    }
    stress = {
        s: evaluate_single_asset(s, f, 2.0, quality[s], compute_pvalues=False)
        for s, f in frames.items()
    }
    cross = evaluate_cross_sectional(eligible) if len(eligible) >= 2 else None
    cross_stress = evaluate_cross_sectional(eligible, 2.0, compute_pvalue=False) if len(eligible) >= 2 else None
    issues = sorted(set(frames) - set(eligible))
    family_pvalues: Dict[str, float] = {}
    for symbol in sorted(eligible):
        for strategy_name, strategy_result in base[symbol]["strategies"].items():
            if strategy_name == "buy_and_hold":
                continue
            metrics = strategy_result["final_holdout_20pct"]
            pvalue = metrics.get("bootstrap_p_value_excess_vs_buy_hold")
            if pvalue is not None and math.isfinite(float(pvalue)):
                family_pvalues[f"{symbol}:{strategy_name}"] = float(pvalue)
    if cross is not None:
        cross_metrics = cross["top1_momentum"]["final_holdout_20pct"]
        cross_p = cross_metrics.get("bootstrap_p_value_excess_vs_equal_weight")
        if cross_p is not None and math.isfinite(float(cross_p)):
            family_pvalues["CROSS_SECTIONAL:top1_126d"] = float(cross_p)
    adjusted = holm_adjust(family_pvalues)
    for hypothesis, adjusted_p in adjusted.items():
        if hypothesis.startswith("CROSS_SECTIONAL:") and cross is not None:
            metrics = cross["top1_momentum"]["final_holdout_20pct"]
            metrics["holm_adjusted_p_value"] = adjusted_p
            metrics["familywise_significant"] = adjusted_p <= FAMILYWISE_ALPHA
            metrics["pre_screen_pass"] = bool(
                metrics.get("entries", 0) >= 30
                and metrics.get("bootstrap_q05_excess_vs_equal_weight", float("-inf")) > 0
                and adjusted_p <= FAMILYWISE_ALPHA
            )
        else:
            symbol, strategy_name = hypothesis.split(":", 1)
            metrics = base[symbol]["strategies"][strategy_name]["final_holdout_20pct"]
            metrics["holm_adjusted_p_value"] = adjusted_p
            metrics["familywise_significant"] = adjusted_p <= FAMILYWISE_ALPHA
            metrics["pre_screen_pass"] = bool(
                metrics.get("entries", 0) >= 30
                and metrics.get("bootstrap_q05_excess_vs_buy_hold", float("-inf")) > 0
                and adjusted_p <= FAMILYWISE_ALPHA
            )
    multiple_testing = {
        "method": "HOLM_BONFERRONI",
        "family": "All eligible single-asset strategy vs same-asset buy-and-hold hypotheses plus cross-sectional top-1 vs equal-weight benchmark; base costs; final chronological holdout only.",
        "family_size": len(family_pvalues),
        "alpha": FAMILYWISE_ALPHA,
        "bootstrap_replicates_per_hypothesis": BOOTSTRAP_PVALUE_REPS,
        "raw_pvalues": family_pvalues,
        "holm_adjusted_pvalues": adjusted,
        "familywise_significant_count": sum(p <= FAMILYWISE_ALPHA for p in adjusted.values()),
        "pre_screen_pass_count": sum(
            bool(base[s]["strategies"][name]["final_holdout_20pct"].get("pre_screen_pass", False))
            for s in eligible
            for name in base[s]["strategies"]
            if name != "buy_and_hold"
        ) + (
            int(bool(cross["top1_momentum"]["final_holdout_20pct"].get("pre_screen_pass", False)))
            if cross is not None else 0
        ),
        "promotion_allowed": False,
    }
    return {
        "ok": True,
        "version": VERSION,
        "pipeline": "rocket_trader_equity_multiyear_research_v0_4",
        "mode": "RESEARCH_ONLY",
        "data_source": source_metadata(source, feed_name)["data_source"],
        "lookback_years_requested": years,
        "symbols_processed": clean,
        "data_quality_pass": not issues,
        "data_quality_by_symbol": quality,
        "symbols_with_data_quality_issues": issues,
        "cross_sectional_universe": sorted(eligible),
        "cross_sectional_skipped_reason": None if len(eligible) >= 2 else "Fewer than two ETFs passed data-quality checks.",
        "cost_assumptions": {
            "commission_bps_per_side": FEE_BPS_SIDE,
            "half_spread_bps_per_side": HALF_SPREAD_BPS_SIDE,
            "slippage_bps_per_side": SLIPPAGE_BPS_SIDE,
            "base_cost_bps_per_side": BASE_COST_SIDE * 10000.0,
            "stress_cost_multiplier": 2.0,
        },
        "single_asset_base_cost": base,
        "single_asset_2x_cost": stress,
        "cross_sectional_base_cost": cross,
        "cross_sectional_2x_cost": cross_stress,
        "multiple_testing": multiple_testing,
        "methodology": {
            "price_adjustment": source_metadata(source, feed_name)["price_adjustment"],
            "signal_timing": "Signals use completed daily close; execution at next session open; returns are open-to-next-open, with final liquidation at the last available open.",
            "chronological_windows": "First 60% train, next 20% validation, final 20% holdout.",
            "strategy_hypotheses": [
                "buy_and_hold", "time_series_momentum_63d",
                "time_series_momentum_126d", "time_series_momentum_252d",
                "sma_50_200_trend", "donchian_55_20",
                "vol_targeted_momentum_126d", "rsi2_10_sma200_exit_sma5",
                "bollinger_20_2_exit_mid", "zscore_5d_2_exit_zero",
                "cross_sectional_momentum_top1_126d",
            ],
            "constraints": "Long-only ETFs, no leverage, no shorts, no options/futures.",
            "data_quality": "Approximate weekday coverage (US holidays included in expected weekday count) >=95%, maximum calendar gap <=7 days.",
            "bootstrap": f"{BOOTSTRAP_REPS} moving-block resamples for return quantiles; {BOOTSTRAP_PVALUE_REPS} centered moving-block resamples per hypothesis for one-sided log-relative p-values.",
            "multiple_testing": "Holm-Bonferroni family-wise error control at alpha 0.05 across all eligible base-cost final-holdout strategy-vs-benchmark hypotheses. Pre-screen also requires at least 30 holdout entries and positive 5th-percentile excess.",
            "promotion": "No strategy is promoted; SIP parity, independent replication, multiple walk-forward folds and sustained Paper validation remain required.",
        },
        "candidate_promotion_allowed": False,
        "paper_approval": False,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261109)
    n = 2600
    dates = pd.bdate_range("2020-01-01", periods=n, tz="UTC")
    frames: Dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(("SPY", "QQQ", "IWM")):
        close = 100 * np.exp(np.cumsum(rng.normal([.0003, .0004, .0002][i], .012, n)))
        op = np.concatenate([[close[0]], close[:-1]])
        raw = pd.DataFrame({
            "timestamp": dates, "open": op,
            "high": np.maximum(op, close) * 1.005,
            "low": np.minimum(op, close) * .995,
            "close": close, "volume": rng.lognormal(12, .4, n),
        })
        frames[symbol] = normalize_frame(raw, symbol, min_rows=MIN_DAILY_BARS)
        quality = data_quality_metrics(frames[symbol])
        assert quality["eligible_for_strategy_evidence"]
        positions = strategy_positions(frames[symbol])
        assert len(positions) == 10
        assert all(((w >= 0) & (w <= 1)).all() for w in positions.values())
    incomplete = frames["SPY"].drop(index=range(0, n, 10)).reset_index(drop=True)
    assert not data_quality_metrics(incomplete)["eligible_for_strategy_evidence"]
    cross = evaluate_cross_sectional(frames)
    assert cross["bars"] > 0
    metrics, _ = evaluate_weights(
        frames["SPY"]["close"], strategy_positions(frames["SPY"])["buy_and_hold"]
    )
    assert metrics.bars == n - 1
    relative_q05 = bootstrap_q05_relative(
        np.full(250, 0.001, dtype=float),
        np.zeros(250, dtype=float),
    )
    assert relative_q05 > 0
    return {
        "ok": True, "version": VERSION,
        "pipeline": "rocket_trader_equity_multiyear_research_v0_4",
        "mode": "RESEARCH_ONLY", "synthetic_daily_bars": n,
        "bootstrap_excess_diagnostic_tested": True,
        "symbols": list(frames), "strategy_hypotheses": 10,
        "candidate_promotion_allowed": False, "paper_approval": False,
        "orders_enabled": False, "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    parser.add_argument("--feed", default="IEX", choices=["IEX", "SIP"])
    parser.add_argument("--source", default="ALPACA", choices=["ALPACA", "YAHOO", "TIINGO"])
    parser.add_argument("--output", default="research_artifacts/equity_multiyear_research_v0_4.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.years < 3:
        parser.error("--years must be >=3")
    result = research(args.symbols, args.years, args.feed, args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
