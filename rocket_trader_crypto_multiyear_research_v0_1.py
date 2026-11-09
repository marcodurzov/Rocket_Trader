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

VERSION = "0.1"
DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_YEARS = 5
MIN_DAILY_BARS = 900
FEE_BPS_SIDE = 25.0
HALF_SPREAD_BPS_SIDE = 10.0
SLIPPAGE_BPS_SIDE = 5.0
BASE_COST_SIDE = (FEE_BPS_SIDE + HALF_SPREAD_BPS_SIDE + SLIPPAGE_BPS_SIDE) / 10000.0
BOOTSTRAP_REPS = 500
BOOTSTRAP_BLOCK = 5


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


def evaluate_weights(
    close: pd.Series,
    weights: pd.Series,
    *,
    cost_multiplier: float = 1.0,
    lo: int = 0,
    hi: Optional[int] = None,
) -> tuple[Metrics, pd.Series]:
    hi = len(close) if hi is None else hi
    returns = close.pct_change().fillna(0.0).iloc[lo:hi]
    w = weights.reindex(close.index).fillna(0.0).clip(0.0, 1.0).iloc[lo:hi]
    prev = w.shift(1).fillna(0.0)
    turnover = (w - prev).abs()
    if len(turnover):
        turnover.iloc[-1] += abs(float(w.iloc[-1]))
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
        entries=int(((w > 0) & (prev <= 0)).sum()),
        profitable_days_pct=float((net > 0).mean()) if n else 0.0,
        bootstrap_q05_total_return=bootstrap_q05(net.to_numpy(dtype=float)),
    )
    return metrics, net


def evaluate_single_asset(symbol: str, frame: pd.DataFrame, cost_multiplier: float = 1.0) -> Dict[str, Any]:
    frame = frame.reset_index(drop=True)
    n = len(frame)
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
                frame["close"], weights, cost_multiplier=cost_multiplier, lo=lo, hi=hi
            )[0])
            for window, (lo, hi) in windows.items()
        }
    benchmark = all_results["buy_and_hold"]["final_holdout_20pct"]["total_return"]
    for name in all_results:
        all_results[name]["final_holdout_20pct"]["excess_vs_buy_hold_same_asset"] = (
            all_results[name]["final_holdout_20pct"]["total_return"] - benchmark
        )
    return {
        "symbol": symbol,
        "bars": n,
        "first_timestamp": frame.iloc[0]["timestamp"].isoformat(),
        "last_timestamp": frame.iloc[-1]["timestamp"].isoformat(),
        "cost_per_side_bps": BASE_COST_SIDE * cost_multiplier * 10000.0,
        "strategies": all_results,
    }


def cross_sectional_top1(frames: Dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.DataFrame({
        s: f.set_index("timestamp")["close"] for s, f in frames.items()
    }).dropna()
    momentum = close.pct_change(90).shift(1)
    top, max_mom = momentum.idxmax(axis=1), momentum.max(axis=1)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for symbol in close.columns:
        weights.loc[(top == symbol) & (max_mom > 0), symbol] = 1.0
    return close, weights


def evaluate_cross_sectional(frames: Dict[str, pd.DataFrame], cost_multiplier: float = 1.0) -> Dict[str, Any]:
    close, weights = cross_sectional_top1(frames)
    returns = close.pct_change().fillna(0.0)
    turnover = (weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[-1] += float(weights.iloc[-1].abs().sum())
    top_returns = (weights * returns).sum(axis=1) - turnover * BASE_COST_SIDE * cost_multiplier
    equal = pd.DataFrame(1.0 / len(close.columns), index=close.index, columns=close.columns)
    equal_turnover = (equal - equal.shift(1).fillna(0.0)).abs().sum(axis=1)
    if len(equal_turnover):
        equal_turnover.iloc[-1] += float(equal.iloc[-1].abs().sum())
    equal_returns = (equal * returns).sum(axis=1) - equal_turnover * BASE_COST_SIDE * cost_multiplier
    n = len(close)
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
    base = {s: evaluate_single_asset(s, f) for s, f in frames.items()}
    stress = {s: evaluate_single_asset(s, f, 2.0) for s, f in frames.items()}
    cross = evaluate_cross_sectional(frames)
    cross_stress = evaluate_cross_sectional(frames, 2.0)
    return {
        "ok": True,
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
            "bootstrap": f"{BOOTSTRAP_REPS} moving-block resamples of {BOOTSTRAP_BLOCK} days; diagnostic, not approval.",
            "promotion": "No strategy is promoted by this report; multiple-testing correction, independent replication and sustained Paper validation remain mandatory.",
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
        pos = strategy_positions(frames[symbol])
        assert len(pos) == 6
        assert all(((w >= 0) & (w <= 1)).all() for w in pos.values())
    cross = evaluate_cross_sectional(frames)
    assert cross["bars"] > 0
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
    parser.add_argument("--output", default="research_artifacts/crypto_multiyear_research_v0_1.json")
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
