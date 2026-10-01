#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — LIVE SIGNAL TEST v0.1

Real market data → FeatureEngine → SignalEngine.

NO ORDERS.
"""

import json

from rocket_trader_live_signal import self_test


def main() -> None:
    print("=" * 72)
    print("ROCKET TRADER — LIVE SIGNAL TEST v0.1")
    print("=" * 72)
    print("MARKET DATA: REAL")
    print("SIGNALS: ENABLED")
    print("ORDERS: DISABLED")
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
    assert result["orders_submitted"] == 0

    print("=" * 72)
    print("ROCKET TRADER LIVE SIGNAL TEST: OK")
    print("=" * 72)


if __name__ == "__main__":
    main()
