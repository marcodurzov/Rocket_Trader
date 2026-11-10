#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regime-aware portfolio selector with fail-closed news context.

This module is deliberately deterministic and dependency-free. It does not
infer sentiment from raw headlines. News assessments must come from a trusted,
versioned evaluator and be point-in-time eligible before they can affect risk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def _unit(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


class RegimeLabel(str, Enum):
    UNKNOWN = "UNKNOWN"
    STRONG_TREND = "STRONG_TREND"
    WEAK_TREND = "WEAK_TREND"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    STRESS = "STRESS"


class NewsSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketState:
    """Normalized market features, each in [0, 1].

    trend_strength: directional persistence, not direction.
    trend_direction: -1 (down) to +1 (up).
    volatility_percentile: current realized volatility percentile.
    breadth: fraction of tracked assets above their trend filter.
    correlation: average cross-asset correlation.
    stress: composite stress indicator (liquidity/credit/volatility).
    data_quality: completeness and freshness score.
    """
    trend_strength: float
    trend_direction: float
    volatility_percentile: float
    breadth: float
    correlation: float
    stress: float
    data_quality: float
    timestamp: str

    def __post_init__(self) -> None:
        for name in ("trend_strength", "volatility_percentile", "breadth",
                     "correlation", "stress", "data_quality"):
            _unit(name, getattr(self, name))
        if not isfinite(float(self.trend_direction)) or not -1 <= self.trend_direction <= 1:
            raise ValueError("trend_direction must be between -1 and 1")
        if not self.timestamp:
            raise ValueError("timestamp is required")


@dataclass(frozen=True)
class RegimeAssessment:
    label: RegimeLabel
    risk_on: float
    risk_off: float
    trend: float
    range_bound: float
    volatility: float
    uncertainty: float
    exposure_cap: float
    rationale: Tuple[str, ...]


class RegimeClassifier:
    """Continuous multi-axis regime assessment; labels are descriptive only."""

    def assess(self, state: MarketState) -> RegimeAssessment:
        if state.data_quality < 0.80:
            return RegimeAssessment(
                RegimeLabel.UNKNOWN, 0.0, 0.0, 0.0, 0.0,
                state.volatility_percentile, 1.0, 0.0,
                ("Market data quality below 0.80; fail closed to cash.",),
            )
        trend = state.trend_strength
        direction_support = (state.trend_direction + 1.0) / 2.0
        breadth_support = state.breadth
        stress = state.stress
        vol = state.volatility_percentile
        risk_off = min(1.0, 0.45 * stress + 0.30 * vol + 0.15 * state.correlation
                       + 0.10 * (1.0 - breadth_support))
        risk_on = min(1.0, 0.40 * trend + 0.35 * breadth_support
                      + 0.25 * direction_support)
        range_bound = (1.0 - trend) * (1.0 - stress)
        uncertainty = min(1.0, 0.40 * abs(risk_on - risk_off)
                         + 0.30 * (1.0 - state.data_quality)
                         + 0.30 * (1.0 - max(trend, range_bound)))
        rationale: List[str] = []
        if stress >= 0.75 or (vol >= 0.90 and state.correlation >= 0.80):
            label = RegimeLabel.STRESS
            rationale.append("Elevated systemic stress/correlation.")
        elif vol >= 0.80:
            label = RegimeLabel.HIGH_VOLATILITY
            rationale.append("Volatility percentile is elevated.")
        elif trend >= 0.70:
            label = RegimeLabel.STRONG_TREND
            rationale.append("Directional persistence is strong.")
        elif trend >= 0.40:
            label = RegimeLabel.WEAK_TREND
            rationale.append("Directional persistence is moderate.")
        else:
            label = RegimeLabel.RANGE
            rationale.append("Low directional persistence; range-like conditions.")
        if breadth_support < 0.35:
            rationale.append("Market breadth is weak.")
        if state.correlation >= 0.80:
            rationale.append("Cross-asset correlation is high; diversification is weaker.")
        cap = 0.80 * (1.0 - 0.75 * risk_off) * (1.0 - 0.60 * uncertainty)
        if label == RegimeLabel.STRESS:
            cap = min(cap, 0.20)
        elif label == RegimeLabel.HIGH_VOLATILITY:
            cap = min(cap, 0.40)
        return RegimeAssessment(label, risk_on, risk_off, trend, range_bound,
                                vol, uncertainty, max(0.0, min(0.80, cap)),
                                tuple(rationale))


@dataclass(frozen=True)
class NewsAssessment:
    """Trusted structured assessment; never construct from raw headline keywords."""
    event_id: str
    observed_at: str
    severity: NewsSeverity
    relevance: float
    credibility: float
    novelty: float
    affected_symbols: Tuple[str, ...] = ()
    point_in_time_eligible: bool = False
    evaluator_version: Optional[str] = None
    rationale: str = ""

    def __post_init__(self) -> None:
        for name in ("relevance", "credibility", "novelty"):
            _unit(name, getattr(self, name))
        if not self.event_id or not self.observed_at:
            raise ValueError("news event_id and observed_at are required")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("news observed_at must be an ISO-8601 timestamp") from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("news observed_at must be timezone-aware")
        if self.severity != NewsSeverity.UNKNOWN and not self.evaluator_version:
            raise ValueError("a versioned evaluator is required for scored news")


@dataclass(frozen=True)
class NewsRisk:
    exposure_multiplier: float
    block_new_entries: bool
    confidence: float
    rationale: Tuple[str, ...]


class NewsRiskOverlay:
    """News can reduce exposure or block entries; it can never increase risk."""

    def evaluate(self, assessments: Sequence[NewsAssessment],
                 symbol: Optional[str] = None,
                 symbols: Optional[Sequence[str]] = None,
                 now: Optional[datetime] = None,
                 max_age_seconds: int = 21600) -> NewsRisk:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("news evaluation time must be timezone-aware")
        relevant = []
        for item in assessments:
            if not item.point_in_time_eligible or item.severity == NewsSeverity.UNKNOWN:
                continue
            observed = datetime.fromisoformat(item.observed_at.replace("Z", "+00:00"))
            age = (current - observed).total_seconds()
            if age < 0 or age > max_age_seconds:
                continue
            target_symbols = ({s.upper() for s in symbols} if symbols
                              else ({symbol.upper()} if symbol else set()))
            if target_symbols and item.affected_symbols and not (
                target_symbols & {s.upper() for s in item.affected_symbols}
            ):
                continue
            weight = item.relevance * item.credibility * item.novelty
            if weight > 0:
                relevant.append((item, weight))
        if not relevant:
            return NewsRisk(1.0, False, 0.0,
                            ("No fresh, eligible, scored news; no risk increase.",))
        multiplier = 1.0
        block = False
        reasons: List[str] = []
        confidence = 0.0
        for item, weight in relevant:
            confidence = max(confidence, weight)
            if item.severity == NewsSeverity.LOW:
                factor = 0.95
            elif item.severity == NewsSeverity.MODERATE:
                factor = 0.80
            elif item.severity == NewsSeverity.HIGH:
                factor = 0.50
            elif item.severity == NewsSeverity.CRITICAL:
                factor = 0.0
                if weight >= 0.65:
                    block = True
            else:
                factor = 1.0
            factor = 1.0 - weight * (1.0 - factor)
            multiplier = min(multiplier, factor)
            reasons.append(f"{item.event_id}: {item.severity.value}, weighted={weight:.3f}")
        return NewsRisk(max(0.0, multiplier), block, confidence, tuple(reasons))


@dataclass(frozen=True)
class StrategyCandidate:
    strategy_id: str
    family: str
    score: float
    expected_net_edge_bps: float
    lower_confidence_bound_bps: float
    uncertainty: float
    data_quality: float
    oos_validated: bool
    costs_empirically_validated: bool
    evidence_class: str = "PRECEDENTED"
    benchmark_support: float = 0.0

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.family:
            raise ValueError("strategy_id and family are required")
        for name in ("score", "uncertainty", "data_quality", "benchmark_support"):
            _unit(name, getattr(self, name))
        if not isfinite(self.expected_net_edge_bps) or not isfinite(self.lower_confidence_bound_bps):
            raise ValueError("edge estimates must be finite")


@dataclass(frozen=True)
class StrategyAllocation:
    strategy_id: str
    weight: float
    adjusted_score: float
    rationale: str


@dataclass(frozen=True)
class PortfolioDecision:
    timestamp: str
    regime: RegimeAssessment
    news_risk: NewsRisk
    allocations: Tuple[StrategyAllocation, ...]
    cash_weight: float
    total_exposure: float
    abstain: bool
    rationale: Tuple[str, ...]


class RegimeAwarePortfolioSelector:
    """Portfolio-level selector. Unqualified candidates are never allocated."""

    FAMILY_AFFINITY = {
        "TREND": (0.85, 0.15, 0.75),
        "MOMENTUM": (0.80, 0.20, 0.70),
        "MEAN_REVERSION": (0.20, 0.85, 0.35),
        "DEFENSIVE": (0.45, 0.35, 0.95),
        "CASH": (0.0, 0.0, 1.0),
    }

    def __init__(self, classifier: Optional[RegimeClassifier] = None,
                 news_overlay: Optional[NewsRiskOverlay] = None,
                 max_candidates: int = 4,
                 novel_exploration_cap: float = 0.01) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        self.classifier = classifier or RegimeClassifier()
        self.news_overlay = news_overlay or NewsRiskOverlay()
        self.max_candidates = max_candidates
        self.novel_exploration_cap = _unit("novel_exploration_cap", novel_exploration_cap)

    def _affinity(self, family: str, regime: RegimeAssessment) -> float:
        trend, range_score, defensive = self.FAMILY_AFFINITY.get(
            family.upper(), (0.25, 0.25, 0.25))
        return max(0.05, min(1.0,
            trend * regime.trend + range_score * regime.range_bound
            + defensive * regime.risk_off))

    def select(self, state: MarketState, candidates: Iterable[StrategyCandidate],
               news: Sequence[NewsAssessment] = (),
               now: Optional[datetime] = None,
               symbols: Optional[Sequence[str]] = None) -> PortfolioDecision:
        regime = self.classifier.assess(state)
        news_risk = self.news_overlay.evaluate(news, symbols=symbols, now=now)
        rationale: List[str] = list(regime.rationale) + list(news_risk.rationale)
        if regime.label == RegimeLabel.UNKNOWN or news_risk.block_new_entries:
            why = "Data quality gate" if regime.label == RegimeLabel.UNKNOWN else "Critical eligible news"
            return PortfolioDecision(state.timestamp, regime, news_risk, (), 1.0, 0.0,
                                     True, tuple(rationale + [why + "; remain in cash."]))
        ranked: List[Tuple[float, StrategyCandidate]] = []
        for c in candidates:
            # Hard gates: no positive allocation based on unvalidated costs,
            # poor data, non-OOS evidence, or non-positive conservative edge.
            if not c.oos_validated or not c.costs_empirically_validated:
                continue
            if c.data_quality < 0.95 or c.expected_net_edge_bps <= 0:
                continue
            if c.lower_confidence_bound_bps <= 0:
                continue
            if c.evidence_class.upper() == "NOVEL":
                if c.uncertainty > 0.25:
                    continue
            elif c.evidence_class.upper() != "PRECEDENTED":
                continue
            score = (c.score * (1.0 - c.uncertainty)
                     * c.data_quality * (0.75 + 0.25 * c.benchmark_support)
                     * self._affinity(c.family, regime))
            if c.evidence_class.upper() == "NOVEL":
                score *= 0.50
            if score > 0:
                ranked.append((score, c))
        ranked.sort(key=lambda x: (-x[0], x[1].strategy_id))
        ranked = ranked[:self.max_candidates]
        if not ranked:
            return PortfolioDecision(state.timestamp, regime, news_risk, (), 1.0, 0.0,
                                     True, tuple(rationale + ["No candidate passed every evidence gate; hold cash."]))
        total_score = sum(score for score, _ in ranked)
        exposure_cap = min(regime.exposure_cap, 0.80) * news_risk.exposure_multiplier
        weights: List[StrategyAllocation] = []
        for score, candidate in ranked:
            weight = exposure_cap * score / total_score
            if candidate.evidence_class.upper() == "NOVEL":
                weight = min(weight, self.novel_exploration_cap)
            weights.append(StrategyAllocation(candidate.strategy_id, weight, score,
                                               "Passed OOS, empirical-cost, data and conservative-edge gates."))
        exposure = sum(x.weight for x in weights)
        # Novel caps may leave idle allocation; never redistribute it into risk.
        cash = max(0.0, 1.0 - exposure)
        return PortfolioDecision(state.timestamp, regime, news_risk, tuple(weights),
                                 cash, exposure, exposure <= 0,
                                 tuple(rationale + ["Unallocated capital remains cash."]))
