#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — MARKET DATA TEST v0.1

Prueba el Market Data Layer contra Alpaca.

NO ENVÍA ÓRDENES.
"""

import json

from rocket_trader_market_data import self_test


def main() -> None:
    print("=" * 72)
    print("ROCKET TRADER — MARKET DATA TEST v0.1")
    print("=" * 72)
    print("MODE: PAPER MARKET DATA")
    print("LIVE ORDERS: DISABLED")
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

    assert result["ok"] is True

    print("=" * 72)
    print("ROCKET TRADER MARKET DATA TEST: OK")
    print("=" * 72)


if __name__ == "__main__":
    main()
