#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — SIGNAL QUALITY / CALIBRATION TEST v0.1

Evalúa el modelo estadístico sobre datos reales de Alpaca sin enviar órdenes.

Pruebas:
- balance de clases
- accuracy
- precision
- recall
- ROC-AUC
- Brier score
- log loss
- matriz de confusión
- distribución de probabilidades
- calibración por bins
- concentración de probabilidades cerca de 0/1
- evaluación estrictamente temporal

NO:
- TradingClient
- submit_order
- compras
- ventas
- modificación de posiciones
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from rocket_trader_market_data import (
    AlpacaMarketDataClient,
    MarketDataError,
)

from rocket_trader_engine import (
    EngineConfig,
    EnsembleModel,
    FeatureEngine,
    TemporalDataset,
)


VERSION = "0.1"

DEFAULT_SYMBOLS = ["SPY", "QQQ"]

HISTORICAL_MINUTES = 10080
MIN_RAW_BARS = 400

TRAIN_FRACTION = 0.80

CALIBRATION_BINS = 10

EXTREME_LOW = 0.05
EXTREME_HIGH = 0.95

MAX_EXTREME_RATE = 0.95

MIN_TEST_ROWS = 100

DEFAULT_THRESHOLD = 0.58


def build_config() -> EngineConfig:
    return EngineConfig(
        horizon_bars=5,
        target_return=0.004,
        min_history_bars=100,
        training_stride=5,
        max_training_rows=1200,
        validation_fraction=0.20,
        min_training_rows=300,
        probability_threshold=DEFAULT_THRESHOLD,
        novelty_distance_threshold=2.5,
        max_candidate_risk_pct=0.01,
    )


def bars_to_dataframe(bars: List[Any]) -> pd.DataFrame:
    if not bars:
        raise MarketDataError(
            "No se recibieron barras."
        )

    frame = pd.DataFrame(
        [
            {
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
    )

    required = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    missing = [
        column
        for column in required
        if column not in frame.columns
    ]

    if missing:
        raise MarketDataError(
            f"Faltan columnas: {missing}"
        )

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    for column in required[1:]:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame = (
        frame
        .dropna(subset=required)
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    if frame.empty:
        raise MarketDataError(
            "No quedaron barras válidas después de normalizar."
        )

    return frame


def fetch_real_data(
    client: AlpacaMarketDataClient,
    symbol: str,
) -> pd.DataFrame:
    bars = client.get_recent_bars(
        symbol=symbol,
        minutes=HISTORICAL_MINUTES,
    )

    if len(bars) < MIN_RAW_BARS:
        raise MarketDataError(
            f"{symbol}: solamente se recibieron "
            f"{len(bars)} barras. "
            f"Mínimo requerido={MIN_RAW_BARS}."
        )

    frame = bars_to_dataframe(bars)

    if len(frame) < MIN_RAW_BARS:
        raise MarketDataError(
            f"{symbol}: solamente quedaron "
            f"{len(frame)} barras después de normalizar."
        )

    return frame


def calculate_calibration(
    probabilities: np.ndarray,
    actual: np.ndarray,
) -> Dict[str, Any]:
    bins: List[Dict[str, Any]] = []

    edges = np.linspace(
        0.0,
        1.0,
        CALIBRATION_BINS + 1,
    )

    for index in range(CALIBRATION_BINS):
        lower = float(edges[index])
        upper = float(edges[index + 1])

        if index == CALIBRATION_BINS - 1:
            mask = (
                (probabilities >= lower)
                & (probabilities <= upper)
            )
        else:
            mask = (
                (probabilities >= lower)
                & (probabilities < upper)
            )

        count = int(mask.sum())

        if count == 0:
            bins.append(
                {
                    "bin": index,
                    "lower": lower,
                    "upper": upper,
                    "count": 0,
                    "mean_probability": None,
                    "actual_rate": None,
                    "absolute_gap": None,
                }
            )
            continue

        mean_probability = float(
            probabilities[mask].mean()
        )

        actual_rate = float(
            actual[mask].mean()
        )

        bins.append(
            {
                "bin": index,
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_probability": mean_probability,
                "actual_rate": actual_rate,
                "absolute_gap": abs(
                    mean_probability - actual_rate
                ),
            }
        )

    populated = [
        item
        for item in bins
        if item["count"] > 0
    ]

    if populated:
        total = sum(
            item["count"]
            for item in populated
        )

        ece = sum(
            (
                item["count"]
                / total
            )
            * item["absolute_gap"]
            for item in populated
        )
    else:
        ece = None

    return {
        "bins": bins,
        "expected_calibration_error": (
            float(ece)
            if ece is not None
            else None
        ),
    }


def evaluate_symbol(
    frame: pd.DataFrame,
    symbol: str,
) -> Dict[str, Any]:
    config = build_config()

    features = FeatureEngine.build(
        frame
    )

    dataset = TemporalDataset(config)

    X, y = dataset.build(
        features
    )

    if len(X) < MIN_TEST_ROWS:
        raise MarketDataError(
            f"{symbol}: solamente existen "
            f"{len(X)} filas utilizables; "
            f"mínimo requerido={MIN_TEST_ROWS}."
        )

    split = int(
        len(X) * TRAIN_FRACTION
    )

    if split < config.min_training_rows:
        raise MarketDataError(
            f"{symbol}: entrenamiento insuficiente. "
            f"train_rows={split}."
        )

    X_train = X.iloc[:split].copy()
    X_test = X.iloc[split:].copy()

    y_train = y.iloc[:split].copy()
    y_test = y.iloc[split:].copy()

    if len(X_test) < MIN_TEST_ROWS:
        raise MarketDataError(
            f"{symbol}: test OOS insuficiente. "
            f"test_rows={len(X_test)}."
        )

    if y_train.nunique() < 2:
        raise MarketDataError(
            f"{symbol}: el conjunto de entrenamiento "
            "contiene una sola clase."
        )

    if y_test.nunique() < 2:
        raise MarketDataError(
            f"{symbol}: el conjunto OOS "
            "contiene una sola clase."
        )

    model = EnsembleModel(
        config
    )

    training = model.fit(
        X_train,
        y_train,
    )

    probabilities, votes = model.predict_proba(
        X_test
    )

    probabilities = np.asarray(
        probabilities,
        dtype=float,
    )

    actual = np.asarray(
        y_test,
        dtype=int,
    )

    probabilities = np.clip(
        probabilities,
        1e-7,
        1.0 - 1e-7,
    )

    predictions = (
        probabilities
        >= config.probability_threshold
    ).astype(int)

    auc = float(
        roc_auc_score(
            actual,
            probabilities,
        )
    )

    accuracy = float(
        accuracy_score(
            actual,
            predictions,
        )
    )

    precision = float(
        precision_score(
            actual,
            predictions,
            zero_division=0,
        )
    )

    recall = float(
        recall_score(
            actual,
            predictions,
            zero_division=0,
        )
    )

    brier = float(
        np.mean(
            (
                probabilities
                - actual
            ) ** 2
        )
    )

    loss = float(
        log_loss(
            actual,
            probabilities,
            labels=[0, 1],
        )
    )

    matrix = confusion_matrix(
        actual,
        predictions,
        labels=[0, 1],
    )

    extreme_mask = (
        (probabilities <= EXTREME_LOW)
        | (probabilities >= EXTREME_HIGH)
    )

    extreme_rate = float(
        extreme_mask.mean()
    )

    near_zero_rate = float(
        (
            probabilities
            <= EXTREME_LOW
        ).mean()
    )

    near_one_rate = float(
        (
            probabilities
            >= EXTREME_HIGH
        ).mean()
    )

    calibration = calculate_calibration(
        probabilities,
        actual,
    )

    model_vote_summary = {}

    for name, values in votes.items():
        values_array = np.asarray(
            values,
            dtype=float,
        )

        model_vote_summary[name] = {
            "mean": float(
                values_array.mean()
            ),
            "min": float(
                values_array.min()
            ),
            "max": float(
                values_array.max()
            ),
        }

    positive_rate = float(
        actual.mean()
    )

    quality_flags: List[str] = []

    if extreme_rate >= MAX_EXTREME_RATE:
        quality_flags.append(
            "PROBABILITY_COLLAPSE"
        )

    if brier >= 0.25:
        quality_flags.append(
            "HIGH_BRIER_SCORE"
        )

    if calibration[
        "expected_calibration_error"
    ] is not None and calibration[
        "expected_calibration_error"
    ] >= 0.15:
        quality_flags.append(
            "POOR_CALIBRATION"
        )

    if auc < 0.52:
        quality_flags.append(
            "LOW_ROC_AUC"
        )

    if accuracy < 0.50:
        quality_flags.append(
            "LOW_ACCURACY"
        )

    if not quality_flags:
        quality_flags.append(
            "NO_MAJOR_AUTOMATED_FLAG"
        )

    return {
        "symbol": symbol,
        "rows_total": int(len(frame)),
        "rows_usable": int(len(X)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "train_positive_rate": float(
            y_train.mean()
        ),
        "test_positive_rate": positive_rate,
        "metrics": {
            "roc_auc": auc,
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "brier_score": brier,
            "log_loss": loss,
        },
        "confusion_matrix": {
            "true_negative": int(matrix[0, 0]),
            "false_positive": int(matrix[0, 1]),
            "false_negative": int(matrix[1, 0]),
            "true_positive": int(matrix[1, 1]),
        },
        "probability_distribution": {
            "mean": float(
                probabilities.mean()
            ),
            "median": float(
                np.median(probabilities)
            ),
            "std": float(
                probabilities.std()
            ),
            "min": float(
                probabilities.min()
            ),
            "max": float(
                probabilities.max()
            ),
            "near_zero_rate": near_zero_rate,
            "near_one_rate": near_one_rate,
            "extreme_rate": extreme_rate,
        },
        "calibration": calibration,
        "model_votes": model_vote_summary,
        "training": training,
        "quality_flags": quality_flags,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def run_quality_test(
    symbols: List[str],
) -> Dict[str, Any]:
    client = AlpacaMarketDataClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
    )

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for raw_symbol in symbols:
        symbol = str(
            raw_symbol
        ).strip().upper()

        if not symbol:
            continue

        print("=" * 72)
        print(
            f"QUALITY TEST: {symbol}"
        )
        print("=" * 72)

        try:
            frame = fetch_real_data(
                client,
                symbol,
            )

            result = evaluate_symbol(
                frame,
                symbol,
            )

            results.append(result)

            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        except Exception as exc:
            failures.append(
                {
                    "symbol": symbol,
                    "error": str(exc),
                }
            )

            print(
                f"{symbol}: FAIL: {exc}",
                file=sys.stderr,
            )

    if not results:
        return {
            "ok": False,
            "version": VERSION,
            "pipeline": "rocket_trader_signal_quality",
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
            "orders_submitted": 0,
            "results": [],
            "failures": failures,
        }

    all_flags = []

    for result in results:
        all_flags.extend(
            result["quality_flags"]
        )

    probability_collapse = (
        "PROBABILITY_COLLAPSE"
        in all_flags
    )

    ok = (
        len(failures) == 0
        and not probability_collapse
    )

    return {
        "ok": ok,
        "version": VERSION,
        "pipeline": "rocket_trader_signal_quality",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "orders_submitted": 0,
        "symbols_processed": [
            result["symbol"]
            for result in results
        ],
        "results": results,
        "failures": failures,
        "summary": {
            "probability_collapse_detected": probability_collapse,
            "symbols_with_results": len(results),
            "symbols_failed": len(failures),
        },
    }


def self_test() -> Dict[str, Any]:
    """
    Self-test puramente estructural.
    No consulta Alpaca.
    No entrena modelos.
    No genera órdenes.
    """
    assert VERSION == "0.1"
    assert HISTORICAL_MINUTES >= 10080
    assert MIN_RAW_BARS >= 400
    assert 0.5 < TRAIN_FRACTION < 1.0
    assert CALIBRATION_BINS >= 5
    assert 0.0 < EXTREME_LOW < 0.5
    assert 0.5 < EXTREME_HIGH < 1.0
    assert MAX_EXTREME_RATE < 1.0
    assert MIN_TEST_ROWS >= 50

    probabilities = np.array(
        [
            0.10,
            0.20,
            0.30,
            0.40,
            0.60,
            0.70,
            0.80,
            0.90,
        ],
        dtype=float,
    )

    actual = np.array(
        [
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
        ],
        dtype=int,
    )

    calibration = calculate_calibration(
        probabilities,
        actual,
    )

    assert calibration[
        "expected_calibration_error"
    ] is not None

    assert math.isfinite(
        calibration[
            "expected_calibration_error"
        ]
    )

    return {
        "ok": True,
        "version": VERSION,
        "pipeline": "rocket_trader_signal_quality",
        "historical_minutes": HISTORICAL_MINUTES,
        "min_raw_bars": MIN_RAW_BARS,
        "train_fraction": TRAIN_FRACTION,
        "calibration_bins": CALIBRATION_BINS,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Rocket Trader Signal Quality "
            "and Calibration Test"
        )
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Símbolos a evaluar.",
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Ejecuta solamente el self-test.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        print("=" * 72)
        print(
            "ROCKET TRADER — SIGNAL QUALITY / "
            f"CALIBRATION TEST v{VERSION}"
        )
        print("=" * 72)
        print("MODE: PAPER ONLY")
        print("LIVE ORDERS: DISABLED")
        print("ORDER SUBMISSION: DISABLED")
        print("=" * 72)

        if args.self_test:
            result = self_test()
        else:
            result = run_quality_test(
                args.symbols
            )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        if result.get("ok"):
            print("=" * 72)
            print(
                "ROCKET TRADER SIGNAL QUALITY TEST: OK"
            )
            print("=" * 72)
        else:
            print("=" * 72)
            print(
                "ROCKET TRADER SIGNAL QUALITY TEST: "
                "FAIL"
            )
            print("=" * 72)
            raise SystemExit(1)

    except KeyboardInterrupt:
        print(
            "\nROCKET TRADER SIGNAL QUALITY TEST: STOPPED"
        )
        raise SystemExit(130)

    except SystemExit:
        raise

    except Exception as exc:
        print(
            "ROCKET TRADER SIGNAL QUALITY TEST: "
            f"FAIL: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
