#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json

from rocket_trader_crypto_market_data import (
    AlpacaCryptoMarketDataClient,
    self_test,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--market-data",
        action="store_true",
        help="Fetch a small real BTC/USD history window from Alpaca (read-only).",
    )
    args = parser.parse_args()

    result = self_test()
    assert result["ok"] is True
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0

    if args.market_data:
        client = AlpacaCryptoMarketDataClient()
        bars = client.get_recent_bars("BTC/USD", minutes=180)
        if len(bars) < 30:
            raise AssertionError(
                f"Alpaca crypto data smoke test: only {len(bars)} bars returned."
            )
        result["real_market_data"] = {
            "symbol": "BTC/USD",
            "bars_received": len(bars),
            "first_timestamp": bars[0].timestamp,
            "last_timestamp": bars[-1].timestamp,
            "orders_enabled": False,
            "orders_submitted": 0,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
