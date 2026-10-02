#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Live Signal Pipeline v0.2

FLUJO:

    Alpaca IEX
        ↓
    Market Data
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

SEGURIDAD:

- MARKET DATA: REAL
- SIGNALS: ENABLED
- ORDERS: DISABLED
- Este módulo NO importa TradingClient.
- Este módulo NO envía órdenes.
- Este módulo NO modifica posiciones.
- Este módulo NO habilita LIVE trading.

IMPORTANTE:
La integración con FeatureEngine y SignalEngine se realiza mediante
introspección controlada para utilizar la API realmente disponible en
rocket_trader_engine.py y evitar asumir métodos que no existen.
"""

from __future__ import annotations

import inspect
import json
import math
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from rocket_trader_engine import (
    FeatureEngine,
    SignalCandidate,
    SignalEngine,
)

from rocket_trader_market_data import (
    AlpacaMarketDataClient,
    MarketBar,
)


# ============================================================================
# CONFIG
# ============================================================================

DEFAULT_SYMBOLS = ("SPY", "QQQ")
DEFAULT_BAR_LIMIT = 300


# ============================================================================
# UTILIDADES
# ============================================================================


def _public_methods(obj: Any) -> List[str]:
    """
    Devuelve métodos públicos de una instancia.
    """
    methods: List[str] = []

    for name in dir(obj):
        if name.startswith("_"):
            continue

        try:
            value = getattr(obj, name)
        except Exception:
            continue

        if callable(value):
            methods.append(name)

    return sorted(methods)


def _safe_repr(value: Any, max_length: int = 1200) -> str:
    """
    Representación segura para logs.
    """
    try:
        if is_dataclass(value):
            text = repr(asdict(value))
        elif hasattr(value, "model_dump"):
            text = repr(value.model_dump())
        elif hasattr(value, "__dict__"):
            text = repr(vars(value))
        else:
            text = repr(value)
    except Exception:
        text = repr(value)

    if len(text) > max_length:
        return text[:max_length] + "...<truncated>"

    return text


def _is_dataframe_like(value: Any) -> bool:
    return isinstance(value, pd.DataFrame)


def _is_series_like(value: Any) -> bool:
    return isinstance(value, pd.Series)


def _is_numeric_matrix(value: Any) -> bool:
    """
    Determina si el resultado parece una matriz numérica.
    """
    if value is None:
        return False

    try:
        if hasattr(value, "shape") and len(value.shape) >= 1:
            return True

        if isinstance(value, (list, tuple)) and value:
            first = value[0]

            if isinstance(first, (list, tuple)):
                float(first[0])
                return True

            float(first)
            return True
    except Exception:
        return False

    return False


def _looks_like_signal(value: Any) -> bool:
    """
    Determina si un objeto parece SignalCandidate.
    """
    if value is None:
        return False

    if isinstance(value, SignalCandidate):
        return True

    names = set()

    try:
        names.update(vars(value).keys())
    except Exception:
        pass

    names.update(
        name
        for name in dir(value)
        if not name.startswith("_")
    )

    signal_fields = {
        "symbol",
        "side",
        "score",
        "confidence",
        "probability_up",
        "expected_return",
        "evidence_class",
        "strategy_id",
    }

    return len(names.intersection(signal_fields)) >= 2


# ============================================================================
# MARKET DATA → DATAFRAME
# ============================================================================


def bars_to_dataframe(
    bars: Sequence[MarketBar],
) -> pd.DataFrame:
    """
    Convierte MarketBar → DataFrame OHLCV.
    """

    if not bars:
        raise RuntimeError("No se recibieron barras de mercado.")

    rows: List[Dict[str, Any]] = []

    for bar in bars:
        rows.append(
            {
                "timestamp": pd.Timestamp(bar.timestamp),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

    frame = pd.DataFrame(rows)

    if frame.empty:
        raise RuntimeError("El DataFrame de mercado está vacío.")

    frame = frame.sort_values("timestamp")
    frame = frame.drop_duplicates(subset=["timestamp"])
    frame = frame.set_index("timestamp")

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric_columns:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame = frame.dropna(subset=numeric_columns)

    if len(frame) < 60:
        raise RuntimeError(
            f"Datos insuficientes para señal: {len(frame)} barras."
        )

    return frame


# ============================================================================
# MARKET DATA
# ============================================================================


def build_real_market_frame(
    client: AlpacaMarketDataClient,
    symbol: str,
    limit: int = DEFAULT_BAR_LIMIT,
) -> pd.DataFrame:
    """
    Descarga datos reales de Alpaca y los convierte a OHLCV.
    """

    bars = client.get_recent_bars(
        symbol=symbol,
        limit=limit,
    )

    frame = bars_to_dataframe(bars)

    if frame.empty:
        raise RuntimeError(
            f"No hay datos reales disponibles para {symbol}."
        )

    return frame


# ============================================================================
# FEATURE ENGINE
# ============================================================================


def build_feature_engine() -> FeatureEngine:
    """
    Construye FeatureEngine usando su constructor REAL.

    Primero intenta constructor sin argumentos.
    Si requiere configuración obligatoria, genera un error explícito.
    """

    try:
        return FeatureEngine()
    except TypeError as exc:
        raise RuntimeError(
            "FeatureEngine requiere argumentos en su constructor y "
            "la integración automática no puede inferirlos de forma segura. "
            f"Firma encontrada: {inspect.signature(FeatureEngine)}"
        ) from exc


def _candidate_feature_method_names() -> Tuple[str, ...]:
    """
    Orden de preferencia para métodos de generación de features.

    El método realmente existente en FeatureEngine será seleccionado
    dinámicamente.
    """

    return (
        "transform",
        "transform_features",
        "build_features",
        "create_features",
        "compute_features",
        "generate_features",
        "engineer_features",
        "make_features",
        "features",
        "build",
        "compute",
        "generate",
        "engineer",
        "make",
        "fit_transform",
    )


def _call_feature_method(
    method: Any,
    frame: pd.DataFrame,
) -> Any:
    """
    Ejecuta un método de FeatureEngine respetando su firma.
    """

    signature = inspect.signature(method)

    parameters = list(signature.parameters.values())

    positional_required = [
        p
        for p in parameters
        if p.name != "self"
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        and p.default is inspect.Parameter.empty
    ]

    if len(positional_required) == 0:
        return method()

    if len(positional_required) == 1:
        return method(frame)

    parameter_names = {
        p.name.lower()
        for p in parameters
        if p.name != "self"
    }

    frame_names = (
        "data",
        "df",
        "frame",
        "dataset",
        "ohlcv",
        "prices",
        "market_data",
    )

    for name in frame_names:
        if name in parameter_names:
            return method(**{name: frame})

    raise RuntimeError(
        "No se pudo determinar cómo pasar el DataFrame a "
        f"{method.__name__}{signature}"
    )


def generate_features(
    feature_engine: FeatureEngine,
    frame: pd.DataFrame,
) -> Any:
    """
    Ejecuta el FeatureEngine real.

    No presupone que exista transform().
    """

    available = _public_methods(feature_engine)

    preferred = [
        name
        for name in _candidate_feature_method_names()
        if name in available
    ]

    if not preferred:
        raise RuntimeError(
            "FeatureEngine no expone un método de generación de features "
            "compatible.\n"
            f"Métodos públicos disponibles: {available}"
        )

    errors: List[str] = []

    for method_name in preferred:
        method = getattr(feature_engine, method_name)

        try:
            result = _call_feature_method(
                method,
                frame,
            )

            if result is None:
                errors.append(
                    f"{method_name}: devolvió None"
                )
                continue

            return result

        except Exception as exc:
            errors.append(
                f"{method_name}: {type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Todos los métodos candidatos de FeatureEngine fallaron.\n"
        + "\n".join(errors)
    )


# ============================================================================
# SIGNAL ENGINE
# ============================================================================


def build_signal_engine(
    feature_engine: Optional[FeatureEngine] = None,
) -> SignalEngine:
    """
    Construye SignalEngine usando introspección de su constructor.
    """

    signature = inspect.signature(SignalEngine)
    parameters = list(signature.parameters.values())

    required = [
        p
        for p in parameters
        if p.name != "self"
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        and p.default is inspect.Parameter.empty
    ]

    if not required:
        return SignalEngine()

    kwargs: Dict[str, Any] = {}

    for parameter in required:
        name = parameter.name.lower()

        if name in {
            "feature_engine",
            "features",
            "feature",
        }:
            if feature_engine is None:
                raise RuntimeError(
                    "SignalEngine requiere FeatureEngine."
                )

            kwargs[parameter.name] = feature_engine
            continue

        raise RuntimeError(
            "SignalEngine requiere un argumento que no puede inferirse "
            f"de forma segura: '{parameter.name}'. "
            f"Firma: {signature}"
        )

    return SignalEngine(**kwargs)


# ============================================================================
# SIGNAL GENERATION
# ============================================================================


def _signal_method_names(
    signal_engine: SignalEngine,
) -> List[str]:
    """
    Obtiene métodos candidatos del SignalEngine.
    """

    preferred = (
        "generate_signal",
        "generate",
        "predict_signal",
        "predict",
        "score",
        "evaluate",
        "infer",
    )

    available = _public_methods(signal_engine)

    return [
        name
        for name in preferred
        if name in available
    ]


def _call_signal_method(
    method: Any,
    symbol: str,
    frame: pd.DataFrame,
    features: Any,
) -> Any:
    """
    Llama SignalEngine respetando la firma real.
    """

    signature = inspect.signature(method)

    parameters = [
        p
        for p in signature.parameters.values()
        if p.name != "self"
    ]

    kwargs: Dict[str, Any] = {}

    for parameter in parameters:
        name = parameter.name.lower()

        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue

        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            continue

        if name in {
            "symbol",
            "ticker",
            "asset",
        }:
            kwargs[parameter.name] = symbol
            continue

        if name in {
            "data",
            "df",
            "frame",
            "dataset",
            "ohlcv",
            "prices",
            "market_data",
        }:
            kwargs[parameter.name] = frame
            continue

        if name in {
            "features",
            "feature_data",
            "feature_frame",
            "x",
        }:
            kwargs[parameter.name] = features
            continue

        if (
            parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ):
            raise RuntimeError(
                f"No se pudo inferir argumento obligatorio "
                f"'{parameter.name}' para {method.__name__}{signature}"
            )

    return method(**kwargs)


def _normalize_signal(
    raw_signal: Any,
    symbol: str,
) -> Any:
    """
    Normaliza/valida mínimamente la señal.

    No inventa valores financieros.
    """

    if raw_signal is None:
        raise RuntimeError(
            f"SignalEngine devolvió None para {symbol}."
        )

    if _looks_like_signal(raw_signal):
        return raw_signal

    if isinstance(raw_signal, dict):
        return raw_signal

    if isinstance(raw_signal, tuple):
        return raw_signal

    raise RuntimeError(
        "SignalEngine devolvió un objeto no reconocido: "
        f"{type(raw_signal).__name__} — {_safe_repr(raw_signal)}"
    )


def generate_signal(
    symbol: str,
    frame: pd.DataFrame,
    feature_engine: FeatureEngine,
    signal_engine: SignalEngine,
) -> Tuple[Any, Any]:
    """
    Ejecuta:

        OHLCV → FeatureEngine → SignalEngine

    Devuelve:

        (features, signal)
    """

    features = generate_features(
        feature_engine=feature_engine,
        frame=frame,
    )

    methods = _signal_method_names(signal_engine)

    if not methods:
        raise RuntimeError(
            "SignalEngine no expone ningún método compatible.\n"
            f"Métodos públicos disponibles: "
            f"{_public_methods(signal_engine)}"
        )

    errors: List[str] = []

    for method_name in methods:
        method = getattr(signal_engine, method_name)

        try:
            raw_signal = _call_signal_method(
                method=method,
                symbol=symbol,
                frame=frame,
                features=features,
            )

            signal = _normalize_signal(
                raw_signal,
                symbol,
            )

            return features, signal

        except Exception as exc:
            errors.append(
                f"{method_name}: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Todos los métodos candidatos de SignalEngine fallaron.\n"
        + "\n".join(errors)
    )


# ============================================================================
# SIGNAL INSPECTION
# ============================================================================


def inspect_signal(
    signal: Any,
) -> Dict[str, Any]:
    """
    Convierte una señal en estructura serializable para diagnóstico.
    """

    if is_dataclass(signal):
        return asdict(signal)

    if hasattr(signal, "model_dump"):
        try:
            return signal.model_dump()
        except Exception:
            pass

    if isinstance(signal, dict):
        return dict(signal)

    if isinstance(signal, tuple):
        return {
            "type": "tuple",
            "value": repr(signal),
        }

    if hasattr(signal, "__dict__"):
        return dict(vars(signal))

    return {
        "type": type(signal).__name__,
        "repr": repr(signal),
    }


# ============================================================================
# SYMBOL PIPELINE
# ============================================================================


def run_symbol(
    client: AlpacaMarketDataClient,
    symbol: str,
    limit: int = DEFAULT_BAR_LIMIT,
) -> Dict[str, Any]:
    """
    Pipeline completo de un símbolo.

    IMPORTANTE:
    Aquí solamente se genera la señal.
    NO se ejecutan órdenes.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("symbol vacío.")

    print()
    print("=" * 72)
    print(f"SYMBOL: {symbol}")
    print("=" * 72)

    frame = build_real_market_frame(
        client=client,
        symbol=symbol,
        limit=limit,
    )

    print(f"REAL BARS: {len(frame)}")
    print(
        "LAST BAR:",
        frame.index[-1].isoformat(),
    )
    print(
        "LAST CLOSE:",
        f"{float(frame['close'].iloc[-1]):.4f}",
    )

    feature_engine = build_feature_engine()

    print(
        "FEATURE ENGINE:",
        type(feature_engine).__name__,
    )

    print(
        "FEATURE METHODS:",
        _public_methods(feature_engine),
    )

    signal_engine = build_signal_engine(
        feature_engine=feature_engine,
    )

    print(
        "SIGNAL ENGINE:",
        type(signal_engine).__name__,
    )

    print(
        "SIGNAL METHODS:",
        _public_methods(signal_engine),
    )

    features, signal = generate_signal(
        symbol=symbol,
        frame=frame,
        feature_engine=feature_engine,
        signal_engine=signal_engine,
    )

    signal_dict = inspect_signal(signal)

    print()
    print("FEATURE OUTPUT TYPE:")
    print(type(features).__name__)

    if isinstance(features, pd.DataFrame):
        print(
            "FEATURE SHAPE:",
            features.shape,
        )
        print(
            "FEATURE COLUMNS:",
            list(features.columns),
        )

    elif isinstance(features, pd.Series):
        print(
            "FEATURE SERIES LENGTH:",
            len(features),
        )

    elif hasattr(features, "shape"):
        print(
            "FEATURE SHAPE:",
            features.shape,
        )

    print()
    print("SIGNAL:")
    print(
        json.dumps(
            signal_dict,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    return {
        "ok": True,
        "symbol": symbol,
        "bars": len(frame),
        "last_timestamp": frame.index[-1].isoformat(),
        "last_close": float(frame["close"].iloc[-1]),
        "feature_type": type(features).__name__,
        "feature_shape": (
            list(features.shape)
            if hasattr(features, "shape")
            else None
        ),
        "signal_type": type(signal).__name__,
        "signal": signal_dict,
        "orders_submitted": 0,
    }


# ============================================================================
# SELF TEST
# ============================================================================


def self_test() -> Dict[str, Any]:
    """
    Prueba end-to-end:

        Alpaca REAL DATA
            ↓
        FeatureEngine
            ↓
        SignalEngine
            ↓
        Signal

    Sin órdenes.
    """

    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL TEST v0.2")
    print("=" * 72)
    print("MARKET DATA: REAL")
    print("FEATURE ENGINE: REAL")
    print("SIGNALS: ENABLED")
    print("ORDERS: DISABLED")
    print("=" * 72)

    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_SECRET_KEY")

    if not api_key:
        raise RuntimeError(
            "Falta ALPACA_API_KEY."
        )

    if not api_secret:
        raise RuntimeError(
            "Falta ALPACA_SECRET_KEY."
        )

    client = AlpacaMarketDataClient(
        api_key=api_key,
        api_secret=api_secret,
    )

    results: List[Dict[str, Any]] = []

    for symbol in DEFAULT_SYMBOLS:
        result = run_symbol(
            client=client,
            symbol=symbol,
            limit=DEFAULT_BAR_LIMIT,
        )

        results.append(result)

    result = {
        "ok": True,
        "market_data": "REAL",
        "signals": "ENABLED",
        "orders_submitted": 0,
        "symbols": results,
    }

    print()
    print("=" * 72)
    print("LIVE SIGNAL TEST RESULT")
    print("=" * 72)
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    print("=" * 72)

    return result


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    result = self_test()

    if not result.get("ok"):
        raise SystemExit(2)

    if result.get("orders_submitted", 0) != 0:
        raise SystemExit(
            "FAIL-SAFE: se detectaron órdenes enviadas."
        )

    for symbol_result in result.get("symbols", []):
        if symbol_result.get("orders_submitted", 0) != 0:
            raise SystemExit(
                "FAIL-SAFE: se detectaron órdenes enviadas "
                f"para {symbol_result.get('symbol')}."
            )

    print()
    print("ROCKET TRADER LIVE SIGNAL TEST: PASS")
    print("ORDERS SUBMITTED: 0")


if __name__ == "__main__":
    main()