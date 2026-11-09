#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rocket_trader_crypto_engine import self_test


def main() -> None:
    result = self_test()
    assert result["ok"] is True
    assert result["mode"] == "RESEARCH_ONLY"
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0
    assert result["sample_taker_round_trip_cost_usd"]["total_round_trip_cost"] > 0
    print(result)


if __name__ == "__main__":
    main()
