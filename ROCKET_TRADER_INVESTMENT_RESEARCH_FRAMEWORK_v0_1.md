# Rocket Trader — Investment Research Framework v0.1

## Purpose

A research process inspired by documented practices of systematic asset managers and investors. It is not a claim that copying a famous investor creates a winning strategy. All ideas must be testable, risk-bounded, and independently validated. The bot must not treat a person, media outlet, social post, or price target as an instruction to trade.

## Principles to encode

1. **Survival before return** (risk-first / capital preservation): hard position limits, maximum portfolio exposure, daily loss lock, drawdown lock, and no leverage by default.
2. **Evidence over narratives** (fundamental/value investors): separate company facts, estimates, and opinions; require timestamps and original sources.
3. **Diversification and factor awareness** (multi-strategy managers): avoid stacking correlated bets; evaluate exposure by sector, factor, and market regime.
4. **Probabilistic thinking** (quantitative/systematic managers): output expected return distribution, uncertainty, sample size, and calibration—not just BUY/SELL.
5. **Cost and execution realism** (market makers/systematic firms): model spreads, fees, slippage, liquidity, partial fills and market hours.
6. **Adversarial validation**: out-of-sample, walk-forward, purged splits when labels overlap, cost stress, parameter stability, bootstrap/permutation checks and benchmark comparison.
7. **Process discipline** (well-known long-term investors): define a thesis, invalidation conditions, and time horizon before entering; never change rules to rescue a failed backtest.
8. **No authority bias**: a famous investor's public holdings/quotes are historical context, not real-time signals. Regulatory filings may be delayed.

## Source tiers and intended use

### Tier 1 — primary / official data
- SEC EDGAR company filings and XBRL: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC company data API: https://data.sec.gov/
- Federal Reserve FRED / ALFRED macro time series and vintage-aware releases: https://fred.stlouisfed.org/docs/api/fred/
- Company investor-relations pages and earnings releases / transcripts (prefer original documents).
- Official exchange / market data feeds and Alpaca historical bars for the current prototype.
- BLS and BEA releases for labor, inflation, GDP and other macro releases.

### Tier 2 — structured estimates and event context
- Yahoo Finance: price/financial summaries and news discovery; verify key facts against filings.
- Earnings calendars, analyst consensus and estimate revisions from licensed providers if a provider and terms are selected.
- Reputable financial press (Reuters, Bloomberg, Financial Times, WSJ): event discovery and context, not standalone trade triggers.

### Tier 3 — sentiment / noisy context
- Public forums, Reddit, Stocktwits, X, newsletters, podcasts, TV commentary (including Fox News): treat as noisy sentiment or event discovery only. Require timestamp, ticker mapping, bot/spam controls, source reputation, duplicate detection, and corroboration. Never let a headline or social post alone place an order.

## Event-time and look-ahead safeguards

- Store `published_at`, `first_seen_at`, `retrieved_at`, `source`, `url`, `ticker`, `event_type`, and a content hash.
- A feature can be used only after `first_seen_at` / publication time, whichever is later and reliably known.
- For revised macro data, use ALFRED vintages or the value that was actually available at that time; do not backfill revised values into historical signals.
- SEC filings become usable only after public filing acceptance time; do not use later 13F holdings as if known on trade date.
- Never backtest current analyst ratings, current index constituents, or present-day news archives as though they were available historically unless point-in-time data is provided.
- Avoid raw sentiment scoring without out-of-sample tests, timestamp integrity, language handling, and manipulation detection.

## Model output contract

Each candidate signal should include:
- probability / expected return and prediction horizon;
- uncertainty interval and training/validation date range;
- sample size, trade count and confidence diagnostics;
- estimated transaction costs and liquidity assumptions;
- benchmark-relative return, drawdown, Sharpe/Sortino and exposure;
- source lineage and feature timestamps;
- regime and risk-limit status;
- decision: `REJECT`, `RESEARCH_ONLY`, or `PAPER_CANDIDATE`.

No `LIVE` state is permitted from this research framework. Live trading remains separately disabled until the user explicitly authorizes a separate safety review.

## Public open-source references reviewed

- QuantConnect LEAN: https://github.com/QuantConnect/Lean — event-driven engine / execution architecture.
- VectorBT: https://github.com/polakowo/vectorbt — vectorized research and performance analysis.
- steveya/backtester: https://github.com/steveya/backtester — walk-forward, purged CV, execution-clock abstractions, bootstrap and deflated Sharpe utilities. Inspect license and dependencies before adopting.
- purged-cross-validation: https://github.com/eslazarev/purged-cross-validation — time-series leakage controls for overlapping labels.

Do not copy third-party code into Rocket Trader without reviewing its license, maintenance, dependencies, and compatibility.
