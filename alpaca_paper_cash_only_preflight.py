#!/usr/bin/env python3
"""Read-only Alpaca Paper cash-only configuration preflight. Never submits orders."""
from __future__ import annotations
import os
import sys

def value(obj, name, default=None):
    item = getattr(obj, name, default)
    return item.value if hasattr(item, "value") else item

def main() -> int:
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: ALPACA_PAPER must be exactly true.")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError("Safety stop: LIVE mode is prohibited.")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Paper credentials are missing.")
    from alpaca.trading.client import TradingClient
    client = TradingClient(key, secret, paper=True)
    account = client.get_account()
    config = client.get_account_configurations()
    report = {
        "environment": "PAPER",
        "status": str(value(account, "status", "UNKNOWN")),
        "currency": str(value(account, "currency", "UNKNOWN")),
        "cash_usd": str(value(account, "cash", "UNKNOWN")),
        "equity_usd": str(value(account, "equity", "UNKNOWN")),
        "account_multiplier": str(value(account, "multiplier", "UNKNOWN")),
        "shorting_enabled": bool(value(account, "shorting_enabled", True)),
        "max_margin_multiplier": str(value(config, "max_margin_multiplier", "UNKNOWN")),
        "no_shorting": bool(value(config, "no_shorting", False)),
        "max_options_trading_level": value(config, "max_options_trading_level", None),
        "trading_blocked": bool(value(account, "trading_blocked", True)),
        "orders_submitted": 0,
        "account_configuration_modified": 0,
    }
    for key_name, item in report.items():
        print(f"{key_name}={item}")
    safe = (
        report["status"].upper() == "ACTIVE"
        and report["currency"].upper() == "USD"
        and report["account_multiplier"] == "1"
        and report["shorting_enabled"] is False
        and report["max_margin_multiplier"] == "1"
        and report["no_shorting"] is True
        and str(report["max_options_trading_level"]) == "0"
        and report["trading_blocked"] is False
    )
    print(f"cash_only_configuration_safe={str(safe).lower()}")
    print("orders_submitted=0")
    return 0 if safe else 2

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("environment=PAPER")
        print("orders_submitted=0")
        print(f"preflight_error={type(exc).__name__}: {exc}")
        raise
