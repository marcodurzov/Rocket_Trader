#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — walk-forward signal research v0.3.

RESEARCH ONLY. This module imports market data and the ML engine, never a
trading client. It does not create, submit, modify, or cancel orders.

Methodology safeguards:
- Features at bar i only use data available through the close of bar i.
- A signal at bar i enters at bar i+1 OPEN (not at the signal bar's close).
- Exit is at the close of the Nth holding bar after entry.
- Training labels are clipped to the training window (no future labels leak).
- Threshold selection uses an earlier chronological OOS selection segment.
- The chosen threshold is evaluated once on a later untouched OOS holdout.
- Round-trip friction and per-side slippage are both charged.
- A research pass is only a research gate; it never enables execution.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from rocket_trader_engine import (
    EngineConfig,
    EnsembleModel,
    FeatureEngine,
    FEATURE_COLUMNS,
    MarketDataValidator,
)

VERSION = "0.3"
DEFAULT_THRESHOLDS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
MIN_TRAIN = 3000
TEST_BLOCK = 1000
MAX_FOLDS = 5
MIN_SELECTION_TRADES = 20
MIN_SELECTION_FOLDS = 2
MIN_HOLDOUT_TRADES = 30
MIN_HOLDOUT_FOLDS = 3


@dataclass(frozen=True)
class Trade:
    symbol: str
    fold: int
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


def fetch_bars(symbol: str, days: int) -> pd.DataFrame:
    """Fetch recent minute bars via the project's market-data-only client."""
    # Delay broker-specific imports so --self-test can run offline.
    from alpaca.data.enums import DataFeed
    from rocket_trader_market_data import AlpacaMarketDataClient

    client = AlpacaMarketDataClient(feed=DataFeed.IEX)
    # The current market-data adapter caps each response at 10,000 bars.
    minutes = max(days * 1440, 10_080)
    bars = client.get_recent_bars(symbol=symbol, minutes=minutes)
    if not bars:
        raise RuntimeError(f"Alpaca no devolvió barras para {symbol}")
    frame = pd.DataFrame([
        {
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ])
    return MarketDataValidator.normalize(frame)


def make_training_set(features: pd.DataFrame, cfg: EngineConfig, train_end: int) -> Tuple[pd.DataFrame, pd.Series]:
    """Only train rows whose entire forward label is inside [0, train_end)."""
    if train_end <= cfg.horizon_bars:
        raise RuntimeError("Ventana de entrenamiento menor al horizonte")
    idx = np.arange(train_end)
    eligible = idx < (train_end - cfg.horizon_bars)
    hist = features.iloc[:train_end].copy()
    future_close = features["close"].shift(-cfg.horizon_bars).iloc[:train_end]
    label = (future_close >= hist["close"] * (1.0 + cfg.target_return)).astype("int8")
    valid = pd.Series(eligible, index=hist.index) & hist[FEATURE_COLUMNS].notna().all(axis=1) & future_close.notna()
    X = hist.loc[valid, FEATURE_COLUMNS]
    y = label.loc[valid]
    if len(X) < cfg.min_training_rows or y.nunique() < 2:
        raise RuntimeError(f"Training insuficiente: rows={len(X)}, classes={y.nunique()}")
    if len(X) > cfg.max_training_rows:
        X, y = X.iloc[-cfg.max_training_rows:], y.iloc[-cfg.max_training_rows:]
    return X.reset_index(drop=True), y.reset_index(drop=True)


def generate_walk_forward_predictions(raw: pd.DataFrame, cfg: EngineConfig) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    features = FeatureEngine.build(raw)
    n = len(features)
    train_end = max(MIN_TRAIN, cfg.min_training_rows)
    if n <= train_end + TEST_BLOCK:
        raise RuntimeError(
            f"Datos insuficientes para walk-forward: {n} barras; se requieren más de {train_end + TEST_BLOCK}."
        )

    predictions: List[pd.DataFrame] = []
    fold_details: List[Dict[str, Any]] = []
    fold = 0
    while train_end < n and fold < MAX_FOLDS:
        test_end = min(train_end + TEST_BLOCK, n)
        X_train, y_train = make_training_set(features, cfg, train_end)
        model = EnsembleModel(cfg)
        fit_info = model.fit(X_train, y_train)

        test = features.iloc[train_end:test_end].copy()
        valid = test[FEATURE_COLUMNS].notna().all(axis=1)
        test = test.loc[valid].copy()
        if not test.empty:
            probs, _ = model.predict_proba(test[FEATURE_COLUMNS])
            test["bar_index"] = test.index.astype(int)
            test["probability_up"] = np.asarray(probs, dtype=float)
            test["fold"] = fold + 1
            predictions.append(test)

        fold_details.append({
            "fold": fold + 1,
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
        train_end = test_end
        fold += 1

    if not predictions:
        raise RuntimeError("No se generaron predicciones fuera de muestra.")
    return pd.concat(predictions).sort_values("bar_index").reset_index(drop=True), fold_details


def simulate_non_overlapping(
    predictions: pd.DataFrame,
    raw: pd.DataFrame,
    symbol: str,
    threshold: float,
    horizon: int,
    round_trip_cost: float,
    slippage_per_side: float,
    max_signal_index: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Trade]]:
    """Simulate long-only trades; signal close -> next-bar open -> Nth bar close."""
    if predictions.empty:
        return metrics_from_trades([], "no_predictions", 0, 0), []
    px = raw.reset_index(drop=True)
    max_idx = len(px) - 1 if max_signal_index is None else min(max_signal_index, len(px) - 1)
    candidates = predictions[predictions["bar_index"] <= max_idx].sort_values("bar_index")
    trades: List[Trade] = []
    next_available_signal_idx = -1
    for _, signal in candidates.iterrows():
        signal_idx = int(signal["bar_index"])
        if signal_idx < next_available_signal_idx or float(signal["probability_up"]) < threshold:
            continue
        entry_idx = signal_idx + 1
        exit_idx = entry_idx + horizon - 1
        # Require the full trade to stay inside the evaluated chronological segment.
        if entry_idx >= len(px) or exit_idx >= len(px) or exit_idx > max_idx:
            continue
        entry = float(px.iloc[entry_idx]["open"])
        exit_price = float(px.iloc[exit_idx]["close"])
        if not (np.isfinite(entry) and np.isfinite(exit_price) and entry > 0 and exit_price > 0):
            continue
        gross = exit_price / entry - 1.0
        slip_total = 2.0 * slippage_per_side
        net = gross - round_trip_cost - slip_total
        trades.append(Trade(
            symbol=symbol,
            fold=int(signal["fold"]),
            signal_timestamp=str(signal["timestamp"]),
            entry_timestamp=str(px.iloc[entry_idx]["timestamp"]),
            exit_timestamp=str(px.iloc[exit_idx]["timestamp"]),
            signal_bar_index=signal_idx,
            entry_bar_index=entry_idx,
            exit_bar_index=exit_idx,
            entry_price=entry,
            exit_price=exit_price,
            probability_up=float(signal["probability_up"]),
            gross_return=float(gross),
            transaction_cost=float(round_trip_cost),
            slippage_cost=float(slip_total),
            net_return=float(net),
        ))
        # One position at a time: no overlapping entries.
        next_available_signal_idx = exit_idx + 1
    return metrics_from_trades(trades, f"probability_up>={threshold:.4f}", len(candidates), horizon), trades


def metrics_from_trades(trades: Sequence[Trade], trigger: str, scored_rows: int, horizon: int) -> Dict[str, Any]:
    returns = np.asarray([t.net_return for t in trades], dtype=float)
    if len(returns) == 0:
        return {
            "trigger": trigger, "scored_rows": int(scored_rows), "trades": 0,
            "folds_with_trades": 0, "profitable_folds": 0, "win_rate": 0.0,
            "avg_net_return": 0.0, "median_net_return": 0.0, "total_return": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "trade_sharpe": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0, "horizon_bars": int(horizon),
        }
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    drawdown = np.concatenate(([1.0], equity)) / peaks - 1.0
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    fold_ids = sorted({t.fold for t in trades})
    fold_returns = [float(np.prod([1 + t.net_return for t in trades if t.fold == f]) - 1) for f in fold_ids]
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    return {
        "trigger": trigger,
        "scored_rows": int(scored_rows),
        "trades": int(len(returns)),
        "folds_with_trades": int(len(fold_ids)),
        "profitable_folds": int(sum(x > 0 for x in fold_returns)),
        "fold_returns": {str(f): r for f, r in zip(fold_ids, fold_returns)},
        "win_rate": float(np.mean(returns > 0)),
        "avg_net_return": float(np.mean(returns)),
        "median_net_return": float(np.median(returns)),
        "total_return": float(equity[-1] - 1.0),
        "profit_factor": float(pf),
        "max_drawdown": float(np.min(drawdown)),
        # Trade-level descriptive statistic only; not annualized and not a forecast.
        "trade_sharpe": float(np.mean(returns) / std * math.sqrt(len(returns))) if std > 0 else 0.0,
        "best_trade": float(np.max(returns)),
        "worst_trade": float(np.min(returns)),
        "horizon_bars": int(horizon),
    }


def buy_and_hold_return(raw: pd.DataFrame, start_idx: int, end_idx: int) -> Optional[float]:
    frame = raw.reset_index(drop=True)
    if start_idx < 0 or end_idx >= len(frame) or end_idx <= start_idx:
        return None
    start = float(frame.iloc[start_idx]["open"])
    end = float(frame.iloc[end_idx]["close"])
    return end / start - 1.0 if start > 0 else None


def select_threshold(selection: pd.DataFrame, raw: pd.DataFrame, symbol: str, cfg: EngineConfig,
                     thresholds: Sequence[float], cost: float, slippage: float) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    evaluations = []
    for threshold in thresholds:
        metric, _ = simulate_non_overlapping(selection, raw, symbol, threshold, cfg.horizon_bars,
                                             cost, slippage, max_signal_index=int(selection["bar_index"].max()))
        metric["selection_qualified"] = bool(
            metric["trades"] >= MIN_SELECTION_TRADES
            and metric["folds_with_trades"] >= MIN_SELECTION_FOLDS
            and metric["avg_net_return"] > 0
            and metric["profit_factor"] > 1.0
            and metric["total_return"] > 0
        )
        # Conservative ranking; no holdout values are used to choose the threshold.
        metric["selection_score"] = (
            metric["total_return"] - 0.50 * abs(min(0.0, metric["max_drawdown"]))
            if metric["selection_qualified"] else -1e9
        )
        evaluations.append(metric)
    qualified = [m for m in evaluations if m["selection_qualified"]]
    if not qualified:
        return None, sorted(evaluations, key=lambda m: (m["trades"], m["avg_net_return"]), reverse=True)
    best = max(qualified, key=lambda m: (m["selection_score"], m["profit_factor"], m["trades"]))
    return float(best["trigger"].split(">=")[-1]), sorted(evaluations, key=lambda m: m["selection_score"], reverse=True)


def evaluate_symbol(symbol: str, days: int, round_trip_cost: float, slippage_per_side: float,
                    thresholds: Sequence[float], selection_fraction: float = 0.60) -> Dict[str, Any]:
    raw = fetch_bars(symbol, days)
    cfg = EngineConfig(target_return=0.001, horizon_bars=5, min_training_rows=300,
                       max_training_rows=5000, probability_threshold=0.50)
    pred, folds = generate_walk_forward_predictions(raw, cfg)
    if len(pred) < 500:
        raise RuntimeError(f"Muy pocas predicciones OOS: {len(pred)}")

    split = int(len(pred) * selection_fraction)
    split = max(1, min(split, len(pred) - 1))
    selection = pred.iloc[:split].copy()
    holdout = pred.iloc[split:].copy()
    threshold, selection_results = select_threshold(selection, raw, symbol, cfg, thresholds,
                                                     round_trip_cost, slippage_per_side)
    holdout_metrics: Optional[Dict[str, Any]] = None
    sample_trades: List[Dict[str, Any]] = []
    holdout_benchmark = buy_and_hold_return(raw, int(holdout["bar_index"].iloc[0]),
                                            int(holdout["bar_index"].iloc[-1]))
    if threshold is not None:
        holdout_end = int(holdout["bar_index"].iloc[-1])
        holdout_metrics, trades = simulate_non_overlapping(
            holdout, raw, symbol, threshold, cfg.horizon_bars,
            round_trip_cost, slippage_per_side, max_signal_index=holdout_end,
        )
        sample_trades = [asdict(t) for t in trades[:20]]
        holdout_metrics["buy_hold_return_same_window"] = holdout_benchmark
        holdout_metrics["threshold_selected_on"] = "earlier_OOS_selection_segment"
        holdout_metrics["holdout_is_untouched_for_threshold_selection"] = True
        research_pass = bool(
            holdout_metrics["trades"] >= MIN_HOLDOUT_TRADES
            and holdout_metrics["folds_with_trades"] >= MIN_HOLDOUT_FOLDS
            and holdout_metrics["profitable_folds"] >= 2
            and holdout_metrics["avg_net_return"] > 0
            and holdout_metrics["total_return"] > 0
            and holdout_metrics["profit_factor"] > 1.10
            and holdout_metrics["max_drawdown"] > -0.15
            and holdout_benchmark is not None
            and holdout_metrics["total_return"] > holdout_benchmark
        )
        reason = (
            "Pasa únicamente el filtro de investigación OOS; aún requiere validación prolongada en paper."
            if research_pass else
            "No supera todos los criterios OOS predefinidos en el holdout; mantener órdenes deshabilitadas."
        )
    else:
        research_pass = False
        reason = "Ningún umbral cumplió los mínimos de selección; no se eligió estrategia ni se evaluó un umbral en holdout."

    return {
        "symbol": symbol,
        "version": VERSION,
        "data_source": "Alpaca IEX minute bars",
        "days_requested": int(days),
        "bars_received": int(len(raw)),
        "first_bar": str(raw["timestamp"].iloc[0]),
        "last_bar": str(raw["timestamp"].iloc[-1]),
        "oos_predictions": int(len(pred)),
        "folds": folds,
        "target_label": f"forward_{cfg.horizon_bars}_bars_return >= {cfg.target_return:.4%}",
        "entry_rule": "signal bar close -> next bar open",
        "exit_rule": f"close of holding bar {cfg.horizon_bars}",
        "round_trip_transaction_cost": float(round_trip_cost),
        "slippage_per_side": float(slippage_per_side),
        "total_slippage_per_trade": float(2 * slippage_per_side),
        "selection_fraction_of_OOS": float(selection_fraction),
        "selection_predictions": int(len(selection)),
        "holdout_predictions": int(len(holdout)),
        "selected_threshold": threshold,
        "selection_grid_top_results": selection_results[:8],
        "holdout_metrics": holdout_metrics,
        "buy_hold_return_same_holdout_window": holdout_benchmark,
        "research_pass": bool(research_pass),
        "reason": reason,
        "sample_holdout_trades": sample_trades,
        "execution_mode": "RESEARCH_ONLY",
        "orders_enabled": False,
        "order_submission_imported": False,
        "orders_submitted": 0,
    }


def self_test() -> Dict[str, Any]:
    """No network/API needed: structural + next-bar execution regression test."""
    rng = np.random.default_rng(20261009)
    n = 4500
    ts = pd.date_range("2025-01-01", periods=n, freq="min", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.0007, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0005, 0.0001, n))
    raw = pd.DataFrame({
        "timestamp": ts,
        "open": open_,
        "high": np.maximum(open_, close) * (1 + spread),
        "low": np.minimum(open_, close) * (1 - spread),
        "close": close,
        "volume": rng.lognormal(8, 0.3, n),
    })
    normalized = MarketDataValidator.normalize(raw)
    features = FeatureEngine.build(normalized)
    assert len(features) == n
    assert all(c in features.columns for c in FEATURE_COLUMNS)

    # Deterministic execution test: signal at index 10 must enter at index 11 open,
    # not at index 10 close; holding=3 exits at index 13 close.
    tiny = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC"),
        "open": np.arange(100, 120, dtype=float),
        "high": np.arange(101, 121, dtype=float),
        "low": np.arange(99, 119, dtype=float),
        "close": np.arange(100.5, 120.5, dtype=float),
        "volume": np.ones(20),
    })
    tiny = MarketDataValidator.normalize(tiny)
    preds = pd.DataFrame({
        "timestamp": [tiny.iloc[10]["timestamp"]],
        "bar_index": [10], "probability_up": [0.9], "fold": [1],
    })
    metric, trades = simulate_non_overlapping(preds, tiny, "TEST", 0.5, 3, 0.0, 0.0, max_signal_index=15)
    assert metric["trades"] == 1
    assert trades[0].entry_bar_index == 11 and trades[0].exit_bar_index == 13
    assert trades[0].entry_price == float(tiny.iloc[11]["open"])
    assert trades[0].exit_price == float(tiny.iloc[13]["close"])
    return {
        "ok": True, "version": VERSION, "pipeline": "rocket_trader_signal_research",
        "feature_rows": len(features), "next_bar_entry_test": "PASS",
        "holding_period_exit_test": "PASS", "orders_enabled": False,
        "order_submission_imported": False, "orders_submitted": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rocket Trader research-only walk-forward evaluation")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--friction", type=float, default=0.00020,
                        help="Round-trip transaction costs as decimal return (e.g. 0.0002 = 2 bps)")
    parser.add_argument("--slippage-per-side", type=float, default=0.00010,
                        help="Slippage for each side (0.0001 = 1 bp each side)")
    parser.add_argument("--selection-fraction", type=float, default=0.60,
                        help="Initial fraction of OOS predictions used to select threshold; remainder is holdout")
    parser.add_argument("--thresholds", nargs="+", type=float, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", default="rocket_trader_signal_research_results.json",
                        help="Ruta del reporte JSON completo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 78)
    print(f"ROCKET TRADER — WALK-FORWARD SIGNAL RESEARCH v{VERSION}")
    print("MODE: RESEARCH ONLY | LIVE ORDERS: DISABLED | ORDER SUBMISSION: NOT IMPORTED")
    print("EXECUTION ASSUMPTION: signal close -> next bar open; non-overlapping long-only trades")
    print("=" * 78)
    if args.self_test:
        print(json.dumps(self_test(), indent=2, ensure_ascii=False, allow_nan=False))
        print("ROCKET TRADER SIGNAL RESEARCH SELF-TEST: OK")
        return 0
    if args.days < 15:
        print("ERROR: --days debe ser >= 15", file=sys.stderr)
        return 2
    if not 0.50 <= args.selection_fraction <= 0.80:
        print("ERROR: --selection-fraction debe estar entre 0.50 y 0.80", file=sys.stderr)
        return 2
    if args.friction < 0 or args.slippage_per_side < 0:
        print("ERROR: los costes no pueden ser negativos", file=sys.stderr)
        return 2
    if any(not 0 < t < 1 for t in args.thresholds):
        print("ERROR: todos los umbrales deben estar entre 0 y 1", file=sys.stderr)
        return 2

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for symbol in [s.upper() for s in args.symbols]:
        try:
            result = evaluate_symbol(symbol, args.days, args.friction, args.slippage_per_side,
                                     args.thresholds, args.selection_fraction)
            results.append(result)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        except Exception as exc:
            failure = {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
            failures.append(failure)
            print(json.dumps(failure, indent=2, ensure_ascii=False))

    summary = {
        "ok": bool(results) and not failures,
        "version": VERSION,
        "pipeline": "rocket_trader_signal_research",
        "mode": "RESEARCH_ONLY",
        "symbols_processed": [r["symbol"] for r in results],
        "symbols_failed": [r["symbol"] for r in failures],
        "research_pass": bool(results) and not failures and all(r["research_pass"] for r in results),
        "orders_enabled": False,
        "order_submission_imported": False,
        "orders_submitted": 0,
        "failures": failures,
    }
    report = {"summary": summary, "results": results}
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
    print(f"Reporte JSON guardado en: {args.output}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    print("ROCKET TRADER SIGNAL RESEARCH: OK" if summary["ok"] else "ROCKET TRADER SIGNAL RESEARCH: FAIL")
    # Technical success is separate from a strategy pass. A negative research result
    # should not mark the CI workflow as broken.
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
