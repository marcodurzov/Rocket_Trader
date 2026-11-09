#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — Crypto spot market data adapter (read-only).

This module fetches public historical crypto bars and latest quotes from Alpaca.
It deliberately has no TradingClient and cannot submit, cancel or modify orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from alpaca.data.enums import CryptoFeed
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame


class CryptoMarketDataError(RuntimeError):
    """Controlled error raised by the crypto market-data layer."""


@dataclass(frozen=True)
class CryptoBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: Optional[int] = None
    vwap: Optional[float] = None


@dataclass(frozen=True)
class CryptoQuote:
    symbol: str
    timestamp: str
    bid: float
    ask: float
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        midpoint = self.midpoint
        return (self.ask - self.bid) / midpoint if midpoint > 0 else float("inf")


class AlpacaCryptoMarketDataClient:
    """Read-only Alpaca crypto data client. Historical data does not require API keys."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: CryptoFeed = CryptoFeed.US,
        client: Optional[CryptoHistoricalDataClient] = None,
    ) -> None:
        self.feed = feed
        self.client = client or CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        value = str(symbol).strip().upper().replace("-", "/")
        if not value or "/" not in value:
            raise CryptoMarketDataError(
                f"Par cripto inválido {symbol!r}; se espera formato BASE/QUOTE, por ejemplo BTC/USD."
            )
        base, quote = value.split("/", 1)
        if not base or not quote or len(base) > 12 or len(quote) > 12:
            raise CryptoMarketDataError(f"Par cripto inválido: {symbol!r}")
        return f"{base}/{quote}"

    @classmethod
    def normalize_bars_frame(
        cls,
        frame: pd.DataFrame,
        symbol: str,
    ) -> pd.DataFrame:
        """Normalize Alpaca's symbol/timestamp MultiIndex or flat OHLCV frame."""
        symbol = cls.normalize_symbol(symbol)
        if frame is None or frame.empty:
            raise CryptoMarketDataError(f"{symbol}: Alpaca devolvió barras vacías.")

        df = frame.copy()
        if isinstance(df.index, pd.MultiIndex):
            levels = [
                set(map(str, df.index.get_level_values(i).unique()))
                for i in range(df.index.nlevels)
            ]
            symbol_level = next(
                (i for i, values in enumerate(levels) if symbol in values),
                None,
            )
            if symbol_level is not None:
                df = df.xs(symbol, level=symbol_level)
        df = df.reset_index()
        df.columns = [str(col).strip().lower() for col in df.columns]

        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise CryptoMarketDataError(
                f"{symbol}: faltan columnas OHLCV: {missing}"
            )

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        invalid = df[required].isna().any(axis=1)
        invalid |= (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        invalid |= df["volume"] < 0
        invalid |= df["high"] < df[["open", "close"]].max(axis=1)
        invalid |= df["low"] > df[["open", "close"]].min(axis=1)
        invalid |= df["high"] < df["low"]
        if invalid.any():
            raise CryptoMarketDataError(
                f"{symbol}: {int(invalid.sum())} barras inválidas; se rechaza el conjunto."
            )

        keep = required + [
            col for col in ("trade_count", "transactions", "vwap")
            if col in df.columns
        ]
        df = (
            df[keep]
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .reset_index(drop=True)
        )
        if df.empty:
            raise CryptoMarketDataError(f"{symbol}: no quedaron barras válidas.")
        return df

    def get_recent_bars(
        self,
        symbol: str,
        minutes: int = 10_080,
        timeframe: TimeFrame = TimeFrame.Minute,
    ) -> List[CryptoBar]:
        if minutes < 1:
            raise ValueError("minutes debe ser >= 1")
        clean_symbol = self.normalize_symbol(symbol)
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        request = CryptoBarsRequest(
            symbol_or_symbols=[clean_symbol],
            timeframe=timeframe,
            start=start,
            end=end,
        )
        try:
            response = self.client.get_crypto_bars(request, feed=self.feed)
            frame = response.df
            normalized = self.normalize_bars_frame(frame, clean_symbol)
        except Exception as exc:
            if isinstance(exc, CryptoMarketDataError):
                raise
            raise CryptoMarketDataError(
                f"Error consultando barras de {clean_symbol} en Alpaca: {type(exc).__name__}: {exc}"
            ) from exc

        bars: List[CryptoBar] = []
        for row in normalized.to_dict(orient="records"):
            bars.append(
                CryptoBar(
                    symbol=clean_symbol,
                    timestamp=pd.Timestamp(row["timestamp"]).isoformat(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    trade_count=(
                        int(row["trade_count"])
                        if row.get("trade_count") is not None and pd.notna(row.get("trade_count"))
                        else int(row["transactions"])
                        if row.get("transactions") is not None and pd.notna(row.get("transactions"))
                        else None
                    ),
                    vwap=(
                        float(row["vwap"])
                        if row.get("vwap") is not None and pd.notna(row.get("vwap"))
                        else None
                    ),
                )
            )
        return bars

    def get_latest_quotes(self, symbols: Sequence[str]) -> Dict[str, CryptoQuote]:
        clean_symbols = sorted({self.normalize_symbol(symbol) for symbol in symbols})
        if not clean_symbols:
            raise ValueError("Se requiere al menos un par cripto.")
        request = CryptoLatestQuoteRequest(symbol_or_symbols=clean_symbols)
        try:
            response = self.client.get_crypto_latest_quote(request, feed=self.feed)
        except Exception as exc:
            raise CryptoMarketDataError(
                f"Error consultando quotes cripto: {type(exc).__name__}: {exc}"
            ) from exc

        quotes: Dict[str, CryptoQuote] = {}
        for symbol in clean_symbols:
            quote = response.get(symbol)
            if quote is None:
                continue
            bid = float(quote.bid_price)
            ask = float(quote.ask_price)
            if bid <= 0 or ask <= 0 or ask < bid:
                raise CryptoMarketDataError(
                    f"{symbol}: quote inválido (bid={bid}, ask={ask})."
                )
            quotes[symbol] = CryptoQuote(
                symbol=symbol,
                timestamp=pd.Timestamp(quote.timestamp).isoformat(),
                bid=bid,
                ask=ask,
                bid_size=(
                    float(quote.bid_size)
                    if getattr(quote, "bid_size", None) is not None
                    else None
                ),
                ask_size=(
                    float(quote.ask_size)
                    if getattr(quote, "ask_size", None) is not None
                    else None
                ),
            )
        return quotes


def self_test() -> Dict[str, Any]:
    import numpy as np

    symbol = "BTC/USD"
    index = pd.MultiIndex.from_product(
        [[symbol], pd.date_range("2026-01-01", periods=4, freq="min", tz="UTC")],
        names=["symbol", "timestamp"],
    )
    frame = pd.DataFrame(
        {
            "open": [100, 101, 102, 103],
            "high": [101, 102, 103, 104],
            "low": [99, 100, 101, 102],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [0, 2, 3, 4],
            "trade_count": [0, 2, 3, 4],
            "vwap": [100.5, 101.5, 102.5, 103.5],
        },
        index=index,
    )
    normalized = AlpacaCryptoMarketDataClient.normalize_bars_frame(frame, symbol)
    assert len(normalized) == 4
    assert normalized["timestamp"].is_monotonic_increasing
    assert normalized.loc[0, "volume"] == 0
    assert AlpacaCryptoMarketDataClient.normalize_symbol("btc-usd") == "BTC/USD"

    quote = CryptoQuote(
        symbol="BTC/USD",
        timestamp="2026-01-01T00:00:00+00:00",
        bid=99.0,
        ask=101.0,
    )
    assert quote.midpoint == 100.0
    assert np.isclose(quote.spread_pct, 0.02)

    rejected = False
    bad = frame.copy()
    bad.iloc[0, bad.columns.get_loc("low")] = 1000
    try:
        AlpacaCryptoMarketDataClient.normalize_bars_frame(bad, symbol)
    except CryptoMarketDataError:
        rejected = True
    assert rejected

    return {
        "ok": True,
        "version": "0.1",
        "pipeline": "rocket_trader_crypto_market_data",
        "mode": "READ_ONLY",
        "bars_normalized": len(normalized),
        "zero_volume_quote_midpoint_bar_supported": True,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
