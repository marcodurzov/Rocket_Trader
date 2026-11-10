#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-year crypto spot trend/momentum benchmark research. RESEARCH ONLY.

Signals use completed daily bars and are shifted one bar before returns are
applied. Long-only spot, no leverage, no shorts. No TradingClient is imported.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from alpaca.data.enums import CryptoFeed
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

VERSION = "0.2"
DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_YEARS = 5
MIN_DAILY_BARS = 900
FEE_BPS_SIDE = 25.0
HALF_SPREAD_BPS_SIDE = 10.0
SLIPPAGE_BPS_SIDE = 5.0
BASE_COST_SIDE = (FEE_BPS_SIDE + HALF_SPREAD_BPS_SIDE + SLIPPAGE_BPS_SIDE) / 10000.0
BOOTSTRAP_REPS = 500
BOOTSTRAP_PVALUE_REPS = 5000
FAMILYWISE_ALPHA = 0.05
BOOTSTRAP_BLOCK = 5
MIN_CALENDAR_COVERAGE = 0.95
MAX_ALLOWED_GAP_DAYS = 3


class CryptoResearchError(RuntimeError):
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
    value = str(symbol).strip().upper().replace("-", "/")
    if "/" not in value:
        raise CryptoResearchError(f"Expected BASE/USD pair, got {symbol!r}")
    base, quote = value.split("/", 1)
    if not base or quote != "USD":
        raise CryptoResearchError("Only USD-quoted crypto spot pairs are supported.")
    return f"{base}/USD"


def normalize_frame(frame: pd.DataFrame, symbol: str, min_rows: int = 1) -> pd.DataFrame:
    symbol = normalize_symbol(symbol)
    if frame is None or frame.empty:
        raise CryptoResearchError(f"{symbol}: empty daily bars.")
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
        raise CryptoResearchError(f"{symbol}: missing OHLCV fields {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    bad = df[required].isna().any(axis=1)
    bad |= (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    bad |= df["volume"] < 0
    bad |= df["high"] < df[["open", "close"]].max(axis=1)
    bad |= df["low"] > df[["open", "close"]].min(axis=1)
    bad |= df["high"] < df["low"]
    if bad.any():
        raise CryptoResearchError(f"{symbol}: {int(bad.sum())} invalid OHLCV rows.")
    df = df[required].sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    df = df.reset_index(drop=True)
    if len(df) < min_rows:
        raise CryptoResearchError(f"{symbol}: {len(df)} daily bars; minimum {min_rows}.")
    return df


def fetch_daily_bars(
    symbol: str,
    *,
    years: int = DEFAULT_YEARS,
    client: Optional[CryptoHistoricalDataClient] = None,
    end: Optional[datetime] = None,
    chunk_days: int = 365,
) -> pd.DataFrame:
    if years < 3 or chunk_days < 30:
        raise ValueError("years must be >=3 and chunk_days >=30.")
    clean = normalize_symbol(symbol)
    api = client or CryptoHistoricalDataClient()
    end_at = end or datetime.now(timezone.utc)
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    cursor = end_at - timedelta(days=365 * years)
    chunks: List[pd.DataFrame] = []
    while cursor < end_at:
        chunk_end = min(cursor + timedelta(days=chunk_days), end_at)
        request = CryptoBarsRequest(
            symbol_or_symbols=[clean],
            timeframe=TimeFrame.Day,
            start=cursor,
            end=chunk_end,
        )
        try:
            response = api.get_crypto_bars(request, feed=CryptoFeed.US)
            frame = response.df
            if frame is not None and not frame.empty:
                chunks.append(normalize_frame(frame, clean, min_rows=1))
        except Exception as exc:
            raise CryptoResearchError(
                f"{clean}: Alpaca daily bars failed: {type(exc).__name__}: {exc}"
            ) from exc
        cursor = chunk_end
    if not chunks:
        raise CryptoResearchError(f"{clean}: no daily data returned for {years} years.")
    combined = pd.concat(chunks, ignore_index=True)
    combined = combined.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if len(combined) < MIN_DAILY_BARS:
        raise CryptoResearchError(f"{clean}: only {len(combined)} daily bars across requested period.")
    return combined


def data_quality_metrics(frame: pd.DataFrame) -> Dict[str, Any]:
    dates = pd.to_datetime(frame["timestamp"], utc=True).dt.floor("D").sort_values()
    if dates.empty:
        raise CryptoResearchError("Cannot assess an empty daily data frame.")
    calendar_days = int((dates.iloc[-1] - dates.iloc[0]).days) + 1
    bars = int(dates.nunique())
    missing_days = max(0, calendar_days - bars)
    gaps = dates.diff().dt.days.dropna()
    max_gap_days = int(gaps.max()) if not gaps.empty else 0
    coverage = bars / calendar_days if calendar_days else 0.0
    eligible = coverage >= MIN_CALENDAR_COVERAGE and max_gap_days <= MAX_ALLOWED_GAP_DAYS
    gap_intervals = []
    for index in range(1, len(dates)):
        gap_days = int((dates.iloc[index] - dates.iloc[index - 1]).days)
        if gap_days > 1:
            gap_intervals.append({
                "previous_bar": dates.iloc[index - 1].isoformat(),
                "next_bar": dates.iloc[index].isoformat(),
                "missing_calendar_days": gap_days - 1,
                "gap_days_between_bars": gap_days,
            })
    return {
        "first_timestamp": dates.iloc[0].isoformat(),
        "last_timestamp": dates.iloc[-1].isoformat(),
        "calendar_days": calendar_days,
        "daily_bars": bars,
        "missing_calendar_days": missing_days,
        "calendar_coverage_pct": coverage,
        "max_gap_days": max_gap_days,
        "gap_interval_count": len(gap_intervals),
        "largest_gap_intervals": sorted(
            gap_intervals,
            key=lambda item: item["gap_days_between_bars"],
            reverse=True,
        )[:20],
        "minimum_coverage_pct": MIN_CALENDAR_COVERAGE,
        "maximum_allowed_gap_days": MAX_ALLOWED_GAP_DAYS,
        "eligible_for_strategy_evidence": eligible,
    }


def strategy_positions(frame: pd.DataFrame) -> Dict[str, pd.Series]:
    close, high, low = frame["close"], frame["high"], frame["low"]
    positions: Dict[str, pd.Series] = {
        "buy_and_hold": pd.Series(1.0, index=frame.index)
    }
    for lookback in (90, 180, 365):
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
    vol = close.pct_change().rolling(30, min_periods=30).std() * math.sqrt(365.0)
    trend = (close.pct_change(180) > 0).astype(float)
    scale = (0.20 / vol.replace(0, np.nan)).clip(lower=0.0, upper=1.0)
    positions["vol_targeted_momentum_180d"] = (trend * scale).shift(1).fillna(0.0).clip(0.0, 1.0)
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


def bootstrap_relative_pvalue(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    seed: int = 20261110,
    reps: int = BOOTSTRAP_PVALUE_REPS,
    block_size: int = BOOTSTRAP_BLOCK,
) -> float:
    """One-sided centered moving-block bootstrap p-value for log excess."""
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
    relative = np.log1p(strategy) - np.log1p(benchmark)
    observed = float(relative.mean())
    centered = relative - observed
    rng = np.random.default_rng(seed)
    n = len(centered)
    blocks = int(math.ceil(n / block_size))
    starts = rng.integers(0, n - block_size + 1, size=(reps, blocks))
    offsets = np.arange(block_size, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]).reshape(reps, -1)[:, :n]
    null_means = centered[indices].mean(axis=1)
    return float((1 + np.count_nonzero(null_means >= observed)) / (reps + 1))


def holm_adjust(pvalues: Dict[str, float]) -> Dict[str, float]:
    """Holm-Bonferroni family-wise adjusted p-values."""
    valid = []
    for key, value in pvalues.items():
        p = float(value)
        if math.isfinite(p):
            if not 0.0 <= p <= 1.0:
                raise CryptoResearchError(f"Invalid p-value for {key}: {p}")
            valid.append((p, str(key)))
    ordered = sorted(valid)
    adjusted: Dict[str, float] = {}
    running = 0.0
    total = len(ordered)
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
    """Apply close-derived weights at the next open; earn open-to-next-open returns."""
    if len(open_prices) < 2:
        raise CryptoResearchError("At least two open prices are required.")
    returns_all = (open_prices.shift(-1) / open_prices - 1.0).iloc[:-1]
    weights_all = (
        weights.reindex(open_prices.index).fillna(0.0).clip(0.0, 1.0).iloc[:-1]
    )
    previous_all = weights_all.shift(1).fillna(0.0)
    turnover_all = (weights_all - previous_all).abs()
    if len(turnover_all):
        turnover_all.iloc[-1] += abs(float(weights_all.iloc[-1]))
    hi = len(returns_all) if hi is None else min(int(hi), len(returns_all))
    lo = int(lo)
    if lo < 0 or hi < lo:
        raise CryptoResearchError("Invalid evaluation window.")
    returns = returns_all.iloc[lo:hi]
    w = weights_all.iloc[lo:hi]
    turnover = turnover_all.iloc[lo:hi]
    net = w * returns - turnover * BASE_COST_SIDE * cost_multiplier
    equity = (1.0 + net).cumprod()
    dd = equity / equity.cummax() - 1.0
    n = len(net)
    years = n / 365.0
    total = float(equity.iloc[-1] - 1.0) if n else 0.0
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else -1.0
    sd = float(net.std(ddof=1)) if n > 1 else 0.0
    metrics = Metrics(
        bars=n,
        total_return=total,
        cagr=cagr,
        max_drawdown=float(dd.min()) if n else 0.0,
        sharpe_annualized=float(net.mean() / sd * math.sqrt(365.0)) if sd > 0 else 0.0,
        volatility_annualized=sd * math.sqrt(365.0),
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
    train_end, val_end = int(n * 0.60), int(n * 0.80)
    windows = {
        "full_period": (0, n),
        "train_60pct": (0, train_end),
        "validation_20pct": (train_end, val_end),
        "final_holdout_20pct": (val_end, n),
    }
    all_results: Dict[str, Any] = {}
    for name, weights in strategy_positions(frame).items():
        all_results[name] = {
            window: asdict(evaluate_weights(
                frame["open"], weights, cost_multiplier=cost_multiplier, lo=lo, hi=hi
            )[0])
            for window, (lo, hi) in windows.items()
        }
    benchmark = all_results["buy_and_hold"]["final_holdout_20pct"]["total_return"]
    _, benchmark_returns = evaluate_weights(
        frame["open"], strategy_positions(frame)["buy_and_hold"],
        cost_multiplier=cost_multiplier, lo=val_end, hi=n,
    )
    for name in all_results:
        all_results[name]["final_holdout_20pct"]["excess_vs_buy_hold_same_asset"] = (
            all_results[name]["final_holdout_20pct"]["total_return"] - benchmark
        )
        if compute_pvalues and name != "buy_and_hold":
            _, candidate_returns = evaluate_weights(
                frame["open"], strategy_positions(frame)[name],
                cost_multiplier=cost_multiplier, lo=val_end, hi=n,
            )
            seed = 20261110 + sum(ord(ch) for ch in f"{symbol}:{name}")
            all_results[name]["final_holdout_20pct"]["bootstrap_p_value_excess_vs_buy_hold"] = (
                bootstrap_relative_pvalue(
                    candidate_returns.to_numpy(dtype=float),
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
        "strategies": all_results,
    }

def cross_sectional_top1(frames: Dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.DataFrame({
        s: f.set_index("timestamp")["close"] for s, f in frames.items()
    }).dropna()
    momentum = close.pct_change(90).shift(1)
    safe_momentum = momentum.fillna(-np.inf)
    top, max_mom = safe_momentum.idxmax(axis=1), safe_momentum.max(axis=1)
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
    equal_turnover = (equal - equal.shift(1).fillna(0.0)).abs().sum(axis=1)
    if len(equal_turnover):
        equal_turnover.iloc[-1] += float(equal.iloc[-1].abs().sum())
    equal_returns = (equal * returns).sum(axis=1) - equal_turnover * BASE_COST_SIDE * cost_multiplier
    n = len(returns)
    windows = {
        "full_period": (0, n),
        "train_60pct": (0, int(n * .60)),
        "validation_20pct": (int(n * .60), int(n * .80)),
        "final_holdout_20pct": (int(n * .80), n),
    }

    def metrics(r: pd.Series, lo: int, hi: int, exposure: pd.Series, turn: pd.Series) -> Dict[str, Any]:
        x = r.iloc[lo:hi]
        eq = (1 + x).cumprod()
        dd = eq / eq.cummax() - 1
        sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
        yrs = len(x) / 365.0
        return {
            "bars": len(x),
            "total_return": float(eq.iloc[-1] - 1) if len(x) else 0.0,
            "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 and eq.iloc[-1] > 0 else -1.0,
            "max_drawdown": float(dd.min()) if len(x) else 0.0,
            "sharpe_annualized": float(x.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0,
            "exposure_pct": float(exposure.iloc[lo:hi].mean()) if len(x) else 0.0,
            "turnover": float(turn.iloc[lo:hi].sum()),
            "bootstrap_q05_total_return": bootstrap_q05(x.to_numpy(dtype=float)),
        }

    top = {w: metrics(top_returns, lo, hi, weights.sum(axis=1), turnover) for w, (lo, hi) in windows.items()}
    eq = {w: metrics(equal_returns, lo, hi, equal.sum(axis=1), equal_turnover) for w, (lo, hi) in windows.items()}
    top["final_holdout_20pct"]["excess_vs_equal_weight_buy_hold"] = (
        top["final_holdout_20pct"]["total_return"] - eq["final_holdout_20pct"]["total_return"]
    )
    holdout_lo = int(n * .80)
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
        "strategy": "cross_sectional_momentum_top1_90d",
        "symbols": list(close.columns),
        "bars": n,
        "top1_momentum": top,
        "equal_weight_buy_and_hold": eq,
    }

def research(symbols: Sequence[str] = DEFAULT_SYMBOLS, years: int = DEFAULT_YEARS) -> Dict[str, Any]:
    clean = sorted({normalize_symbol(s) for s in symbols})
    if len(clean) < 2:
        raise CryptoResearchError("Cross-sectional research requires at least two symbols.")
    frames: Dict[str, pd.DataFrame] = {}
    failures = []
    for symbol in clean:
        try:
            frames[symbol] = fetch_daily_bars(symbol, years=years)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    if failures:
        return {
            "ok": False, "version": VERSION,
            "pipeline": "rocket_trader_crypto_multiyear_research",
            "mode": "RESEARCH_ONLY", "symbols_processed": sorted(frames),
            "symbols_failed": failures, "candidate_promotion_allowed": False,
            "paper_approval": False, "orders_enabled": False, "orders_submitted": 0,
        }
    quality = {s: data_quality_metrics(f) for s, f in frames.items()}
    eligible_frames = {
        s: f for s, f in frames.items()
        if quality[s]["eligible_for_strategy_evidence"]
    }
    base = {
        s: evaluate_single_asset(
            s, f, quality=quality[s], compute_pvalues=(s in eligible_frames)
        )
        for s, f in frames.items()
    }
    stress = {
        s: evaluate_single_asset(s, f, 2.0, quality=quality[s], compute_pvalues=False)
        for s, f in frames.items()
    }
    cross = (
        evaluate_cross_sectional(eligible_frames)
        if len(eligible_frames) >= 2 else None
    )
    cross_stress = (
        evaluate_cross_sectional(eligible_frames, 2.0, compute_pvalue=False)
        if len(eligible_frames) >= 2 else None
    )
    quality_issues = sorted(set(frames) - set(eligible_frames))
    family_pvalues: Dict[str, float] = {}
    for symbol in sorted(eligible_frames):
        for strategy_name, strategy_result in base[symbol]["strategies"].items():
            if strategy_name == "buy_and_hold":
                continue
            pvalue = strategy_result["final_holdout_20pct"].get(
                "bootstrap_p_value_excess_vs_buy_hold"
            )
            if pvalue is not None and math.isfinite(float(pvalue)):
                family_pvalues[f"{symbol}:{strategy_name}"] = float(pvalue)
    if cross is not None:
        cross_p = cross["top1_momentum"]["final_holdout_20pct"].get(
            "bootstrap_p_value_excess_vs_equal_weight"
        )
        if cross_p is not None and math.isfinite(float(cross_p)):
            family_pvalues["CROSS_SECTIONAL:top1_90d"] = float(cross_p)
    adjusted = holm_adjust(family_pvalues)
    for hypothesis, adjusted_p in adjusted.items():
        if hypothesis.startswith("CROSS_SECTIONAL:") and cross is not None:
            metrics = cross["top1_momentum"]["final_holdout_20pct"]
            metrics["holm_adjusted_p_value"] = adjusted_p
            metrics["familywise_significant"] = adjusted_p <= FAMILYWISE_ALPHA
            metrics["pre_screen_pass"] = bool(
                metrics.get("entries", 0) >= 30
                and metrics.get("excess_vs_equal_weight_buy_hold", float("-inf")) > 0
                and adjusted_p <= FAMILYWISE_ALPHA
            )
        else:
            symbol, strategy_name = hypothesis.split(":", 1)
            metrics = base[symbol]["strategies"][strategy_name]["final_holdout_20pct"]
            metrics["holm_adjusted_p_value"] = adjusted_p
            metrics["familywise_significant"] = adjusted_p <= FAMILYWISE_ALPHA
            metrics["pre_screen_pass"] = bool(
                metrics.get("entries", 0) >= 30
                and metrics.get("excess_vs_buy_hold_same_asset", float("-inf")) > 0
                and adjusted_p <= FAMILYWISE_ALPHA
            )
    multiple_testing = {
        "method": "HOLM_BONFERRONI",
        "family": "All eligible crypto single-asset strategies vs same-asset buy-and-hold plus cross-sectional top-1 vs equal-weight; base costs; final chronological holdout.",
        "family_size": len(family_pvalues),
        "alpha": FAMILYWISE_ALPHA,
        "bootstrap_replicates_per_hypothesis": BOOTSTRAP_PVALUE_REPS,
        "raw_pvalues": family_pvalues,
        "holm_adjusted_pvalues": adjusted,
        "familywise_significant_count": sum(p <= FAMILYWISE_ALPHA for p in adjusted.values()),
        "pre_screen_pass_count": sum(
            bool(base[s]["strategies"][name]["final_holdout_20pct"].get("pre_screen_pass", False))
            for s in eligible_frames
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
        "data_quality_pass": not failures and not quality_issues,
        "data_quality_by_symbol": quality,
        "symbols_with_data_quality_issues": quality_issues,
        "cross_sectional_universe": sorted(eligible_frames),
        "cross_sectional_skipped_reason": (
            None if len(eligible_frames) >= 2
            else "Fewer than two symbols passed daily coverage/continuity checks."
        ),
        "version": VERSION,
        "pipeline": "rocket_trader_crypto_multiyear_research",
        "mode": "RESEARCH_ONLY",
        "data_source": "Alpaca CryptoFeed.US daily bars",
        "lookback_years_requested": years,
        "symbols_processed": clean,
        "cost_assumptions": {
            "taker_fee_bps_per_side": FEE_BPS_SIDE,
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
            "signal_timing": "Completed daily close signal shifted one bar before applying next daily return.",
            "chronological_windows": "First 60% train, next 20% validation, final 20% holdout.",
            "strategy_hypotheses": [
                "time_series_momentum_90d", "time_series_momentum_180d",
                "time_series_momentum_365d", "sma_50_200_trend",
                "donchian_55_20", "vol_targeted_momentum_180d",
                "cross_sectional_momentum_top1_90d", "buy_and_hold",
            ],
            "constraints": "Long-only spot, no leverage, no shorts, no margin.",
            "bootstrap": f"{BOOTSTRAP_REPS} moving-block resamples for return quantiles; {BOOTSTRAP_PVALUE_REPS} centered moving-block resamples per hypothesis for one-sided log-relative p-values.",
            "multiple_testing": "Holm-Bonferroni family-wise error control at alpha 0.05 across all eligible base-cost final-holdout strategy-vs-benchmark hypotheses; pre-screen also requires at least 30 holdout entries and positive excess.",
            "promotion": "No strategy is promoted; independent replication, multiple walk-forward folds, realistic fee verification and sustained Paper validation remain required.",
        },
        "candidate_promotion_allowed": False,
        "paper_approval": False,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261109)
    n = 1500
    ts = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    frames: Dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(("BTC/USD", "ETH/USD", "SOL/USD")):
        close = 100 * np.exp(np.cumsum(rng.normal([.0007, .0004, .0002][i], .025, n)))
        op = np.concatenate([[close[0]], close[:-1]])
        raw = pd.DataFrame({
            "timestamp": ts, "open": op,
            "high": np.maximum(op, close) * 1.01,
            "low": np.minimum(op, close) * .99,
            "close": close, "volume": rng.lognormal(8, .5, n),
        })
        frames[symbol] = normalize_frame(raw, symbol, min_rows=MIN_DAILY_BARS)
        quality = data_quality_metrics(frames[symbol])
        assert quality["eligible_for_strategy_evidence"] is True
        pos = strategy_positions(frames[symbol])
        assert len(pos) == 7
        assert all(((w >= 0) & (w <= 1)).all() for w in pos.values())
    cross = evaluate_cross_sectional(frames)
    assert cross["bars"] > 0
    gappy = frames["BTC/USD"].drop(index=range(100, 200)).reset_index(drop=True)
    gappy_quality = data_quality_metrics(gappy)
    assert gappy_quality["eligible_for_strategy_evidence"] is False
    assert gappy_quality["calendar_coverage_pct"] < MIN_CALENDAR_COVERAGE
    assert gappy_quality["gap_interval_count"] > 0
    assert gappy_quality["largest_gap_intervals"][0]["missing_calendar_days"] >= 9
    metric, _ = evaluate_weights(
        frames["BTC/USD"]["close"],
        strategy_positions(frames["BTC/USD"])["buy_and_hold"],
    )
    assert metric.bars == n
    assert metric.bootstrap_q05_total_return == metric.bootstrap_q05_total_return
    return {
        "ok": True, "version": VERSION,
        "pipeline": "rocket_trader_crypto_multiyear_research",
        "mode": "RESEARCH_ONLY", "synthetic_daily_bars": n,
        "symbols": list(frames), "strategy_hypotheses": 8,
        "candidate_promotion_allowed": False, "paper_approval": False,
        "orders_enabled": False, "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    parser.add_argument("--output", default="research_artifacts/crypto_multiyear_research_v0_2.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.years < 3:
        parser.error("--years must be >=3")
    result = research(args.symbols, args.years)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
