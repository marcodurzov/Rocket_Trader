#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rocket_trader_adaptive import (
    CapitalPolicy,
    NewsEngine,
    MarketRegimeEngine,
    AdaptiveRiskEngine,
)


def main() -> None:

    policy = CapitalPolicy()

    # Debajo de 100k: 100% reinversión
    test_1 = policy.allocation(
        operating_capital=50_000,
        profit=10_000,
    )

    assert test_1.reinvestment_amount == 10_000
    assert test_1.personal_amount == 0
    assert test_1.reserve_amount == 0

    # En 100k: cambia automáticamente a 70/20/10
    test_2 = policy.allocation(
        operating_capital=100_000,
        profit=10_000,
    )

    assert test_2.reinvestment_amount == 7_000
    assert test_2.personal_amount == 2_000
    assert test_2.reserve_amount == 1_000

    # Noticia positiva
    news = NewsEngine().assess(
        "AAPL",
        "Company beats earnings estimates and raises guidance",
    )

    assert news.impact.value == "POSITIVE"

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

    # Noticia negativa urgente debe bloquear
    negative_news = NewsEngine().assess(
        "AAPL",
        "Company under fraud investigation",
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
