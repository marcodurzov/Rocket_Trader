# Paper regime observer (observe-only)

## Purpose

The service reads minute bars already persisted by `rocket-trader-paper-observer`, derives cross-sectional features independently for the ETF and crypto universes, evaluates `RegimeAwarePortfolioSelector`, and stores timestamped decision snapshots in `regime_decisions.sqlite3`.

It is a research/monitoring layer, not an execution engine. It receives no Alpaca credentials and imports no order-submission client.

## Current feature definitions

- Trend strength: average absolute 20-bar log momentum divided by 20-bar realized volatility, scaled and clipped to [0, 1].
- Trend direction: cross-sectional average sign of 20-bar log momentum.
- Breadth: fraction of universe symbols with positive 20-bar log momentum.
- Volatility percentile: empirical rank of the latest 20-bar realized volatility against the rolling history available in the last 180 bars.
- Correlation: mean pairwise Pearson correlation of aligned minute log returns, normalized to the selector's [0, 1] input.
- Stress: transparent heuristic combining volatility percentile, positive cross-asset correlation and 60-bar peak-to-current drawdown.
- Data quality: freshness and cross-symbol timestamp alignment.

The observer requires at least 60 common aligned bars per symbol universe, at least 95% timestamp overlap for every symbol, rejects future/stale bars, rejects cross-symbol timestamp skew above three minutes, and fails closed when a gap in the common aligned series exceeds three minutes. Returns and correlations are calculated only after joining each asset on exact normalized UTC timestamps; they are never paired by array position. The selector independently fails closed below its data-quality threshold.

These are initial descriptive features. They are not claimed to predict returns, and their thresholds have not yet been calibrated or validated out of sample. Minute bars are not a substitute for tradeable bid/ask quotes or execution-cost measurements.

## Capital policy

The candidate list is deliberately empty. Every evaluation therefore remains 100% cash / abstain. No strategy can enter this service merely because its family appears in the reference registry. A candidate must first pass chronological out-of-sample validation, empirically measured costs, data-quality gates and a positive conservative lower confidence bound.

Raw news remains disconnected from allocation. A separate human-reviewed event store now supplies only approved, point-in-time-eligible and unexpired assessments to the selector, filtered by the active symbol universe. Source article IDs, URLs, provider publication timestamps and first-live-seen timestamps are verified against the durable official/Alpaca/GDELT ingestion databases before an assessment can be approved. Critical events require two independent source groups plus minimum credibility, relevance and novelty thresholds. The overlay can only reduce risk or block new entries; it cannot increase exposure. No model or keyword classifier is allowed to score raw headlines automatically.

## Persistence and operations

- Input: `ROCKET_TRADER_RUNTIME_DB` (same durable volume as the Paper market observer).
- Output: `ROCKET_TRADER_REGIME_DB`, default `/app/data/regime_decisions.sqlite3`.
- Poll interval: 60 seconds.
- Each asset class has an append-only decision history with evaluation time, latest market-bar time, regime, feature diagnostics and cash decision.
- Health reports observer liveness. Market-data freshness and decision abstention are reported separately in the decision payload; a live process can correctly be healthy while refusing to allocate due to stale or insufficient data.

## Next validation work

1. Compare calculated features against independently computed reference values and test edge cases (missing bars, duplicate timestamps, outliers, market closures and daylight-saving transitions).
2. Run the feature pipeline over archived point-in-time data and test regime stability/hysteresis.
3. Test whether regimes improve net risk-adjusted results versus a fixed baseline after realistic spreads, fees, slippage and multiple-testing correction.
4. Only register strategies that pass the complete research approval process. Until then the observer must remain cash-only.


## Timestamp-alignment correction — 2026-11-10

A code audit found that the previous observer calculated cross-asset correlation by taking the last N return values from each symbol and pairing them by array position. If one symbol had missing minute bars, the paired returns could refer to different timestamps even when the latest timestamps were close. This could distort correlation, breadth/stress inputs and regime classification.

The observer now:
- normalizes bar timestamps to UTC instants;
- intersects exact timestamps across every symbol before computing returns;
- requires at least 60 common bars and at least 95% aligned coverage for each symbol;
- rejects a common-series gap greater than 180 seconds;
- reports per-symbol aligned coverage, common bar count and maximum gap;
- remains fail-closed to cash on insufficient alignment or stale/unaligned data.

Regression tests cover a single missing bar (which is aligned correctly), material cross-symbol missing data (rejected), and a shared multi-minute gap (rejected). This validates alignment logic offline; it does not yet validate regime predictive power or live host operation.
