#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — Bridge v0.1

Conecta el motor estadístico/ML con el núcleo de riesgo/decisión sin acoplar
ninguna lógica de trading al broker.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict

from rocket_trader_core import (
    AccountState,
    BenchmarkRepository,
    Decision,
    InMemoryBenchmarkRepository,
    RocketTraderCore,
    Side,
    StrategySignal,
    TraderBenchmarkConfig,
    RiskConfig,
)
from rocket_trader_engine import SignalCandidate, SignalEngine


class EngineBridge:
    def __init__(
        self,
        signal_engine: SignalEngine,
        core: RocketTraderCore,
    ) -> None:
        self.signal_engine = signal_engine
        self.core = core

    @staticmethod
    def candidate_to_signal(candidate: SignalCandidate) -> StrategySignal:
        # LONG-ONLY: el engine actual solamente genera oportunidades alcistas.
        return StrategySignal(
            symbol=candidate.symbol,
            side=Side.BUY,
            score=candidate.score,
            expected_return=candidate.expected_return,
            confidence=candidate.confidence,
            rationale={
                "probability_up": candidate.probability_up,
                "evidence_novel": 1.0 if candidate.evidence_class == "NOVEL" else 0.0,
            },
            strategy_id="statistical_ensemble_v0_1",
            setup_signature=candidate.setup_signature,
        )

    def evaluate(
        self,
        market_data,
        symbol: str,
        account: AccountState,
        execute: bool = False,
    ) -> Dict[str, Any]:
        candidate = self.signal_engine.generate_signal(market_data, symbol)
        signal = self.candidate_to_signal(candidate)
        decision = self.core.evaluate_and_maybe_execute(
            account=account,
            snapshot=self._snapshot(candidate, market_data),
            signal=signal,
            execute=execute,
        )
        return {
            "candidate": dataclasses.asdict(candidate),
            "signal": dataclasses.asdict(signal),
            "decision": dataclasses.asdict(decision),
        }

    @staticmethod
    def _snapshot(candidate: SignalCandidate, market_data):
        from rocket_trader_core import MarketSnapshot
        latest = market_data.iloc[-1]
        return MarketSnapshot(
            symbol=candidate.symbol,
            timestamp=str(candidate.timestamp),
            price=float(latest["close"]),
            volume=float(latest["volume"]),
        )


def build_bridge(signal_engine: SignalEngine | None = None) -> EngineBridge:
    engine = signal_engine or SignalEngine()
    core = RocketTraderCore(
        risk_config=RiskConfig(
            initial_capital=1000.0,
            permanent_floor=0.0,
            allow_short=False,
            allow_margin=False,
        ),
        benchmark_config=TraderBenchmarkConfig(),
        benchmark_repository=InMemoryBenchmarkRepository(),
    )
    return EngineBridge(engine, core)


if __name__ == "__main__":
    print(json.dumps({
        "ok": True,
        "component": "rocket_trader_bridge",
        "mode": "BROKER_INDEPENDENT",
