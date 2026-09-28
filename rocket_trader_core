#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rocket Trader — Core v0.1

Primer núcleo ejecutable del sistema.

Objetivos de esta versión:
- Separar DECISIÓN, RIESGO y EJECUCIÓN.
- Implementar el concepto de capital operativo vs. piso protegido.
- Mantener un registro auditable de decisiones y órdenes.
- Incorporar comparación contra precedentes/benchmarks de traders exitosos
  sin convertirlos en una copia ciega.
- Distinguir entre PRECEDENTED y NOVEL cuando la evidencia disponible no
  permite una comparación fiable.
- Tener PAPER execution como único modo de ejecución por defecto.
- No contener todavía una estrategia específica de acciones/cripto: esa capa
  requiere definir primero el mercado y la fuente de datos.

Este archivo es autocontenido y usa únicamente Python estándar.
No envía órdenes reales.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple


# ============================================================================
# UTILIDADES
# ============================================================================


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{prefix}_{digest}"


# ============================================================================
# ENUMS
# ============================================================================


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class DecisionStatus(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOVEL_RISK = "NOVEL_RISK"
    KILL_SWITCH = "KILL_SWITCH"


class EvidenceClass(str, enum.Enum):
    PRECEDENTED = "PRECEDENTED"
    NOVEL = "NOVEL"
    INSUFFICIENT = "INSUFFICIENT"


class ExecutionMode(str, enum.Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


# ============================================================================
# CONFIGURACIÓN
# ============================================================================


@dataclass(frozen=True)
class RiskConfig:
    """Reglas duras de protección del capital operativo."""

    initial_capital: float = 1000.0
    permanent_floor: float = 0.0
    reserve_cash: float = 0.0

    max_position_pct: float = 0.25
    max_total_exposure_pct: float = 0.80
    max_loss_per_trade_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05

    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    trailing_stop_pct: float = 0.015

    max_trades_per_day: int = 10
    max_consecutive_losses: int = 3

    min_signal_score: float = 0.60
    min_benchmark_confidence: float = 0.55
    novel_risk_budget_pct: float = 0.01

    def validate(self) -> None:
        numeric_pct = {
            "max_position_pct": self.max_position_pct,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "max_loss_per_trade_pct": self.max_loss_per_trade_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "min_signal_score": self.min_signal_score,
            "min_benchmark_confidence": self.min_benchmark_confidence,
            "novel_risk_budget_pct": self.novel_risk_budget_pct,
        }
        for name, value in numeric_pct.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} debe estar entre 0 y 1")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital debe ser > 0")
        if self.permanent_floor < 0:
            raise ValueError("permanent_floor no puede ser negativo")
        if self.reserve_cash < 0:
            raise ValueError("reserve_cash no puede ser negativo")
        if self.max_position_pct > self.max_total_exposure_pct:
            raise ValueError("max_position_pct no puede superar max_total_exposure_pct")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day debe ser >= 1")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses debe ser >= 1")


@dataclass(frozen=True)
class TraderBenchmarkConfig:
    """Configuración del uso de precedentes externos."""

    min_comparable_traders: int = 3
    min_comparable_events: int = 20
    min_confidence: float = 0.55
    novelty_penalty: float = 0.15
    benchmark_weight: float = 0.25

    def validate(self) -> None:
        if self.min_comparable_traders < 1:
            raise ValueError("min_comparable_traders debe ser >= 1")
        if self.min_comparable_events < 1:
            raise ValueError("min_comparable_events debe ser >= 1")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence debe estar entre 0 y 1")
        if not 0 <= self.novelty_penalty <= 1:
            raise ValueError("novelty_penalty debe estar entre 0 y 1")
        if not 0 <= self.benchmark_weight <= 1:
            raise ValueError("benchmark_weight debe estar entre 0 y 1")


# ============================================================================
# DATOS DE MERCADO
# ============================================================================


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timestamp: str
    price: float
    volume: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    features: Dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("symbol vacío")
        if self.price <= 0:
            raise ValueError("price debe ser > 0")
        if self.volume < 0:
            raise ValueError("volume no puede ser negativo")
        if self.bid is not None and self.bid <= 0:
            raise ValueError("bid debe ser > 0")
        if self.ask is not None and self.ask <= 0:
            raise ValueError("ask debe ser > 0")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid no puede ser mayor que ask")


# ============================================================================
# ESTADO DE CUENTA / POSICIONES
# ============================================================================


@dataclass
class Position:
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None

    @property
    def notional(self) -> float:
        return abs(self.quantity * self.entry_price)


@dataclass
class AccountState:
    equity: float
    cash: float
    protected_floor: float
    reserve_cash: float = 0.0
    daily_start_equity: float = 0.0
    realized_pnl_today: float = 0.0
    unrealized_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    positions: Dict[str, Position] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""

    def __post_init__(self) -> None:
        if self.daily_start_equity <= 0:
            self.daily_start_equity = self.equity

    @property
    def operational_equity(self) -> float:
        return max(0.0, self.equity - self.protected_floor - self.reserve_cash)

    @property
    def exposure(self) -> float:
        return sum(p.notional for p in self.positions.values())

    @property
    def exposure_pct(self) -> float:
        if self.operational_equity <= 0:
            return 1.0 if self.exposure > 0 else 0.0
        return self.exposure / self.operational_equity

    @property
    def daily_loss_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 1.0
        loss = self.daily_start_equity - self.equity
        return max(0.0, loss / self.daily_start_equity)


# ============================================================================
# SEÑALES
# ============================================================================


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    side: Side
    score: float
    expected_return: float
    confidence: float
    rationale: Dict[str, float] = field(default_factory=dict)
    strategy_id: str = "unknown"

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("signal.symbol vacío")
        if not 0 <= self.score <= 1:
            raise ValueError("signal.score debe estar entre 0 y 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("signal.confidence debe estar entre 0 y 1")
        if self.side == Side.HOLD and abs(self.expected_return) > 0:
            raise ValueError("HOLD no debe tener expected_return distinto de 0")


@dataclass(frozen=True)
class BenchmarkEvent:
    trader_id: str
    symbol: str
    setup_signature: str
    side: Side
    outcome_return: float
    timestamp: str
    source: str


@dataclass(frozen=True)
class BenchmarkAssessment:
    evidence_class: EvidenceClass
    comparable_traders: int
    comparable_events: int
    confidence: float
    historical_mean_return: float
    historical_win_rate: float
    agreement_rate: float
    reason: str


@dataclass(frozen=True)
class Decision:
    decision_id: str
    timestamp: str
    symbol: str
    side: Side
    status: DecisionStatus
    score: float
    risk_fraction: float
    quantity: float
    entry_price: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    evidence_class: EvidenceClass
    benchmark_confidence: float
    benchmark_mean_return: float
    rationale: Dict[str, Any]


# ============================================================================
# BENCHMARK ENGINE
# ============================================================================


class BenchmarkRepository(Protocol):
    def events(self) -> Sequence[BenchmarkEvent]:
        ...


@dataclass
class InMemoryBenchmarkRepository:
    _events: List[BenchmarkEvent] = field(default_factory=list)

    def events(self) -> Sequence[BenchmarkEvent]:
        return tuple(self._events)

    def add(self, event: BenchmarkEvent) -> None:
        self._events.append(event)


class BenchmarkEngine:
    """
    Usa traders exitosos como referencia estadística, no como autoridad.

    Si existe suficiente evidencia comparable, clasifica PRECEDENTED.
    Si no existe, clasifica NOVEL o INSUFFICIENT y deja que el motor de riesgo
    decida cuánto riesgo adicional puede asumir.
    """

    def __init__(self, repo: BenchmarkRepository, config: TraderBenchmarkConfig):
        config.validate()
        self.repo = repo
        self.config = config

    @staticmethod
    def _similarity(snapshot: MarketSnapshot, event: BenchmarkEvent) -> float:
        """Similitud simple y determinista; se reemplazará por el modelo real."""
        if snapshot.symbol != event.symbol:
            return 0.0
        signature = snapshot.features.get("setup_signature")
        if signature is not None and str(signature) == event.setup_signature:
            return 1.0
        return 0.0

    def assess(self, snapshot: MarketSnapshot, signal: StrategySignal) -> BenchmarkAssessment:
        candidates = [
            e for e in self.repo.events()
            if e.symbol == snapshot.symbol and e.side == signal.side
        ]

        comparable = [
            e for e in candidates
            if self._similarity(snapshot, e) >= 0.99
        ]

        traders = len({e.trader_id for e in comparable})
        events = len(comparable)

        if events == 0:
            return BenchmarkAssessment(
                evidence_class=EvidenceClass.NOVEL,
                comparable_traders=0,
                comparable_events=0,
                confidence=0.0,
                historical_mean_return=0.0,
                historical_win_rate=0.0,
                agreement_rate=0.0,
                reason="No existe precedente comparable para este setup.",
            )

        returns = [e.outcome_return for e in comparable]
        mean_return = sum(returns) / len(returns)
        win_rate = sum(1 for r in returns if r > 0) / len(returns)
        agreement = sum(1 for e in comparable if e.side == signal.side) / len(comparable)

        trader_factor = min(1.0, traders / self.config.min_comparable_traders)
        event_factor = min(1.0, events / self.config.min_comparable_events)
        confidence = trader_factor * event_factor

        if traders >= self.config.min_comparable_traders and events >= self.config.min_comparable_events and confidence >= self.config.min_confidence:
            evidence = EvidenceClass.PRECEDENTED
            reason = "Existe suficiente evidencia comparable de traders de referencia."
        else:
            evidence = EvidenceClass.INSUFFICIENT
            reason = "Existe precedente, pero no suficiente evidencia para tratarlo como referencia robusta."

        return BenchmarkAssessment(
            evidence_class=evidence,
            comparable_traders=traders,
            comparable_events=events,
            confidence=confidence,
            historical_mean_return=mean_return,
            historical_win_rate=win_rate,
            agreement_rate=agreement,
            reason=reason,
        )


# ============================================================================
# RISK ENGINE
# ============================================================================


class RiskEngine:
    def __init__(self, config: RiskConfig):
        config.validate()
        self.config = config

    def refresh_kill_switch(self, account: AccountState) -> None:
        if account.equity <= account.protected_floor:
            account.halted = True
            account.halt_reason = "Equity alcanzó el piso protegido."
            return
        if account.daily_loss_pct >= self.config.daily_loss_limit_pct:
            account.halted = True
            account.halt_reason = "Límite de pérdida diaria alcanzado."
            return
        if account.consecutive_losses >= self.config.max_consecutive_losses:
            account.halted = True
            account.halt_reason = "Máximo de pérdidas consecutivas alcanzado."
            return
        if account.trades_today >= self.config.max_trades_per_day:
            account.halted = True
            account.halt_reason = "Máximo de operaciones diarias alcanzado."

    def max_trade_notional(self, account: AccountState, novel: bool) -> float:
        operational = account.operational_equity
        if operational <= 0:
            return 0.0

        base = operational * self.config.max_position_pct
        if novel:
            base = min(base, operational * self.config.novel_risk_budget_pct)
        exposure_remaining = max(
            0.0,
            operational * self.config.max_total_exposure_pct - account.exposure,
        )
        return max(0.0, min(base, exposure_remaining))

    def approve(
        self,
        account: AccountState,
        signal: StrategySignal,
        benchmark: BenchmarkAssessment,
        price: float,
    ) -> Tuple[DecisionStatus, float, str]:
        self.refresh_kill_switch(account)
        if account.halted:
            return DecisionStatus.KILL_SWITCH, 0.0, account.halt_reason

        if signal.side == Side.HOLD:
            return DecisionStatus.REJECTED, 0.0, "Señal HOLD."

        if signal.score < self.config.min_signal_score:
            return DecisionStatus.REJECTED, 0.0, "Score de señal inferior al mínimo."

        if signal.confidence < self.config.min_signal_score:
            return DecisionStatus.REJECTED, 0.0, "Confianza de señal inferior al mínimo."

        if benchmark.evidence_class == EvidenceClass.PRECEDENTED:
            if benchmark.confidence < self.config.min_benchmark_confidence:
                return DecisionStatus.REJECTED, 0.0, "Benchmark comparable pero con confianza insuficiente."
            return DecisionStatus.APPROVED, self.config.max_position_pct, "Señal respaldada por precedente comparable."

        if benchmark.evidence_class == EvidenceClass.NOVEL:
            return DecisionStatus.NOVEL_RISK, self.config.novel_risk_budget_pct, "Setup novedoso: riesgo reducido y explícitamente limitado."

        return DecisionStatus.NOVEL_RISK, self.config.novel_risk_budget_pct, "Precedente insuficiente: se trata como oportunidad de riesgo reducido."

    def build_order_parameters(
        self,
        account: AccountState,
        signal: StrategySignal,
        price: float,
        novel: bool,
    ) -> Tuple[float, float, float]:
        notional = self.max_trade_notional(account, novel)
        if notional <= 0 or price <= 0:
            return 0.0, 0.0, 0.0

        quantity = notional / price
        if signal.side == Side.BUY:
            stop = price * (1.0 - self.config.stop_loss_pct)
            take = price * (1.0 + self.config.take_profit_pct)
        elif signal.side == Side.SELL:
            stop = price * (1.0 + self.config.stop_loss_pct)
            take = price * (1.0 - self.config.take_profit_pct)
        else:
            return 0.0, 0.0, 0.0
        return quantity, stop, take


# ============================================================================
# DECISION ENGINE
# ============================================================================


class DecisionEngine:
    def __init__(
        self,
        risk: RiskEngine,
        benchmark: BenchmarkEngine,
        benchmark_config: TraderBenchmarkConfig,
    ):
        self.risk = risk
        self.benchmark = benchmark
        self.benchmark_config = benchmark_config

    def evaluate(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
    ) -> Decision:
        snapshot.validate()
        signal.validate()

        assessment = self.benchmark.assess(snapshot, signal)
        status, _, status_reason = self.risk.approve(
            account, signal, assessment, snapshot.price
        )

        novel = assessment.evidence_class != EvidenceClass.PRECEDENTED
        quantity, stop, take = self.risk.build_order_parameters(
            account, signal, snapshot.price, novel
        )

        benchmark_component = clamp(
            assessment.confidence * (0.5 + 0.5 * clamp(assessment.historical_win_rate, 0, 1)),
            0.0,
            1.0,
        )
        if assessment.evidence_class == EvidenceClass.NOVEL:
            benchmark_component = 1.0 - self.benchmark_config.novelty_penalty
        elif assessment.evidence_class == EvidenceClass.INSUFFICIENT:
            benchmark_component *= 0.5

        combined_score = clamp(
            (1.0 - self.benchmark_config.benchmark_weight) * signal.score
            + self.benchmark_config.benchmark_weight * benchmark_component,
            0.0,
            1.0,
        )

        if status in {DecisionStatus.APPROVED, DecisionStatus.NOVEL_RISK} and quantity <= 0:
            status = DecisionStatus.REJECTED
            status_reason = "El motor de riesgo no permitió tamaño de posición."

        decision_id = stable_id(
            "dec",
            {
                "symbol": snapshot.symbol,
                "timestamp": snapshot.timestamp,
                "side": signal.side.value,
                "strategy": signal.strategy_id,
                "score": signal.score,
            },
        )

        rationale = {
            "strategy_id": signal.strategy_id,
            "signal_score": signal.score,
            "signal_confidence": signal.confidence,
            "expected_return": signal.expected_return,
            "benchmark_reason": assessment.reason,
            "benchmark_traders": assessment.comparable_traders,
            "benchmark_events": assessment.comparable_events,
            "benchmark_confidence": assessment.confidence,
            "benchmark_mean_return": assessment.historical_mean_return,
            "benchmark_win_rate": assessment.historical_win_rate,
            "benchmark_agreement": assessment.agreement_rate,
            "status_reason": status_reason,
            "combined_score": combined_score,
            "novel": novel,
        }

        return Decision(
            decision_id=decision_id,
            timestamp=utc_now(),
            symbol=snapshot.symbol,
            side=signal.side,
            status=status,
            score=combined_score,
            risk_fraction=self.risk.config.novel_risk_budget_pct if novel else self.risk.config.max_position_pct,
            quantity=quantity if status in {DecisionStatus.APPROVED, DecisionStatus.NOVEL_RISK} else 0.0,
            entry_price=snapshot.price,
            stop_price=stop if status in {DecisionStatus.APPROVED, DecisionStatus.NOVEL_RISK} else None,
            take_profit_price=take if status in {DecisionStatus.APPROVED, DecisionStatus.NOVEL_RISK} else None,
            evidence_class=assessment.evidence_class,
            benchmark_confidence=assessment.confidence,
            benchmark_mean_return=assessment.historical_mean_return,
            rationale=rationale,
        )


# ============================================================================
# EJECUCIÓN
# ============================================================================


@dataclass(frozen=True)
class ExecutionOrder:
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    mode: ExecutionMode
    timestamp: str


class ExecutionAdapter(Protocol):
    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        ...


class PaperExecutionAdapter:
    """Simulador mínimo y determinista. Nunca toca un broker."""

    def __init__(self) -> None:
        self.orders: List[ExecutionOrder] = []

    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        if order.mode != ExecutionMode.PAPER:
            raise ValueError("PaperExecutionAdapter solo acepta PAPER")
        if order.quantity <= 0:
            raise ValueError("quantity debe ser > 0")
        self.orders.append(order)
        return {
            "accepted": True,
            "mode": order.mode.value,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "price": order.price,
            "timestamp": order.timestamp,
        }


# ============================================================================
# AUDITORÍA / PERSISTENCIA
# ============================================================================


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {
            "timestamp": utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# ============================================================================
# ORQUESTADOR SEGURO
# ============================================================================


class RocketTraderCore:
    """Orquestador: datos -> señal -> benchmark -> riesgo -> decisión -> ejecución."""

    def __init__(
        self,
        risk_config: RiskConfig,
        benchmark_config: TraderBenchmarkConfig,
        benchmark_repository: Optional[BenchmarkRepository] = None,
        execution_adapter: Optional[ExecutionAdapter] = None,
        audit_path: str | Path = "data/rocket_trader_audit.jsonl",
    ):
        self.risk = RiskEngine(risk_config)
        repo = benchmark_repository or InMemoryBenchmarkRepository()
        self.benchmark = BenchmarkEngine(repo, benchmark_config)
        self.decisions = DecisionEngine(self.risk, self.benchmark, benchmark_config)
        self.execution = execution_adapter or PaperExecutionAdapter()
        self.audit = AuditLog(audit_path)

    def evaluate_and_maybe_execute(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        execute: bool = False,
    ) -> Decision:
        decision = self.decisions.evaluate(account, snapshot, signal)
        self.audit.append("DECISION", dataclasses.asdict(decision))

        if not execute:
            return decision

        if decision.status not in {DecisionStatus.APPROVED, DecisionStatus.NOVEL_RISK}:
            return decision

        order = ExecutionOrder(
            client_order_id=str(uuid.uuid4()),
            symbol=decision.symbol,
            side=decision.side,
            quantity=decision.quantity,
            price=decision.entry_price,
            stop_price=decision.stop_price,
            take_profit_price=decision.take_profit_price,
            mode=ExecutionMode.PAPER,
            timestamp=utc_now(),
        )
        result = self.execution.submit(order)
        self.audit.append("PAPER_EXECUTION", result)
        return decision


# ============================================================================
# EJEMPLO EJECUTABLE / SELF-TEST
# ============================================================================


def build_demo_core() -> RocketTraderCore:
    risk_config = RiskConfig(
        initial_capital=1000.0,
        permanent_floor=0.0,
        reserve_cash=0.0,
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

    return RocketTraderCore(
        risk_config=risk_config,
        benchmark_config=benchmark_config,
        benchmark_repository=InMemoryBenchmarkRepository(),
        execution_adapter=PaperExecutionAdapter(),
        audit_path="data/rocket_trader_audit.jsonl",
    )


def self_test() -> Dict[str, Any]:
    core = build_demo_core()
    account = AccountState(
        equity=1000.0,
        cash=1000.0,
        protected_floor=0.0,
    )

    snapshot = MarketSnapshot(
        symbol="DEMO",
        timestamp=utc_now(),
        price=100.0,
        volume=1000.0,
        features={"setup_signature": "NOVEL_SETUP_A"},
    )

    signal = StrategySignal(
        symbol="DEMO",
        side=Side.BUY,
        score=0.80,
        expected_return=0.03,
        confidence=0.80,
        rationale={"demo_signal": 1.0},
        strategy_id="demo",
    )

    decision = core.evaluate_and_maybe_execute(
        account=account,
        snapshot=snapshot,
        signal=signal,
        execute=True,
    )

    assert decision.status == DecisionStatus.NOVEL_RISK
    assert decision.evidence_class == EvidenceClass.NOVEL
    assert decision.quantity > 0
    assert decision.quantity <= 0.1
    assert decision.stop_price == 98.0
    assert decision.take_profit_price == 104.0

    return {
        "ok": True,
        "decision_id": decision.decision_id,
        "status": decision.status.value,
        "evidence_class": decision.evidence_class.value,
        "quantity": decision.quantity,
        "stop_price": decision.stop_price,
        "take_profit_price": decision.take_profit_price,
    }


def main() -> None:
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()