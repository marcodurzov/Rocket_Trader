#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Integration Gate v0.2

Valida:

1. rocket_trader_core
2. rocket_trader_engine
3. rocket_trader_bridge
4. rocket_trader_adaptive
5. Alpaca Paper authentication
6. Alpaca Paper account
7. Alpaca market data
8. Open orders

NO envía órdenes.
NO modifica posiciones.
LIVE está explícitamente deshabilitado.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timedelta, timezone


SEPARATOR = "=" * 72


def print_header() -> None:

    print(SEPARATOR)
    print(
        "ROCKET TRADER — INTEGRATION GATE v0.2"
    )
    print(SEPARATOR)
    print("MODE: PAPER ONLY")
    print("LIVE ORDERS: DISABLED")
    print(SEPARATOR)


def run_module_self_test(
    module_name: str,
) -> bool:

    print(
        f"[MODULE] importing {module_name} ..."
    )

    try:

        module = importlib.import_module(
            module_name
        )

        print(
            f"[MODULE] {module_name}: OK"
        )

    except Exception as exc:

        print(
            f"FAIL: No se pudo importar "
            f"{module_name}: "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    self_test = getattr(
        module,
        "self_test",
        None,
    )

    if self_test is None:

        print(
            f"[SELF-TEST] {module_name}: "
            f"SKIPPED"
        )

        return True

    print(
        f"[SELF-TEST] {module_name} ..."
    )

    try:

        result = self_test()

        print(
            f"[SELF-TEST] {module_name}: OK"
        )

        print(
            f"[SELF-TEST RESULT] {result}"
        )

        return True

    except Exception as exc:

        print(
            f"FAIL: self_test de "
            f"{module_name}: "
            f"{type(exc).__name__}: {exc}"
        )

        return False


def verify_environment() -> bool:

    print("[ENV] checking secrets ...")

    required = [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ]

    for name in required:

        if not os.getenv(name):

            print(
                f"FAIL: falta secret {name}"
            )

            return False

    paper = os.getenv(
        "ALPACA_PAPER",
        "true",
    ).lower()

    live = os.getenv(
        "ALPACA_LIVE_ENABLED",
        "false",
    ).lower()

    if paper != "true":

        print(
            "FAIL: ALPACA_PAPER debe ser true"
        )

        return False

    if live == "true":

        print(
            "FAIL: ALPACA_LIVE_ENABLED "
            "debe permanecer false"
        )

        return False

    print("[ENV] secrets: OK")
    print("[ENV] PAPER: OK")
    print("[ENV] LIVE: DISABLED")

    return True


def verify_alpaca() -> bool:

    print(
        "[ALPACA] connecting to Paper ..."
    )

    try:

        from alpaca.trading.client import (
            TradingClient,
        )

        from alpaca.data.historical import (
            StockHistoricalDataClient,
        )

        from alpaca.data.requests import (
            StockBarsRequest,
        )

        from alpaca.data.timeframe import (
            TimeFrame,
        )

    except Exception as exc:

        print(
            f"FAIL: alpaca-py import: "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    api_key = os.environ[
        "ALPACA_API_KEY"
    ]

    secret = os.environ[
        "ALPACA_SECRET_KEY"
    ]

    try:

        trading_client = TradingClient(
            api_key,
            secret,
            paper=True,
        )

        account = (
            trading_client.get_account()
        )

        print(
            "[ALPACA] account: OK"
        )

        print(
            f"[ALPACA] currency: "
            f"{account.currency}"
        )

        if str(account.currency).upper() != "USD":

            print(
                "FAIL: Alpaca account currency "
                "unexpected"
            )

            return False

    except Exception as exc:

        print(
            f"FAIL: Alpaca account: "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    try:

        data_client = (
            StockHistoricalDataClient(
                api_key,
                secret,
            )
        )

        end = datetime.now(
            timezone.utc
        )

        start = (
            end - timedelta(days=7)
        )

        request = StockBarsRequest(
            symbol_or_symbols=[
                "SPY",
                "QQQ",
                "AAPL",
            ],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex",
        )

        bars = data_client.get_stock_bars(
            request
        )

        df = bars.df

        if df is None or df.empty:

            print(
                "FAIL: market data vacío"
            )

            return False

        print(
            "[ALPACA] market data: OK"
        )

        print(
            f"[ALPACA] rows received: "
            f"{len(df)}"
        )

        required_columns = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        missing = (
            required_columns
            - set(df.columns)
        )

        if missing:

            print(
                "FAIL: OHLCV missing: "
                f"{sorted(missing)}"
            )

            return False

        print(
            "[ALPACA] OHLCV validation: OK"
        )

    except Exception as exc:

        print(
            f"FAIL: Alpaca market data: "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    try:

        orders = (
            trading_client.get_orders()
        )

        print(
            "[ALPACA] open orders query: OK"
        )

        print(
            f"[ALPACA] orders returned: "
            f"{len(orders)}"
        )

    except Exception as exc:

        print(
            f"FAIL: open orders query: "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    print(
        "[ALPACA] NO orders submitted"
    )

    print(
        "[ALPACA] NO positions modified"
    )

    return True


def main() -> int:

    print_header()

    modules = [
        "rocket_trader_core",
        "rocket_trader_engine",
        "rocket_trader_bridge",
        "rocket_trader_adaptive",
    ]

    for module_name in modules:

        if not run_module_self_test(
            module_name
        ):

            print(SEPARATOR)
            print(
                "ROCKET TRADER "
                "INTEGRATION GATE: FAIL"
            )
            print(SEPARATOR)

            return 2

    if not verify_environment():

        print(SEPARATOR)
        print(
            "ROCKET TRADER "
            "INTEGRATION GATE: FAIL"
        )
        print(SEPARATOR)

        return 2

    if not verify_alpaca():

        print(SEPARATOR)
        print(
            "ROCKET TRADER "
            "INTEGRATION GATE: FAIL"
        )
        print(SEPARATOR)

        return 2

    print(SEPARATOR)
    print(
        "ROCKET TRADER "
        "INTEGRATION GATE: PASS"
    )
    print(SEPARATOR)

    return 0


if __name__ == "__main__":
    sys.exit(main())