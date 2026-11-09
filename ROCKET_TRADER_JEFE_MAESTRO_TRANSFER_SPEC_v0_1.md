# Rocket Trader — Jefe Maestro Transfer Specification v0.1

## Purpose

This document defines how Rocket Trader reuses the engineering and research discipline developed in MDV PS / Jefe Maestro without copying lottery-specific assumptions into financial markets.

Source repository reviewed: https://github.com/marcodurzov/mdv-ps-jefe-maestro

Relevant source components reviewed:
- `core/system/jefe_maestro_v6_elite_predictor.py`
- `core/system/advanced_stats.py`
- `core/system/information_theory.py`
- `core/system/statistical_lab.py`
- `core/system/statistical_lab_fix08.py`
- `results/statistical_lab/FIX08_real_data_report.json`
- `MDV_PS_CONTINUITY_STATE.md` and `README_FIX08.md`

## Transferable capabilities

| Jefe Maestro / MDV PS capability | Rocket Trader adaptation |
|---|---|
| Temporal feature engineering and snapshots | Point-in-time market features; every feature must be available at decision time |
| Heterogeneous model ensemble | Combine models only when each adds stable out-of-sample value |
| Time-ordered training and walk-forward evaluation | Purged walk-forward validation for overlapping financial labels |
| Historical-data fingerprinting | Immutable market-data and strategy-run fingerprints |
| Cache invalidation when data/protocol changes | Model cache keyed by data fingerprint, feature schema, code and config versions |
| Bootstrap / block permutation | Uncertainty intervals and dependence-aware significance checks on trading outcomes |
| Global multiple-testing correction | Correct for all strategy, symbol, timeframe and parameter trials in the research family |
| Attribution and continuity reports | Explain P&L by strategy, symbol, market regime, signal, cost and execution |
| Novelty / regime diagnostics | Reduce risk or reject signals outside validated historical support |
| Auto-tuning | Research-only parameter search with untouched final holdout and trial-count accounting |

## Explicit non-transfer rules

The historical Melate, Revancha and Revanchita CSV rows are not financial market observations and must never be mixed into financial model training.

Lottery-specific number frequencies, pair co-occurrence, draw gaps, lottery entropy assumptions, lottery social-bias features, SMOTE treatment and physical-draw hypotheses are not financial alpha features. A concept may be re-expressed as a financial hypothesis only after a domain-specific definition, point-in-time data source, and independent test exist.

Jefe Maestro production code is not to be modified as part of Rocket Trader development. The statistical labs remain separate research artifacts.

## Evidence discipline inherited from MDV PS

The MDV PS FIX 08 report evaluated 4,632 historical hypotheses globally with Holm-Bonferroni correction. It reported 188 raw p-values below 0.05 and zero surviving the global correction. Its own decision correctly states that predictive evidence was not established and production changes were not authorized.

This is a software/research lesson, not a financial-market result:
- descriptive patterns are not predictive evidence;
- a successful workflow is not evidence of an edge;
- the number of experiments must be counted;
- final holdout data must remain untouched;
- prospective performance must be independently replicated.

## Rocket Trader research acceptance protocol

A strategy candidate must record:
1. hypothesis and rationale, including whether it is precedent-based or novel;
2. market, symbol universe, timeframe and regime scope;
3. exact point-in-time data sources and data fingerprint;
4. features, labels, target horizon and code/config versions;
5. all parameter/model trials performed;
6. chronological train, validation, selection and untouched final holdout periods;
7. purge/embargo for overlapping labels;
8. benchmark-relative return, trade count, exposure, turnover, drawdown, Sharpe/Sortino, profit factor and uncertainty;
9. fees, spread, slippage, liquidity, partial-fill and market-hours assumptions;
10. attribution by symbol, strategy, regime and execution;
11. decision: REJECT, RESEARCH_ONLY or PAPER_CANDIDATE.

No candidate may become PAPER_CANDIDATE merely because it beats a weak or mismatched benchmark. Compare against buy-and-hold, cash, simple systematic baselines, and a risk-matched benchmark over the same dates.

## Trader and news intelligence

Publicly documented strategies from successful traders/investors are reference hypotheses, not order instructions. Record the person/strategy, source URL, publication time, observation date, market regime, and whether the information was actually available at the simulated decision time.

News and social information must include `published_at`, `first_seen_at`, `retrieved_at`, source, URL, ticker/entity mapping and content hash. A headline or social post alone must never submit an order. Delayed filings, revised macro data, survivorship-biased constituents and current information backfilled into historical tests are prohibited.

## Current known engineering gates

The existing Rocket Trader Engine had several issues identified during audit:
- `novelty_score` was nested below a return inside `predict_proba`, making it inaccessible as a model method;
- the validation split did not purge the forward-label horizon;
- OOS returns were selected by tail length rather than preserved source-row positions;
- historical `ret_5` momentum was being exposed as if it were a forward expected-return forecast;
- feature-space similarity alone was being labelled `PRECEDENTED`, although similarity is not proof of a validated trading edge.

The correction branch moves `novelty_score` to the class level, adds a horizon-sized purge, preserves original row positions for exact OOS alignment, marks expected return as `NOT_ESTIMATED` until a separate return model is validated, and reserves `PRECEDENTED` for independently validated strategy evidence.

The current `NewsEngine` is a keyword-count heuristic, not a real news ingestion or NLP system. It has no source lineage, publication/first-seen timestamps, point-in-time archive, deduplication or corroboration. It must remain a placeholder and must not drive trading decisions until a proper news pipeline is built.

These fixes require passing CI and further review before merge.

## Non-negotiable safety

- Research and Paper execution remain separate.
- The broker layer cannot bypass Core risk controls.
- Live trading is disabled and requires a separate explicit authorization.
- No leverage, margin, shorts, options, futures or perpetuals in the initial system.
- Do not claim profitability from code tests, historical descriptive statistics or a small trade sample.
