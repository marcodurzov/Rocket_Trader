#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rocket Trader — Adaptive Risk & Capital Policy v0.1

Capa independiente para:

- Capitalización 100/0/0 antes del primer hito de 100,000 MXN.
- Regla de distribución 50/40/10 después de alcanzar el hito.
- El motor Core es la fuente de verdad persistente del hito.
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

import enumfrom dataclasses import dataclass
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


# Capital allocation is owned exclusively by ProfitAllocator in rocket_trader_core.


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
    Fail-closed placeholder.

    Article ingestion is implemented separately in rocket_trader_news.py.
    Until a point-in-time NLP/scoring model is validated, this engine must not
    infer sentiment from keyword counts or influence trading risk.
    """

    def assess(
        self,
        symbol: str,
        headline: str,
        summary: str = "",
    ) -> NewsAssessment:
        # Keep the interface stable, but do not turn words in a headline into
        # an actionable positive/negative signal.
        return NewsAssessment(
            symbol=str(symbol).strip().upper(),
            impact=NewsImpact.UNKNOWN,
            score=0.0,
            confidence=0.0,
            urgency=0.0,
            matched_terms=(),
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
    # CANONICAL PERSISTENT CAPITAL POLICY (CORE)
    # ----------------------------------------------------------------------

    # Adaptive must not implement a second, in-memory capital policy.
    # Exercise the Core allocator here so the Integration Gate validates the
    # same durable milestone implementation used by the system.
    from tempfile import TemporaryDirectory
    from rocket_trader_core import ProfitAllocator

    with TemporaryDirectory() as temp_dir:
        milestone_path = f"{temp_dir}/capital-milestone.json"
        policy = ProfitAllocator(milestone_path=milestone_path)

        below = policy.plan(
            distributable_profit=10_000,
            operating_capital=50_000,
        )
        assert below.reinvestment_pct == 1.0
        assert below.personal_pct == 0.0
        assert below.reserve_pct == 0.0
        assert below.reinvestment_amount == 10_000
        assert below.personal_amount == 0
        assert below.reserve_amount == 0

        above = policy.plan(
            distributable_profit=10_000,
            operating_capital=120_000,
        )
        assert above.threshold_reached is True
        assert above.reinvestment_pct == 0.50
        assert above.personal_pct == 0.40
        assert above.reserve_pct == 0.10
        assert above.reinvestment_amount == 5_000
        assert above.personal_amount == 4_000
        assert above.reserve_amount == 1_000

        # Reconstruct the allocator to prove the milestone survives restart.
        restarted_policy = ProfitAllocator(milestone_path=milestone_path)
        after_drawdown = restarted_policy.plan(
            distributable_profit=10_000,
            operating_capital=70_000,
        )
        assert after_drawdown.threshold_reached is True
        assert after_drawdown.target_reinvestment_pct == 0.50
        assert after_drawdown.target_personal_pct == 0.40
        assert after_drawdown.target_reserve_pct == 0.10
        assert after_drawdown.payouts_suspended is True
        assert after_drawdown.reinvestment_pct == 1.0
        assert after_drawdown.personal_pct == 0.0
        assert after_drawdown.reserve_pct == 0.0

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
        "capital_policy": "delegated_to_core_persistent_profit_allocator",
        "news_engine": "heuristic_paper_only",
        "adaptive_risk": "passed",
    }


if __name__ == "__main__":
    print(self_test())
