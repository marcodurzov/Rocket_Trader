#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — LIVE SIGNAL PIPELINE v0.4

Flujo:
    Alpaca Market Data
        ↓
    MarketData Layer
        ↓
    FeatureEngine
        ↓
    SignalEngine / Ensemble
        ↓
    SignalCandidate

SEGURIDAD
---------
- MARKET DATA ONLY + SIGNAL RESEARCH.
- NO TradingClient.
- NO submit_order().
- NO compra.
- NO venta.
- NO modificación de posiciones.
- El pipeline solamente genera una señal estadística.
- La ejecución continúa separada y bloqueada en PAPER.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, List

import pandas as pd

from rocket_trader_market_data import (
    AlpacaMarketDataClient,
    MarketBar,
    MarketDataError,
)

from rocket_trader_engine import (
    EngineConfig,
    SignalEngine,
)


PIPELINE_VERSION = "0.4"

# 1,200 minutos calendario ya produjo 401 barras reales en Market Data v0.3.
DEFAULT_MINUTES = 1200

# Si IEX devuelve menos barras de las necesarias, ampliamos automáticamente.
FALLBACK_MINUTES = 10080  # 7 días calendario.

# El Engine requiere >= 300 filas de entrenamiento.
# Dejamos margen para warm-up de indicadores y horizonte de predicción.
MIN_RAW_BARS = 400

DEFAULT_SYMBOLS = ["SPY", "QQQ"]


def bars_to_dataframe(bars: List[MarketBar]) -> pd.DataFrame:
    """Convierte MarketBar a OHLCV DataFrame compatible con SignalEngine."""
    if not bars:
        raise MarketDataError("No se recibieron barras para construir el DataFrame.")

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

    required = ["timestamp", "open", "high", "low", "close", "volume"]

    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise MarketDataError(
            f"Faltan columnas requeridas para SignalEngine: {missing}"
        )

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)

    for column in required[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = (
        frame.dropna(subset=required)
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )

    if frame.empty:
        raise MarketDataError(
            "Después de normalizar OHLCV no quedaron barras utilizables."
        )

    return frame


def fetch_training_bars(
    client: AlpacaMarketDataClient,
    symbol: str,
) -> tuple[List[MarketBar], int]:
    """
    Obtiene suficiente historial real.

    Primero usa la ventana normal de 1,200 minutos.
    Si IEX entrega menos de 400 barras, amplía automáticamente a 7 días.
    """
    bars = client.get_recent_bars(
        symbol=symbol,
        minutes=DEFAULT_MINUTES,
    )

    if len(bars) >= MIN_RAW_BARS:
        return bars, DEFAULT_MINUTES

    fallback_bars = client.get_recent_bars(
        symbol=symbol,
        minutes=FALLBACK_MINUTES,
    )

    if len(fallback_bars) >= MIN_RAW_BARS:
        return fallback_bars, FALLBACK_MINUTES

    raise MarketDataError(
        f"{symbol}: historial insuficiente. "
        f"Ventana normal={len(bars)} barras; "
        f"fallback={len(fallback_bars)} barras; "
        f"mínimo requerido={MIN_RAW_BARS}."
    )


def build_signal_engine() -> SignalEngine:
    """
    Configuración alineada con el Engine actual.
    """
    config = EngineConfig(
        horizon_bars=5,
        target_return=0.004,
        min_history_bars=100,
        training_stride=5,
        max_training_rows=1200,
        validation_fraction=0.20,
        min_training_rows=300,
        probability_threshold=0.58,
        novelty_distance_threshold=2.5,
        max_candidate_risk_pct=0.01,
    )

    return SignalEngine(config)


def process_symbol(
    client: AlpacaMarketDataClient,
    symbol: str,
) -> Dict[str, Any]:
    symbol = str(symbol).strip().upper()

    if not symbol:
        raise ValueError("El símbolo no puede estar vacío.")

    bars, requested_minutes = fetch_training_bars(client, symbol)

    frame = bars_to_dataframe(bars)

    if len(frame) < MIN_RAW_BARS:
        raise MarketDataError(
            f"{symbol}: después de normalizar quedaron {len(frame)} barras; "
            f"mínimo requerido={MIN_RAW_BARS}."
        )

    engine = build_signal_engine()

    training = engine.train(frame)
    signal = engine.generate_signal(frame, symbol)

    return {
        "symbol": symbol,
        "pipeline_version": PIPELINE_VERSION,
        "engine_version": training.get("engine_version"),
        "requested_minutes": requested_minutes,
        "raw_bars_received": len(bars),
        "normalized_bars": len(frame),
        "training": training,
        "signal": asdict(signal),
        "execution": {
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
            "order_submitted": False,
        },
    }


def run_pipeline(symbols: List[str]) -> Dict[str, Any]:
    client = AlpacaMarketDataClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
    )

    results: List[Dict[str, Any]] = []

    for symbol in symbols:
        print("=" * 72)
        print(f"PROCESSING SYMBOL: {symbol}")
        print("=" * 72)

        result = process_symbol(client, symbol)
        results.append(result)

        signal = result["signal"]

        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "probability_up": signal["probability_up"],
                    "expected_return": signal["expected_return"],
                    "confidence": signal["confidence"],
                    "score": signal["score"],
                    "evidence_class": signal["evidence_class"],
                    "setup_signature": signal["setup_signature"],
                    "model_votes": signal["model_votes"],
                    "raw_bars_received": result["raw_bars_received"],
                    "normalized_bars": result["normalized_bars"],
                    "requested_minutes": result["requested_minutes"],
                    "orders_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    return {
        "ok": True,
        "pipeline": "rocket_trader_live_signal",
        "version": PIPELINE_VERSION,
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "order_submitted": False,
        "orders_submitted": 0,
        "symbols_processed": [result["symbol"] for result in results],
        "results": results,
    }


def self_test() -> Dict[str, Any]:
    """
    Self-test estructural.
    No consulta Alpaca y no genera órdenes.
    """
    assert PIPELINE_VERSION == "0.4"
    assert DEFAULT_MINUTES >= 1200
    assert FALLBACK_MINUTES > DEFAULT_MINUTES
    assert MIN_RAW_BARS >= 400

    frame = pd.DataFrame(
        [
            {
                "timestamp": "2026-10-02T20:00:00+00:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            },
            {
                "timestamp": "2026-10-02T20:01:00+00:00",
                "open": 100.5,
                "high": 101.5,
                "low": 100.0,
                "close": 101.0,
                "volume": 1100.0,
            },
        ]
    )

    normalized = bars_to_dataframe(
        [
            MarketBar(
                symbol="TEST",
                timestamp=row["timestamp"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            for _, row in frame.iterrows()
        ]
    )

    assert list(normalized.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert len(normalized) == 2

    return {
        "ok": True,
        "pipeline_version": PIPELINE_VERSION,
        "default_minutes": DEFAULT_MINUTES,
        "fallback_minutes": FALLBACK_MINUTES,
        "min_raw_bars": MIN_RAW_BARS,
        "orders_enabled": False,
    }


def parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rocket Trader Live Signal Pipeline"
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Símbolos a procesar.",
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Ejecuta solamente el self-test estructural.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        print("=" * 72)
        print(f"ROCKET TRADER — LIVE SIGNAL PIPELINE v{PIPELINE_VERSION}")
        print("=" * 72)
        print("MODE: PAPER ONLY")
        print("LIVE ORDERS: DISABLED")
        print("ORDER SUBMISSION: DISABLED")
        print("=" * 72)

        if args.self_test:
            result = self_test()
        else:
            result = run_pipeline(args.symbols)

        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        if result.get("ok"):
            print("=" * 72)
            print("ROCKET TRADER LIVE SIGNAL PIPELINE: OK")
            print("=" * 72)

    except KeyboardInterrupt:
        print("\nROCKET TRADER LIVE SIGNAL PIPELINE: STOPPED")
        return

    except Exception as exc:
        print(
            f"ROCKET TRADER LIVE SIGNAL PIPELINE: FAIL: {exc}",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
