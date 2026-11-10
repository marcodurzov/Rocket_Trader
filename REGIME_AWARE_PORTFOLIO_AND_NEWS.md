# Regime-aware allocation and financial-social news

## Decision principle
Rocket Trader does not seek one universally winning strategy. It estimates a continuous market state and allocates only among strategies whose evidence is valid for the current regime. Regime labels are summaries, not hard-coded market truths: trend persistence, direction, volatility, breadth, correlation and systemic stress remain separate continuous dimensions.

## Market regimes
The initial classifier emits UNKNOWN, STRONG_TREND, WEAK_TREND, RANGE, HIGH_VOLATILITY or STRESS while retaining continuous risk-on, risk-off, trend, range, volatility and uncertainty scores. Poor/stale data quality forces UNKNOWN and 100% cash. Stress and high-volatility conditions reduce the total exposure cap.

## Strategy families
The selector currently supports TREND, MOMENTUM, MEAN_REVERSION and DEFENSIVE family affinities. These are priors for ranking, not claims of alpha. Every candidate must independently pass:
- chronological out-of-sample validation;
- empirically validated fees, spread and slippage;
- data quality >= 95%;
- positive net expected edge and positive conservative lower confidence bound;
- precedent evidence, or a separately capped NOVEL exploration budget with low uncertainty.

The selector ranks up to four candidates and distributes no more than the regime/news exposure cap. Residual capital remains cash. If no candidate qualifies, it abstains and holds cash. No holdout tuning is permitted.

## Financial-social news
The existing Alpaca News collector preserves article revisions, provider timestamps, first observation and point-in-time eligibility. This module deliberately does not classify raw headlines or use keyword-count sentiment. A news assessment must be structured, versioned and point-in-time eligible; relevance, credibility and novelty determine how strongly its severity affects exposure. LOW/MODERATE/HIGH reduce exposure; CRITICAL blocks new entries. Unknown, historical-backfill-only or unscored news cannot increase conviction or risk.

News scope should expand over time to macroeconomic releases, central-bank/fiscal policy, geopolitics, regulation, labor/social disruptions, supply chains and sector/company events. Each event must be mapped to affected assets, direction only when validated, expected horizon, source credibility and uncertainty. Conflicting reports should increase uncertainty, not produce a forced directional signal.

## Important limitation
This is a pure decision component, not yet wired into the live/Paper runtime or the Alpaca order path. The current cost assumptions and strategy research have not passed approval. It must remain observe-only until a separately reviewed integration, historical point-in-time replay, tests and representative Paper validation are complete. No orders are enabled by this change.
