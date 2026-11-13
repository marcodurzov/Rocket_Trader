#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Core v0.3

Núcleo de seguridad, decisión, capital y ejecución.

REGLAS:
- LONG ONLY
- CASH ONLY
- SIN MARGIN
- SIN LEVERAGE
- SIN SHORT
- PAPER por defecto
- LIVE requiere habilitación explícita
- Antes del primer hito de 100,000 MXN:
    100% reinversión de utilidades netas realizadas
    0% retiros personales
    0% reserva separada (la liquidez no invertida sigue dentro del capital operativo)
- Después de alcanzar 100,000 MXN una vez:
    50% reinversión
    40% personal
    10% reserva
- El cambio de política es irreversible y se persiste en un estado durable.
- La distribución es mensual.
- Las transferencias reales están deshabilitadas.
- Adaptive Risk puede reducir o bloquear riesgo.
- Adaptive Risk nunca puede saltarse los límites duros del Core.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from rocket_trader_currency import (
    CurrencyBudgetError,
    FXQuote,
    calculate_position_budget,
)

from rocket_trader_drawdown_guard import (
    DrawdownGuardError,
    PersistentDrawdownGuard,
)


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
    SAFE_MODE = "SAFE_MODE"


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
    permanent_floor: float = 0.0

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
            raise ValueError(
                "max_position_pct no puede superar max_total_exposure_pct"
            )

        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day debe ser >= 1")

        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses debe ser >= 1")

        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct debe ser > 0")

        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct debe ser > 0")


# ============================================================================
# CAPITAL / DISTRIBUCIÓN
# ============================================================================

@dataclass(frozen=True)
class ProfitDistributionConfig:
    threshold_mxn: float = 100000.0

    # Fase de capitalización: cada peso de utilidad neta realizada permanece
    # dentro del capital operativo hasta alcanzar por primera vez el hito.
    below_threshold_reserve_pct: float = 0.00
    below_threshold_reinvestment_pct: float = 1.00
    below_threshold_personal_pct: float = 0.00

    at_or_above_threshold_reserve_pct: float = 0.10
    at_or_above_threshold_reinvestment_pct: float = 0.50
    at_or_above_threshold_personal_pct: float = 0.40

    frequency: str = "MONTHLY"

    def validate(self) -> None:
        if self.threshold_mxn <= 0:
            raise ValueError("threshold_mxn debe ser > 0")

        groups = [
            (
                self.below_threshold_reserve_pct,
                self.below_threshold_reinvestment_pct,
                self.below_threshold_personal_pct,
            ),
            (
                self.at_or_above_threshold_reserve_pct,
                self.at_or_above_threshold_reinvestment_pct,
                self.at_or_above_threshold_personal_pct,
            ),
        ]

        for values in groups:
            if any(value < 0 or value > 1 for value in values):
                raise ValueError(
                    "Los porcentajes de distribución deben estar entre 0 y 1"
                )

            if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
                raise ValueError(
                    "Cada esquema de distribución debe sumar 100%"
                )

        if self.frequency != "MONTHLY":
            raise ValueError("La frecuencia configurada actualmente es MONTHLY")


@dataclass(frozen=True)
class DistributionPlan:
    period: str
    operating_capital: float
    distributable_profit: float

    threshold_mxn: float

    reserve_pct: float
    reinvestment_pct: float
    personal_pct: float

    reserve_amount: float
    reinvestment_amount: float
    personal_amount: float

    capital_policy: str
    threshold_reached: bool

    target_reserve_pct: float
    target_reinvestment_pct: float
    target_personal_pct: float

    payouts_suspended: bool
    payout_suspension_reason: Optional[str]
    operating_capital_after_distribution: float
    milestone_qualifying_capital_mxn: Optional[float] = None


class ProfitAllocator:
    """
    Regla automática:

    antes del primer hito de 100,000 MXN:
        100% reinversión / 0% personal / 0% reserva separada

    después de alcanzar el hito una vez:
        50% reinversión / 40% personal / 10% reserva

    El hito no se revierte si el capital cae posteriormente.
    """

    def __init__(
        self,
        config: Optional[ProfitDistributionConfig] = None,
        milestone_path: Optional[str] = None,
    ) -> None:
        self.config = config or ProfitDistributionConfig()
        self.config.validate()
        configured_path = milestone_path or os.getenv("ROCKET_TRADER_CAPITAL_MILESTONE_PATH")
        self.milestone_path = Path(configured_path) if configured_path else None
        self._threshold_reached = False
        self._threshold_reached_at: Optional[str] = None
        if self.milestone_path and self.milestone_path.exists():
            try:
                state = json.loads(self.milestone_path.read_text(encoding="utf-8"))
                if float(state.get("threshold_mxn")) != self.config.threshold_mxn:
                    raise ValueError("El umbral guardado no coincide con la configuración")
                self._threshold_reached = bool(state.get("threshold_reached", False))
                self._threshold_reached_at = state.get("threshold_reached_at")
            except Exception as exc:
                raise RuntimeError(
                    "No se pudo validar el estado persistente del hito de capital; "
                    "se bloquea la distribución para evitar revertir la política."
                ) from exc

    def _persist_milestone(self) -> None:
        if not self.milestone_path:
            return
        self.milestone_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "threshold_mxn": self.config.threshold_mxn,
            "threshold_reached": True,
            "threshold_reached_at": self._threshold_reached_at or utc_now(),
        }
        temporary = self.milestone_path.with_suffix(self.milestone_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        json.loads(temporary.read_text(encoding="utf-8"))
        temporary.replace(self.milestone_path)

    def percentages_for_capital(
        self,
        operating_capital: float,
        earned_growth_capital_mxn: Optional[float] = None,
    ) -> Tuple[float, float, float, str, bool]:

        if operating_capital < 0:
            raise ValueError("operating_capital no puede ser negativo")
        qualifying_capital = (
            operating_capital
            if earned_growth_capital_mxn is None
            else float(earned_growth_capital_mxn)
        )
        if qualifying_capital < 0:
            raise ValueError("earned_growth_capital_mxn no puede ser negativo")
        if qualifying_capital >= self.config.threshold_mxn and not self._threshold_reached:
            self._threshold_reached = True
            self._threshold_reached_at = utc_now()
            self._persist_milestone()

        if not self._threshold_reached:
            return (
                self.config.below_threshold_reserve_pct,
                self.config.below_threshold_reinvestment_pct,
                self.config.below_threshold_personal_pct,
                "ACCUMULATION_BELOW_100K",
                False,
            )

        return (
            self.config.at_or_above_threshold_reserve_pct,
            self.config.at_or_above_threshold_reinvestment_pct,
            self.config.at_or_above_threshold_personal_pct,
            "DISTRIBUTION_THRESHOLD_PERMANENTLY_REACHED",
            True,
        )

    def plan(
        self,
        distributable_profit: float,
        operating_capital: float,
        period: Optional[str] = None,
        earned_growth_capital_mxn: Optional[float] = None,
    ) -> DistributionPlan:

        if distributable_profit < 0:
            raise ValueError(
                "No se distribuyen pérdidas como utilidades"
            )

        target_reserve_pct, target_reinvestment_pct, target_personal_pct, policy, threshold_reached = (
            self.percentages_for_capital(
                operating_capital,
                earned_growth_capital_mxn=earned_growth_capital_mxn,
            )
        )

        amount = float(distributable_profit)
        reserve_pct = target_reserve_pct
        reinvestment_pct = target_reinvestment_pct
        personal_pct = target_personal_pct

        reserve = amount * reserve_pct
        reinvestment = amount * reinvestment_pct
        personal = amount - reserve - reinvestment
        payouts_suspended = False
        suspension_reason: Optional[str] = None

        # operating_capital is the MXN operating balance after realized net profit
        # is credited but before this period's reserve/personal transfers.
        # Once the milestone is reached, never let a payout take the operating
        # balance below the protected floor. The target 50/10/40 rule remains
        # recorded, but actual transfers are withheld until there is headroom.
        if threshold_reached:
            post_distribution_capital = operating_capital - reserve - personal
            if post_distribution_capital < self.config.threshold_mxn - 1e-8:
                payouts_suspended = True
                suspension_reason = "WITHHOLD_DISTRIBUTIONS_TO_PRESERVE_OPERATING_FLOOR"
                reserve_pct = 0.0
                reinvestment_pct = 1.0
                personal_pct = 0.0
                reserve = 0.0
                reinvestment = amount
                personal = 0.0
                policy = "DISTRIBUTION_THRESHOLD_PERMANENTLY_REACHED_FLOOR_HOLD"

        capital_after = operating_capital - reserve - personal

        return DistributionPlan(
            period=period or month_key(),
            operating_capital=round(operating_capital, 2),
            distributable_profit=round(amount, 2),
            threshold_mxn=self.config.threshold_mxn,
            reserve_pct=reserve_pct,
            reinvestment_pct=reinvestment_pct,
            personal_pct=personal_pct,
            reserve_amount=round(reserve, 2),
            reinvestment_amount=round(reinvestment, 2),
            personal_amount=round(personal, 2),
            capital_policy=policy,
            threshold_reached=threshold_reached,
            target_reserve_pct=target_reserve_pct,
            target_reinvestment_pct=target_reinvestment_pct,
            target_personal_pct=target_personal_pct,
            payouts_suspended=payouts_suspended,
            payout_suspension_reason=suspension_reason,
            operating_capital_after_distribution=round(capital_after, 2),
            milestone_qualifying_capital_mxn=round(
                operating_capital if earned_growth_capital_mxn is None
                else float(earned_growth_capital_mxn), 2
            ),
        )


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

        if (
            self.bid is not None
            and self.ask is not None
            and self.bid > self.ask
        ):
            raise ValueError("bid no puede ser mayor que ask")

        for key, value in self.features.items():
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"feature inválida: {key}"
                )

            if not math.isfinite(float(value)):
                raise ValueError(
                    f"feature no finita: {key}"
                )


# ============================================================================
# CUENTA / POSICIONES
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
    # Broker-side account values and position notionals are USD (Alpaca account currency).
    equity: float
    cash: float

    # Preserve the original third positional field for compatibility.
    # Broker-side emergency floor remains denominated in USD.
    protected_floor: float = 0.0
    account_currency: str = "USD"

    # Strategy capital is maintained separately in MXN. A sourced, timestamped
    # FX quote is mandatory before this capital can authorize a USD order.
    strategy_capital_mxn: Optional[float] = None
    fx_quote: Optional[FXQuote] = None
    # Risk limits for the allocated strategy must be measured in MXN, not
    # against Alpaca's much larger virtual Paper account equity in USD.
    strategy_equity_mxn: Optional[float] = None
    strategy_daily_pnl_pct: Optional[float] = None

    positions: Dict[str, Position = field(default_factory=dict)

    day_start_equity: Optional[float] = None

    trades_today: int = 0
    consecutive_losses: int = 0
    realized_pnl_today: float = 0.0

    def __post_init__(self) -> None:
        if self.account_currency.upper() != "USD":
            raise ValueError("Rocket Trader broker AccountState must be denominated in USD")

        for field_name, value in (
            ("equity", self.equity),
            ("cash", self.cash),
            ("protected_floor", self.protected_floor),
            ("realized_pnl_today", self.realized_pnl_today),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{field_name} debe ser finito")
        if self.equity < 0 or self.cash < 0 or self.protected_floor < 0:
            raise ValueError("equity, cash y protected_floor no pueden ser negativos")
        if self.strategy_capital_mxn is not None:
            if not math.isfinite(self.strategy_capital_mxn) or self.strategy_capital_mxn < 0:
                raise ValueError("strategy_capital_mxn debe ser finito y no negativo")
        if self.day_start_equity is not None:
            if not math.isfinite(self.day_start_equity) or self.day_start_equity <= 0:
                raise ValueError("day_start_equity debe ser finito y positivo")

        if self.fx_quote is not None and self.strategy_capital_mxn is None:
            raise ValueError("fx_quote requiere strategy_capital_mxn explícito")

        if self.fx_quote is not None and not isinstance(self.fx_quote, FXQuote):
            raise ValueError("fx_quote debe ser una instancia FXQuote validada")

        if self.strategy_equity_mxn is not None:
            if self.strategy_capital_mxn is None or not math.isfinite(self.strategy_equity_mxn) or self.strategy_equity_mxn <= 0:
                raise ValueError("strategy_equity_mxn requires explicit strategy capital and must be finite/positive")
        if self.strategy_daily_pnl_pct is not None:
            if self.strategy_capital_mxn is None or not math.isfinite(self.strategy_daily_pnl_pct):
                raise ValueError("strategy_daily_pnl_pct requires explicit strategy capital and must be finite")
        for field_name, value in (("trades_today", self.trades_today), ("consecutive_losses", self.consecutive_losses)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for symbol, position in self.positions.items():
            if not isinstance(position, Position) or symbol != position.symbol:
                raise ValueError("positions must map symbols to matching Position records")
            if (
                not math.isfinite(position.quantity) or position.quantity <= 0
                or not math.isfinite(position.entry_price) or position.entry_price <= 0
            ):
                raise ValueError("position quantity and entry_price must be finite and positive")

        if self.equity < 0:
            raise ValueError("equity no puede ser negativa")

        if self.cash < 0:
            raise ValueError("cash no puede ser negativo")

        if self.protected_floor < 0:
            raise ValueError(
                "protected_floor no puede ser negativo"
            )

        if self.day_start_equity is None:
            self.day_start_equity = self.equity

    @property
    def operating_capital(self) -> float:
        return max(
            0.0,
            self.equity - self.protected_floor,
        )

    @property
    def total_exposure(self) -> float:
        return sum(
            position.notional
            for position in self.positions.values()
        )

    @property
    def daily_pnl_pct(self) -> float:
        if (
            self.day_start_equity is None
            or self.day_start_equity <= 0
        ):
            return 0.0

        return (
            self.equity - self.day_start_equity
        ) / self.day_start_equity


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

    rationale: Dict[str, float] = field(
        default_factory=dict
    )

    strategy_id: str = "unknown"
    setup_signature: str = ""

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("signal.symbol vacío")

        if not 0 <= self.score <= 1:
            raise ValueError(
                "signal.score debe estar entre 0 y 1"
            )

        if not 0 <= self.confidence <= 1:
            raise ValueError(
                "signal.confidence debe estar entre 0 y 1"
            )

        if not math.isfinite(
            float(self.expected_return)
        ):
            raise ValueError(
                "signal.expected_return inválido"
            )


# ============================================================================
# BENCHMARK
# ============================================================================

@dataclass(frozen=True)
class TraderBenchmarkConfig:
    min_comparable_traders: int = 3
    min_comparable_events: int = 20
    min_confidence: float = 0.55

    novelty_penalty: float = 0.15
    benchmark_weight: float = 0.25

    def validate(self) -> None:
        if self.min_comparable_traders < 1:
            raise ValueError(
                "min_comparable_traders debe ser >= 1"
            )

        if self.min_comparable_events < 1:
            raise ValueError(
                "min_comparable_events debe ser >= 1"
            )

        if not 0 <= self.min_confidence <= 1:
            raise ValueError(
                "min_confidence inválida"
            )

        if not 0 <= self.novelty_penalty <= 1:
            raise ValueError(
                "novelty_penalty inválida"
            )

        if not 0 <= self.benchmark_weight <= 1:
            raise ValueError(
                "benchmark_weight inválido"
            )


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

    def comparable_events(
        self,
        setup_signature: str,
        strategy_family: str,
    ) -> Sequence[BenchmarkEvent]:
        ...


class InMemoryBenchmarkRepository:

    def __init__(
        self,
        events: Optional[
            Iterable[BenchmarkEvent]
        ] = None,
    ) -> None:
        self._events = list(events or [])

    def add(
        self,
        event: BenchmarkEvent,
    ) -> None:
        self._events.append(event)

    def comparable_events(
        self,
        setup_signature: str,
        strategy_family: str,
    ) -> Sequence[BenchmarkEvent]:

        return [
            event
            for event in self._events
            if (
                event.setup_signature
                == setup_signature
                and event.strategy_family
                == strategy_family
            )
        ]


class BenchmarkEngine:

    def __init__(
        self,
        config: TraderBenchmarkConfig,
        repository: BenchmarkRepository,
    ) -> None:

        self.config = config
        self.repository = repository

        self.config.validate()

    def assess(
        self,
        signal: StrategySignal,
    ) -> BenchmarkAssessment:

        events = list(
            self.repository.comparable_events(
                signal.setup_signature,
                signal.strategy_id,
            )
        )

        traders = {
            event.trader_id
            for event in events
        }

        if not events:
            return BenchmarkAssessment(
                evidence_class=EvidenceClass.INSUFFICIENT,
                comparable_traders=0,
                comparable_events=0,
                confidence=0.0,
                benchmark_score=0.0,
                rationale=(
                    "No existe evidencia comparable registrada."
                ),
            )

        weights = [
            max(0.0, event.sample_weight)
            for event in events
        ]

        weighted_returns = [
            clamp(event.outcome_return, -1.0, 1.0)
            * max(0.0, event.sample_weight)
            for event in events
        ]

        total_weight = sum(weights) or 1.0

        avg_return = (
            sum(weighted_returns)
            / total_weight
        )

        positive_rate = (
            sum(
                1
                for event in events
                if event.outcome_return > 0
            )
            / len(events)
        )

        consistency = 1.0 - min(
            1.0,
            abs(
                avg_return
                - signal.expected_return
            ),
        )

        confidence = min(
            1.0,
            0.35
            * min(
                1.0,
                len(traders)
                / self.config.min_comparable_traders,
            )
            + 0.35
            * min(
                1.0,
                len(events)
                / self.config.min_comparable_events,
            )
            + 0.30 * positive_rate,
        )

        benchmark_score = clamp(
            0.50 * positive_rate
            + 0.25 * consistency
            + 0.25
            * clamp(
                avg_return + 0.5,
                0,
                1,
            ),
            0,
            1,
        )

        if (
            len(traders)
            >= self.config.min_comparable_traders
            and len(events)
            >= self.config.min_comparable_events
            and confidence
            >= self.config.min_confidence
        ):
            evidence = EvidenceClass.PRECEDENTED
            rationale = (
                "Existe un precedente comparable "
                "suficientemente amplio."
            )
        else:
            evidence = EvidenceClass.INSUFFICIENT
            rationale = (
                "Existe precedente, pero no alcanza "
                "la evidencia mínima."
            )

        return BenchmarkAssessment(
            evidence_class=evidence,
            comparable_traders=len(traders),
            comparable_events=len(events),
            confidence=confidence,
            benchmark_score=benchmark_score,
            rationale=rationale,
        )


# ============================================================================
# ADAPTIVE RISK
# ============================================================================

class AdaptiveMarketRegime(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


class AdaptiveNewsImpact(str, enum.Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT_NEGATIVE = "URGENT_NEGATIVE"


@dataclass(frozen=True)
class AdaptiveRiskDecision:
    allowed: bool
    multiplier: float
    max_position_pct: float
    reason: str


class AdaptiveRiskOverlay:
    """
    Capa defensiva integrada al Core.

    Esta versión es deliberadamente conservadora:
    - Puede REDUCIR riesgo.
    - Puede BLOQUEAR riesgo.
    - No puede superar max_position_pct del Core.
    """

    def __init__(
        self,
        max_multiplier: float = 1.0,
    ) -> None:
        self.max_multiplier = clamp(
            max_multiplier,
            0.0,
            1.0,
        )

    def evaluate(
        self,
        account: AccountState,
        signal: StrategySignal,
        evidence_class: EvidenceClass,
        market_regime: str = "NEUTRAL",
        news_impact: str = "NONE",
    ) -> AdaptiveRiskDecision:

        regime = str(
            market_regime
        ).upper()

        news = str(
            news_impact
        ).upper()

        if regime in {
            "RISK_OFF",
            "DOWN",
        }:
            return AdaptiveRiskDecision(
                allowed=False,
                multiplier=0.0,
                max_position_pct=0.0,
                reason="Adaptive bloqueó por régimen RISK_OFF.",
            )

        if news in {
            "URGENT_NEGATIVE",
            "HIGH_NEGATIVE",
        }:
            return AdaptiveRiskDecision(
                allowed=False,
                multiplier=0.0,
                max_position_pct=0.0,
                reason=(
                    "Adaptive bloqueó por impacto negativo "
                    "de noticias."
                ),
            )

        multiplier = 1.0

        if evidence_class == EvidenceClass.NOVEL:
            multiplier *= 0.50

        if evidence_class == EvidenceClass.INSUFFICIENT:
            multiplier *= 0.75

        if signal.confidence < 0.70:
            multiplier *= 0.75

        if signal.score < 0.70:
            multiplier *= 0.75

        multiplier = clamp(
            multiplier,
            0.0,
            self.max_multiplier,
        )

        return AdaptiveRiskDecision(
            allowed=multiplier > 0,
            multiplier=multiplier,
            max_position_pct=multiplier,
            reason=(
                "Adaptive aprobó con multiplicador "
                f"{multiplier:.4f}."
            ),
        )


# ============================================================================
# RIESGO DURO
# ============================================================================

class RiskEngine:

    def __init__(
        self,
        config: RiskConfig,
    ) -> None:

        self.config = config
        self.config.validate()

    def kill_switch_reason(
        self,
        account: AccountState,
    ) -> Optional[str]:

        if account.equity <= account.protected_floor:
            return "broker_equity_at_or_below_protected_floor"

        if account.strategy_capital_mxn is not None:
            if (
                account.strategy_equity_mxn is None
                or account.strategy_daily_pnl_pct is None
            ):
                return "strategy_risk_metrics_missing"
            if account.strategy_equity_mxn <= 0:
                return "strategy_equity_at_or_below_zero"
            if account.strategy_daily_pnl_pct <= -self.config.daily_loss_limit_pct:
                return "strategy_daily_loss_limit"
        elif account.daily_pnl_pct <= -self.config.daily_loss_limit_pct:
            return "broker_daily_loss_limit"

        if (
            account.trades_today
            >= self.config.max_trades_per_day
        ):
            return "max_trades_per_day"

        if (
            account.consecutive_losses
            >= self.config.max_consecutive_losses
        ):
            return "max_consecutive_losses"

        return None

    def available_operating_cash(
        self,
        account: AccountState,
    ) -> float:

        return max(
            0.0,
            min(
                account.cash,
                account.operating_capital,
            ),
        )

    def position_size(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        evidence: EvidenceClass,
        signal_confidence: float,
        adaptive_multiplier: float = 1.0,
    ) -> float:

        # No se permite inferir capital MXN a partir del buying power Paper.
        # Sin ledger MXN explícito y FX reciente/fuenteado, el sizing se bloquea.
        if (
            account.strategy_capital_mxn is None
            or account.fx_quote is None
            or account.cash <= 0
        ):
            return 0.0

        base_pct = self.config.max_position_pct

        if evidence == EvidenceClass.NOVEL:
            base_pct = min(
                base_pct,
                self.config.novel_risk_budget_pct,
            )

        elif evidence == EvidenceClass.INSUFFICIENT:
            base_pct = min(
                base_pct,
                self.config.novel_risk_budget_pct
                * 1.5,
            )

        adaptive_multiplier = clamp(
            adaptive_multiplier,
            0.0,
            1.0,
        )

        base_pct *= adaptive_multiplier

        confidence_multiplier = clamp(
            signal_confidence,
            0.25,
            1.0,
        )

        if snapshot.price <= 0:
            return 0.0

        effective_position_pct = base_pct * confidence_multiplier
        if effective_position_pct <= 0:
            return 0.0

        try:
            budget = calculate_position_budget(
                capital_mxn=account.strategy_capital_mxn,
                available_cash_usd=account.cash,
                current_exposure_usd=account.total_exposure,
                fx_quote=account.fx_quote,
                max_position_pct=effective_position_pct,
                max_total_exposure_pct=self.config.max_total_exposure_pct,
                max_loss_per_trade_pct=self.config.max_loss_per_trade_pct,
                stop_distance_pct=self.config.stop_loss_pct,
                min_order_usd=Decimal("1.00"),
                max_fx_age=timedelta(hours=24),
            )
        except CurrencyBudgetError:
            return 0.0

        if not budget.allowed:
            return 0.0

        # Alpaca equity orders are sized in USD notional; quantity is shares.
        return float(budget.max_notional_usd) / snapshot.price

    def prices_for_long(
        self,
        entry_price: float,
    ) -> Tuple[float, float]:

        stop = (
            entry_price
            * (1.0 - self.config.stop_loss_pct)
        )

        take_profit = (
            entry_price
            * (1.0 + self.config.take_profit_pct)
        )

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

    adaptive_multiplier: float
    adaptive_reason: str

    reason: str


class DecisionEngine:

    def __init__(
        self,
        risk_engine: RiskEngine,
        benchmark_engine: BenchmarkEngine,
        adaptive_overlay: Optional[
            AdaptiveRiskOverlay
        ] = None,
    ) -> None:

        self.risk_engine = risk_engine
        self.benchmark_engine = benchmark_engine
        self.adaptive_overlay = (
            adaptive_overlay
            or AdaptiveRiskOverlay()
        )

    def evaluate(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        market_regime: str = "NEUTRAL",
        news_impact: str = "NONE",
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

        kill_reason = (
            self.risk_engine.kill_switch_reason(
                account
            )
        )

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
                adaptive_multiplier=0.0,
                adaptive_reason="Hard kill switch.",
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
                adaptive_multiplier=0.0,
                adaptive_reason="LONG-ONLY.",
                reason=(
                    "La configuración actual "
                    "es LONG-ONLY."
                ),
            )

        # Apply the same minimum signal-quality gate to precedent-based and
        # novel setups. The previous novel branch bypassed this check and could
        # approve low-score/low-confidence signals at the reduced novelty budget.
        minimum_quality = self.risk_engine.config.min_signal_score
        if signal.score < minimum_quality or signal.confidence < minimum_quality:
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
                adaptive_multiplier=0.0,
                adaptive_reason="Minimum signal-quality gate.",
                reason=(
                    f"Signal score/confidence below minimum "
                    f"{minimum_quality:.4f}."
                ),
            )

        assessment = (
            self.benchmark_engine.assess(signal)
        )

        if (
            assessment.evidence_class
            == EvidenceClass.INSUFFICIENT
        ):
            evidence_class = EvidenceClass.NOVEL

            benchmark_score = 0.0
            benchmark_confidence = 0.0

            combined_score = (
                signal.score
                * (
                    1.0
                    - self.benchmark_engine.config
                    .novelty_penalty
                )
            )

            status = DecisionStatus.NOVEL_RISK

            reason = (
                "No hay precedente suficiente; "
                "se aplica presupuesto de riesgo "
                "de novedad."
            )

        else:
            evidence_class = (
                assessment.evidence_class
            )

            benchmark_score = (
                assessment.benchmark_score
            )

            benchmark_confidence = (
                assessment.confidence
            )

            weight = (
                self.benchmark_engine.config
                .benchmark_weight
            )

            combined_score = (
                (1.0 - weight) * signal.score
                + weight * benchmark_score
            )

            status = DecisionStatus.APPROVED

            reason = assessment.rationale

            if (
                signal.confidence
                < self.risk_engine.config
                .min_signal_score
            ):
                status = DecisionStatus.REJECTED
                reason = (
                    "Confianza/señal insuficiente."
                )

            elif (
                combined_score
                < self.risk_engine.config
                .min_signal_score
            ):
                status = DecisionStatus.REJECTED
                reason = (
                    "Score combinado insuficiente."
                )

            elif (
                evidence_class
                == EvidenceClass.PRECEDENTED
                and benchmark_confidence
                < self.risk_engine.config
                .min_benchmark_confidence
            ):
                status = DecisionStatus.REJECTED
                reason = (
                    "Benchmark comparable con "
                    "confianza insuficiente."
                )

        adaptive = (
            self.adaptive_overlay.evaluate(
                account=account,
                signal=signal,
                evidence_class=evidence_class,
                market_regime=market_regime,
                news_impact=news_impact,
            )
        )

        if not adaptive.allowed:
            return Decision(
                decision_id=decision_id,
                timestamp=utc_now(),
                status=DecisionStatus.SAFE_MODE,
                evidence_class=evidence_class,
                symbol=snapshot.symbol,
                side=Side.HOLD,
                quantity=0.0,
                entry_price=snapshot.price,
                stop_price=None,
                take_profit_price=None,
                combined_score=combined_score,
                signal_score=signal.score,
                benchmark_score=benchmark_score,
                benchmark_confidence=benchmark_confidence,
                adaptive_multiplier=0.0,
                adaptive_reason=adaptive.reason,
                reason=adaptive.reason,
            )

        quantity = (
            self.risk_engine.position_size(
                account=account,
                snapshot=snapshot,
                evidence=evidence_class,
                signal_confidence=signal.confidence,
                adaptive_multiplier=(
                    adaptive.multiplier
                ),
            )
        )

        if quantity <= 0:
            status = DecisionStatus.REJECTED
            reason = (
                "No existe capital operativo "
                "disponible para abrir la posición."
            )

        stop_price, take_profit_price = (
            self.risk_engine.prices_for_long(
                snapshot.price
            )
        )

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
            side=(
                Side.BUY
                if quantity > 0
                else Side.HOLD
            ),
            quantity=quantity,
            entry_price=snapshot.price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            combined_score=combined_score,
            signal_score=signal.score,
            benchmark_score=benchmark_score,
            benchmark_confidence=benchmark_confidence,
            adaptive_multiplier=adaptive.multiplier,
            adaptive_reason=adaptive.reason,
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

    def submit(
        self,
        order: ExecutionOrder,
    ) -> Dict[str, Any]:
        ...


class PaperExecutionAdapter:

    def submit(
        self,
        order: ExecutionOrder,
    ) -> Dict[str, Any]:

        if order.mode != ExecutionMode.PAPER:
            raise RuntimeError(
                "PaperExecutionAdapter solo acepta PAPER"
            )

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
            "take_profit_price": (
                order.take_profit_price
            ),
            "timestamp": utc_now(),
        }


class AlpacaExecutionAdapter:
    """
    Adaptador Alpaca.

    PAPER es el default.

    LIVE está bloqueado de forma absoluta en esta fase.
    No se permite habilitarlo mediante variables de entorno.

    Rocket Trader no envía SELL/SHORT.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> None:

        self.api_key = api_key
        self.api_secret = api_secret
        self.mode = mode

        if self.mode == ExecutionMode.LIVE:
            raise RuntimeError(
                "SAFETY STOP: LIVE está deshabilitado en esta fase. "
                "Rocket Trader solo permite Paper Trading hasta que exista "
                "una autorización independiente y un cambio revisado."
            )

        try:
            from alpaca.trading.client import (
                TradingClient,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Falta alpaca-py. "
                "Instala: pip install alpaca-py"
            ) from exc

        self.client = TradingClient(
            self.api_key,
            self.api_secret,
            paper=(
                self.mode
                == ExecutionMode.PAPER
            ),
        )

    def submit(
        self,
        order: ExecutionOrder,
    ) -> Dict[str, Any]:

        if order.mode != self.mode:
            raise RuntimeError(
                "El modo de la orden no coincide "
                "con el adaptador Alpaca."
            )

        if order.side != Side.BUY:
            raise RuntimeError(
                "Rocket Trader solo permite BUY/LONG."
            )

        if order.quantity <= 0:
            raise ValueError(
                "quantity debe ser > 0"
            )

        if not float(order.quantity).is_integer():
            raise RuntimeError(
                "Fractional MARKET_BRACKET orders are blocked until Alpaca "
                "fractional bracket compatibility and the full fractional "
                "exit lifecycle are independently verified."
            )

        if (
            order.stop_price is None
            or order.take_profit_price is None
        ):
            raise ValueError(
                "Toda entrada debe llevar "
                "stop y take profit."
            )

        from alpaca.trading.enums import (
            OrderClass,
            OrderSide,
            TimeInForce,
        )

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
            take_profit=TakeProfitRequest(
                limit_price=round(
                    order.take_profit_price,
                    2,
                )
            ),
            stop_loss=StopLossRequest(
                stop_price=round(
                    order.stop_price,
                    2,
                )
            ),
            client_order_id=(
                order.client_order_id
            ),
        )

        result = self.client.submit_order(
            order_data=request
        )

        return {
            "accepted": True,
            "mode": self.mode.value,
            "order_id": str(result.id),
            "client_order_id": (
                order.client_order_id
            ),
            "symbol": order.symbol,
            "status": str(result.status),
        }


# ============================================================================
# TRANSFERENCIAS
# ============================================================================

class MoneyTransferAdapter(Protocol):

    def transfer(
        self,
        amount: float,
        destination: str,
        reference: str,
    ) -> Dict[str, Any]:
        ...


class DisabledMoneyTransferAdapter:

    def transfer(
        self,
        amount: float,
        destination: str,
        reference: str,
    ) -> Dict[str, Any]:

        raise RuntimeError(
            "Transferencias automáticas reales "
            "están deshabilitadas en esta fase."
        )


# ============================================================================
# AUDITORÍA
# ============================================================================

class AuditLog:

    def __init__(
        self,
        path: str = (
            "data/rocket_trader_audit.jsonl"
        ),
    ) -> None:

        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def write(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:

        record = {
            "timestamp": utc_now(),
            "event_type": event_type,
            "payload": payload,
        }

        with self.path.open(
            "a",
            encoding="utf-8",
        ) as fh:
            fh.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )


# ============================================================================
# CORE
# ============================================================================

class RocketTraderCore:

    def __init__(
        self,
        risk_config: RiskConfig,
        benchmark_config: TraderBenchmarkConfig,

        distribution_config: Optional[
            ProfitDistributionConfig
        ] = None,

        benchmark_repository: Optional[
            BenchmarkRepository
        ] = None,

        execution_adapter: Optional[
            ExecutionAdapter
        ] = None,

        adaptive_overlay: Optional[
            AdaptiveRiskOverlay
        ] = None,

        audit_path: str = (
            "data/rocket_trader_audit.jsonl"
        ),
        capital_milestone_path: Optional[str] = None,
        require_persistent_milestone: bool = True,
        drawdown_guard_path: Optional[str] = None,
        require_persistent_drawdown_guard: bool = True,
        max_drawdown_pct: float = 0.15,
    ) -> None:

        self.require_persistent_milestone = bool(require_persistent_milestone)
        configured_milestone_path = (
            capital_milestone_path
            or os.getenv("ROCKET_TRADER_CAPITAL_MILESTONE_PATH")
        )
        if require_persistent_milestone and not configured_milestone_path:
            raise RuntimeError(
                "SAFETY STOP: RocketTraderCore requiere "
                "ROCKET_TRADER_CAPITAL_MILESTONE_PATH apuntando a almacenamiento "
                "durable para no perder el hito permanente de MXN 100,000."
            )

        self.risk_engine = RiskEngine(
            risk_config
        )

        self.benchmark_engine = BenchmarkEngine(
            benchmark_config,
            benchmark_repository
            or InMemoryBenchmarkRepository(),
        )

        self.adaptive_overlay = (
            adaptive_overlay
            or AdaptiveRiskOverlay()
        )

        self.decision_engine = DecisionEngine(
            risk_engine=self.risk_engine,
            benchmark_engine=self.benchmark_engine,
            adaptive_overlay=self.adaptive_overlay,
        )

        self.profit_allocator = ProfitAllocator(
            distribution_config or ProfitDistributionConfig(),
            milestone_path=configured_milestone_path,
        )

        self.execution_adapter = (
            execution_adapter
            or PaperExecutionAdapter()
        )

        self.audit = AuditLog(
            audit_path
        )

        self.drawdown_guard = None
        configured_drawdown_path = (
            drawdown_guard_path
            or os.getenv("ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH")
        )
        if require_persistent_drawdown_guard and not configured_drawdown_path:
            raise RuntimeError(
                "SAFETY STOP: RocketTraderCore requiere "
                "ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH apuntando a almacenamiento "
                "durable para persistir el high-water mark de estrategia en MXN."
            )
        if configured_drawdown_path:
            self.drawdown_guard = PersistentDrawdownGuard(
                state_path=configured_drawdown_path,
                max_drawdown_pct=max_drawdown_pct,
                equity_currency="MXN",
            )

    def evaluate_and_maybe_execute(
        self,
        account: AccountState,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        execute: bool = True,
        market_regime: str = "NEUTRAL",
        news_impact: str = "NONE",
    ) -> Decision:

        if self.drawdown_guard is not None:
            try:
                if (
                    account.strategy_equity_mxn is None
                    or account.strategy_daily_pnl_pct is None
                ):
                    decision = self.decision_engine.evaluate(
                        account=account,
                        snapshot=snapshot,
                        signal=signal,
                        market_regime=market_regime,
                        news_impact=news_impact,
                    )
                else:
                    drawdown = self.drawdown_guard.evaluate(account.strategy_equity_mxn)
                    if not drawdown.allowed:
                        decision = Decision(
                            decision_id=stable_id(
                                "drawdown_lock",
                                {
                                    "symbol": snapshot.symbol,
                                    "timestamp": snapshot.timestamp,
                                    "strategy_equity_mxn": account.strategy_equity_mxn,
                                },
                            ),
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
                            adaptive_multiplier=0.0,
                            adaptive_reason="Persistent max-drawdown lock.",
                            reason=(
                                f"persistent_drawdown_lock:{drawdown.reason}; "
                                f"drawdown_pct={drawdown.drawdown_pct:.6f}; "
                                f"limit_pct={drawdown.max_drawdown_pct:.6f}"
                            ),
                        )
                    else:
                        decision = self.decision_engine.evaluate(
                            account=account,
                            snapshot=snapshot,
                            signal=signal,
                            market_regime=market_regime,
                            news_impact=news_impact,
                        )
            except DrawdownGuardError as exc:
                decision = Decision(
                    decision_id=stable_id(
                        "drawdown_state_error",
                        {"symbol": snapshot.symbol, "timestamp": snapshot.timestamp},
                    ),
                    timestamp=utc_now(),
                    status=DecisionStatus.SAFE_MODE,
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
                    adaptive_multiplier=0.0,
                    adaptive_reason="Persistent drawdown state unavailable or invalid.",
                    reason=f"persistent_drawdown_state_error:{exc}",
                )
        else:
            decision = self.decision_engine.evaluate(
                account=account,
                snapshot=snapshot,
                signal=signal,
                market_regime=market_regime,
                news_impact=news_impact,
            )

        self.audit.write(
            "decision",
            dataclasses.asdict(decision),
        )

        if (
            execute
            and decision.quantity > 0
            and decision.status
            in {
                DecisionStatus.APPROVED,
                DecisionStatus.NOVEL_RISK,
            }
        ):

            order = ExecutionOrder(
                client_order_id=stable_id(
                    "order",
                    decision.decision_id,
                ),
                symbol=decision.symbol,
                side=decision.side,
                quantity=decision.quantity,
                order_type="MARKET_BRACKET",
                entry_price=decision.entry_price,
                stop_price=decision.stop_price,
                take_profit_price=(
                    decision.take_profit_price
                ),
                mode=ExecutionMode.PAPER,
            )

            result = self.execution_adapter.submit(
                order
            )

            self.audit.write(
                "execution",
                result,
            )

        return decision

    def monthly_distribution_plan(
        self,
        distributable_profit: float,
        operating_capital: float,
        period: Optional[str] = None,
        earned_growth_capital_mxn: Optional[float] = None,
    ) -> DistributionPlan:

        if self.require_persistent_milestone and earned_growth_capital_mxn is None:
            raise RuntimeError(
                "SAFETY STOP: monthly_distribution_plan requiere "
                "earned_growth_capital_mxn del ledger para excluir depósitos externos "
                "del hito de MXN 100,000."
            )

        plan = self.profit_allocator.plan(
            distributable_profit=(
                distributable_profit
            ),
            operating_capital=(
                operating_capital
            ),
            period=period,
            earned_growth_capital_mxn=earned_growth_capital_mxn,
        )

        self.audit.write(
            "distribution_plan",
            dataclasses.asdict(plan),
        )

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

    distribution_config = (
        ProfitDistributionConfig(
            threshold_mxn=100000.0,

            below_threshold_reserve_pct=0.00,
            below_threshold_reinvestment_pct=1.00,
            below_threshold_personal_pct=0.00,

            at_or_above_threshold_reserve_pct=0.10,
            at_or_above_threshold_reinvestment_pct=0.50,
            at_or_above_threshold_personal_pct=0.40,

            frequency="MONTHLY",
        )
    )

    return RocketTraderCore(
        risk_config=risk_config,
        benchmark_config=benchmark_config,
        distribution_config=distribution_config,
        benchmark_repository=(
            InMemoryBenchmarkRepository()
        ),
        execution_adapter=(
            PaperExecutionAdapter()
        ),
        adaptive_overlay=(
            AdaptiveRiskOverlay()
        ),
        audit_path=(
            "data/rocket_trader_audit.jsonl"
        ),
        require_persistent_milestone=False,
        require_persistent_drawdown_guard=False,
    )


# ============================================================================
# SELF TEST
# ============================================================================

def self_test() -> Dict[str, Any]:

    core = build_demo_core()

    # Production Core must refuse to start without durable milestone storage.
    production_milestone_guarded = False
    try:
        RocketTraderCore(
            risk_config=core.risk_engine.config,
            benchmark_config=core.benchmark_engine.config,
            require_persistent_milestone=True,
        )
    except RuntimeError as exc:
        production_milestone_guarded = (
            "ROCKET_TRADER_CAPITAL_MILESTONE_PATH" in str(exc)
        )
    assert production_milestone_guarded is True

    production_drawdown_guarded = False
    try:
        RocketTraderCore(
            risk_config=core.risk_engine.config,
            benchmark_config=core.benchmark_engine.config,
            require_persistent_milestone=False,
            require_persistent_drawdown_guard=True,
        )
    except RuntimeError as exc:
        production_drawdown_guarded = (
            "ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH" in str(exc)
        )
    assert production_drawdown_guarded is True

    account = AccountState(
        equity=1000.0,
        cash=1000.0,
        account_currency="USD",
        strategy_capital_mxn=1000.0,
        fx_quote=FXQuote(
            mxn_per_usd=Decimal("18.00"),
            observed_at=datetime.now(timezone.utc),
            source="OFFLINE_TEST_FIXTURE",
        ),
        strategy_equity_mxn=1000.0,
        strategy_daily_pnl_pct=0.0,
        protected_floor=0.0,
    )

    snapshot = MarketSnapshot(
        symbol="DEMO",
        timestamp=utc_now(),
        price=100.0,
        volume=1000.0,
        features={
            "signal_quality": 0.80,
        },
    )

    signal = StrategySignal(
        symbol="DEMO",
        side=Side.BUY,
        score=0.80,
        expected_return=0.03,
        confidence=0.80,
        rationale={
            "demo_signal": 1.0,
        },
        strategy_id="demo",
        setup_signature="NOVEL_SETUP_A",
    )

    # Novel setups must not bypass the minimum score/confidence gate.
    quality_gate_account = AccountState(
        equity=10000.0,
        cash=10000.0,
        account_currency="USD",
        strategy_capital_mxn=100000.0,
        fx_quote=FXQuote(
            mxn_per_usd=Decimal("18.00"),
            observed_at=datetime.now(timezone.utc),
            source="OFFLINE_TEST_FIXTURE",
        ),
        strategy_equity_mxn=100000.0,
        strategy_daily_pnl_pct=0.0,
    )
    low_score_signal = dataclasses.replace(signal, score=0.59)
    low_confidence_signal = dataclasses.replace(signal, confidence=0.59)
    for weak_signal in (low_score_signal, low_confidence_signal):
        weak_decision = core.decision_engine.evaluate(
            account=quality_gate_account,
            snapshot=snapshot,
            signal=weak_signal,
        )
        assert weak_decision.status == DecisionStatus.REJECTED
        assert weak_decision.quantity == 0.0
        assert weak_decision.evidence_class == EvidenceClass.INSUFFICIENT

    decision = (
        core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=True,
        )
    )

    # MXN 1,000 converts to less than USD 1 of allowed novel-risk notional;
    # the broker minimum therefore blocks the order rather than rounding up.
    assert decision.status == DecisionStatus.REJECTED

    assert decision.evidence_class == (
        EvidenceClass.NOVEL
    )

    assert decision.quantity == 0.0
    assert decision.stop_price is None
    assert decision.take_profit_price is None

    # A larger explicit MXN ledger can pass the USD minimum-order gate.
    larger_account = AccountState(
        equity=1000.0,
        cash=1000.0,
        account_currency="USD",
        strategy_capital_mxn=6000.0,
        fx_quote=FXQuote(
            mxn_per_usd=Decimal("18.00"),
            observed_at=datetime.now(timezone.utc),
            source="OFFLINE_TEST_FIXTURE",
        ),
        strategy_equity_mxn=6000.0,
        strategy_daily_pnl_pct=0.0,
    )
    larger_budget_decision = core.evaluate_and_maybe_execute(
        account=larger_account,
        snapshot=snapshot,
        signal=signal,
        execute=False,
    )
    assert larger_budget_decision.status == DecisionStatus.NOVEL_RISK
    assert larger_budget_decision.quantity * snapshot.price >= 1.0
    assert larger_budget_decision.quantity * snapshot.price <= (6000.0 / 18.0) * 0.01 * larger_budget_decision.adaptive_multiplier * 0.80 + 1e-9

    # Missing FX must fail closed even if the broker reports abundant Paper cash.
    missing_fx_account = AccountState(
        equity=1000.0,
        cash=1000.0,
        strategy_capital_mxn=6000.0,
    )
    missing_fx_decision = core.evaluate_and_maybe_execute(
        account=missing_fx_account,
        snapshot=snapshot,
        signal=signal,
        execute=False,
    )
    assert missing_fx_decision.status == DecisionStatus.KILL_SWITCH
    assert missing_fx_decision.quantity == 0.0
    assert missing_fx_decision.reason == "strategy_risk_metrics_missing"

    # Strategy daily-loss protection must use the MXN allocation metrics,
    # not the much larger virtual Paper account's USD equity denominator.
    strategy_daily_loss_account = dataclasses.replace(
        account, strategy_daily_pnl_pct=-0.06
    )
    strategy_daily_loss_decision = core.decision_engine.evaluate(
        account=strategy_daily_loss_account,
        snapshot=snapshot,
        signal=signal,
    )
    assert strategy_daily_loss_decision.status == DecisionStatus.KILL_SWITCH
    assert strategy_daily_loss_decision.reason == "strategy_daily_loss_limit"

    # Non-finite account and strategy risk inputs must be rejected at the boundary.
    invalid_account_inputs_rejected = True
    for invalid_kwargs in (
        {"equity": float("nan")},
        {"strategy_capital_mxn": float("nan")},
        {"strategy_equity_mxn": float("nan")},
        {"strategy_daily_pnl_pct": float("nan")},
    ):
        values = {
            "equity": 1000.0,
            "cash": 1000.0,
            "strategy_capital_mxn": 1000.0,
            "strategy_equity_mxn": 1000.0,
            "strategy_daily_pnl_pct": 0.0,
        }
        values.update(invalid_kwargs)
        try:
            AccountState(**values)
        except (TypeError, ValueError):
            continue
        invalid_account_inputs_rejected = False
        break
    assert invalid_account_inputs_rejected is True

    # The legacy Core Alpaca adapter must also block fractional equity brackets.
    fractional_adapter = object.__new__(AlpacaExecutionAdapter)
    fractional_adapter.mode = ExecutionMode.PAPER
    fractional_order_blocked = False
    try:
        fractional_adapter.submit(
            ExecutionOrder(
                client_order_id="fractional_core_guard_test",
                symbol="SPY",
                side=Side.BUY,
                quantity=0.5,
                order_type="MARKET_BRACKET",
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=104.0,
                mode=ExecutionMode.PAPER,
            )
        )
    except RuntimeError as exc:
        fractional_order_blocked = "Fractional MARKET_BRACKET" in str(exc)
    assert fractional_order_blocked is True

    # ------------------------------------------------
    # CAPITAL POLICY < 100K
    # ------------------------------------------------

    plan_accumulation = (
        core.monthly_distribution_plan(
            distributable_profit=1000.0,
            operating_capital=50000.0,
            period="2026-09",
        )
    )

    assert (
        plan_accumulation.reserve_amount
        == 0.0
    )

    assert (
        plan_accumulation.reinvestment_amount
        == 1000.0
    )

    assert (
        plan_accumulation.personal_amount
        == 0.0
    )

    assert (
        plan_accumulation.capital_policy
        == "ACCUMULATION_BELOW_100K"
    )

    # ------------------------------------------------
    # CAPITAL POLICY >= 100K
    # ------------------------------------------------

    plan_distribution = (
        core.monthly_distribution_plan(
            distributable_profit=1000.0,
            operating_capital=101000.0,
            period="2026-09",
        )
    )

    assert (
        plan_distribution.reserve_amount
        == 100.0
    )

    assert (
        plan_distribution.reinvestment_amount
        == 500.0
    )

    assert (
        plan_distribution.personal_amount
        == 400.0
    )

    assert (
        plan_distribution.capital_policy
        == "DISTRIBUTION_THRESHOLD_PERMANENTLY_REACHED"
    )
    assert plan_distribution.threshold_reached is True
    assert plan_distribution.payouts_suspended is False
    assert plan_distribution.target_reinvestment_pct == 0.50
    assert plan_distribution.target_reserve_pct == 0.10
    assert plan_distribution.target_personal_pct == 0.40
    assert plan_distribution.operating_capital_after_distribution == 100500.0

    floor_hold = core.monthly_distribution_plan(
        distributable_profit=1000.0,
        operating_capital=100000.0,
        period="2026-10",
    )
    assert floor_hold.threshold_reached is True
    assert floor_hold.payouts_suspended is True
    assert floor_hold.reinvestment_pct == 1.0
    assert floor_hold.reserve_pct == 0.0
    assert floor_hold.personal_pct == 0.0
    assert floor_hold.target_reinvestment_pct == 0.50
    assert floor_hold.target_reserve_pct == 0.10
    assert floor_hold.target_personal_pct == 0.40
    assert floor_hold.operating_capital_after_distribution == 100000.0

    with tempfile.TemporaryDirectory() as temp_dir:
        milestone_file = str(Path(temp_dir) / "capital_milestone.json")
        persistent_allocator = ProfitAllocator(
            ProfitDistributionConfig(), milestone_path=milestone_file
        )
        first_hit = persistent_allocator.plan(1000.0, 100000.0, "2026-11")
        assert first_hit.threshold_reached is True
        assert first_hit.payouts_suspended is True
        after_drawdown = persistent_allocator.plan(1000.0, 70000.0, "2026-12")
        assert after_drawdown.payouts_suspended is True
        assert after_drawdown.reinvestment_pct == 1.0
        assert after_drawdown.target_reinvestment_pct == 0.50
        assert after_drawdown.target_personal_pct == 0.40
        assert after_drawdown.target_reserve_pct == 0.10
        restarted_allocator = ProfitAllocator(
            ProfitDistributionConfig(), milestone_path=milestone_file
        )
        after_restart = restarted_allocator.plan(1000.0, 70000.0, "2027-01")
        assert after_restart.threshold_reached is True
        assert after_restart.payouts_suspended is True
        assert after_restart.target_reinvestment_pct == 0.50
        assert after_restart.target_personal_pct == 0.40

    # ------------------------------------------------
    # KILL SWITCH FLOOR
    # ------------------------------------------------

    floor_account = AccountState(
        equity=500.0,
        cash=500.0,
        protected_floor=500.0,
    )

    floor_decision = (
        core.evaluate_and_maybe_execute(
            account=floor_account,
            snapshot=snapshot,
            signal=signal,
            execute=False,
        )
    )

    assert (
        floor_decision.status
        == DecisionStatus.KILL_SWITCH
    )

    # ------------------------------------------------
    # PERSISTENT MAX DRAWDOWN GUARD
    # ------------------------------------------------
    with tempfile.TemporaryDirectory() as drawdown_temp:
        core.drawdown_guard = PersistentDrawdownGuard(
            str(Path(drawdown_temp) / "drawdown.json"),
            max_drawdown_pct=0.10,
            equity_currency="MXN",
        )
        core.drawdown_guard.evaluate(account.strategy_equity_mxn)
        drawdown_account = dataclasses.replace(
            account,
            strategy_equity_mxn=account.strategy_equity_mxn * 0.89,
            strategy_daily_pnl_pct=0.0,
        )
        drawdown_decision = core.evaluate_and_maybe_execute(
            account=drawdown_account,
            snapshot=snapshot,
            signal=signal,
            execute=True,
        )
        assert drawdown_decision.status == DecisionStatus.KILL_SWITCH
        assert drawdown_decision.quantity == 0.0
        restarted_guard = PersistentDrawdownGuard(
            str(Path(drawdown_temp) / "drawdown.json"),
            max_drawdown_pct=0.10,
            equity_currency="MXN",
        )
        assert restarted_guard.evaluate(account.strategy_equity_mxn * 1.20).locked is True

    # ------------------------------------------------
    # ADAPTIVE BLOCK
    # ------------------------------------------------

    risk_off_decision = (
        core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=False,
            market_regime="RISK_OFF",
            news_impact="NONE",
        )
    )

    assert (
        risk_off_decision.status
        == DecisionStatus.SAFE_MODE
    )

    # ------------------------------------------------
    # NEWS BLOCK
    # ------------------------------------------------

    news_block_decision = (
        core.evaluate_and_maybe_execute(
            account=account,
            snapshot=snapshot,
            signal=signal,
            execute=False,
            market_regime="NEUTRAL",
            news_impact="URGENT_NEGATIVE",
        )
    )

    assert (
        news_block_decision.status
        == DecisionStatus.SAFE_MODE
    )

    return {
        "ok": True,

        "decision": {
            "status": decision.status.value,
            "evidence_class": (
                decision.evidence_class.value
            ),
            "quantity": decision.quantity,
            "stop_price": decision.stop_price,
            "take_profit_price": (
                decision.take_profit_price
            ),
            "adaptive_multiplier": (
                decision.adaptive_multiplier
            ),
        },

        "capital_policy_below_100k": {
            "reserve": (
                plan_accumulation.reserve_amount
            ),
            "reinvestment": (
                plan_accumulation.reinvestment_amount
            ),
            "personal": (
                plan_accumulation.personal_amount
            ),
        },

        "capital_policy_at_100k": {
            "reserve": (
                plan_distribution.reserve_amount
            ),
            "reinvestment": (
                plan_distribution.reinvestment_amount
            ),
            "personal": (
                plan_distribution.personal_amount
            ),
        },

        "floor_kill_switch": (
            floor_decision.status.value
        ),

        "risk_off_lock": (
            risk_off_decision.status.value
        ),

        "negative_news_lock": (
            news_block_decision.status.value
        ),
    }


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:

    result = self_test()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()