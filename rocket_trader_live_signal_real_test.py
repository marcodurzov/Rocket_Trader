#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — LIVE SIGNAL REAL TEST v0.1

Valida el pipeline completo usando datos reales de Alpaca:

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
- Datos reales de mercado.
- Señales reales.
- NO TradingClient.
- NO submit_order().
- NO compra.
- NO venta.
- NO modificación de posiciones.
- El resultado solamente se utiliza para investigación.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from rocket_trader_live_signal import run_pipeline


SYMBOLS = ["SPY", "QQQ"]


def validate_signal_result(result: Dict[str, Any]) -> None:
    assert result["ok"] is True
    assert result["pipeline"] == "rocket_trader_live_signal"
    assert result["version"] == "0.4"

    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0
    assert result["order_submitted"] is False

    assert set(result["symbols_processed"]) == set(SYMBOLS)

    results = result["results"]

    assert len(results) == len(SYMBOLS)

    for item in results:
        assert item["symbol"] in SYMBOLS

        assert item["raw_bars_received"] >= 400
        assert item["normalized_bars"] >= 400

        assert item["training"] is not None
        assert item["signal"] is not None

        signal = item["signal"]

        assert 0.0 <= float(signal["probability_up"]) <= 1.0
        assert 0.0 <= float(signal["confidence"]) <= 1.0
        assert 0.0 <= float(signal["score"]) <= 1.0

        assert signal["evidence_class"] in {
            "PRECEDENTED",
            "NOVEL",
            "INSUFFICIENT",
        }

        assert isinstance(signal["setup_signature"], str)

        assert item["execution"]["orders_enabled"] is False
        assert item["execution"]["order_submitted"] is False


def main() -> None:
    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL REAL TEST v0.1")
    print("=" * 72)
    print("MARKET DATA: REAL")
    print("SIGNALS: REAL")
    print("ORDERS: DISABLED")
    print("SYMBOLS: SPY, QQQ")
    print("=" * 72)

    if not os.getenv("ALPACA_API_KEY"):
        raise RuntimeError("ALPACA_API_KEY no está configurada.")

    if not os.getenv("ALPACA_SECRET_KEY"):
        raise RuntimeError("ALPACA_SECRET_KEY no está configurada.")

    result = run_pipeline(SYMBOLS)

    validate_signal_result(result)

    print("=" * 72)
    print("REAL SIGNAL RESULTS")
    print("=" * 72)

    for item in result["results"]:
        signal = item["signal"]

        output = {
            "symbol": item["symbol"],
            "raw_bars_received": item["raw_bars_received"],
            "normalized_bars": item["normalized_bars"],
            "requested_minutes": item["requested_minutes"],
            "probability_up": signal["probability_up"],
            "expected_return": signal["expected_return"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "evidence_class": signal["evidence_class"],
            "setup_signature": signal["setup_signature"],
            "model_votes": signal["model_votes"],
            "orders_enabled": False,
            "orders_submitted": 0,
        }

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    print("=" * 72)
    print("ROCKET TRADER LIVE SIGNAL REAL TEST: OK")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"ROCKET TRADER LIVE SIGNAL REAL TEST: FAIL: {exc}",
            file=sys.stderr,
        )
        raise
