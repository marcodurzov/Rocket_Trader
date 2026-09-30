#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Adaptive Risk & Capital Policy v0.1

Capa independiente para:

- Regla automática de capitalización hasta 100,000 MXN.
- Distribución mensual 70/20/10 después del umbral.
- Clasificación básica de régimen de mercado.
- Evaluación inicial de noticias.
- Sizing dinámico condicionado por convicción.

IMPORTANTE:

Esta capa NO ejecuta órdenes.

No utiliza:
- margen
- apalancamiento
- short
- futuros
- perpetuos
- dinero prestado

La ejecución seguirá siendo responsabilidad de RocketTraderCore.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# ENUMS
# ============================================================================


class MarketRegime(str, enum.Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


class NewsImpact(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


# ============================================================================
# CAPITAL POLICY
# ============================================================================


@dataclass(frozen=True)
class CapitalAllocation:
    operating_capital: float
    profit: float
    threshold: float

    reserve_pct: float
    reinvestment_pct: float
    personal_pct: float

    reserve_amount: float
    reinvestment_amount: float
    personal_amount: float

    threshold_reached: bool


@dataclass(frozen=True)
class CapitalPolicyConfig:
    threshold_mxn: float = 100_000.0

    # Antes de llegar a 100,000 MXN
    below_threshold_reinvestment_pct: float = 1.00
    below_threshold_personal_pct: float = 0.00
    below_threshold_reserve_pct: float = 0.00

    # Desde 100,000 MXN
    above_threshold_reinvestment_pct: float = 0.70
    above_threshold_personal_pct: float = 0.20
    above_threshold_reserve_pct: float = 0.10

    def validate(self) -> None:
        if self.threshold_mxn <= 0:
            raise ValueError("threshold_mxn debe ser > 0")

        values = (
            self.below_threshold_reinvestment_pct,
            self.below_threshold_personal_pct,
            self.below_threshold_reserve_pct,
            self.above_threshold_reinvestment_pct,
            self.above_threshold_personal_pct,
            self.above_threshold_reserve_pct,
        )

        if any(value < 0 or value > 1 for value in values):
            raise ValueError("Los porcentajes deben estar entre 0 y 1")

        if not math.isclose(
            self.below_threshold_reinvestment_pct
            + self.below_threshold_personal_pct
            + self.below_threshold_reserve_pct,
            1.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "La distribución debajo de 100,000 MXN debe sumar 100%"
            )

        if not math.isclose(
            self.above_threshold_reinvestment_pct
            + self.above_threshold_personal_pct
            + self.above_threshold_reserve_pct,
            1.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "La distribución desde 100,000 MXN debe sumar 100%"
            )


class CapitalPolicy:
    """
    Regla automática de crecimiento del capital.

    < 100,000 MXN:
        100% reinversión
        0% personal
        0% reserva

    >= 100,000 MXN:
        70% reinversión
        20% personal
        10% reserva
    """

    def __init__(
        self,
        config: Optional[CapitalPolicyConfig] = None,
    ) -> None:

        self.config = config or CapitalPolicyConfig()
        self.config.validate()

    def allocation(
        self,
        operating_capital: float,
        profit: float,
    ) -> CapitalAllocation:

        if operating_capital < 0:
            raise ValueError(
                "operating_capital no puede ser negativo"
            )

        if profit < 0:
            raise ValueError(
                "profit no puede ser negativo"
            )

        threshold_reached = (
            operating_capital >= self.config.threshold_mxn
        )

        if threshold_reached:

            reserve_pct = (
                self.config.above_threshold_reserve_pct
            )

            reinvestment_pct = (
                self.config.above_threshold_reinvestment_pct
            )

            personal_pct = (
                self.config.above_threshold_personal_pct
            )

        else:

            reserve_pct = (
                self.config.below_threshold_reserve_pct
            )

            reinvestment_pct = (
                self.config.below_threshold_reinvestment_pct
            )

            personal_pct = (
                self.config.below_threshold_personal_pct
            )

        reserve = round(
            profit * reserve_pct,
            2,
        )

        reinvestment = round(
            profit * reinvestment_pct,
            2,
        )

        personal = round(
            profit - reserve - reinvestment,
            2,
        )

        return CapitalAllocation(
            operating_capital=operating_capital,
            profit=profit,
            threshold=self.config.threshold_mxn,
            reserve_pct=reserve_pct,
            reinvestment_pct=reinvestment_pct,
            personal_pct=personal_pct,
            reserve_amount=reserve,
            reinvestment_amount=reinvestment,
            personal_amount=personal,
            threshold_reached=threshold_reached,
        )


# ============================================================================
# MARKET REGIME
# ============================================================================


@dataclass(frozen=True)
class RegimeAssessment:
    regime: MarketRegime
    score: float
    volatility: float
    trend: float
    breadth: float


class MarketRegimeEngine:
    """
    Clasificador inicial y determinista.

    Posteriormente será reemplazado/complementado por modelos
    estadísticos entrenados con datos históricos.
    """

    def assess(
        self,
        *,
        trend: float,
        volatility: float,
        breadth: float = 0.0,
    ) -> RegimeAssessment:

        trend = max(-1.0, min(1.0, trend))
        volatility = max(0.0, min(1.0, volatility))
        breadth = max(-1.0, min(1.0, breadth))

        if volatility >= 0.80:

            if trend < 0:
                regime = MarketRegime.RISK_OFF
            else:
                regime = MarketRegime.HIGH_VOLATILITY

        elif trend >= 0.45 and breadth >= -0.20:

            regime = MarketRegime.TRENDING_UP

        elif trend <= -0.45:

            regime = MarketRegime.TRENDING_DOWN

        else:

            regime = MarketRegime.RANGE

        score = max(
            0.0,
            min(
                1.0,
                0.50
                + 0.30 * trend
                + 0.20 * breadth,
            ),
        )

        return RegimeAssessment(
            regime=regime,
            score=score,
            volatility=volatility,
            trend=trend,
            breadth=breadth,
        )


# ============================================================================
# NEWS
# ============================================================================


@dataclass(frozen=True)
class NewsAssessment:
    symbol: str
    impact: NewsImpact
    score: float
    confidence: float
    urgency: float
    matched_terms: tuple[str, ...]


class NewsEngine:
    """
    Motor heurístico inicial para PAPER.

    No pretende ser un modelo definitivo de sentimiento.

    Su función inicial es transformar noticias en una señal
    cuantificable, auditable y reproducible.
    """

    POSITIVE_TERMS = {
        "beat",
        "beats",
        "surge",
        "upgrade",
        "raises guidance",
        "raised guidance",
        "strong demand",
        "record revenue",
        "profit",
        "profits",
        "approval",
        "partnership",
        "buyback",
        "positive outlook",
        "contract win",
    }

    NEGATIVE_TERMS = {
        "miss",
        "misses",
        "downgrade",
        "cuts guidance",
        "cut guidance",
        "weak demand",
        "layoffs",
        "lawsuit",
        "investigation",
        "recall",
        "bankruptcy",
        "fraud",
        "warning",
        "negative outlook",
        "loss",
        "losses",
        "default",
        "regulatory action",
    }

    HIGH_URGENCY_TERMS = {
        "halt",
        "bankruptcy",
        "fraud",
        "recall",
        "investigation",
        "approval",
        "earnings",
        "guidance",
        "merger",
        "acquisition",
    }

    def assess(
        self,
        symbol: str,
        headline: str,
        summary: str = "",
    ) -> NewsAssessment:

        text = (
            f"{headline} {summary}"
        ).lower()

        positive = [
            term
            for term in self.POSITIVE_TERMS
            if term in text
        ]

        negative = [
            term
            for term in self.NEGATIVE_TERMS
            if term in text
        ]

        urgent = [
            term
            for term in self.HIGH_URGENCY_TERMS
            if term in text
        ]

        raw = len(positive) - len(negative)

        if raw > 0:
            impact = NewsImpact.POSITIVE

        elif raw < 0:
            impact = NewsImpact.NEGATIVE

        else:
            impact = NewsImpact.NEUTRAL

        matched = tuple(
            positive
            + negative
            + urgent
        )

        confidence = min(
            1.0,
            0.35
            + 0.10 * len(matched),
        )

        score = max(
            -1.0,
            min(
                1.0,
                raw / 3.0,
            ),
        )

        urgency = min(
            1.0,
            0.25
            + 0.20 * len(urgent),
        )

        return NewsAssessment(
            symbol=symbol,
            impact=impact,
            score=score,
            confidence=confidence,
            urgency=urgency,
            matched_terms=matched,
        )


# ============================================================================
# ADAPTIVE RISK
# ============================================================================


@dataclass(frozen=True)
class AdaptiveRiskDecision:
    allowed: bool
    risk_multiplier: float
    max_position_pct: float
    reason: str


class AdaptiveRiskEngine:
    """
    Agresividad condicionada por evidencia.

    Límites absolutos:

    - LONG ONLY
    - CASH ONLY
    - sin margen
    - sin apalancamiento
    - sin short
    - exposición total limitada
    - límite de pérdida diaria
    """

    def __init__(
        self,
        *,
        base_max_position_pct: float = 0.25,
        aggressive_max_position_pct: float = 0.30,
        max_total_exposure_pct: float = 0.80,
        daily_loss_limit_pct: float = 0.05,
    ) -> None:

        if not (
            0
            < base_max_position_pct
            <= aggressive_max_position_pct
            <= 1
        ):
            raise ValueError(
                "Límites de posición inválidos"
            )

        if not (
            0
            < max_total_exposure_pct
            <= 1
        ):
            raise ValueError(
                "max_total_exposure_pct inválido"
            )

        if not (
            0
            < daily_loss_limit_pct
            < 1
        ):
            raise ValueError(
                "daily_loss_limit_pct inválido"
            )

        self.base_max_position_pct = (
            base_max_position_pct
        )

        self.aggressive_max_position_pct = (
            aggressive_max_position_pct
        )

        self.max_total_exposure_pct = (
            max_total_exposure_pct
        )

        self.daily_loss_limit_pct = (
            daily_loss_limit_pct
        )

    def decide(
        self,
        *,
        signal_score: float,
        signal_confidence: float,
        regime: RegimeAssessment,
        news: Optional[NewsAssessment] = None,
        evidence_score: float = 0.0,
        daily_pnl_pct: float = 0.0,
    ) -> AdaptiveRiskDecision:

        signal_score = max(
            0.0,
            min(1.0, signal_score),
        )

        signal_confidence = max(
            0.0,
            min(1.0, signal_confidence),
        )

        evidence_score = max(
            0.0,
            min(1.0, evidence_score),
        )

        # ================================================================
        # HARD LOCKS
        # ================================================================

        if (
            daily_pnl_pct
            <= -self.daily_loss_limit_pct
        ):
            return AdaptiveRiskDecision(
                allowed=False,
                risk_multiplier=0.0,
                max_position_pct=0.0,
                reason="daily_loss_limit",
            )

        if regime.regime in {
            MarketRegime.RISK_OFF,
            MarketRegime.TRENDING_DOWN,
        }:
            return AdaptiveRiskDecision(
                allowed=False,
                risk_multiplier=0.0,
                max_position_pct=0.0,
                reason=(
                    "regime_"
                    + regime.regime.value.lower()
                ),
            )

        if (
            news
            and news.impact == NewsImpact.NEGATIVE
            and news.urgency >= 0.65
        ):
            return AdaptiveRiskDecision(
                allowed=False,
                risk_multiplier=0.0,
                max_position_pct=0.0,
                reason="urgent_negative_news",
            )

        # ================================================================
        # CONVICTION
        # ================================================================

        conviction = (
            0.45 * signal_score
            + 0.30 * signal_confidence
            + 0.25 * evidence_score
        )

        if news:
            conviction += (
                0.10
                * news.score
                * news.confidence
            )

        conviction = max(
            0.0,
            min(1.0, conviction),
        )

        if conviction < 0.60:
            return AdaptiveRiskDecision(
                allowed=False,
                risk_multiplier=conviction,
                max_position_pct=0.0,
                reason=(
                    "insufficient_conviction"
                ),
            )

        # ================================================================
        # DYNAMIC RISK
        # ================================================================

        if (
            regime.regime
            == MarketRegime.HIGH_VOLATILITY
        ):
            multiplier = 0.60

        elif (
            regime.regime
            == MarketRegime.TRENDING_UP
            and conviction >= 0.80
        ):
            multiplier = 1.20

        else:
            multiplier = 0.90

        if (
            news
            and news.impact
            == NewsImpact.POSITIVE
            and news.confidence >= 0.60
        ):
            multiplier *= 1.05

        multiplier = min(
            1.20,
            max(0.0, multiplier),
        )

        max_position = min(
            self.aggressive_max_position_pct,
            self.base_max_position_pct
            * multiplier,
        )

        return AdaptiveRiskDecision(
            allowed=True,
            risk_multiplier=multiplier,
            max_position_pct=max_position,
            reason=(
                f"conviction={conviction:.3f};"
                f"regime={regime.regime.value}"
            ),
        )


# ============================================================================
# SELF TEST
# ============================================================================


def self_test() -> dict:

    # ----------------------------------------------------------------------
    # CAPITAL POLICY
    # ----------------------------------------------------------------------

    policy = CapitalPolicy()

    below = policy.allocation(
        operating_capital=50_000,
        profit=10_000,
    )

    assert below.reinvestment_pct == 1.00
    assert below.personal_pct == 0.00
    assert below.reserve_pct == 0.00

    assert below.reinvestment_amount == 10_000
    assert below.personal_amount == 0
    assert below.reserve_amount == 0

    above = policy.allocation(
        operating_capital=100_000,
        profit=10_000,
    )

    assert above.reinvestment_pct == 0.70
    assert above.personal_pct == 0.20
    assert above.reserve_pct == 0.10

    assert above.reinvestment_amount == 7_000
    assert above.personal_amount == 2_000
    assert above.reserve_amount == 1_000

    # ----------------------------------------------------------------------
    # NEWS
    # ----------------------------------------------------------------------

    news = NewsEngine().assess(
        symbol="AAPL",
        headline=(
            "Company beats earnings estimates "
            "and raises guidance"
        ),
    )

    assert news.impact == NewsImpact.POSITIVE

    # ----------------------------------------------------------------------
    # REGIME
    # ----------------------------------------------------------------------

    regime = MarketRegimeEngine().assess(
        trend=0.70,
        volatility=0.25,
        breadth=0.30,
    )

    assert (
        regime.regime
        == MarketRegime.TRENDING_UP
    )

    # ----------------------------------------------------------------------
    # ADAPTIVE RISK
    # ----------------------------------------------------------------------

    risk = AdaptiveRiskEngine().decide(
        signal_score=0.90,
        signal_confidence=0.90,
        evidence_score=0.85,
        regime=regime,
        news=news,
    )

    assert risk.allowed
    assert risk.max_position_pct > 0.25

    # ----------------------------------------------------------------------
    # NEGATIVE NEWS LOCK
    # ----------------------------------------------------------------------

    negative_news = NewsAssessment(
        symbol="AAPL",
        impact=NewsImpact.NEGATIVE,
        score=-1.0,
        confidence=1.0,
        urgency=1.0,
        matched_terms=("fraud",),
    )

    blocked = AdaptiveRiskEngine().decide(
        signal_score=0.95,
        signal_confidence=0.95,
        evidence_score=0.90,
        regime=regime,
        news=negative_news,
    )

    assert not blocked.allowed

    return {
        "ok": True,
        "capital_policy": (
            "100% reinvestment below "
            "100,000 MXN; 70/20/10 at or above"
        ),
        "news_engine": "heuristic_paper_only",
        "adaptive_risk": "passed",
    }


if __name__ == "__main__":
    print(self_test())
