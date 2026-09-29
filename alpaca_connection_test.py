#!/usr/bin/env python3
"""
Rocket Trader - Alpaca Paper Trading Connection Test

This module ONLY verifies authentication against Alpaca Paper Trading.
It does NOT submit, cancel, or modify any orders.
"""

from __future__ import annotations

import os
import sys


def require_environment() -> tuple[str, str]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    paper_raw = os.getenv("ALPACA_PAPER", "").strip().lower()

    if not api_key:
        raise RuntimeError("Missing required environment variable: ALPACA_API_KEY")
    if not secret_key:
        raise RuntimeError("Missing required environment variable: ALPACA_SECRET_KEY")
    if paper_raw != "true":
        raise RuntimeError(
            "SAFETY STOP: ALPACA_PAPER must be exactly 'true'. "
            "This test refuses to connect to a non-Paper environment."
        )

    return api_key, secret_key


def main() -> int:
    try:
        api_key, secret_key = require_environment()

        from alpaca.trading.client import TradingClient

        # Explicitly force Paper Trading.
        trading_client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
        )

        # Read-only account request. No order or position mutation occurs.
        account = trading_client.get_account()

        status = getattr(account, "status", None)
        currency = getattr(account, "currency", None)
        trading_blocked = getattr(account, "trading_blocked", None)

        print("ROCKET_TRADER_ALPACA_CONNECTION_TEST")
        print("connection_ok=true")
        print("environment=PAPER")
        print(f"account_status={status}")
        print(f"currency={currency}")
        print(f"trading_blocked={trading_blocked}")
        print("orders_submitted=0")
        print("orders_cancelled=0")
        print("test_result=PASS")
        return 0

    except Exception as exc:
        print("ROCKET_TRADER_ALPACA_CONNECTION_TEST")
        print("connection_ok=false")
        print("environment=PAPER")
        print("orders_submitted=0")
        print("orders_cancelled=0")
        print("test_result=FAIL")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
