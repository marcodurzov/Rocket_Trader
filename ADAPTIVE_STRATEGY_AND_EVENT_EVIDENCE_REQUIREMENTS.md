# Rocket Trader — Adaptive Strategy & Event Evidence Requirements
**Version:** 1.0  
**Date:** 2026-11-11  
**Status:** Architecture/research specification; not evidence of validated alpha.

## 1. User requirements

Rocket Trader must:
- Rotate among suitable strategy families as regimes and opportunities change.
- Maintain a continuously updated knowledge/evidence registry across applicable trading disciplines.
- Validate financial, macroeconomic, political, geopolitical and social/news events as possible leading or risk indicators.
- Apply the statistical discipline developed in the user's prior project, **Jefe Maestro**, without assuming lottery statistics transfer to financial markets.
- Preserve all working rules, failed experiments and next steps in the canonical Handoff.

## 2. Adaptive strategy architecture

The controller must not simply classify a market as "bull/bear" and switch blindly. It should:
1. Validate data, tradability, account health, liquidity and execution constraints.
2. Estimate probabilistic regimes and confidence across trend, volatility, correlation, breadth, liquidity and event stress.
3. Generate eligible candidates from independently tested strategy modules.
4. Estimate conditional net expectancy and uncertainty for each candidate.
5. Allocate subject to portfolio correlation, turnover, capacity, drawdown and exposure constraints.
6. Use hysteresis, switching penalties, minimum evidence and shadow champion/challenger evaluation.
7. Select cash/no-trade whenever evidence or data quality is insufficient.
8. Keep deterministic execution and hard risk controls outside model discretion.

Required benchmark set: cash, buy-and-hold, each strategy standalone, static equal-weight ensemble and simple regime rules. Adaptive selection must demonstrate incremental out-of-sample net utility after realistic costs.

## 3. Strategy knowledge registry

For every strategy family record: hypothesis, mechanism, market, horizon, applicable regimes, required data/granularity/latency, entry/exit/sizing, execution assumptions, costs/capacity, failure modes, source links/evidence grade, pre-registered tests, OOS results and promotion status.

The goal is comprehensive practical coverage, not an unverifiable claim to know every strategy ever invented. Methods that require unavailable order-book data, shorting, leverage, derivatives, paid feeds or ultra-low latency remain out of scope or research-only unless separately authorized and technically justified.

## 4. Jefe Maestro statistical method transfer

Jefe Maestro contributes research discipline:
- production/research separation;
- pre-registered hypotheses and frozen parameters;
- chronological train/selection/final/prospective splits;
- walk-forward evaluation;
- random/null and matched controls;
- immutable evidence logs, data/code fingerprints and fixed random seeds;
- block bootstrap, permutation/sign inference and confidence intervals;
- Holm or defensible family-wise multiple-testing correction;
- individual and combined signal evaluation;
- separation of descriptive patterns, predictive evidence and economic utility;
- prospective validation before promotion.

Prior Jefe Maestro results are cautionary: FIX07 did not validate predictive advantage (CIs included zero; adjusted p=1.000); FIX09 examined 4,629 hypotheses, with 227 nominal p<0.05 and zero surviving Holm correction. This is evidence of the danger of multiple testing, not a financial-market result. Lottery null assumptions must not be reused for financial returns.

## 5. Event/news/social evidence pipeline

Existing ingestion observers and curated assessment pipeline are inputs, not trading signals. Store source/provenance, independent source group, publication/first-seen/retrieval/event timestamps, revisions, hashes, asset/event mapping, novelty, confidence, contradictions, causal channel and expected horizon.

Research event impact with:
- predeclared event classes and horizons;
- point-in-time event studies and matched controls;
- abnormal returns, volatility, spreads, volume, gaps and cross-asset spillovers;
- lead/lag tests that enforce information availability;
- deduplication and source-independence clustering;
- placebo timestamps, shuffled labels and negative controls;
- block bootstrap and multiple-testing correction;
- comparison against structured-event and price/volume-only baselines;
- incremental OOS net utility after latency and execution costs.

LLM summaries, raw headlines, sentiment and viral social claims cannot directly allocate capital. Political/social coding must be neutral and evidence-based. Respect privacy, licensing and platform terms; exclude sources without defensible point-in-time provenance.

## 6. Promotion gates

A candidate remains research-only until data quality, reproducibility, OOS performance, uncertainty, costs, capacity, drawdown, robustness and incremental value versus baselines are demonstrated. Shadow mode precedes Paper. Paper precedes any separately authorized live consideration. No model may promote itself or bypass risk controls.

## 7. Current implementation status

This document records requirements and design. It does not assert that adaptive rotation, comprehensive strategy knowledge, event predictive value or social-signal alpha has been implemented or validated. Current news ingestion is observer/assessment-oriented; statistical event studies and proven incremental predictive value remain work items.

## 8. Next work

1. Expand machine-readable strategy registry across applicable families.
2. Add immutable hypothesis/event experiment ledger.
3. Build point-in-time event-study datasets and statistical baselines.
4. Validate regime posterior and switching stability.
5. Compare adaptive selector with static baselines out of sample.
6. Integrate in shadow mode only and update the Handoff with every result.
