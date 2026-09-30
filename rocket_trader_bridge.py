#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Bridge v0.2

Conecta:

    rocket_trader_engine
            ↓
    StrategySignal
            ↓
    rocket_trader_core
            ↓
    Decision

IMPORTANTE:
- Este módulo NO decide cuánto arriesgar.
- El RiskEngine del Core mantiene el control.
- LONG-ONLY.
- PAPER por defecto.
- execute=False por defecto.
- No utiliza margen.
- No utiliza leverage.
- No utiliza short.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from rocket_trader_core import (
    AccountState,
    MarketSnapshot,
    RocketTraderCore,
    Side,
    StrategySignal,
    Decision,
)

from rocket_trader_engine import (
    SignalCandidate,
)


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass(frozen=True)
class BridgeConfig:
    execute_by_default: bool = False


# ============================================================================
# BRIDGE
# ============================================================================


class RocketTraderBridge:
    """
    Adaptador entre el motor estadístico y RocketTraderCore.
    """

    def __init__(
        self,
        core: RocketTraderCore,
        config: Optional[BridgeConfig] = None,
    ) -> None:

        self.core = core
        self.config = config or BridgeConfig()

    # ------------------------------------------------------------------------
    # SIGNAL CONVERSION
    # ------------------------------------------------------------------------

    @staticmethod
    def candidate_to_strategy_signal(
        candidate: SignalCandidate,
    ) -> StrategySignal:

        symbol = str(
            getattr(candidate, "symbol", "")
        )

        score = float(
            getattr(candidate, "score", 0.0)
        )

        expected_return = float(
            getattr(candidate, "expected_return", 0.0)
        )

        confidence = float(
            getattr(candidate, "confidence", 0.0)
        )

        strategy_id = str(
            getattr(
                candidate,
                "strategy_id",
                "rocket_trader_engine",
            )
        )

        setup_signature = str(
            getattr(
                candidate,
                "setup_signature",
                "",
            )
        )

        rationale = getattr(
            candidate,
            "rationale",
            {},
        )

        if not isinstance(rationale, dict):
            rationale = {
                "engine_score": score,
            }

        side_value = getattr(
            candidate,
            "side",
            "BUY",
        )

        if isinstance(side_value, Side):
            side = side_value

        else:
            side_text = str(
                side_value
            ).upper()

            if side_text in {
                "BUY",
                "LONG",
            }:
                side = Side.BUY

            elif side_text in {
                "SELL",
                "SHORT",
            }:
                side = Side.SELL

            else:
                side = Side.HOLD

        return StrategySignal(
            symbol=symbol,
            side=side,
            score=score,
            expected_return=expected_return,
            confidence=confidence,
            rationale=rationale,
            strategy_id=strategy_id,
            setup_signature=setup_signature,
        )

    # ------------------------------------------------------------------------
    # EVALUATION
    # ------------------------------------------------------------------------

    def evaluate_candidate(
        self,
        *,
        account: AccountState,
        snapshot: MarketSnapshot,
        candidate: SignalCandidate,
    ) -> Decision:

        signal = self.candidate_to_strategy_signal(
            candidate
        )

        return self.core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=False,
        )

    # ------------------------------------------------------------------------
    # EXECUTION
    # ------------------------------------------------------------------------

    def execute_candidate(
        self,
        *,
        account: AccountState,
        snapshot: MarketSnapshot,
        candidate: SignalCandidate,
        execute: Optional[bool] = None,
    ) -> Decision:

        signal = self.candidate_to_strategy_signal(
            candidate
        )

        should_execute = (
            self.config.execute_by_default
            if execute is None
            else execute
        )

        return self.core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=should_execute,
        )

    # ------------------------------------------------------------------------
    # DICTIONARY HELPER
    # ------------------------------------------------------------------------

    @staticmethod
    def candidate_to_dict(
        candidate: SignalCandidate,
    ) -> Dict[str, Any]:

        if hasattr(candidate, "__dict__"):
            return dict(candidate.__dict__)

        return {
            "symbol": getattr(
                candidate,
                "symbol",
                None,
            ),
            "score": getattr(
                candidate,
                "score",
                None,
            ),
            "expected_return": getattr(
                candidate,
                "expected_return",
                None,
            ),
            "confidence": getattr(
                candidate,
                "confidence",
                None,
            ),
            "strategy_id": getattr(
                candidate,
                "strategy_id",
                None,
            ),
            "setup_signature": getattr(
                candidate,
                "setup_signature",
                None,
            ),
        }


# ============================================================================
# FACTORY
# ============================================================================


def build_bridge(
    core: RocketTraderCore,
    *,
    execute_by_default: bool = False,
) -> RocketTraderBridge:

    return RocketTraderBridge(
        core=core,
        config=BridgeConfig(
            execute_by_default=execute_by_default
        ),
    )


# ============================================================================
# SELF TEST
# ============================================================================


def self_test() -> Dict[str, Any]:

    from rocket_trader_core import (
        RiskConfig,
        TraderBenchmarkConfig,
        InMemoryBenchmarkRepository,
        PaperExecutionAdapter,
        utc_now,
    )

    core = RocketTraderCore(
        risk_config=RiskConfig(
            initial_capital=1000.0,
            permanent_floor=0.0,
            allow_short=False,
            allow_margin=False,
        ),
        benchmark_config=TraderBenchmarkConfig(),
        benchmark_repository=InMemoryBenchmarkRepository(),
        execution_adapter=PaperExecutionAdapter(),
        audit_path="data/rocket_trader_bridge_test.jsonl",
    )

    bridge = RocketTraderBridge(
        core=core,
        config=BridgeConfig(
            execute_by_default=False
        ),
    )

    # Construimos un candidate dinámicamente para mantener
    # compatibilidad con la versión actual del engine.
    try:

        candidate = SignalCandidate(
            symbol="DEMO",
            score=0.85,
            expected_return=0.03,
            confidence=0.85,
            strategy_id="bridge_test",
            setup_signature="BRIDGE_TEST_SETUP",
        )

    except TypeError:

        # Algunas versiones del engine pueden tener
        # argumentos adicionales. Intentamos construirlo
        # mediante introspección de campos disponibles.

        import inspect

        fields = inspect.signature(
            SignalCandidate
        ).parameters

        kwargs = {}

        if "symbol" in fields:
            kwargs["symbol"] = "DEMO"

        if "score" in fields:
            kwargs["score"] = 0.85

        if "expected_return" in fields:
            kwargs["expected_return"] = 0.03

        if "confidence" in fields:
            kwargs["confidence"] = 0.85

        if "strategy_id" in fields:
            kwargs["strategy_id"] = "bridge_test"

        if "setup_signature" in fields:
            kwargs["setup_signature"] = (
                "BRIDGE_TEST_SETUP"
            )

        if "side" in fields:
            kwargs["side"] = "BUY"

        if "rationale" in fields:
            kwargs["rationale"] = {
                "bridge_test": 1.0
            }

        candidate = SignalCandidate(
            **kwargs
        )

    snapshot = MarketSnapshot(
        symbol="DEMO",
        timestamp=utc_now(),
        price=100.0,
        volume=1000.0,
    )

    account = AccountState(
        equity=1000.0,
        cash=1000.0,
        protected_floor=0.0,
    )

    signal = bridge.candidate_to_strategy_signal(
        candidate
    )

    assert signal.symbol == "DEMO"
    assert signal.side in {
        Side.BUY,
        Side.HOLD,
        Side.SELL,
    }

    decision = bridge.evaluate_candidate(
        account=account,
        snapshot=snapshot,
        candidate=candidate,
    )

    assert decision is not None

    # El método evaluate_candidate jamás debe ejecutar
    # una orden por sí mismo.
    assert bridge.config.execute_by_default is False

    return {
        "ok": True,
        "module": "rocket_trader_bridge",
        "execution_default": False,
        "live_enabled": False,
    }


if __name__ == "__main__":

    result = self_test()

    print(
        "ROCKET TRADER BRIDGE SELF-TEST: PASS"
    )

    print(result)