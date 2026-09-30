#!/usr/bin/env python3
"""Rocket Trader - Alpaca Paper account + market data read-only test."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

TEST_SYMBOLS = ["SPY", "QQQ", "AAPL"]


def require_environment() -> tuple[str, str]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    paper_raw = os.getenv("ALPACA_PAPER", "").strip().lower()
    if not api_key:
        raise RuntimeError("Missing required environment variable: ALPACA_API_KEY")
    if not secret_key:
        raise RuntimeError("Missing required environment variable: ALPACA_SECRET_KEY")
    if paper_raw != "true":
        raise RuntimeError("SAFETY STOP: ALPACA_PAPER must be exactly 'true'.")
    return api_key, secret_key


def validate_bars_dataframe(df) -> tuple[int, list[str]]:
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(set(df.columns)))
    if missing:
        raise RuntimeError("Missing columns: " + ", ".join(missing))
    if df.empty:
        raise RuntimeError("Zero market-data bars returned.")
    for column in required:
        if df[column].isna().any():
            raise RuntimeError(f"Column '{column}' contains NaN values.")
    if (df["high"] < df["low"]).any():
        raise RuntimeError("Invalid bar: high < low.")
    if ((df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).any():
        raise RuntimeError("Invalid bar: non-positive price.")
    if (df["volume"] < 0).any():
        raise RuntimeError("Invalid bar: negative volume.")
    return len(df), sorted(required)


def main() -> int:
    try:
        api_key, secret_key = require_environment()
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        trading_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
        account = trading_client.get_account()
        positions = trading_client.get_all_positions()
        config = trading_client.get_account_configurations()

        data_client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        now = datetime.now(timezone.utc)
        request = StockBarsRequest(
            symbol_or_symbols=TEST_SYMBOLS,
            timeframe=TimeFrame.Day,
            start=now - timedelta(days=10),
            end=now,
            feed=DataFeed.IEX,
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df
        count, columns = validate_bars_dataframe(df)

        symbols_returned = []
        if getattr(df.index, "nlevels", 1) >= 2:
            symbols_returned = sorted({str(x) for x in df.index.get_level_values(0)})

        print("ROCKET_TRADER_ALPACA_MARKET_DATA_TEST")
        print("connection_ok=true")
        print("environment=PAPER")
        print(f"account_status={getattr(account, 'status', None)}")
        print(f"currency={getattr(account, 'currency', None)}")
        print(f"equity={getattr(account, 'equity', None)}")
        print(f"buying_power={getattr(account, 'buying_power', None)}")
        print(f"trading_blocked={getattr(account, 'trading_blocked', None)}")
        print(f"positions_count={len(positions)}")
        print(f"no_shorting={getattr(config, 'no_shorting', None)}")
        print(f"max_margin_multiplier={getattr(config, 'max_margin_multiplier', None)}")
        print(f"symbols_requested={','.join(TEST_SYMBOLS)}")
        print(f"symbols_returned={','.join(symbols_returned)}")
        print(f"bars_returned={count}")
        print(f"validated_columns={','.join(columns)}")
        print("market_data_feed=IEX")
        print("orders_submitted=0")
        print("orders_cancelled=0")
        print("positions_modified=0")
        print("account_configuration_modified=0")
        print("test_result=PASS")
        return 0
    except Exception as exc:
        print("ROCKET_TRADER_ALPACA_MARKET_DATA_TEST")
        print("connection_ok=false")
        print("environment=PAPER")
        print("orders_submitted=0")
        print("orders_cancelled=0")
        print("positions_modified=0")
        print("account_configuration_modified=0")
        print("test_result=FAIL")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
