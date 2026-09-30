#!/usr/bin/env python3
"""
Rocket Trader — Integration Gate v0.1

Objetivo:
1. Verificar que core, engine y bridge importan correctamente.
2. Ejecutar sus self-tests cuando estén disponibles.
3. Verificar conexión PAPER con Alpaca.
4. Leer datos reales de mercado.
5. NO enviar órdenes.
6. NO modificar posiciones.
7. Fallar cerrado ante cualquier inconsistencia.

Este archivo NO habilita LIVE.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timedelta, timezone


MODULES = (
    "rocket_trader_core",
    "rocket_trader_engine",
    "rocket_trader_bridge",
)

SYMBOLS = ("SPY", "QQQ", "AAPL")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(2)


def check_module(name: str):
    print(f"[MODULE] importing {name} ...")
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        fail(f"No se pudo importar {name}: {type(exc).__name__}: {exc}")

    print(f"[MODULE] {name}: OK")

    self_test = getattr(module, "self_test", None)
    if callable(self_test):
        print(f"[SELF-TEST] {name} ...")
        try:
            result = self_test()
        except Exception as exc:
            fail(
                f"El self_test de {name} falló: "
                f"{type(exc).__name__}: {exc}"
            )
        print(f"[SELF-TEST] {name}: OK")
        return module, result

    print(f"[SELF-TEST] {name}: no disponible; importación verificada")
    return module, None


def check_alpaca():
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    paper = os.getenv("ALPACA_PAPER", "true").strip().lower()

    if not api_key or not api_secret:
        fail("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY.")

    if paper != "true":
        fail("ALPACA_PAPER debe ser exactamente 'true'.")

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.trading.client import TradingClient
    except Exception as exc:
        fail(f"No se pudo importar alpaca-py: {type(exc).__name__}: {exc}")

    print("[ALPACA] conectando en PAPER ...")

    try:
        trading = TradingClient(api_key, api_secret, paper=True)
        account = trading.get_account()
    except Exception as exc:
        fail(f"Falló la lectura de cuenta PAPER: {type(exc).__name__}: {exc}")

    if str(getattr(account, "currency", "")).upper() != "USD":
        fail(f"Moneda inesperada en Alpaca: {getattr(account, 'currency', None)}")

    print(
        "[ALPACA] account OK | "
        f"status={getattr(account, 'status', None)} | "
        f"cash={getattr(account, 'cash', None)} | "
        f"equity={getattr(account, 'equity', None)}"
    )

    try:
        market = StockHistoricalDataClient(api_key, api_secret)

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)

        request = StockBarsRequest(
            symbol_or_symbols=list(SYMBOLS),
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex",
        )

        bars = market.get_stock_bars(request)
    except Exception as exc:
        fail(f"Falló la lectura de mercado: {type(exc).__name__}: {exc}")

    print("[ALPACA] market data OK")

    for symbol in SYMBOLS:
        try:
            rows = bars[symbol]
        except Exception:
            rows = []

        if not rows:
            fail(f"No se recibieron barras IEX para {symbol}.")

        last = rows[-1]

        fields = {
            "open": getattr(last, "open", None),
            "high": getattr(last, "high", None),
            "low": getattr(last, "low", None),
            "close": getattr(last, "close", None),
            "volume": getattr(last, "volume", None),
        }

        if any(value is None for value in fields.values()):
            fail(f"OHLCV incompleto para {symbol}: {fields}")

        if fields["open"] <= 0 or fields["high"] <= 0:
            fail(f"Precio inválido para {symbol}: {fields}")

        if fields["low"] > fields["high"]:
            fail(f"Rango inválido para {symbol}: {fields}")

        if fields["volume"] < 0:
            fail(f"Volumen inválido para {symbol}: {fields}")

        print(
            f"[DATA] {symbol} | "
            f"O={fields['open']} H={fields['high']} "
            f"L={fields['low']} C={fields['close']} "
            f"V={fields['volume']}"
        )

    # Seguridad: este gate no debe modificar órdenes ni posiciones.
    try:
        open_orders = trading.get_orders()
    except Exception as exc:
        fail(f"No se pudo verificar la lista de órdenes: {type(exc).__name__}: {exc}")

    print(f"[SAFETY] órdenes abiertas detectadas: {len(open_orders)}")
    print("[SAFETY] este test no crea, modifica ni cancela órdenes.")

    return {
        "account_status": str(getattr(account, "status", "")),
        "currency": str(getattr(account, "currency", "")),
        "symbols": list(SYMBOLS),
        "open_orders_checked": len(open_orders),
    }


def main() -> None:
    print("=" * 72)
    print("ROCKET TRADER — INTEGRATION GATE v0.1")
    print("MODE: PAPER ONLY")
    print("LIVE ORDERS: DISABLED")
    print("=" * 72)

    results = {}

    for module_name in MODULES:
        module, self_test_result = check_module(module_name)
        results[module_name] = {
            "imported": True,
            "self_test": self_test_result is not None,
        }

    alpaca_result = check_alpaca()

    print("=" * 72)
    print("PASS — Rocket Trader integration gate completed.")
    print("No trading order was submitted.")
    print("No position was modified.")
    print("=" * 72)

    print(
        {
            "modules": results,
            "alpaca": alpaca_result,
            "live_enabled": False,
        }
    )


if __name__ == "__main__":
    main()
