#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Bridge v0.3

Conecta el motor estadístico/ML con RocketTraderCore.

Responsabilidades:
- Recibir un SignalCandidate del engine.
- Convertirlo a StrategySignal del core.
- Mantener LONG-ONLY.
- No ejecutar por defecto.
- Mantener PAPER como modo seguro.
- No conocer detalles internos del broker.
- Permitir que el Core siga siendo responsable de riesgo y ejecución.

IMPORTANTE:
- Este bridge NO decide cuánto capital arriesgar.
- Este bridge NO habilita LIVE.
- El Core sigue siendo la autoridad de riesgo.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from typing import Any, Dict, Optional

from rocket_trader_core import (
    AccountState,
    MarketSnapshot,
    RocketTraderCore,
    Side,
    StrategySignal,
    Decision,
    EvidenceClass,
    RiskConfig,
    TraderBenchmarkConfig,
    ProfitDistributionConfig,
    InMemoryBenchmarkRepository,
    PaperExecutionAdapter,
    utc_now,
)

from rocket_trader_engine import SignalCandidate


# ============================================================================
# UTILIDADES
# ============================================================================


def _enum_value(value: Any) -> Any:
    """Devuelve .value cuando el objeto es un Enum."""
    return getattr(value, "value", value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_field(candidate: Any, name: str, default: Any = None) -> Any:
    return getattr(candidate, name, default)


# ============================================================================
# CONVERSIÓN ENGINE -> CORE
# ============================================================================


def candidate_to_strategy_signal(candidate: SignalCandidate) -> StrategySignal:
    """
    Convierte SignalCandidate del engine a StrategySignal del Core.

    El engine es la fuente de:
    - probability_up
    - expected_return
    - confidence
    - score
    - setup_signature
    - evidence_class
    - features
    - model_votes

    El Core sigue siendo responsable de:
    - benchmark
    - sizing
    - riesgo
    - stops
    - kill switch
    - ejecución
    """

    symbol = str(_candidate_field(candidate, "symbol", "")).strip()

    if not symbol:
        raise ValueError("SignalCandidate no contiene symbol válido.")

    probability_up = _safe_float(
        _candidate_field(candidate, "probability_up", 0.0)
    )

    expected_return = _safe_float(
        _candidate_field(candidate, "expected_return", 0.0)
    )

    confidence = _safe_float(
        _candidate_field(candidate, "confidence", 0.0)
    )

    score = _safe_float(
        _candidate_field(candidate, "score", 0.0)
    )

    setup_signature = str(
        _candidate_field(candidate, "setup_signature", "")
    )

    evidence_raw = _candidate_field(
        candidate,
        "evidence_class",
        EvidenceClass.INSUFFICIENT,
    )

    if isinstance(evidence_raw, EvidenceClass):
        evidence_class = evidence_raw
    else:
        try:
            evidence_class = EvidenceClass(str(evidence_raw))
        except ValueError:
            evidence_class = EvidenceClass.INSUFFICIENT

    features = _candidate_field(candidate, "features", {}) or {}
    model_votes = _candidate_field(candidate, "model_votes", {}) or {}

    rationale: Dict[str, float] = {
        "probability_up": probability_up,
        "model_confidence": confidence,
    }

    if isinstance(features, dict):
        for key, value in features.items():
            try:
                rationale[f"feature_{key}"] = float(value)
            except (TypeError, ValueError):
                continue

    if isinstance(model_votes, dict):
        for key, value in model_votes.items():
            try:
                rationale[f"vote_{key}"] = float(value)
            except (TypeError, ValueError):
                continue

    # LONG-ONLY:
    # Una probabilidad > 50% puede producir BUY, pero el Core decide
    # finalmente si el score/riesgo permite operar.
    side = Side.BUY if probability_up >= 0.50 else Side.HOLD

    return StrategySignal(
        symbol=symbol,
        side=side,
        score=max(0.0, min(1.0, score)),
        expected_return=expected_return,
        confidence=max(0.0, min(1.0, confidence)),
        rationale=rationale,
        strategy_id="statistical_ml_ensemble",
        setup_signature=setup_signature,
    )


# ============================================================================
# BRIDGE
# ============================================================================


class RocketTraderBridge:
    """
    Orquestador entre Engine y Core.

    Por defecto execute=False.
    """

    def __init__(
        self,
        core: RocketTraderCore,
    ) -> None:
        self.core = core

    def evaluate_candidate(
        self,
        candidate: SignalCandidate,
        account: AccountState,
        price: float,
        volume: float = 0.0,
        timestamp: Optional[str] = None,
        execute: bool = False,
    ) -> Decision:

        strategy_signal = candidate_to_strategy_signal(candidate)

        snapshot = MarketSnapshot(
            symbol=str(candidate.symbol),
            timestamp=timestamp or _candidate_field(
                candidate,
                "timestamp",
                utc_now(),
            ),
            price=float(price),
            volume=float(volume),
        )

        return self.core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=strategy_signal,
            execute=execute,
        )


# ============================================================================
# DEMO CORE
# ============================================================================


def build_bridge_demo_core() -> RocketTraderCore:
    """
    Construye un Core exclusivamente para el self-test.

    No conecta con Alpaca.
    No envía órdenes reales.
    """

    risk_config = RiskConfig(
        initial_capital=1000.0,
        permanent_floor=0.0,
        allow_short=False,
        allow_margin=False,
        max_position_pct=0.25,
        max_total_exposure_pct=0.80,
        max_loss_per_trade_pct=0.02,
        daily_loss_limit_pct=0.05,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        trailing_stop_pct=0.015,
        max_trades_per_day=10,
        max_consecutive_losses=3,
        min_signal_score=0.60,
        min_benchmark_confidence=0.55,
        novel_risk_budget_pct=0.01,
    )

    benchmark_config = TraderBenchmarkConfig(
        min_comparable_traders=3,
        min_comparable_events=20,
        min_confidence=0.55,
        novelty_penalty=0.15,
        benchmark_weight=0.25,
    )

    # Mantiene la configuración actualmente compatible con el Core.
    distribution_config = ProfitDistributionConfig(
        reserve_pct=0.10,
        reinvestment_pct=0.70,
        personal_pct=0.20,
        frequency="MONTHLY",
    )

    return RocketTraderCore(
        risk_config=risk_config,
        benchmark_config=benchmark_config,
        distribution_config=distribution_config,
        benchmark_repository=InMemoryBenchmarkRepository(),
        execution_adapter=PaperExecutionAdapter(),
        audit_path="data/rocket_trader_bridge_test.jsonl",
    )


# ============================================================================
# SELF-TEST
# ============================================================================


def _build_test_candidate() -> SignalCandidate:
    """
    Construye un SignalCandidate compatible con la versión instalada
    del engine.

    Se utiliza introspección únicamente para que el bridge no vuelva
    a romperse si se agregan campos obligatorios al dataclass del engine.
    """

    signature = inspect.signature(SignalCandidate)

    available_values: Dict[str, Any] = {
        "symbol": "DEMO",
        "timestamp": utc_now(),
        "probability_up": 0.72,
        "expected_return": 0.03,
        "confidence": 0.80,
        "score": 0.80,
        "setup_signature": "BRIDGE_TEST_SETUP",
        "evidence_class": EvidenceClass.NOVEL,
        "features": {
            "demo_feature": 1.0,
        },
        "model_votes": {
            "logistic": 0.70,
            "xgb": 0.74,
            "lightgbm": 0.72,
        },
    }

    kwargs: Dict[str, Any] = {}

    for name, parameter in signature.parameters.items():

        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue

        if name in available_values:
            kwargs[name] = available_values[name]
            continue

        if parameter.default is not inspect.Parameter.empty:
            continue

        # Fallbacks para cualquier campo obligatorio adicional.
        annotation = parameter.annotation

        if annotation is bool:
            kwargs[name] = False
        elif annotation is int:
            kwargs[name] = 0
        elif annotation is float:
            kwargs[name] = 0.0
        elif annotation is str:
            kwargs[name] = ""
        elif annotation in (dict, Dict):
            kwargs[name] = {}
        elif annotation in (list,):
            kwargs[name] = []
        else:
            # Último recurso para campos obligatorios desconocidos.
            kwargs[name] = None

    return SignalCandidate(**kwargs)


def self_test() -> Dict[str, Any]:
    candidate = _build_test_candidate()

    strategy_signal = candidate_to_strategy_signal(candidate)

    assert strategy_signal.symbol == "DEMO"
    assert strategy_signal.side == Side.BUY
    assert 0.0 <= strategy_signal.score <= 1.0
    assert 0.0 <= strategy_signal.confidence <= 1.0
    assert strategy_signal.strategy_id == "statistical_ml_ensemble"

    core = build_bridge_demo_core()
    bridge = RocketTraderBridge(core)

    account = AccountState(
        equity=1000.0,
        cash=1000.0,
        protected_floor=0.0,
    )

    decision = bridge.evaluate_candidate(
        candidate=candidate,
        account=account,
        price=100.0,
        volume=1000.0,
        execute=False,
    )

    # El candidato es NOVEL, por lo que el Core debe aplicar
    # su presupuesto de riesgo para novedad.
    assert decision.evidence_class == EvidenceClass.NOVEL
    assert decision.quantity >= 0.0
    assert decision.stop_price in (None, 98.0)
    assert decision.take_profit_price in (None, 104.0)

    return {
        "ok": True,
        "bridge_version": "0.3",
        "candidate": {
            "symbol": strategy_signal.symbol,
            "side": strategy_signal.side.value,
            "score": strategy_signal.score,
            "confidence": strategy_signal.confidence,
            "expected_return": strategy_signal.expected_return,
            "strategy_id": strategy_signal.strategy_id,
            "setup_signature": strategy_signal.setup_signature,
        },
        "decision": {
            "status": decision.status.value,
            "evidence_class": decision.evidence_class.value,
            "quantity": decision.quantity,
            "entry_price": decision.entry_price,
            "stop_price": decision.stop_price,
            "take_profit_price": decision.take_profit_price,
        },
        "execution_requested": False,
        "live_orders": False,
    }


def main() -> None:
    result = self_test()
    print("=" * 72)
    print("ROCKET TRADER — BRIDGE SELF-TEST v0.3")
    print("=" * 72)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 72)
    print("BRIDGE SELF-TEST: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()