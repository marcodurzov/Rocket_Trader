#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only check of crypto asset metadata on the Alpaca Paper endpoint.

This script does not submit, cancel or modify orders. It only checks the account
metadata and whether selected crypto assets are exposed as tradable by Alpaca.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict


SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]


def main() -> int:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    paper = os.getenv("ALPACA_PAPER", "").strip().lower()
    if not api_key or not secret_key:
        print(json.dumps({"ok": False, "error": "Missing Alpaca credentials"}))
        return 2
    if paper != "true":
        print(json.dumps({"ok": False, "error": "ALPACA_PAPER must be true"}))
        return 2

    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key, secret_key, paper=True)
        account = client.get_account()
        output: Dict[str, Any] = {
            "ok": True,
            "environment": "PAPER",
            "account_status": str(getattr(account, "status", None)),
            "account_currency": str(getattr(account, "currency", None)),
            "crypto_status": str(getattr(account, "crypto_status", None)),
            "trading_blocked": getattr(account, "trading_blocked", None),
            "assets": {},
            "orders_submitted": 0,
            "orders_cancelled": 0,
            "positions_modified": 0,
        }
        for symbol in SYMBOLS:
            try:
                asset = client.get_asset(symbol)
                output["assets"][symbol] = {
                    "lookup": "SUCCESS",
                    "asset_class": str(getattr(asset, "class", None)),
                    "status": str(getattr(asset, "status", None)),
                    "tradable": getattr(asset, "tradable", None),
                    "fractionable": getattr(asset, "fractionable", None),
                    "min_order_size": str(getattr(asset, "min_order_size", None)),
                    "min_trade_increment": str(getattr(asset, "min_trade_increment", None)),
                    "price_increment": str(getattr(asset, "price_increment", None)),
                }
            except Exception as exc:
                output["assets"][symbol] = {
                    "lookup": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "environment": "PAPER",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "orders_submitted": 0,
            "orders_cancelled": 0,
            "positions_modified": 0,
        }, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
