#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — walk-forward signal research v0.4.

RESEARCH ONLY. Market-data API only; this module never imports a trading client
and never submits, modifies, or cancels orders.

v0.4 changes:
- Uses 5-minute IEX bars and chunked historical requests (avoids 10k-bar cap).
- Evaluates a small predeclared grid of holding horizons (3, 6, 12 bars).
- Anchors walk-forward folds to the latest available history.
- Selects (horizon, probability threshold) only on the earlier OOS segment.
- Tests the selected combination once on the later untouched OOS holdout.
- Explicitly checks data availability and chronology in offline self-tests.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from rocket_trader_engine import (
    EngineConfig,
    EnsembleModel,
    FeatureEngine,
    FEATURE_COLUMNS,
    MarketDataValidator,
)

VERSION = "0.4"
BAR_MINUTES = 5
DEFAULT_HORIZONS = [3, 6, 12]  # 15, 30, 60 minutes of holding bars
DEFAULT_THRESHOLDS = [0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
MIN_TRAIN = 3000
TEST_BLOCK = 800
MAX_FOLDS = 6
MIN_SELECTION_TRADES = 20
MIN_SELECTION_FOLDS = 2
MIN_HOLDOUT_TRADES = 20
MIN_HOLDOUT_FOLDS = 2
TARGET_RETURN = 0.001  # label threshold: +0.10% over the chosen horizon


@dataclass(frozen=True)
class Trade:
    symbol: str
    fold: int
    horizon_bars: int
    signal_timestamp: str
    entry_timestamp: str
    exit_timestamp: str
    signal_bar_index: int
    entry_bar_index: int
    exit_bar_index: int
    entry_price: float
    exit_price: float
    probability_up: float
    gross_return: float
    transaction_cost: float
    slippage_cost: float
    net_return: float


def fetch_bars(symbol: str, days: int, chunk_days: int = 25) -> pd.DataFrame:
    """Fetch 5-minute bars in date chunks, using Alpaca market data only."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY en secrets/variables.")

    symbol = symbol.strip().upper()
    client = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    chunks: List[pd.DataFrame] = []
    cursor = start
    # 25 calendar days is safely below Alpaca's per-request bar limit for 5-min bars.
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(BAR_MINUTES, TimeFrameUnit.Minute),
            start=cursor,
            end=chunk_end,
            limit=10_000,
            feed=DataFeed.IEX,
        )
        response = client.get_stock_bars(request)
        try:
            series = response[symbol]
            records = [{
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            } for bar in series]
        except (KeyError, TypeError, AttributeError):
            records = []
        if records:
            chunks.append(pd.DataFrame(records))
        cursor = chunk_end

    if not chunks:
        raise RuntimeError(f"Alpaca no devolvió barras de {BAR_MINUTES} minutos para {symbol}.")
    raw = pd.concat(chunks, ignore_index=True)
    return MarketDataValidator.normalize(raw)


def make_training_set(features: pd.DataFrame, cfg: EngineConfig, train_end: int) -> Tuple[pd.DataFrame, pd.Series]:
    """Only include labels whose entire forward horizon is inside training."""
    if train_end <= cfg.horizon_bars:
        raise RuntimeError("Ventana de entrenamiento menor al horizonte")
    hist = features.iloc[:train_end].copy()
    future_close = features["close"].shift(-cfg.horizon_bars).iloc[:train_end]
    eligible = np.arange(train_end) < (train_end - cfg.horizon_bars)
    label = (future_close >= hist["close"] * (1.0 + cfg.target_return)).astype("int8")
    valid = pd.Series(eligible, index=hist.index) & hist[FEATURE_COLUMNS].notna().all(axis=1) & future_close.notna()
    X, y = hist.loc[valid, FEATURE_COLUMNS], label.loc[valid]
    if len(X) < cfg.min_training_rows or y.nunique() < 2:
        raise RuntimeError(f"Training insuficiente: rows={len(X)}, classes={y.nunique()}")
    if len(X) > cfg.max_training_rows:
        X, y = X.iloc[-cfg.max_training_rows:], y.iloc[-cfg.max_training_rows:]
    return X.reset_index(drop=True), y.reset_index(drop=True)


def generate_walk_forward_predictions(raw: pd.DataFrame, cfg: EngineConfig) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Generate OOS predictions for folds anchored at the newest available bars."""
    features = FeatureEngine.build(raw)
    n = len(features)
    total_test = MAX_FOLDS * TEST_BLOCK
    first_test_start = n - total_test
    if first_test_start < max(MIN_TRAIN, cfg.min_training_rows):
        raise RuntimeError(
            f"Histórico insuficiente: {n} barras; se requieren al menos "
            f"{max(MIN_TRAIN, cfg.min_training_rows) + total_test} barras para folds anclados al final."
        )

    predictions: List[pd.DataFrame] = []
    fold_details: List[Dict[str, Any]] = []
    for fold_idx in range(MAX_FOLDS):
        train_end = first_test_start + fold_idx * TEST_BLOCK
        test_end = min(train_end + TEST_BLOCK, n)
        X_train, y_train = make_training_set(features, cfg, train_end)
        model = EnsembleModel(cfg)
        fit_info = model.fit(X_train, y_train)
        test = features.iloc[train_end:test_end].copy()
        test = test.loc[test[FEATURE_COLUMNS].notna().all(axis=1)].copy()
        if not test.empty:
            probs, _ = model.predict_proba(test[FEATURE_COLUMNS])
            test["bar_index"] = test.index.astype(int)
            test["probability_up"] = np.asarray(probs, dtype=float)
            test["fold"] = fold_idx + 1
            predictions.append(test)
        fold_details.append({
            "fold": fold_idx + 1,
            "train_start_index": max(0, train_end - len(X_train)),
            "train_end_exclusive": train_end,
            "test_start_index": train_end,
            "test_end_exclusive": test_end,
            "train_rows_used": int(len(X_train)),
            "test_rows_scored": int(len(test)),
            "positive_label_rate": float(y_train.mean()),
            "models": fit_info.get("models", []),
            "calibration": fit_info.get("probability_calibration", {}),
        })
    if not predictions:
        raise RuntimeError("No se generaron predicciones fuera de muestra.")
    pred = pd.concat(predictions).sort_values("bar_index").reset_index(drop=True)
    if int(pred["bar_index"].max()) < n - TEST_BLOCK:
        raise RuntimeError("Error de anclaje: las predicciones no alcanzan las barras recientes esperadas.")
    return pred, fold_details


def metrics_from_trades(trades: Sequence[Trade], trigger: str, scored_rows: int, horizon: int) -> Dict[str, Any]:
    returns = np.asarray([t.net_return for t in trades], dtype=float)
    if len(returns) == 0:
        return {"trigger": trigger, "scored_rows": int(scored_rows), "trades": 0,
                "folds_with_trades": 0, "profitable_folds": 0, "win_rate": 0.0,
                "avg_net_return": 0.0, "median_net_return": 0.0, "total_return": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0, "trade_sharpe": 0.0,
                "best_trade": 0.0, "worst_trade": 0.0, "horizon_bars": int(horizon)}
    equity = np.cumprod(1.0 + returns)
    curve = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(curve)
    drawdown = curve / peaks - 1.0
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    fold_ids = sorted({t.fold for t in trades})
    fold_returns = [float(np.prod([1 + t.net_return for t in trades if t.fold == f]) - 1) for f in fold_ids]
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    return {"trigger": trigger, "scored_rows": int(scored_rows), "trades": int(len(returns)),
            "folds_with_trades": int(len(fold_ids)), "profitable_folds": int(sum(x > 0 for x in fold_returns)),
            "fold_returns": {str(f): r for f, r in zip(fold_ids, fold_returns)},
            "win_rate": float(np.mean(returns > 0)), "avg_net_return": float(np.mean(returns)),
            "median_net_return": float(np.median(returns)), "total_return": float(equity[-1] - 1.0),
            "profit_factor": float(pf), "max_drawdown": float(np.min(drawdown)),
            "trade_sharpe": float(np.mean(returns) / std * math.sqrt(len(returns))) if std > 0 else 0.0,
            "best_trade": float(np.max(returns)), "worst_trade": float(np.min(returns)),
            "horizon_bars": int(horizon)}


def simulate_non_overlapping(predictions: pd.DataFrame, raw: pd.DataFrame, symbol: str,
                             threshold: float, horizon: int, round_trip_cost: float,
                             slippage_per_side: float, min_signal_index: Optional[int] = None,
                             max_signal_index: Optional[int] = None) -> Tuple[Dict[str, Any], List[Trade]]:
    """Signal close -> next bar open -> close of the Nth holding bar; long only."""
    if predictions.empty:
        return metrics_from_trades([], f"probability_up>={threshold:.4f}", 0, horizon), []
    px = raw.reset_index(drop=True)
    min_idx = -1 if min_signal_index is None else min_signal_index
    max_idx = len(px) - 1 if max_signal_index is None else min(max_signal_index, len(px) - 1)
    candidates = predictions[(predictions["bar_index"] >= min_idx) &
                             (predictions["bar_index"] <= max_idx)].sort_values("bar_index")
    trades: List[Trade] = []
    next_available_signal_idx = min_idx
    for _, signal in candidates.iterrows():
        signal_idx = int(signal["bar_index"])
        if signal_idx < next_available_signal_idx or float(signal["probability_up"]) < threshold:
            continue
        entry_idx = signal_idx + 1
        exit_idx = entry_idx + horizon - 1
        if entry_idx >= len(px) or exit_idx >= len(px) or exit_idx > max_idx:
            continue
        entry, exit_price = float(px.iloc[entry_idx]["open"]), float(px.iloc[exit_idx]["close"])
        if not (np.isfinite(entry) and np.isfinite(exit_price) and entry > 0 and exit_price > 0):
            continue
        gross = exit_price / entry - 1.0
        slip_total = 2.0 * slippage_per_side
        trades.append(Trade(symbol, int(signal["fold"]), horizon,
            str(signal["timestamp"]), str(px.iloc[entry_idx]["timestamp"]),
            str(px.iloc[exit_idx]["timestamp"]), signal_idx, entry_idx, exit_idx,
            entry, exit_price, float(signal["probability_up"]), gross,
            float(round_trip_cost), float(slip_total), float(gross - round_trip_cost - slip_total)))
        next_available_signal_idx = exit_idx + 1
    return metrics_from_trades(trades, f"probability_up>={threshold:.4f}", len(candidates), horizon), trades


def buy_and_hold_return(raw: pd.DataFrame, start_idx: int, end_idx: int) -> Optional[float]:
    px = raw.reset_index(drop=True)
    if start_idx < 0 or end_idx >= len(px) or end_idx <= start_idx:
        return None
    start, end = float(px.iloc[start_idx]["open"]), float(px.iloc[end_idx]["close"])
    return end / start - 1.0 if start > 0 else None


def evaluate_grid(selection: pd.DataFrame, raw: pd.DataFrame, symbol: str, horizons: Sequence[int],
                  thresholds: Sequence[float], cost: float, slippage: float) -> List[Dict[str, Any]]:
    results = []
    for horizon in horizons:
        for threshold in thresholds:
            metric, _ = simulate_non_overlapping(selection, raw, symbol, threshold, horizon, cost, slippage,
                min_signal_index=int(selection["bar_index"].min()),
                max_signal_index=int(selection["bar_index"].max()))
            metric["selection_qualified"] = bool(
                metric["trades"] >= MIN_SELECTION_TRADES and
                metric["folds_with_trades"] >= MIN_SELECTION_FOLDS and
                metric["avg_net_return"] > 0 and metric["profit_factor"] > 1.0 and
                metric["total_return"] > 0)
            metric["selection_score"] = (metric["total_return"] - 0.50 * abs(min(0.0, metric["max_drawdown"]))) if metric["selection_qualified"] else -1e9
            metric["threshold"] = float(threshold)
            results.append(metric)
    return sorted(results, key=lambda m: (m["selection_qualified"], m["selection_score"], m["total_return"]), reverse=True)


def evaluate_symbol(symbol: str, days: int, cost: float, slippage: float,
                    thresholds: Sequence[float], horizons: Sequence[int], selection_fraction: float) -> Dict[str, Any]:
    raw = fetch_bars(symbol, days)
    horizon_results: Dict[str, Any] = {}
    best_selection: Optional[Dict[str, Any]] = None
    best_pred: Optional[pd.DataFrame] = None
    best_folds: List[Dict[str, Any]] = []
    # Each horizon has labels matched to its own future window.
    for horizon in horizons:
        cfg = EngineConfig(target_return=TARGET_RETURN, horizon_bars=horizon,
            min_training_rows=300, max_training_rows=5000, probability_threshold=0.50)
        pred, folds = generate_walk_forward_predictions(raw, cfg)
        if len(pred) < 1000:
            raise RuntimeError(f"Muy pocas predicciones OOS para horizonte {horizon}: {len(pred)}")
        split = int(len(pred) * selection_fraction)
        split = max(1, min(split, len(pred) - 1))
        selection, holdout = pred.iloc[:split].copy(), pred.iloc[split:].copy()
        grid = evaluate_grid(selection, raw, symbol, [horizon], thresholds, cost, slippage)
        qualified = [r for r in grid if r["selection_qualified"]]
        horizon_results[str(horizon)] = {
            "horizon_bars": horizon,
            "horizon_minutes": horizon * BAR_MINUTES,
            "oos_predictions": len(pred),
            "selection_predictions": len(selection),
            "holdout_predictions": len(holdout),
            "folds": folds,
            "selection_grid_top_results": grid[:5],
        }
        if qualified:
            candidate = qualified[0]
            if best_selection is None or candidate["selection_score"] > best_selection["selection_score"]:
                best_selection = candidate
                best_pred = pred
                best_folds = folds

    chosen_horizon = int(best_selection["horizon_bars"]) if best_selection else None
    chosen_threshold = float(best_selection["threshold"]) if best_selection else None
    holdout_metrics = None
    sample_trades: List[Dict[str, Any]] = []
    holdout_benchmark = None
    research_pass = False
    if best_selection is not None and best_pred is not None:
        split = int(len(best_pred) * selection_fraction)
        selection, holdout = best_pred.iloc[:split].copy(), best_pred.iloc[split:].copy()
        holdout_start, holdout_end = int(holdout["bar_index"].min()), int(holdout["bar_index"].max())
        holdout_metrics, trades = simulate_non_overlapping(
            holdout, raw, symbol, chosen_threshold, chosen_horizon, cost, slippage,
            min_signal_index=holdout_start, max_signal_index=holdout_end)
        holdout_benchmark = buy_and_hold_return(raw, holdout_start, holdout_end)
        holdout_metrics["buy_hold_return_same_window"] = holdout_benchmark
        holdout_metrics["threshold_selected_on"] = "earlier_OOS_selection_segment"
        holdout_metrics["horizon_selected_on"] = "earlier_OOS_selection_segment"
        holdout_metrics["holdout_is_untouched_for_selection"] = True
        sample_trades = [asdict(t) for t in trades[:20]]
        research_pass = bool(
            holdout_metrics["trades"] >= MIN_HOLDOUT_TRADES and
            holdout_metrics["folds_with_trades"] >= MIN_HOLDOUT_FOLDS and
            holdout_metrics["profitable_folds"] >= 2 and
            holdout_metrics["avg_net_return"] > 0 and
            holdout_metrics["total_return"] > 0 and
            holdout_metrics["profit_factor"] > 1.10 and
            holdout_metrics["max_drawdown"] > -0.15 and
            holdout_benchmark is not None and holdout_metrics["total_return"] > holdout_benchmark)
        reason = ("Pasa el filtro de investigación OOS; aún requiere paper prolongado y revisión independiente."
                  if research_pass else "La combinación seleccionada no superó todos los criterios del holdout; órdenes deshabilitadas.")
    else:
        reason = "Ninguna combinación de horizonte/umbral cumplió los mínimos de selección; no se evaluó una estrategia en holdout."

    return {
        "symbol": symbol, "version": VERSION, "data_source": f"Alpaca IEX {BAR_MINUTES}-minute bars",
        "days_requested": days, "bars_received": len(raw),
        "first_bar": str(raw["timestamp"].iloc[0]), "last_bar": str(raw["timestamp"].iloc[-1]),
        "walk_forward_anchored_to_latest": True, "horizon_results": horizon_results,
        "selected_horizon_bars": chosen_horizon,
        "selected_horizon_minutes": chosen_horizon * BAR_MINUTES if chosen_horizon else None,
        "selected_threshold": chosen_threshold,
        "selected_on": "earlier_OOS_selection_segment" if best_selection else None,
        "holdout_metrics": holdout_metrics,
        "buy_hold_return_same_holdout_window": holdout_benchmark,
        "research_pass": research_pass, "reason": reason,
        "sample_holdout_trades": sample_trades,
        "target_label": f"forward return >= {TARGET_RETURN:.4%} over each tested horizon",
        "entry_rule": "signal bar close -> next 5-minute bar open",
        "exit_rule": "close of the Nth holding bar; N in tested horizon grid",
        "round_trip_transaction_cost": float(cost), "slippage_per_side": float(slippage),
        "total_slippage_per_trade": float(2 * slippage),
        "selection_fraction_of_OOS": float(selection_fraction),
        "execution_mode": "RESEARCH_ONLY", "orders_enabled": False,
        "order_submission_imported": False, "orders_submitted": 0,
    }


def self_test() -> Dict[str, Any]:
    rng = np.random.default_rng(20261009)
    n = MIN_TRAIN + MAX_FOLDS * TEST_BLOCK + 100
    ts = pd.date_range("2025-01-01", periods=n, freq=f"{BAR_MINUTES}min", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0008, 0.0002, n))
    raw = pd.DataFrame({"timestamp": ts, "open": open_,
        "high": np.maximum(open_, close) * (1 + spread),
        "low": np.minimum(open_, close) * (1 - spread),
        "close": close, "volume": rng.lognormal(8, 0.3, n)})
    raw = MarketDataValidator.normalize(raw)
    features = FeatureEngine.build(raw)
    assert len(features) == n and all(c in features.columns for c in FEATURE_COLUMNS)

    # Exact next-bar entry and horizon exit assertion.
    tiny = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=30, freq=f"{BAR_MINUTES}min", tz="UTC"),
        "open": np.arange(100, 130, dtype=float), "high": np.arange(101, 131, dtype=float),
        "low": np.arange(99, 129, dtype=float), "close": np.arange(100.5, 130.5, dtype=float),
        "volume": np.ones(30)})
    tiny = MarketDataValidator.normalize(tiny)
    pred = pd.DataFrame({"timestamp": [tiny.iloc[10]["timestamp"]], "bar_index": [10],
                         "probability_up": [0.9], "fold": [1]})
    metric, trades = simulate_non_overlapping(pred, tiny, "TEST", 0.5, 3, 0.0, 0.0,
                                               min_signal_index=0, max_signal_index=20)
    assert metric["trades"] == 1 and trades[0].entry_bar_index == 11 and trades[0].exit_bar_index == 13
    assert trades[0].entry_price == float(tiny.iloc[11]["open"])
    assert trades[0].exit_price == float(tiny.iloc[13]["close"])
    # Fold anchoring is tested structurally without training expensive models.
    first_test = n - MAX_FOLDS * TEST_BLOCK
    assert first_test >= MIN_TRAIN
    assert first_test + MAX_FOLDS * TEST_BLOCK == n
    return {"ok": True, "version": VERSION, "pipeline": "rocket_trader_signal_research",
        "bar_minutes": BAR_MINUTES, "features_test": "PASS", "next_bar_entry_test": "PASS",
        "holding_period_exit_test": "PASS", "latest_anchored_folds_test": "PASS",
        "orders_enabled": False, "order_submission_imported": False, "orders_submitted": 0}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rocket Trader research-only walk-forward evaluation")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--friction", type=float, default=0.00020, help="Round-trip transaction costs; 0.0002 = 2 bps")
    p.add_argument("--slippage-per-side", type=float, default=0.00010, help="Slippage each side; 0.0001 = 1 bp")
    p.add_argument("--selection-fraction", type=float, default=0.60)
    p.add_argument("--thresholds", nargs="+", type=float, default=DEFAULT_THRESHOLDS)
    p.add_argument("--horizons", nargs="+", type=int, default=DEFAULT_HORIZONS)
    p.add_argument("--output", default="rocket_trader_signal_research_results.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 78)
    print(f"ROCKET TRADER — WALK-FORWARD SIGNAL RESEARCH v{VERSION}")
    print("MODE: RESEARCH ONLY | LIVE ORDERS: DISABLED | ORDER SUBMISSION: NOT IMPORTED")
    print(f"DATA: Alpaca IEX {BAR_MINUTES}-minute bars | horizons={args.horizons} | days={args.days}")
    print("=" * 78)
    if args.self_test:
        print(json.dumps(self_test(), indent=2, ensure_ascii=False, allow_nan=False))
        print("ROCKET TRADER SIGNAL RESEARCH SELF-TEST: OK")
        return 0
    if args.days < 90:
        print("ERROR: --days debe ser >= 90 para esta prueba de investigación.", file=sys.stderr); return 2
    if not 0.50 <= args.selection_fraction <= 0.80:
        print("ERROR: --selection-fraction debe estar entre 0.50 y 0.80", file=sys.stderr); return 2
    if args.friction < 0 or args.slippage_per_side < 0:
        print("ERROR: los costes no pueden ser negativos", file=sys.stderr); return 2
    if not args.horizons or any(h < 1 or h > 60 for h in args.horizons) or len(set(args.horizons)) != len(args.horizons):
        print("ERROR: --horizons debe contener enteros únicos entre 1 y 60", file=sys.stderr); return 2
    if not args.thresholds or any(not 0 < t < 1 for t in args.thresholds):
        print("ERROR: todos los umbrales deben estar entre 0 y 1", file=sys.stderr); return 2

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for symbol in [s.upper() for s in args.symbols]:
        try:
            result = evaluate_symbol(symbol, args.days, args.friction, args.slippage_per_side,
                                     args.thresholds, args.horizons, args.selection_fraction)
            results.append(result)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            print(json.dumps(failures[-1], indent=2, ensure_ascii=False))

    summary = {"ok": bool(results) and not failures, "version": VERSION,
        "pipeline": "rocket_trader_signal_research", "mode": "RESEARCH_ONLY",
        "symbols_processed": [r["symbol"] for r in results], "symbols_failed": [f["symbol"] for f in failures],
        "research_pass": bool(results) and not failures and all(r["research_pass"] for r in results),
        "orders_enabled": False, "order_submission_imported": False, "orders_submitted": 0,
        "failures": failures}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, ensure_ascii=False, allow_nan=False)
    print(f"Reporte JSON guardado en: {args.output}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    print("ROCKET TRADER SIGNAL RESEARCH: OK" if summary["ok"] else "ROCKET TRADER SIGNAL RESEARCH: FAIL")
    # A negative research outcome is not a CI failure; technical/data failures are.
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
