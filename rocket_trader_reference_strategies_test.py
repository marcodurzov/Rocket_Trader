#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rocket_trader_reference_strategies import self_test


def main() -> None:
    result = self_test()
    assert result["ok"] is True
    assert result["source_only_precedent_approval"] is False
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0
    print(result)


if __name__ == "__main__":
    main()
