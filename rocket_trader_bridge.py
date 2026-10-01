#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER — BRIDGE v0.4

Conecta:

    rocket_trader_engine.py
              ↓
       SignalCandidate
              ↓
    rocket_trader_core.py
              ↓
       Risk / Decision
              ↓
        PAPER execution

SEGURIDAD
---------
- PAPER ONLY.
- LIVE no se habilita desde este archivo.
- No contiene API keys.
- No contiene configuración de distribución de utilidades.
- La política de capital pertenece exclusivamente al Core.
- El Bridge nunca puede saltarse RiskEngine.
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
    build_demo_core,
)

from rocket_trader_engine import SignalCandidate


# ============================================================================
# UTILIDADES
# ============================================================================


def _enum_value(value: Any) -> Any:
    """Devuelve .value si el objeto es un Enum."""
    return getattr(value, "value", value)


def _get_field(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    """Lee un campo de un objeto o diccionario."""
    if hasattr(obj, name):
        return getattr(obj, name)

    if isinstance(obj, dict):
        return obj.get(name, default)

    return default


def _as_dict(obj: Any) -> Dict[str, Any]:
    """Convierte un objeto a diccionario para auditoría/test."""
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)

    if isinstance(obj, dict):
        return dict(obj)

    if hasattr(obj, "__dict__"):
        return dict(vars(obj))

    return {}


# ============================================================================
# ENGINE -> CORE
# ============================================================================


def candidate_to_strategy_signal(
    candidate: SignalCandidate,
) -> StrategySignal:
    """
    Convierte SignalCandidate del Engine al formato StrategySignal del Core.

    El Engine genera la señal.
    El Core decide si esa señal puede operar.
    """

    symbol = str(
        _get_field(candidate, "symbol", "DEMO")
    )

    probability_up = float(
        _get_field(candidate, "probability_up", 0.50)
    )

    expected_return = float(
        _get_field(candidate, "expected_return", 0.0)
    )

    confidence = float(
        _get_field(candidate, "confidence", 0.0)
    )

    score = float(
        _get_field(candidate, "score", 0.0)
    )

    setup_signature = str(
        _get_field(
            candidate,
            "setup_signature",
            "UNKNOWN_SETUP",
        )
    )

    features = _get_field(
        candidate,
        "features",
        {},
    )

    model_votes = _get_field(
        candidate,
        "model_votes",
        {},
    )

    rationale = {
        "source": "rocket_trader_engine",
        "probability_up": probability_up,
        "expected_return": expected_return,
        "confidence": confidence,
        "model_votes": model_votes,
        "features": features,
    }

    return StrategySignal(
        symbol=symbol,
        side=Side.BUY,
        score=score,
        expected_return=expected_return,
        confidence=confidence,
        rationale=rationale,
        strategy_id="rocket_trader_engine",
        setup_signature=setup_signature,
    )


# ============================================================================
# BRIDGE
# ============================================================================


class RocketTraderBridge:
    """
    Adaptador entre el motor estadístico y RocketTraderCore.
    """

    def __init__(
        self,
        core: Optional[RocketTraderCore] = None,
    ) -> None:

        self.core = core or build_demo_core()

    def evaluate_candidate(
        self,
        candidate: SignalCandidate,
        price: float,
        volume: float = 0.0,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        account: Optional[AccountState] = None,
        execute: bool = False,
    ):
        """
        Envía una señal del Engine al Core.

        execute=False es el default.

        Si execute=True, el Core continúa forzando PAPER.
        """

        timestamp = _get_field(
            candidate,
            "timestamp",
            None,
        )

        if timestamp is None:
            timestamp = "1970-01-01T00:00:00+00:00"

        symbol = str(
            _get_field(
                candidate,
                "symbol",
                "DEMO",
            )
        )

        snapshot = MarketSnapshot(
            symbol=symbol,
            timestamp=str(timestamp),
            price=float(price),
            volume=float(volume),
            bid=bid,
            ask=ask,
        )

        signal = candidate_to_strategy_signal(
            candidate
        )

        if account is None:
            account = AccountState(
                equity=1000.0,
                cash=1000.0,
                protected_floor=0.0,
            )

        return self.core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=execute,
        )


# ============================================================================
# DEMO CORE
# ============================================================================


def build_bridge_demo_core() -> RocketTraderCore:
    """
    Construye el Core oficial.

    IMPORTANTE:
    No construimos ProfitDistributionConfig aquí.

    La política de capital está centralizada en Core.
    """

    return build_demo_core()


# ============================================================================
# TEST SIGNAL
# ============================================================================


def _build_test_candidate() -> SignalCandidate:
    """
    Construye un SignalCandidate compatible con la versión instalada
    del Engine.

    Se utiliza introspección para evitar asumir una firma exacta.
    """

    signature = inspect.signature(
        SignalCandidate
    )

    values: Dict[str, Any] = {}

    known_values: Dict[str, Any] = {
        "symbol": "DEMO",

        "timestamp":
            "2026-09-30T20:00:00+00:00",

        "probability_up": 0.72,

        "expected_return": 0.03,

        "confidence": 0.80,

        "score": 0.80,

        "setup_signature":
            "BRIDGE_TEST_SETUP",

        "evidence_class":
            "NOVEL",

        "features": {
            "trend_strength": 0.80,
            "rsi_14": 0.55,
            "volume_ratio_20": 1.20,
        },

        "model_votes": {
            "logistic": 0.70,
            "xgb": 0.74,
            "lightgbm": 0.72,
        },
    }

    for name, parameter in signature.parameters.items():

        if name == "self":
            continue

        if name in known_values:
            values[name] = known_values[name]
            continue

        if parameter.default is not inspect.Parameter.empty:
            continue

        annotation = parameter.annotation

        if annotation is str:
            values[name] = ""

        elif annotation is float:
            values[name] = 0.0

        elif annotation is int:
            values[name] = 0

        elif annotation is bool:
            values[name] = False

        elif annotation is dict:
            values[name] = {}

        else:
            if name == "evidence_class":
                values[name] = "NOVEL"
            else:
                values[name] = None

    return SignalCandidate(
        **values
    )


# ============================================================================
# SELF TEST
# ============================================================================


def self_test() -> Dict[str, Any]:
    """
    Self-test del Bridge.

    NO envía órdenes reales.
    """

    core = build_bridge_demo_core()

    bridge = RocketTraderBridge(
        core=core
    )

    candidate = _build_test_candidate()

    account = AccountState(
        equity=1000.0,
        cash=1000.0,
        protected_floor=0.0,
    )

    decision = bridge.evaluate_candidate(
        candidate=candidate,
        price=100.0,
        volume=1000.0,
        account=account,
        execute=False,
    )

    # ------------------------------------------------------------------------
    # Validaciones básicas
    # ------------------------------------------------------------------------

    assert decision is not None

    assert hasattr(
        decision,
        "status",
    )

    assert hasattr(
        decision,
        "quantity",
    )

    assert hasattr(
        decision,
        "symbol",
    )

    assert decision.symbol == "DEMO"

    # ------------------------------------------------------------------------
    # SEGURIDAD
    # ------------------------------------------------------------------------

    # Signal de prueba = NOVEL.
    #
    # El Core debe limitarla al presupuesto de riesgo de novedad.
    #
    # Cuenta = $1,000
    # Riesgo máximo de novedad = 1%
    # Notional máximo = $10
    # Precio = $100
    # Quantity máxima = 0.10

    assert decision.quantity <= 0.10

    # ------------------------------------------------------------------------
    # FLOOR KILL SWITCH
    # ------------------------------------------------------------------------

    floor_account = AccountState(
        equity=500.0,
        cash=500.0,
        protected_floor=500.0,
    )

    floor_decision = bridge.evaluate_candidate(
        candidate=candidate,
        price=100.0,
        volume=1000.0,
        account=floor_account,
        execute=False,
    )

    assert (
        _enum_value(
            floor_decision.status
        )
        == "KILL_SWITCH"
    )

    # ------------------------------------------------------------------------
    # RESULTADO
    # ------------------------------------------------------------------------

    return {
        "ok": True,

        "bridge_version": "0.4",

        "execution": "PAPER_ONLY",

        "live_orders": False,

        "candidate": _as_dict(
            candidate
        ),

        "decision": {
            "status":
                _enum_value(
                    decision.status
                ),

            "evidence_class":
                _enum_value(
                    decision.evidence_class
                ),

            "symbol":
                decision.symbol,

            "quantity":
                decision.quantity,

            "stop_price":
                decision.stop_price,

            "take_profit_price":
                decision.take_profit_price,
        },

        "floor_kill_switch":
            _enum_value(
                floor_decision.status
            ),
    }


# ============================================================================
# MAIN
# ============================================================================


def main() -> None:

    print("=" * 72)

    print(
        "ROCKET TRADER — BRIDGE v0.4"
    )

    print("=" * 72)

    print(
        "MODE: PAPER ONLY"
    )

    print(
        "LIVE ORDERS: DISABLED"
    )

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

    print(
        "ROCKET TRADER BRIDGE SELF-TEST: OK"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
