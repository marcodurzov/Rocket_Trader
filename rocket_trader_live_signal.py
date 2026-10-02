#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Live Signal Pipeline v0.3

FLUJO:

    Alpaca IEX
        ↓
    Market Data REAL
        ↓
    pandas OHLCV
        ↓
    FeatureEngine REAL
        ↓
    SignalEngine REAL
        ↓
    SignalCandidate
        ↓
    diagnóstico de señal

IMPORTANTE:

- MARKET DATA: REAL
- SIGNALS: ENABLED
- ORDERS: DISABLED
- Este módulo NO coloca órdenes.
- Este módulo NO usa TradingClient.
- Este módulo NO modifica posiciones.
- Este módulo únicamente obtiene datos reales y genera señales
  mediante el Statistical / ML Engine existente.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Dict, List

import pandas as pd

from rocket_trader_engine import (
    EngineConfig,
    FeatureEngine,
    MarketDataValidator,
    SignalCandidate,
    SignalEngine,
)

from rocket_trader_market_data import (
    AlpacaMarketDataClient,
    MarketBar,
)


PIPELINE_VERSION = "0.3"

DEFAULT_SYMBOLS = ("SPY", "QQQ")

# Se solicitan suficientes minutos para que, aun con mercado
# cerrado/fines de semana/horarios no negociables, exista
# historial suficiente para entrenar el modelo.
DEFAULT_MINUTES = 1200

MIN_RAW_BARS = 400

ORDERS_ENABLED = False


def _print_header() -> None:
    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL PIPELINE v0.3")
    print("=" * 72)
    print("MARKET DATA: REAL")
    print("FEATURE ENGINE: REAL")
    print("SIGNALS: ENABLED")
    print("ORDERS: DISABLED")
    print("=" * 72)


def bars_to_dataframe(
    bars: List[MarketBar],
) -> pd.DataFrame:
    """
    Convierte las MarketBar reales de Alpaca a un DataFrame
    compatible con MarketDataValidator / FeatureEngine.
    """

    if not bars:
        raise ValueError("Alpaca no devolvió barras de mercado.")

    rows: List[Dict[str, Any]] = []

    for bar in bars:
        rows.append(
            {
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

    frame = pd.DataFrame(rows)

    frame = MarketDataValidator.normalize(frame)

    return frame


def build_engine_config() -> EngineConfig:
    """
    Configuración operacional del SignalEngine.

    Se mantiene alineada con el Engine real.
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

    config.validate()

    return config


def build_signal_engine() -> SignalEngine:
    """
    Construye el SignalEngine real de Rocket Trader.
    """

    config = build_engine_config()

    return SignalEngine(config)


def build_real_market_frame(
    client: AlpacaMarketDataClient,
    symbol: str,
    minutes: int = DEFAULT_MINUTES,
) -> pd.DataFrame:
    """
    Obtiene datos reales de Alpaca y los convierte al formato
    esperado por FeatureEngine / SignalEngine.
    """

    bars = client.get_recent_bars(
        symbol=symbol,
        minutes=minutes,
    )

    if len(bars) < MIN_RAW_BARS:
        raise RuntimeError(
            f"{symbol}: historial insuficiente. "
            f"Se recibieron {len(bars)} barras; "
            f"mínimo requerido: {MIN_RAW_BARS}."
        )

    frame = bars_to_dataframe(bars)

    if len(frame) < MIN_RAW_BARS:
        raise RuntimeError(
            f"{symbol}: DataFrame insuficiente después de normalización: "
            f"{len(frame)} barras."
        )

    return frame


def inspect_features(
    frame: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Ejecuta FeatureEngine REAL y devuelve diagnóstico.
    """

    features = FeatureEngine.build(frame)

    required_columns = [
        "ret_1",
        "ret_3",
        "ret_5",
        "ret_10",
        "ret_20",
        "vol_5",
        "vol_10",
        "vol_20",
        "atr_pct",
        "rsi_14",
        "macd_norm",
        "macd_signal_norm",
        "macd_hist_norm",
        "bb_position",
        "bb_width",
        "volume_ratio_20",
        "volume_z_20",
        "high_break_20",
        "low_break_20",
        "trend_strength",
        "drawdown_20",
    ]

    missing = [
        column
        for column in required_columns
        if column not in features.columns
    ]

    if missing:
        raise RuntimeError(
            f"FeatureEngine no produjo las features esperadas: {missing}"
        )

    latest = features.iloc[-1]

    return {
        "rows": int(len(features)),
        "columns": int(len(features.columns)),
        "latest_timestamp": str(latest["timestamp"]),
        "latest_close": float(latest["close"]),
        "feature_columns_present": len(required_columns),
        "features": {
            column: (
                float(latest[column])
                if pd.notna(latest[column])
                else None
            )
            for column in required_columns
        },
    }


def generate_signal(
    frame: pd.DataFrame,
    symbol: str,
) -> SignalCandidate:
    """
    Entrena el SignalEngine REAL con el historial disponible
    y genera una SignalCandidate REAL sobre la última barra.

    No coloca órdenes.
    """

    if frame is None or frame.empty:
        raise ValueError(
            f"{symbol}: market frame vacío."
        )

    engine = build_signal_engine()

    training = engine.train(frame)

    if not engine.trained:
        raise RuntimeError(
            f"{symbol}: SignalEngine no quedó entrenado."
        )

    signal = engine.generate_signal(
        frame,
        symbol,
    )

    if not isinstance(signal, SignalCandidate):
        raise TypeError(
            f"{symbol}: generate_signal devolvió "
            f"{type(signal).__name__}; "
            f"se esperaba SignalCandidate."
        )

    print("")
    print(f"[{symbol}] ENGINE TRAINING")
    print(f"  rows: {training['rows']}")
    print(f"  positive_rate: {training['positive_rate']:.6f}")
    print(f"  fingerprint: {training['fingerprint']}")
    print(f"  models: {training['models']}")
    print(f"  weights: {training['weights']}")

    return signal


def signal_to_dict(
    signal: SignalCandidate,
) -> Dict[str, Any]:
    """
    Convierte SignalCandidate a un diccionario serializable.
    """

    return dataclasses.asdict(signal)


def print_signal(
    signal: SignalCandidate,
) -> None:
    """
    Imprime el diagnóstico de la señal.
    """

    print("")
    print("=" * 72)
    print(f"SIGNAL DIAGNOSTIC — {signal.symbol}")
    print("=" * 72)

    print(f"timestamp:       {signal.timestamp}")
    print(f"probability_up:  {signal.probability_up:.6f}")
    print(f"expected_return: {signal.expected_return:.6f}")
    print(f"confidence:      {signal.confidence:.6f}")
    print(f"score:            {signal.score:.6f}")
    print(f"evidence_class:  {signal.evidence_class}")
    print(f"setup_signature: {signal.setup_signature}")

    print("")
    print("MODEL VOTES:")

    for name, value in signal.model_votes.items():
        print(
            f"  {name}: {value:.6f}"
        )

    print("")
    print("SELECTED FEATURES:")

    for name, value in signal.features.items():
        print(
            f"  {name}: {value:.8f}"
        )

    print("=" * 72)


def run_symbol(
    client: AlpacaMarketDataClient,
    symbol: str,
    minutes: int = DEFAULT_MINUTES,
) -> Dict[str, Any]:
    """
    Ejecuta todo el pipeline para un símbolo:

        Alpaca
        → OHLCV
        → FeatureEngine
        → SignalEngine
        → SignalCandidate
    """

    symbol = str(symbol).strip().upper()

    if not symbol:
        raise ValueError(
            "El símbolo no puede estar vacío."
        )

    print("")
    print("-" * 72)
    print(f"PROCESSING SYMBOL: {symbol}")
    print("-" * 72)

    frame = build_real_market_frame(
        client=client,
        symbol=symbol,
        minutes=minutes,
    )

    print(
        f"[{symbol}] REAL MARKET DATA: "
        f"{len(frame)} bars"
    )

    print(
        f"[{symbol}] FIRST BAR: "
        f"{frame.iloc[0]['timestamp']}"
    )

    print(
        f"[{symbol}] LAST BAR: "
        f"{frame.iloc[-1]['timestamp']}"
    )

    print(
        f"[{symbol}] LAST CLOSE: "
        f"{float(frame.iloc[-1]['close']):.6f}"
    )

    feature_diagnostic = inspect_features(frame)

    print("")
    print(
        f"[{symbol}] FEATURE ENGINE: OK"
    )

    print(
        f"[{symbol}] FEATURE ROWS: "
        f"{feature_diagnostic['rows']}"
    )

    signal = generate_signal(
        frame=frame,
        symbol=symbol,
    )

    print_signal(signal)

    result = {
        "symbol": symbol,
        "bars": int(len(frame)),
        "first_timestamp": str(frame.iloc[0]["timestamp"]),
        "last_timestamp": str(frame.iloc[-1]["timestamp"]),
        "last_close": float(frame.iloc[-1]["close"]),
        "feature_diagnostic": feature_diagnostic,
        "signal": signal_to_dict(signal),
        "orders_enabled": False,
    }

    return result


def self_test() -> Dict[str, Any]:
    """
    Test completo del Live Signal Pipeline.

    Usa:
    - credenciales reales de Alpaca
    - market data real IEX
    - FeatureEngine real
    - SignalEngine real

    Nunca coloca órdenes.
    """

    _print_header()

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key:
        raise RuntimeError(
            "Falta ALPACA_API_KEY en las variables de entorno."
        )

    if not secret_key:
        raise RuntimeError(
            "Falta ALPACA_SECRET_KEY en las variables de entorno."
        )

    if ORDERS_ENABLED:
        raise RuntimeError(
            "FAIL-SAFE: ORDERS_ENABLED no puede estar activo "
            "en Live Signal Pipeline."
        )

    client = AlpacaMarketDataClient(
        api_key=api_key,
        secret_key=secret_key,
    )

    results: Dict[str, Any] = {}

    for symbol in DEFAULT_SYMBOLS:
        results[symbol] = run_symbol(
            client=client,
            symbol=symbol,
            minutes=DEFAULT_MINUTES,
        )

    if not results:
        raise RuntimeError(
            "No se generaron resultados."
        )

    for symbol, result in results.items():
        signal = result["signal"]

        probability = float(
            signal["probability_up"]
        )

        confidence = float(
            signal["confidence"]
        )

        score = float(
            signal["score"]
        )

        if not 0.0 <= probability <= 1.0:
            raise AssertionError(
                f"{symbol}: probability_up fuera de rango."
            )

        if not 0.0 <= confidence <= 1.0:
            raise AssertionError(
                f"{symbol}: confidence fuera de rango."
            )

        if score < 0.0:
            raise AssertionError(
                f"{symbol}: score negativo."
            )

        if not signal["setup_signature"]:
            raise AssertionError(
                f"{symbol}: setup_signature vacío."
            )

    print("")
    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL TEST RESULT")
    print("=" * 72)

    for symbol, result in results.items():
        signal = result["signal"]

        print("")
        print(f"{symbol}")
        print(f"  bars:             {result['bars']}")
        print(
            f"  last_close:       "
            f"{result['last_close']:.6f}"
        )
        print(
            f"  probability_up:   "
            f"{signal['probability_up']:.6f}"
        )
        print(
            f"  expected_return:  "
            f"{signal['expected_return']:.6f}"
        )
        print(
            f"  confidence:       "
            f"{signal['confidence']:.6f}"
        )
        print(
            f"  score:            "
            f"{signal['score']:.6f}"
        )
        print(
            f"  evidence_class:   "
            f"{signal['evidence_class']}"
        )

    print("")
    print("ORDERS SUBMITTED: 0")
    print("POSITIONS MODIFIED: 0")
    print("MODE: SIGNAL ONLY")
    print("=" * 72)

    return {
        "ok": True,
        "pipeline_version": PIPELINE_VERSION,
        "market_data": "REAL",
        "feed": "IEX",
        "feature_engine": "REAL",
        "signal_engine": "REAL",
        "orders_enabled": False,
        "orders_submitted": 0,
        "positions_modified": 0,
        "symbols": results,
    }


def main() -> None:
    result = self_test()

    print("")
    print("[SELF-TEST RESULT]")
    print(result)


if __name__ == "__main__":
    main()
