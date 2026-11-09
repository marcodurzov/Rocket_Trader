#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — independent crypto research engine and cost model.

Research only: this module does not import TradingClient and cannot place orders.
It owns separate SignalEngine instances for crypto symbols and keeps crypto costs
(explicit fees, spread and slippage) separate from equity assumptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from alpaca.data.timeframe import TimeFrame

from rocket_trader_crypto_market_data import (
    AlpacaCryptoMarketDataClient,
    CryptoBar,
    CryptoMarketDataError,
)
from rocket_trader_engine import EngineConfig, SignalEngine


@dataclass(frozen=True)
class CryptoCostEstimate:
    notional_quote: float
    maker_or_taker: str
    fee_bps_per_side: float
    spread_pct: float
    slippage_bps_per_side: float
    entry_fee: float
    exit_fee: float
    spread_cost: float
    slippage_cost: float
    total_round_trip_cost: float
    total_round_trip_cost_pct: float


@dataclass(frozen=True)
class CryptoFeeSchedule:
    """Initial Alpaca lowest-volume-tier fee assumptions; update from account tier."""
    maker_bps: float = 15.0
    taker_bps: float = 25.0

    def validate(self) -> None:
        if self.maker_bps < 0 or self.taker_bps < 0:
            raise ValueError("Las comisiones no pueden ser negativas.")


class CryptoExecutionCostModel:
    """Conservative round-trip cost estimate; never treats paper fills as free."""

    def __init__(
        self,
        fee_schedule: Optional[CryptoFeeSchedule] = None,
        slippage_bps_per_side: float = 5.0,
    ) -> None:
        self.fee_schedule = fee_schedule or CryptoFeeSchedule()
        self.fee_schedule.validate()
        if slippage_bps_per_side < 0:
            raise ValueError("slippage_bps_per_side no puede ser negativo.")
        self.slippage_bps_per_side = float(slippage_bps_per_side)

    def estimate_round_trip(
        self,
        notional_quote: float,
        bid: float,
        ask: float,
        maker: bool = False,
    ) -> CryptoCostEstimate:
        if notional_quote <= 0 or bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError("Notional o quote inválido para estimar costos.")
        fee_bps = (
            self.fee_schedule.maker_bps
            if maker
            else self.fee_schedule.taker_bps
        )
        midpoint = (bid + ask) / 2.0
        spread_pct = (ask - bid) / midpoint
        entry_fee = notional_quote * fee_bps / 10_000.0
        exit_fee = notional_quote * fee_bps / 10_000.0
        spread_cost = notional_quote * spread_pct
        slippage_cost = (
            notional_quote
            * 2.0
            * self.slippage_bps_per_side
            / 10_000.0
        )
        total = entry_fee + exit_fee + spread_cost + slippage_cost
        return CryptoCostEstimate(
            notional_quote=float(notional_quote),
            maker_or_taker="MAKER" if maker else "TAKER",
            fee_bps_per_side=float(fee_bps),
            spread_pct=float(spread_pct),
            slippage_bps_per_side=self.slippage_bps_per_side,
            entry_fee=round(entry_fee, 8),
            exit_fee=round(exit_fee, 8),
            spread_cost=round(spread_cost, 8),
            slippage_cost=round(slippage_cost, 8),
            total_round_trip_cost=round(total, 8),
            total_round_trip_cost_pct=float(total / notional_quote),
        )


class CryptoSignalResearchEngine:
    """Independent crypto signal research wrapper around a dedicated SignalEngine."""

    def __init__(
        self,
        engine_config: EngineConfig,
        market_data_client: Optional[AlpacaCryptoMarketDataClient] = None,
        lookback_minutes: int = 43_200,
        timeframe: TimeFrame = TimeFrame.Minute,
        min_bars: int = 400,
    ) -> None:
        if lookback_minutes < 1:
            raise ValueError("lookback_minutes debe ser >= 1")
        if min_bars < engine_config.min_history_bars:
            raise ValueError("min_bars no puede ser menor que min_history_bars")
        self.engine_config = engine_config
        self.market_data = market_data_client or AlpacaCryptoMarketDataClient()
        self.lookback_minutes = int(lookback_minutes)
        self.timeframe = timeframe
        self.min_bars = int(min_bars)
        self.engines: Dict[str, SignalEngine] = {}

    @staticmethod
    def bars_to_dataframe(bars: Sequence[CryptoBar]) -> pd.DataFrame:
        if not bars:
            raise CryptoMarketDataError("No hay barras cripto para construir OHLCV.")
        frame = pd.DataFrame(
            [
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ]
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = (
            frame.dropna()
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .reset_index(drop=True)
        )
        if frame.empty:
            raise CryptoMarketDataError("OHLCV cripto inválido después de normalizar.")
        return frame

    def process_symbol(self, symbol: str) -> Dict[str, Any]:
        bars = self.market_data.get_recent_bars(
            symbol=symbol,
            minutes=self.lookback_minutes,
            timeframe=self.timeframe,
        )
        if len(bars) < self.min_bars:
            raise CryptoMarketDataError(
                f"{symbol}: {len(bars)} barras; mínimo requerido {self.min_bars}."
            )
        frame = self.bars_to_dataframe(bars)
        engine = SignalEngine(self.engine_config)
        training = engine.train(frame)
        signal = engine.generate_signal(frame, symbol)
        self.engines[symbol] = engine
        return {
            "symbol": symbol,
            "rows": len(frame),
            "first_timestamp": frame.iloc[0]["timestamp"].isoformat(),
            "last_timestamp": frame.iloc[-1]["timestamp"].isoformat(),
            "training": training,
            "signal": asdict(signal),
            "research_status": "RESEARCH_ONLY",
            "orders_enabled": False,
            "orders_submitted": 0,
        }

    def run(self, symbols: Sequence[str]) -> Dict[str, Any]:
        clean = sorted(
            {
                AlpacaCryptoMarketDataClient.normalize_symbol(symbol)
                for symbol in symbols
            }
        )
        if not clean:
            raise ValueError("Se requiere al menos un par cripto.")
        results: List[Dict[str, Any]] = []
        failures: List[Dict[str, str]] = []
        for symbol in clean:
            try:
                results.append(self.process_symbol(symbol))
            except Exception as exc:
                failures.append(
                    {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
                )
        return {
            "ok": bool(results) and not failures,
            "version": "0.1",
            "pipeline": "rocket_trader_crypto_signal_research",
            "mode": "RESEARCH_ONLY",
            "symbols_processed": [item["symbol"] for item in results],
            "results": results,
            "failures": failures,
            "orders_enabled": False,
            "orders_submitted": 0,
        }


def self_test() -> Dict[str, Any]:
    from rocket_trader_crypto_market_data import CryptoBar

    bars = [
        CryptoBar(
            symbol="BTC/USD",
            timestamp=f"2026-01-01T00:0{i}:00+00:00",
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=float(i),
        )
        for i in range(4)
    ]
    frame = CryptoSignalResearchEngine.bars_to_dataframe(bars)
    assert len(frame) == 4
    assert frame["timestamp"].is_monotonic_increasing

    model = CryptoExecutionCostModel(
        fee_schedule=CryptoFeeSchedule(maker_bps=15, taker_bps=25),
        slippage_bps_per_side=5,
    )
    estimate = model.estimate_round_trip(
        notional_quote=1000.0,
        bid=99.0,
        ask=101.0,
        maker=False,
    )
    assert estimate.entry_fee == 2.5
    assert estimate.exit_fee == 2.5
    assert estimate.spread_cost == 20.0
    assert estimate.slippage_cost == 1.0
    assert estimate.total_round_trip_cost == 26.0
    assert estimate.total_round_trip_cost_pct == 0.026

    return {
        "ok": True,
        "version": "0.1",
        "pipeline": "rocket_trader_crypto_signal_research",
        "mode": "RESEARCH_ONLY",
        "crypto_bars_normalized": len(frame),
        "sample_taker_round_trip_cost_usd": asdict(estimate),
        "orders_enabled": False,
        "orders_submitted": 0,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(self_test(), ensure_ascii=False, indent=2, default=str))
