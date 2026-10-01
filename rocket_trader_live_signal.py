#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — LIVE SIGNAL PIPELINE v0.1

Flujo:

    Alpaca Market Data
            ↓
    Real OHLCV
            ↓
    FeatureEngine
            ↓
    SignalEngine
            ↓
    SignalCandidate
            ↓
    NO EXECUTION

SEGURIDAD
---------
- Real market data.
- No TradingClient.
- No submit_order().
- No buy.
- No sell.
- No position modification.
- Signal generation only.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

from rocket_trader_engine import (
    FeatureEngine,
    SignalEngine,
    SignalCandidate,
)

from rocket_trader_market_data import (
    AlpacaMarketDataClient,
)


DEFAULT_SYMBOLS = ["SPY", "QQQ"]
DEFAULT_MINUTES = 300


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)

    if isinstance(obj, dict):
        return obj.get(name, default)

    return default


def _candidate_to_dict(candidate: Any) -> Dict[str, Any]:
    if candidate is None:
        return {}

    if hasattr(candidate, "__dataclass_fields__"):
        return asdict(candidate)

    if hasattr(candidate, "__dict__"):
        return dict(vars(candidate))

    if isinstance(candidate, dict):
        return dict(candidate)

    return {
        "value": str(candidate),
    }


def bars_to_dataframe(bars: List[Any]) -> pd.DataFrame:
    """
    Convierte MarketBar[] al formato OHLCV esperado por FeatureEngine.
    """

    if not bars:
        raise ValueError(
            "No se recibieron barras de mercado."
        )

    rows = []

    for bar in bars:
        rows.append(
            {
                "timestamp": pd.to_datetime(
                    _get_value(bar, "timestamp"),
                    utc=True,
                ),
                "open": float(
                    _get_value(bar, "open")
                ),
                "high": float(
                    _get_value(bar, "high")
                ),
                "low": float(
                    _get_value(bar, "low")
                ),
                "close": float(
                    _get_value(bar, "close")
                ),
                "volume": float(
                    _get_value(bar, "volume")
                ),
            }
        )

    frame = pd.DataFrame(rows)

    if frame.empty:
        raise ValueError(
            "El DataFrame de mercado quedó vacío."
        )

    frame = frame.sort_values(
        "timestamp"
    ).drop_duplicates(
        subset=["timestamp"],
        keep="last",
    )

    frame = frame.set_index(
        "timestamp"
    )

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

    frame = frame.dropna(
        subset=numeric_columns
    )

    if len(frame) < 60:
        raise ValueError(
            f"Insuficientes barras válidas: {len(frame)}. "
            "Se requieren al menos 60."
        )

    return frame


def build_real_market_frame(
    client: AlpacaMarketDataClient,
    symbol: str,
    minutes: int = DEFAULT_MINUTES,
) -> pd.DataFrame:
    bars = client.get_recent_bars(
        symbol=symbol,
        minutes=minutes,
    )

    frame = bars_to_dataframe(bars)

    return frame


def build_feature_engine() -> FeatureEngine:
    return FeatureEngine()


def build_signal_engine() -> SignalEngine:
    """
    Construye SignalEngine utilizando introspección para mantener
    compatibilidad con la implementación actual del engine.
    """

    signature = inspect.signature(
        SignalEngine
    )

    kwargs: Dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if name == "self":
            continue

        if parameter.default is not inspect.Parameter.empty:
            continue

        if name == "model":
            kwargs[name] = None
            continue

        if name == "ensemble":
            kwargs[name] = None
            continue

        if name == "config":
            continue

    try:
        return SignalEngine(**kwargs)
    except TypeError:
        return SignalEngine()


def generate_signal(
    symbol: str,
    frame: pd.DataFrame,
) -> Any:
    """
    Genera una señal utilizando el engine existente.

    Esta función intenta las firmas compatibles más comunes
    del SignalEngine actual sin alterar el engine.
    """

    feature_engine = build_feature_engine()
    signal_engine = build_signal_engine()

    features = feature_engine.transform(frame)

    attempts = [
        lambda: signal_engine.generate_signal(
            symbol=symbol,
            data=frame,
            features=features,
        ),
        lambda: signal_engine.generate_signal(
            symbol=symbol,
            features=features,
        ),
        lambda: signal_engine.generate(
            symbol=symbol,
            data=frame,
            features=features,
        ),
        lambda: signal_engine.generate(
            symbol=symbol,
            features=features,
        ),
        lambda: signal_engine.predict(
            symbol=symbol,
            features=features,
        ),
    ]

    errors = []

    for attempt in attempts:
        try:
            result = attempt()

            if result is not None:
                return result

        except AttributeError as exc:
            errors.append(
                f"AttributeError: {exc}"
            )

        except TypeError as exc:
            errors.append(
                f"TypeError: {exc}"
            )

    raise RuntimeError(
        "No se pudo generar una señal con la API actual "
        "de SignalEngine.\n"
        + "\n".join(errors)
    )


def inspect_signal(
    symbol: str,
    frame: pd.DataFrame,
    signal: Any,
) -> Dict[str, Any]:
    latest = frame.iloc[-1]

    return {
        "symbol": symbol,
        "market_data_source": "alpaca",
        "market_data_feed": "iex",
        "data_type": "REAL",
        "bars_used": len(frame),
        "first_bar": frame.index[0].isoformat(),
        "last_bar": frame.index[-1].isoformat(),
        "latest_close": float(latest["close"]),
        "latest_volume": float(latest["volume"]),
        "signal": _candidate_to_dict(signal),
        "execution": {
            "enabled": False,
            "mode": "SIGNAL_ONLY",
            "orders_submitted": 0,
        },
    }


def run_symbol(
    client: AlpacaMarketDataClient,
    symbol: str,
    minutes: int = DEFAULT_MINUTES,
) -> Dict[str, Any]:

    frame = build_real_market_frame(
        client=client,
        symbol=symbol,
        minutes=minutes,
    )

    signal = generate_signal(
        symbol=symbol,
        frame=frame,
    )

    return inspect_signal(
        symbol=symbol,
        frame=frame,
        signal=signal,
    )


def self_test() -> Dict[str, Any]:
    client = AlpacaMarketDataClient()

    results = []

    for symbol in DEFAULT_SYMBOLS:
        result = run_symbol(
            client=client,
            symbol=symbol,
            minutes=DEFAULT_MINUTES,
        )

        results.append(result)

    assert len(results) == len(DEFAULT_SYMBOLS)

    for result in results:
        assert result["market_data_source"] == "alpaca"
        assert result["data_type"] == "REAL"
        assert result["bars_used"] >= 60
        assert result["execution"]["enabled"] is False
        assert result["execution"]["orders_submitted"] == 0

    return {
        "ok": True,
        "module": "rocket_trader_live_signal",
        "version": "0.1",
        "market_data": "REAL_ALPACA_DATA",
        "feed": "IEX",
        "execution": "DISABLED",
        "orders_submitted": 0,
        "symbols": results,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def main() -> None:
    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL PIPELINE v0.1")
    print("=" * 72)
    print("MARKET DATA: REAL ALPACA DATA")
    print("FEED: IEX")
    print("SIGNAL GENERATION: ENABLED")
    print("ORDER EXECUTION: DISABLED")
    print("=" * 72)

    result = self_test()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    print("=" * 72)
    print("ROCKET TRADER LIVE SIGNAL PIPELINE: OK")
    print("=" * 72)


if __name__ == "__main__":
    main()
