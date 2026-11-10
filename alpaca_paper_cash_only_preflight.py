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
    positions = client.get_all_positions()
    apply_config = os.getenv("ROCKET_TRADER_APPLY_CASH_ONLY_CONFIG", "false").strip().lower()
    if apply_config not in {"true", "false"}:
        raise RuntimeError("ROCKET_TRADER_APPLY_CASH_ONLY_CONFIG must be true or false.")
    if apply_config == "true":
        if str(value(account, "status", "")).upper() != "ACTIVE":
            raise RuntimeError("Refusing configuration change: Paper account is not ACTIVE.")
        if str(value(account, "currency", "")).upper() != "USD":
            raise RuntimeError("Refusing configuration change: Paper account currency is not USD.")
        import requests
        response = requests.patch(
            "https://paper-api.alpaca.markets/v2/account/configurations",
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "max_margin_multiplier": "1",
                "no_shorting": True,
                "max_options_trading_level": 0,
            },
            timeout=20,
        )
        response.raise_for_status()
        config = client.get_account_configurations()
        account = client.get_account()
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
        "positions_count": len(positions),
        "crypto_positions": [
            {"symbol": str(value(p, "symbol", "")), "qty": str(value(p, "qty", "0"))}
            for p in positions if "/" in str(value(p, "symbol", ""))
        ],
        "orders_submitted": 0,
        "account_configuration_modified": 1 if apply_config == "true" else 0,
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
