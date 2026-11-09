#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rocket_trader_adaptive import (
    CapitalPolicy,
    NewsEngine,
    NewsAssessment,
    NewsImpact,
    MarketRegimeEngine,
    AdaptiveRiskEngine,
)


def main() -> None:

    policy = CapitalPolicy()

    # Antes de 100k: 100% de utilidades netas realizadas se reinvierte.
    test_1 = policy.allocation(
        operating_capital=50_000,
        profit=10_000,
    )

    assert test_1.reinvestment_amount == 10_000
    assert test_1.personal_amount == 0
    assert test_1.reserve_amount == 0
    assert test_1.reinvestment_pct == 1.0
    assert test_1.threshold_reached is False

    # En 100k: cambia automáticamente a 50/40/10
    test_2 = policy.allocation(
        operating_capital=100_000,
        profit=10_000,
    )

    assert test_2.reinvestment_amount == 5_000
    assert test_2.personal_amount == 4_000
    assert test_2.reserve_amount == 1_000

    # Noticia positiva
    news = NewsEngine().assess(
        "AAPL",
        "Company beats earnings estimates and raises guidance",
    )

    assert news.impact == NewsImpact.UNKNOWN
    assert news.score == 0.0
    assert news.confidence == 0.0
    assert news.urgency == 0.0
    assert news.matched_terms == ()

    # Régimen alcista
    regime = MarketRegimeEngine().assess(
        trend=0.70,
        volatility=0.25,
        breadth=0.30,
    )

    assert regime.regime.value == "TRENDING_UP"

    # Alta convicción
    risk = AdaptiveRiskEngine().decide(
        signal_score=0.90,
        signal_confidence=0.90,
        evidence_score=0.85,
        regime=regime,
        news=news,
    )

    assert risk.allowed
    assert risk.max_position_pct > 0.25

    # Sin un modelo de noticias validado, la noticia no puede aumentar el riesgo.
    risk_without_news = AdaptiveRiskEngine().decide(
        signal_score=0.90,
        signal_confidence=0.90,
        evidence_score=0.85,
        regime=regime,
        news=None,
    )
    assert risk.max_position_pct == risk_without_news.max_position_pct
    assert risk.risk_multiplier == risk_without_news.risk_multiplier

    # El control de riesgo sigue bloqueando una evaluación negativa validada.
    negative_news = NewsAssessment(
        symbol="AAPL",
        impact=NewsImpact.NEGATIVE,
        score=-1.0,
        confidence=1.0,
        urgency=1.0,
        matched_terms=("validated_test_event",),
    )

    blocked = AdaptiveRiskEngine().decide(
        signal_score=0.95,
        signal_confidence=0.95,
        evidence_score=0.90,
        regime=regime,
        news=negative_news,
    )

    assert not blocked.allowed

    print("ROCKET TRADER ADAPTIVE TEST: PASS")
    print("Capital policy: PASS")
    print("News engine: PASS")
    print("Market regime: PASS")
    print("Adaptive risk: PASS")
    print("Negative news lock: PASS")


if __name__ == "__main__":
    main()
