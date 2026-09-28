#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rocket Trader — Core v0.2

Núcleo de seguridad, decisión y ejecución desacoplada.

PRINCIPIOS:
1. El cerebro NO conoce los detalles del broker.
2. El broker NO decide cuánto riesgo asumir.
3. El panel web NO ejecuta lógica financiera crítica.
4. PAPER es el modo por defecto y LIVE requiere una habilitación explícita.
5. Rocket Trader opera inicialmente LONG-ONLY y con capital disponible en cash.
6. Nunca se usa margen/apalancamiento deliberadamente.
7. Los precedentes de traders exitosos sirven como benchmark, no como copia.
8. Una situación novedosa puede ser aceptada, pero con presupuesto de riesgo
   específico para novedad.
9. El piso protegido y las reservas no forman parte del capital operativo.
10. El reparto mensual es 10% reserva / 70% reinversión / 20% flujo personal.

IMPORTANTE:
- Este archivo NO contiene todavía la estrategia predictiva de mercado.
- Tampoco habilita por sí mismo transferencias reales ni trading LIVE.
- Es la base sobre la que se conectará el motor estadístico/ML.
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


def month_key(timestamp: Optional[str] = None) -> str:
    if timestamp:
        return timestamp[:7]
    return datetime.now(timezone.utc).strftime("%Y-%m")


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


class AllocationBucket(str, enum.Enum):
    RESERVE = "RESERVE"
    REINVESTMENT = "REINVESTMENT"
    PERSONAL = "PERSONAL"


# ============================================================================
# CONFIGURACIÓN DE RIESGO
# ============================================================================


@dataclass(frozen=True)
class RiskConfig:
    initial_capital: float = 1000.0

    # El piso empieza en 0 porque el primer objetivo es construirlo.
    # Cuando se alcance un hito, se debe elevar explícitamente.
    permanent_floor: float = 0.0

    # Operación inicialmente LONG-ONLY y CASH-ONLY.
    allow_short: bool = False
    allow_margin: bool = False

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

    # Una situación novedosa jamás recibe automáticamente el mismo presupuesto
    # de riesgo que una situación con precedente robusto.
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
        if self.max_position_pct > self.max_total_exposure_pct:
            raise ValueError("max_position_pct no puede superar max_total_exposure_pct")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day debe ser >= 1")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses debe ser >= 1")
        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct debe ser > 0")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct debe ser > 0")


@dataclass(frozen=True)
class TraderBenchmarkConfig:
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


@dataclass(frozen=True)
class ProfitDistributionConfig:
    reserve_pct: float = 0.10
    reinvestment_pct: float = 0.70
    personal_pct: float = 0.20
    frequency: str = "MONTHLY"

    def validate(self) -> None:
        values = (self.reserve_pct, self.reinvestment_pct, self.personal_pct)
        if any(x < 0 for x in values):
            raise ValueError("Los porcentajes de distribución no pueden ser negativos")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("La distribución debe sumar 100%")
        if self.frequency != "MONTHLY":
            raise ValueError("La frecuencia configurada actualmente es MONTHLY")


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
    protected_floor: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    day_start_equity: Optional[float] = None
    trades_today: int = 0
    consecutive_losses: int = 0
    realized_pnl_today: float = 0.0

    def __post_init__(self) -> None:
        if self.day_start_equity is None:
            self.day_start_equity = self.equity

    @property
    def operating_capital(self) -> float:
        return max(0.0, self.equity - self.protected_floor)

    @property
    def total_exposure(self) -> float:
        return sum(p.notional for p in self.positions.values())

    @property
    def daily_pnl_pct(self) -> float:
        if not self.day_start_equity or self.day_start_equity <= 0:
            return 0.0
        return (self.equity - self.day_start_equity) / self.day_start_equity


# ============================================================================
# SEÑAL
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
    setup_signature: str = ""

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("signal.symbol vacío")
        if not 0 <= self.score <= 1:
            raise ValueError("signal.score debe estar entre 0 y 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("signal.confidence debe estar entre 0 y 1")


# ============================================================================
# BENCHMARK DE TRADERS EXITOSOS
# ============================================================================


@dataclass(frozen=True)
class BenchmarkEvent:
    trader_id: str
    strategy_family: str
    setup_signature: str
    timestamp: str
    outcome_return: float
    risk_taken_pct: float
    sample_weight: float = 1.0


@dataclass(frozen=True)
class BenchmarkAssessment:
    evidence_class: EvidenceClass
    comparable_traders: int
    comparable_events: int
    confidence: float
    benchmark_score: float
    rationale: str


class BenchmarkRepository(Protocol):
    def comparable_events(self, setup_signature: str, strategy_family: str) -> Sequence[BenchmarkEvent]:
        ...


class InMemoryBenchmarkRepository:
    def __init__(self, events: Optional[Iterable[BenchmarkEvent]] = None) -> None:
        self._events = list(events or [])

    def add(self, event: BenchmarkEvent) -> None:
        self._events.append(event)

    def comparable_events(self, setup_signature: str, strategy_family: str) -> Sequence[BenchmarkEvent]:
        return [
            event
            for event in self._events
            if event.setup_signature == setup_signature
            and event.strategy_family == strategy_family
        ]


class BenchmarkEngine:
    def __init__(self, config: TraderBenchmarkConfig, repository: BenchmarkRepository) -> None:
        self.config = config
        self.repository = repository
        self.config.validate()

    def assess(self, signal: StrategySignal) -> BenchmarkAssessment:
        events = list(
            self.repository.comparable_events(
                signal.setup_signature,
                signal.strategy_id,
            )
        )

        traders = {e.trader_id for e in events}
        if not events:
            return BenchmarkAssessment(
                evidence_class=EvidenceClass.INSUFFICIENT,
                comparable_traders=0,
                comparable_events=0,
                confidence=0.0,
                benchmark_score=0.0,
                rationale="No existe evidencia comparable registrada.",
            )

        weighted_returns = [max(-1.0, min(1.0, e.outcome_return)) * e.sample_weight for e in events]
        weights = [max(0.0, e.sample_weight) for e in events]
        total_weight = sum(weights) or 1.0
        avg_return = sum(weighted_returns) / total_weight
        positive_rate = sum(1 for e in events if e.outcome_return > 0) / len(events)
        consistency = 1.0 - min(1.0, abs(avg_return - signal.expected_return))
        confidence = min(
            1.0,
            0.35 * min(1.0, len(traders) / self.config.min_comparable_traders)
            + 0.35 * min(1.0, len(events) / self.config.min_comparable_events)
            + 0.30 * positive_rate,
        )
        benchmark_score = clamp(
            0.50 * positive_rate + 0.25 * consistency + 0.25 * clamp(avg_return + 0.5, 0, 1),
            0,
            1,
        )

        if (
            len(traders) >= self.config.min_comparable_traders
            and len(events) >= self.config.min_comparable_events
            and confidence >= self.config.min_confidence
        ):
            evidence = EvidenceClass.PRECEDENTED
            rationale = "Existe un precedente comparable suficientemente amplio."
        else:
            evidence = EvidenceClass.INSUFFICIENT
            rationale = "Existe precedente, pero no alcanza la evidencia mínima."

        return BenchmarkAssessment(
            evidence_class=evidence,
            comparable_traders=len(traders),
            comparable_events=len(events),
            confidence=confidence,
            benchmark_score=benchmark_score,
            rationale=rationale,
        )


# ============================================================================
# RIESGO
# ============================================================================


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.config.validate()

    def kill_switch_reason(self, account: AccountState) -> Optional[str]:
        if account.equity <= account.protected_floor:
            return "equity_at_or_below_protected_floor"
        if account.daily_pnl_pct <= -self.config.daily_loss_limit_pct:
            return "daily_loss_limit"
        if account.trades_today >= self.config.max_trades_per_day:
            return "max_trades_per_day"
        if account.consecutive_losses >= self.config.max_consecutive_losses:
            return "max_consecutive_losses"
        return None

    def _available_operating_cash(self, account: AccountState) -> float:
        # Cash-only deliberado. Nunca usamos buying power de margen para decidir
        # cuánto puede comprar el bot.
        return max(0.0, min(account.cash, account.operating_capital))

    def position_size(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        evidence: EvidenceClass,
        signal_confidence: float,
    ) -> float:
        operating = account.operating_capital
        if operating <= 0:
            return 0.0

        available_cash = self._available_operating_cash(account)
        if available_cash <= 0:
            return 0.0

        base_pct = self.config.max_position_pct
        if evidence == EvidenceClass.NOVEL:
            base_pct = min(base_pct, self.config.novel_risk_budget_pct)
        elif evidence == EvidenceClass.INSUFFICIENT:
            base_pct = min(base_pct, self.config.novel_risk_budget_pct * 1.5)

        confidence_multiplier = clamp(signal_confidence, 0.25, 1.0)
        max_notional = operating * base_pct * confidence_multiplier
        remaining_exposure = max(
            0.0,
            operating * self.config.max_total_exposure_pct - account.total_exposure,
        )
        notional = min(max_notional, remaining_exposure, available_cash)
        if snapshot.price <= 0:
            return 0.0
        return max(0.0, notional / snapshot.price)

    def prices_for_long(self, entry_price: float) -> Tuple[float, float]:
        stop = entry_price * (1.0 - self.config.stop_loss_pct)
        take_profit = entry_price * (1.0 + self.config.take_profit_pct)
        return stop, take_profit


# ============================================================================
# DECISIÓN
# ============================================================================


@dataclass(frozen=True)
class Decision:
    decision_id: str
    timestamp: str
    status: DecisionStatus
    evidence_class: EvidenceClass
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    combined_score: float
    signal_score: float
    benchmark_score: float
    benchmark_confidence: float
    reason: str


class DecisionEngine:
    def __init__(
        self,
        risk_engine: RiskEngine,
        benchmark_engine: BenchmarkEngine,
    ) -> None:
        self.risk_engine = risk_engine
        self.benchmark_engine = benchmark_engine

    def evaluate(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
    ) -> Decision:
        snapshot.validate()
        signal.validate()

        decision_id = stable_id(
            "decision",
            {
                "symbol": snapshot.symbol,
                "timestamp": snapshot.timestamp,
                "price": snapshot.price,
                "strategy": signal.strategy_id,
            },
        )

        kill_reason = self.risk_engine.kill_switch_reason(account)
        if kill_reason:
            return Decision(
                decision_id=decision_id,
                timestamp=utc_now(),
                status=DecisionStatus.KILL_SWITCH,
                evidence_class=EvidenceClass.INSUFFICIENT,
                symbol=snapshot.symbol,
                side=Side.HOLD,
                quantity=0.0,
                entry_price=snapshot.price,
                stop_price=None,
                take_profit_price=None,
                combined_score=0.0,
                signal_score=signal.score,
                benchmark_score=0.0,
                benchmark_confidence=0.0,
                reason=kill_reason,
            )

        if signal.side != Side.BUY:
            return Decision(
                decision_id=decision_id,
                timestamp=utc_now(),
                status=DecisionStatus.REJECTED,
                evidence_class=EvidenceClass.INSUFFICIENT,
                symbol=snapshot.symbol,
                side=Side.HOLD,
                quantity=0.0,
                entry_price=snapshot.price,
                stop_price=None,
                take_profit_price=None,
                combined_score=0.0,
                signal_score=signal.score,
                benchmark_score=0.0,
                benchmark_confidence=0.0,
                reason="La configuración inicial es LONG-ONLY.",
            )

        assessment = self.benchmark_engine.assess(signal)

        if assessment.evidence_class == EvidenceClass.INSUFFICIENT:
            evidence_class = EvidenceClass.NOVEL
            benchmark_score = 0.0
            benchmark_confidence = 0.0
            combined_score = signal.score * (1.0 - self.benchmark_engine.config.novelty_penalty)
            status = DecisionStatus.NOVEL_RISK
            reason = "No hay precedente suficiente; se aplica presupuesto de riesgo de novedad."
        else:
            evidence_class = assessment.evidence_class
            benchmark_score = assessment.benchmark_score
            benchmark_confidence = assessment.confidence
            weight = self.benchmark_engine.config.benchmark_weight
            combined_score = (1.0 - weight) * signal.score + weight * benchmark_score
            status = DecisionStatus.APPROVED
            reason = assessment.rationale

            if signal.confidence < self.risk_engine.config.min_signal_score:
                status = DecisionStatus.REJECTED
                reason = "Confianza/señal insuficiente."
            elif combined_score < self.risk_engine.config.min_signal_score:
                status = DecisionStatus.REJECTED
                reason = "Score combinado insuficiente."
            elif (
                evidence_class == EvidenceClass.PRECEDENTED
                and benchmark_confidence < self.risk_engine.config.min_benchmark_confidence
            ):
                status = DecisionStatus.REJECTED
                reason = "Benchmark comparable con confianza insuficiente."

        quantity = self.risk_engine.position_size(
            account,
            snapshot,
            evidence_class,
            signal.confidence,
        )

        if quantity <= 0:
            status = DecisionStatus.REJECTED
            reason = "No existe capital operativo disponible para abrir la posición."

        stop_price, take_profit_price = self.risk_engine.prices_for_long(snapshot.price)

        if status == DecisionStatus.REJECTED:
            quantity = 0.0
            stop_price = None
            take_profit_price = None

        return Decision(
            decision_id=decision_id,
            timestamp=utc_now(),
            status=status,
            evidence_class=evidence_class,
            symbol=snapshot.symbol,
            side=Side.BUY if quantity > 0 else Side.HOLD,
            quantity=quantity,
            entry_price=snapshot.price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            combined_score=combined_score,
            signal_score=signal.score,
            benchmark_score=benchmark_score,
            benchmark_confidence=benchmark_confidence,
            reason=reason,
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
    order_type: str
    entry_price: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    mode: ExecutionMode


class ExecutionAdapter(Protocol):
    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        ...


class PaperExecutionAdapter:
    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        if order.mode != ExecutionMode.PAPER:
            raise RuntimeError("PaperExecutionAdapter solo acepta PAPER")
        return {
            "accepted": True,
            "mode": order.mode.value,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "entry_price": order.entry_price,
            "stop_price": order.stop_price,
            "take_profit_price": order.take_profit_price,
            "timestamp": utc_now(),
        }


class AlpacaExecutionAdapter:
    """Adaptador opcional para alpaca-py.

    Por seguridad:
    - PAPER es el default.
    - LIVE requiere ALPACA_LIVE_ENABLED=true.
    - No envía SELL SHORT.
    - Envía bracket orders para BUY.
    - El quantity recibido ya fue calculado por nuestro RiskEngine usando cash,
      no buying power de margen.
    """

    def __init__(self, api_key: str, api_secret: str, mode: ExecutionMode = ExecutionMode.PAPER) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.mode = mode

        if self.mode == ExecutionMode.LIVE and os.getenv("ALPACA_LIVE_ENABLED", "false").lower() != "true":
            raise RuntimeError("LIVE está bloqueado. Define ALPACA_LIVE_ENABLED=true explícitamente.")

        try:
            from alpaca.trading.client import TradingClient
            self._TradingClient = TradingClient
        except ImportError as exc:
            raise RuntimeError("Falta alpaca-py. Instala: pip install alpaca-py") from exc

        self.client = TradingClient(
            self.api_key,
            self.api_secret,
            paper=self.mode == ExecutionMode.PAPER,
        )

    def submit(self, order: ExecutionOrder) -> Dict[str, Any]:
        if order.mode != self.mode:
            raise RuntimeError("El modo de la orden no coincide con el adaptador Alpaca")
        if order.side != Side.BUY:
            raise RuntimeError("Rocket Trader v0.2 solo permite BUY/LONG")
        if order.quantity <= 0:
            raise ValueError("quantity debe ser > 0")
        if order.stop_price is None or order.take_profit_price is None:
            raise ValueError("Toda entrada debe llevar stop y take profit")

        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        request = MarketOrderRequest(
            symbol=order.symbol,
            qty=order.quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(order.take_profit_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(order.stop_price, 2)),
            client_order_id=order.client_order_id,
        )

        result = self.client.submit_order(order_data=request)
        return {
            "accepted": True,
            "mode": self.mode.value,
            "order_id": str(result.id),
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "status": str(result.status),
        }


# ============================================================================
# DISTRIBUCIÓN MENSUAL DE UTILIDADES
# ============================================================================


@dataclass(frozen=True)
class DistributionPlan:
    period: str
    distributable_profit: float
    reserve_amount: float
    reinvestment_amount: float
    personal_amount: float


class ProfitAllocator:
    """Calcula el reparto; no mueve dinero por sí mismo."""

    def __init__(self, config: ProfitDistributionConfig) -> None:
        self.config = config
        self.config.validate()

    def plan(self, distributable_profit: float, period: Optional[str] = None) -> DistributionPlan:
        if distributable_profit < 0:
            raise ValueError("No se distribuyen pérdidas como utilidades")
        amount = float(distributable_profit)
        reserve = amount * self.config.reserve_pct
        reinvestment = amount * self.config.reinvestment_pct
        personal = amount * self.config.personal_pct
        # Evita pérdida por redondeos en centavos.
        personal = amount - reserve - reinvestment
        return DistributionPlan(
            period=period or month_key(),
            distributable_profit=amount,
            reserve_amount=round(reserve, 2),
            reinvestment_amount=round(reinvestment, 2),
            personal_amount=round(personal, 2),
        )


class MoneyTransferAdapter(Protocol):
    def transfer(self, amount: float, destination: str, reference: str) -> Dict[str, Any]:
        ...


class DisabledMoneyTransferAdapter:
    """Bloquea transferencias reales hasta implementar y validar el rail bancario."""

    def transfer(self, amount: float, destination: str, reference: str) -> Dict[str, Any]:
        raise RuntimeError(
            "Transferencias automáticas reales están deshabilitadas en esta fase. "
            "El plan se calcula y audita, pero no se mueve dinero."
        )


# ============================================================================
# AUDITORÍA
# ============================================================================


class AuditLog:
    def __init__(self, path: str = "data/rocket_trader_audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {
            "timestamp": utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ============================================================================
# CORE
# ============================================================================


class RocketTraderCore:
    def __init__(
        self,
        risk_config: RiskConfig,
        benchmark_config: TraderBenchmarkConfig,
        distribution_config: Optional[ProfitDistributionConfig] = None,
        benchmark_repository: Optional[BenchmarkRepository] = None,
        execution_adapter: Optional[ExecutionAdapter] = None,
        audit_path: str = "data/rocket_trader_audit.jsonl",
    ) -> None:
        self.risk_engine = RiskEngine(risk_config)
        self.benchmark_engine = BenchmarkEngine(
            benchmark_config,
            benchmark_repository or InMemoryBenchmarkRepository(),
        )
        self.decision_engine = DecisionEngine(
            self.risk_engine,
            self.benchmark_engine,
        )
        self.profit_allocator = ProfitAllocator(
            distribution_config or ProfitDistributionConfig()
        )
        self.execution_adapter = execution_adapter or PaperExecutionAdapter()
        self.audit = AuditLog(audit_path)

    def evaluate_and_maybe_execute(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        execute: bool = True,
    ) -> Decision:
        decision = self.decision_engine.evaluate(account, snapshot, signal)
        self.audit.write("decision", dataclasses.asdict(decision))

        if execute and decision.quantity > 0 and decision.status in {
            DecisionStatus.APPROVED,
            DecisionStatus.NOVEL_RISK,
        }:
            order = ExecutionOrder(
                client_order_id=stable_id("order", decision.decision_id),
                symbol=decision.symbol,
                side=decision.side,
                quantity=decision.quantity,
                order_type="MARKET_BRACKET",
                entry_price=decision.entry_price,
                stop_price=decision.stop_price,
                take_profit_price=decision.take_profit_price,
                mode=ExecutionMode.PAPER,
            )
            result = self.execution_adapter.submit(order)
            self.audit.write("execution", result)

        return decision

    def monthly_distribution_plan(self, distributable_profit: float, period: Optional[str] = None) -> DistributionPlan:
        plan = self.profit_allocator.plan(distributable_profit, period)
        self.audit.write("distribution_plan", dataclasses.asdict(plan))
        return plan


# ============================================================================
# CONFIGURACIÓN DEMO
# ============================================================================


def build_demo_core() -> RocketTraderCore:
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
        audit_path="data/rocket_trader_audit.jsonl",
    )


# ============================================================================
# SELF-TEST
# ============================================================================


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
    )

    signal = StrategySignal(
        symbol="DEMO",
        side=Side.BUY,
        score=0.80,
        expected_return=0.03,
        confidence=0.80,
        rationale={"demo_signal": 1.0},
        strategy_id="demo",
        setup_signature="NOVEL_SETUP_A",
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

    plan = core.monthly_distribution_plan(1000.0, "2026-09")
    assert plan.reserve_amount == 100.0
    assert plan.reinvestment_amount == 700.0
    assert plan.personal_amount == 200.0

    # Kill switch por piso.
    floor_account = AccountState(
        equity=500.0,
        cash=500.0,
        protected_floor=500.0,
    )
    floor_decision = core.evaluate_and_maybe_execute(
        account=floor_account,
        snapshot=snapshot,
        signal=signal,
        execute=False,
    )
    assert floor_decision.status == DecisionStatus.KILL_SWITCH

    return {
        "ok": True,
        "decision": {
            "status": decision.status.value,
            "evidence_class": decision.evidence_class.value,
            "quantity": decision.quantity,
            "stop_price": decision.stop_price,
            "take_profit_price": decision.take_profit_price,
        },
        "monthly_distribution": dataclasses.asdict(plan),
        "floor_kill_switch": floor_decision.status.value,
    }


def main() -> None:
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()