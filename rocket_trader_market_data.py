#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — MARKET DATA v0.2

Responsabilidad
---------------
Conectar Rocket Trader con Alpaca Market Data y entregar datos
normalizados al resto del sistema.

Flujo:

    Alpaca Market Data
            ↓
    MarketDataClient
            ↓
    MarketSnapshotData
            ↓
    Rocket Trader Engine

SEGURIDAD
---------
- MARKET DATA ONLY.
- No TradingClient.
- No submit_order().
- No compra.
- No venta.
- No modificación de posiciones.
- No contiene API keys.
- Las credenciales se leen exclusivamente desde variables de entorno.
- Feed inicial: IEX.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestBarRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame


@dataclass(frozen=True)
class MarketBar:
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
class MarketSnapshotData:
    symbol: str
    timestamp: str
    price: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid: Optional[float]
    ask: Optional[float]
    latest_bar_timestamp: Optional[str]
    previous_close: Optional[float]


class MarketDataError(RuntimeError):
    """Error controlado del Market Data Layer."""


class AlpacaMarketDataClient:
    """
    Cliente exclusivo de Market Data.

    No tiene acceso a TradingClient.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        feed: DataFeed = DataFeed.IEX,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")

        if not self.api_key:
            raise MarketDataError(
                "Falta ALPACA_API_KEY en las variables de entorno."
            )

        if not self.secret_key:
            raise MarketDataError(
                "Falta ALPACA_SECRET_KEY en las variables de entorno."
            )

        self.feed = feed

        self.client = StockHistoricalDataClient(
            self.api_key,
            self.secret_key,
        )

    @staticmethod
    def _to_iso(value) -> str:
        if value is None:
            return ""

        if hasattr(value, "isoformat"):
            return value.isoformat()

        return str(value)

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def get_latest_bars(
        self,
        symbols: List[str],
    ) -> List[MarketBar]:
        """
        Obtiene la última barra de 1 minuto disponible para cada símbolo.
        """

        clean_symbols = sorted(
            {
                str(symbol).strip().upper()
                for symbol in symbols
                if str(symbol).strip()
            }
        )

        if not clean_symbols:
            raise MarketDataError(
                "La lista de símbolos está vacía."
            )

        request = StockLatestBarRequest(
            symbol_or_symbols=clean_symbols,
            feed=self.feed,
        )

        try:
            response = self.client.get_stock_latest_bar(request)
        except Exception as exc:
            raise MarketDataError(
                f"Error consultando latest bars de Alpaca: {exc}"
            ) from exc

        result: List[MarketBar] = []

        for symbol in clean_symbols:
            bar = response.get(symbol)

            if bar is None:
                continue

            result.append(
                MarketBar(
                    symbol=symbol,
                    timestamp=self._to_iso(bar.timestamp),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume),
                    trade_count=self._safe_int(
                        getattr(bar, "trade_count", None)
                    ),
                    vwap=self._safe_float(
                        getattr(bar, "vwap", None)
                    ),
                )
            )

        return result

    def get_recent_bars(
        self,
        symbol: str,
        minutes: int = 120,
    ) -> List[MarketBar]:
        """
        Obtiene barras históricas recientes de 1 minuto.

        Se utiliza para alimentar posteriormente FeatureEngine.
        """

        symbol = str(symbol).strip().upper()

        if not symbol:
            raise MarketDataError(
                "El símbolo no puede estar vacío."
            )

        if minutes < 1:
            raise MarketDataError(
                "minutes debe ser >= 1."
            )

        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=minutes)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=now,
            limit=min(minutes + 10, 10_000),
            feed=self.feed,
        )

        try:
            response = self.client.get_stock_bars(request)
        except Exception as exc:
            raise MarketDataError(
                f"Error consultando historical bars de Alpaca: {exc}"
            ) from exc

        bars = response.get(symbol, [])

        result: List[MarketBar] = []

        for bar in bars:
            result.append(
                MarketBar(
                    symbol=symbol,
                    timestamp=self._to_iso(bar.timestamp),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume),
                    trade_count=self._safe_int(
                        getattr(bar, "trade_count", None)
                    ),
                    vwap=self._safe_float(
                        getattr(bar, "vwap", None)
                    ),
                )
            )

        return result

    def get_snapshot(
        self,
        symbol: str,
    ) -> MarketSnapshotData:
        """
        Obtiene un snapshot completo del símbolo.

        Incluye:
        - latest trade
        - latest quote
        - latest minute bar
        - latest daily bar
        - previous daily bar
        """

        symbol = str(symbol).strip().upper()

        if not symbol:
            raise MarketDataError(
                "El símbolo no puede estar vacío."
            )

        request = StockSnapshotRequest(
            symbol_or_symbols=symbol,
            feed=self.feed,
        )

        try:
            response = self.client.get_stock_snapshot(request)
        except Exception as exc:
            raise MarketDataError(
                f"Error consultando snapshot de Alpaca: {exc}"
            ) from exc

        snapshot = response.get(symbol)

        if snapshot is None:
            raise MarketDataError(
                f"Alpaca no devolvió snapshot para {symbol}."
            )

        latest_trade = getattr(snapshot, "latest_trade", None)
        latest_quote = getattr(snapshot, "latest_quote", None)
        minute_bar = getattr(snapshot, "minute_bar", None)
        daily_bar = getattr(snapshot, "daily_bar", None)
        previous_daily_bar = getattr(
            snapshot,
            "previous_daily_bar",
            None,
        )

        if latest_trade is not None:
            price = float(latest_trade.price)
            timestamp = self._to_iso(latest_trade.timestamp)
        elif minute_bar is not None:
            price = float(minute_bar.close)
            timestamp = self._to_iso(minute_bar.timestamp)
        elif daily_bar is not None:
            price = float(daily_bar.close)
            timestamp = self._to_iso(daily_bar.timestamp)
        else:
            raise MarketDataError(
                f"Snapshot de {symbol} no contiene precio utilizable."
            )

        if minute_bar is not None:
            open_price = float(minute_bar.open)
            high_price = float(minute_bar.high)
            low_price = float(minute_bar.low)
            close_price = float(minute_bar.close)
            volume = float(minute_bar.volume)
            latest_bar_timestamp = self._to_iso(
                minute_bar.timestamp
            )
        elif daily_bar is not None:
            open_price = float(daily_bar.open)
            high_price = float(daily_bar.high)
            low_price = float(daily_bar.low)
            close_price = float(daily_bar.close)
            volume = float(daily_bar.volume)
            latest_bar_timestamp = self._to_iso(
                daily_bar.timestamp
            )
        else:
            open_price = price
            high_price = price
            low_price = price
            close_price = price
            volume = 0.0
            latest_bar_timestamp = None

        bid = None
        ask = None

        if latest_quote is not None:
            bid = self._safe_float(
                getattr(latest_quote, "bid_price", None)
            )
            ask = self._safe_float(
                getattr(latest_quote, "ask_price", None)
            )

        previous_close = None

        if previous_daily_bar is not None:
            previous_close = self._safe_float(
                getattr(previous_daily_bar, "close", None)
            )

        return MarketSnapshotData(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            bid=bid,
            ask=ask,
            latest_bar_timestamp=latest_bar_timestamp,
            previous_close=previous_close,
        )


class MarketDataLoop:
    """
    Loop de lectura de mercado.

    Importante:
    este componente solamente PRODUCE datos.

    No toma decisiones y no ejecuta operaciones.
    """

    def __init__(
        self,
        client: AlpacaMarketDataClient,
        symbols: List[str],
        interval_seconds: int = 60,
    ) -> None:
        if not symbols:
            raise MarketDataError(
                "MarketDataLoop requiere al menos un símbolo."
            )

        if interval_seconds < 1:
            raise MarketDataError(
                "interval_seconds debe ser >= 1."
            )

        self.client = client
        self.symbols = [
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        ]
        self.interval_seconds = interval_seconds

    def poll_once(self) -> Dict[str, object]:
        bars = self.client.get_latest_bars(self.symbols)

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "alpaca",
            "feed": "iex",
            "mode": "PAPER_MARKET_DATA",
            "orders_enabled": False,
            "symbols_requested": self.symbols,
            "bars_received": len(bars),
            "bars": [asdict(bar) for bar in bars],
        }

        return payload

    def run(
        self,
        iterations: Optional[int] = None,
    ) -> None:
        count = 0

        while True:
            payload = self.poll_once()

            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

            count += 1

            if iterations is not None and count >= iterations:
                break

            time.sleep(self.interval_seconds)


def build_client() -> AlpacaMarketDataClient:
    return AlpacaMarketDataClient(
        feed=DataFeed.IEX,
    )


def self_test() -> Dict[str, object]:
    client = build_client()

    symbols = ["SPY", "QQQ"]

    bars = client.get_latest_bars(symbols)

    assert isinstance(bars, list)

    for bar in bars:
        assert bar.symbol in symbols
        assert bar.open > 0
        assert bar.high > 0
        assert bar.low > 0
        assert bar.close > 0
        assert bar.volume >= 0
        assert bar.high >= bar.low

    recent = client.get_recent_bars(
        symbol="SPY",
        minutes=1200,
    )

    assert isinstance(recent, list)

    for bar in recent:
        assert bar.symbol == "SPY"
        assert bar.open > 0
        assert bar.high >= bar.low
        assert bar.close > 0

    snapshot = client.get_snapshot("SPY")

    assert snapshot.symbol == "SPY"
    assert snapshot.price > 0
    assert snapshot.high >= snapshot.low

    return {
        "ok": True,
        "module": "rocket_trader_market_data",
        "version": "0.2",
        "source": "Alpaca",
        "feed": "IEX",
        "mode": "PAPER_MARKET_DATA",
        "orders_enabled": False,
        "latest_bars_received": len(bars),
        "recent_spy_bars": len(recent),
        "snapshot": asdict(snapshot),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rocket Trader Market Data Layer"
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["SPY", "QQQ"],
        help="Símbolos a consultar.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta una sola lectura.",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Número de iteraciones del loop.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Segundos entre lecturas.",
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Ejecuta el self-test completo.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        if args.self_test:
            print("=" * 72)
            print("ROCKET TRADER — MARKET DATA v0.2")
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

            print("=" * 72)
            print("ROCKET TRADER MARKET DATA SELF-TEST: OK")
            print("=" * 72)
            return

        client = build_client()

        loop = MarketDataLoop(
            client=client,
            symbols=args.symbols,
            interval_seconds=args.interval,
        )

        if args.once:
            payload = loop.poll_once()

            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

            return

        loop.run(
            iterations=args.iterations,
        )

    except KeyboardInterrupt:
        print(
            "\nROCKET TRADER MARKET DATA: STOPPED"
        )
        return

    except Exception as exc:
        print(
            f"ROCKET TRADER MARKET DATA: FAIL: {exc}",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()