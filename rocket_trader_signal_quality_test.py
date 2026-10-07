#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rocket Trader — Signal Quality / Calibration Test v0.2

Valida la calidad estadística del objetivo y del ensemble sobre datos reales
sin enviar órdenes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from rocket_trader_engine import EngineConfig, EnsembleModel, FeatureEngine, TemporalDataset
from rocket_trader_market_data import AlpacaMarketDataClient

VERSION = "0.4"
MIN_BARS = 400
REQUEST_MINUTES = 43200
TEST_FRACTION = 0.20
NEAR_ZERO_THRESHOLD = 0.05
NEAR_ONE_THRESHOLD = 0.95
PROBABILITY_COLLAPSE_RATE = 0.95
MIN_POSITIVE_RATE = 0.05
MIN_NEGATIVE_RATE = 0.05
MIN_TEST_POSITIVE_EVENTS = 10
MIN_TEST_NEGATIVE_EVENTS = 10


def bars_to_dataframe(bars: List[Any]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for bar in bars:
        rows.append({
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
    return pd.DataFrame(rows)


def fetch_bars(client: AlpacaMarketDataClient, symbol: str) -> pd.DataFrame:
    bars = client.get_recent_bars(symbol=symbol, minutes=REQUEST_MINUTES)
    if len(bars) < MIN_BARS:
        raise ValueError(f"{symbol}: solo se recibieron {len(bars)} barras; mínimo {MIN_BARS}")
    return bars_to_dataframe(bars)


def calibration_report(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> Dict[str, Any]:
    result = []
    ece = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for i in range(bins):
        lower, upper = float(edges[i]), float(edges[i + 1])
        if i == bins - 1:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        count = int(mask.sum())
        if count:
            mean_probability = float(probabilities[mask].mean())
            actual_rate = float(y_true[mask].mean())
            gap = abs(mean_probability - actual_rate)
            ece += (count / len(y_true)) * gap
        else:
            mean_probability = None
            actual_rate = None
            gap = None
        result.append({
            "bin": i,
            "lower": lower,
            "upper": upper,
            "count": count,
            "mean_probability": mean_probability,
            "actual_rate": actual_rate,
            "absolute_gap": gap,
        })
    return {"bins": result, "expected_calibration_error": float(ece)}


def evaluate_symbol(client: AlpacaMarketDataClient, symbol: str) -> Dict[str, Any]:
    raw = fetch_bars(client, symbol)
    features = FeatureEngine.build(raw)
    config = EngineConfig()
    dataset = TemporalDataset(config)
    X, y = dataset.build(features)

    split = int(len(X) * (1.0 - TEST_FRACTION))
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    if y_train.nunique() < 2 or y_test.nunique() < 2:
        raise ValueError(f"{symbol}: el split temporal no contiene ambas clases")

    model = EnsembleModel(config)
    training = model.fit(X_train, y_train)
    probabilities, votes = model.predict_proba(X_test)
    probabilities = np.asarray(probabilities, dtype=float)
    y_true = y_test.to_numpy(dtype=int)
    predictions = (probabilities >= config.probability_threshold).astype(int)

    auc = float(roc_auc_score(y_true, probabilities))
    accuracy = float(accuracy_score(y_true, predictions))
    precision = float(precision_score(y_true, predictions, zero_division=0))
    recall = float(recall_score(y_true, predictions, zero_division=0))
    brier = float(brier_score_loss(y_true, probabilities))
    loss = float(log_loss(y_true, probabilities, labels=[0, 1]))
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()

    near_zero_rate = float(np.mean(probabilities <= NEAR_ZERO_THRESHOLD))
    near_one_rate = float(np.mean(probabilities >= NEAR_ONE_THRESHOLD))
    extreme_rate = near_zero_rate + near_one_rate
    test_positive_rate = float(y_true.mean())
    train_positive_rate = float(y_train.mean())

    calibration = calibration_report(y_true, probabilities)
    flags: List[str] = []
    if extreme_rate >= PROBABILITY_COLLAPSE_RATE:
        flags.append("PROBABILITY_COLLAPSE")
    positive_events = int(y_true.sum())
    negative_events = int(len(y_true) - positive_events)
    if test_positive_rate < MIN_POSITIVE_RATE or test_positive_rate > (1.0 - MIN_NEGATIVE_RATE):
        flags.append("TEST_CLASS_IMBALANCE")
    if positive_events < MIN_TEST_POSITIVE_EVENTS or negative_events < MIN_TEST_NEGATIVE_EVENTS:
        flags.append("INSUFFICIENT_TEST_EVENTS")
    if calibration["expected_calibration_error"] >= 0.15:
        flags.append("POOR_CALIBRATION")
    if brier >= 0.25:
        flags.append("HIGH_BRIER_SCORE")
    if auc < 0.52:
        flags.append("LOW_ROC_AUC")

    return {
        "symbol": symbol,
        "rows_total": int(len(raw)),
        "rows_usable": int(len(X)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "target_return": config.target_return,
        "horizon_bars": config.horizon_bars,
        "train_positive_rate": train_positive_rate,
        "test_positive_rate": test_positive_rate,
        "metrics": {
            "roc_auc": auc,
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "brier_score": brier,
            "log_loss": loss,
        },
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
        "probability_distribution": {
            "mean": float(probabilities.mean()),
            "median": float(np.median(probabilities)),
            "std": float(probabilities.std()),
            "min": float(probabilities.min()),
            "max": float(probabilities.max()),
            "near_zero_rate": near_zero_rate,
            "near_one_rate": near_one_rate,
            "extreme_rate": extreme_rate,
        },
        "calibration": calibration,
        "model_votes": {
            name: {
                "mean": float(np.mean(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            }
            for name, values in votes.items()
        },
        "training": training,
        "quality_flags": flags,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def run(symbols: List[str]) -> Dict[str, Any]:
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY")

    client = AlpacaMarketDataClient(api_key=api_key, secret_key=secret_key)
    results = []
    failures = []

    for symbol in symbols:
        try:
            result = evaluate_symbol(client, symbol)
            results.append(result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})
            print(json.dumps({"symbol": symbol, "error": str(exc)}, indent=2, ensure_ascii=False))

    collapse = any("PROBABILITY_COLLAPSE" in r["quality_flags"] for r in results)
    imbalance = any("TEST_CLASS_IMBALANCE" in r["quality_flags"] for r in results)
    insufficient_events = any("INSUFFICIENT_TEST_EVENTS" in r["quality_flags"] for r in results)
    hard_quality_flags = any(
        any(flag in r["quality_flags"] for flag in (
            "PROBABILITY_COLLAPSE",
            "INSUFFICIENT_TEST_EVENTS",
            "POOR_CALIBRATION",
            "HIGH_BRIER_SCORE",
            "LOW_ROC_AUC",
        ))
        for r in results
    )
    ok = bool(results) and not failures and not hard_quality_flags

    return {
        "ok": ok,
        "version": VERSION,
        "pipeline": "rocket_trader_signal_quality",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "orders_submitted": 0,
        "symbols_processed": [r["symbol"] for r in results],
        "results": results,
        "failures": failures,
        "summary": {
            "probability_collapse_detected": collapse,
            "class_imbalance_detected": imbalance,
            "insufficient_test_events_detected": insufficient_events,
            "hard_quality_failure_detected": hard_quality_flags,
            "symbols_with_results": len(results),
            "symbols_failed": len(failures),
            "target_return": EngineConfig().target_return,
            "horizon_bars": EngineConfig().horizon_bars,
        },
    }


def self_test() -> Dict[str, Any]:
    config = EngineConfig()
    config.validate()
    return {
        "ok": True,
        "version": VERSION,
        "target_return": config.target_return,
        "horizon_bars": config.horizon_bars,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    args = parser.parse_args()

    print("=" * 72)
    print(f"ROCKET TRADER — SIGNAL QUALITY / CALIBRATION TEST v{VERSION}")
    print("=" * 72)
    print("MODE: PAPER ONLY")
    print("LIVE ORDERS: DISABLED")
    print("ORDER SUBMISSION: DISABLED")
    print("=" * 72)

    if args.self_test:
        print(json.dumps(self_test(), indent=2, ensure_ascii=False))
        return 0

    report = run([s.upper() for s in args.symbols])
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("=" * 72)
    if report["ok"]:
        print("ROCKET TRADER SIGNAL QUALITY TEST: OK")
        return 0
    print("ROCKET TRADER SIGNAL QUALITY TEST: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
