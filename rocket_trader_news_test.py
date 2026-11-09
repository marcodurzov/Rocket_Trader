#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rocket_trader_news import self_test


def main() -> None:
    result = self_test()
    assert result["ok"] is True
    assert result["historical_backfill_point_in_time_eligible_by_default"] is False
    assert result["sentiment_scoring_enabled"] is False
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0
    print(result)


if __name__ == "__main__":
    main()
