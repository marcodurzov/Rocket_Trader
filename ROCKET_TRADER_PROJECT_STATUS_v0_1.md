# Rocket Trader — Project Status v0.1
**Last reviewed:** 2026-11-09  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Primary reference system:** https://github.com/marcodurzov/mdv-ps-jefe-maestro

## Executive status

Rocket Trader has a meaningful research and data foundation, but it is **not yet an autonomous end-to-end Paper Trading service**. Research workflows and read-only Alpaca integrations have been tested. No strategy passed the latest OOS acceptance gate. No orders were submitted by the research, crypto-data, news-ingestion or regression workflows.

Do not interpret a successful GitHub Actions run as evidence of profitability.

## Financial policy — confirmed

- Before the first time operating capital reaches MXN 100,000: 70% reinvestment / 10% reserve / 20% personal distribution.
- Once MXN 100,000 is reached for the first time: 50% reinvestment / 10% reserve / 40% personal distribution.
- The transition is permanent even if capital later falls below MXN 100,000.
- Distributions must be based on realized net profit after fees, spread, slippage and losses, not on unrealized P&L or gross account balance.
- The MXN 100,000 operating-capital floor is a withdrawal policy, not a guarantee against market losses.
- Production `RocketTraderCore` now refuses to start unless `ROCKET_TRADER_CAPITAL_MILESTONE_PATH` or an explicit durable milestone path is configured. The demo Core is exempt for offline tests only.
- After the milestone, the target remains 50/10/40 permanently. If reserve and personal transfers would take operating capital below MXN 100,000, both transfers are withheld and actual allocation becomes 100% reinvestment until there is sufficient headroom. The plan records both target and actual percentages.
- If the state file is corrupt or its threshold differs from configuration, allocation fails closed.
- The Paper account reports USD values. The production ledger must use a timestamped FX conversion source before comparing USD account equity with the MXN threshold or calculating MXN distributions.

## Work integrated into main

### 1. Core capital policy
- Core and Adaptive defaults now use 70/10/20 before the first threshold hit and 50/10/40 after it.
- Core has a permanent milestone latch and regression tests covering drawdown and process restart when a durable state path is configured.
- GitHub Actions: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42683172988
- Earlier capital policy PR: https://github.com/marcodurzov/Rocket_Trader/pull/1
- Protected floor payout gate PR: https://github.com/marcodurzov/Rocket_Trader/pull/11
- Durable milestone startup guard PR: https://github.com/marcodurzov/Rocket_Trader/pull/12

### 2. Jefe Maestro / MDV PS transfer
- Added `ROCKET_TRADER_JEFE_MAESTRO_TRANSFER_SPEC_v0_1.md`.
- Transferable practices include temporal feature engineering, model ensembles, walk-forward validation, data/model fingerprints, bootstrap and permutation tests, multiple-testing correction, attribution and continuity reports.
- Historical Melate/Revancha/Revancha CSV records are not financial-market data and must never be used as market-model training rows.
- Lottery-specific frequencies, pairs, draw gaps and lottery assumptions are not financial alpha features. Only domain-redefined hypotheses with financial data and independent tests may be considered.

### 3. Engine validation corrections
- Fixed `novelty_score` so it is a real model method.
- Added a purge equal to the forward-label horizon.
- Preserved source row positions for exact OOS return alignment.
- Historical momentum is no longer mislabeled as an expected-return forecast. Until a separately validated return model exists, signal output says `expected_return_status=NOT_ESTIMATED`.
- Feature-space similarity alone no longer qualifies a signal as `PRECEDENTED`.
- Classifier-only research cannot approve a strategy for Paper because it does not model executable positions, capital, fees, spread, slippage or fills.
- Engine/capital regression run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42685654652
- Integrated PR: https://github.com/marcodurzov/Rocket_Trader/pull/2

### 4. Crypto market-data and research foundation
- Added a read-only Alpaca crypto OHLCV/quote adapter.
- Added an independent crypto research wrapper with per-symbol SignalEngine instances.
- Added a configurable crypto cost model. Initial fee assumptions are 15 bps maker / 25 bps taker per side for the lowest published volume tier; the live account tier must be verified. Spread and slippage are added separately.
- Crypto market data and research do not submit orders.
- Crypto data test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42686255611
- Crypto engine test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42686520713
- Read-only Paper permission check: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42688397781
- Integrated PRs: https://github.com/marcodurzov/Rocket_Trader/pull/3 and https://github.com/marcodurzov/Rocket_Trader/pull/4

### 5. News ingestion
- Added Alpaca News API ingestion and a SQLite article/revision ledger.
- Stores provider timestamps separately from first observation time, records content hashes, deduplicates revisions and prevents older provider revisions from overwriting newer ones.
- Callers must explicitly select `LIVE` or `HISTORICAL_BACKFILL`. Historical backfills are not point-in-time eligible until the collector later observes an article live.
- A read-only News API smoke test using the existing GitHub Actions secrets fetched 20 articles successfully.
- News ingestion is not yet sentiment analysis and is not connected to trading decisions.
- Test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42687280788
- Integrated PR: https://github.com/marcodurzov/Rocket_Trader/pull/5

### 6. Public strategy reference registry
- Added sourced quantitative references for time-series momentum/trend following and cross-sectional momentum.
- Added qualitative references for Buffett/Berkshire capital stewardship and Jesse Livermore trend/loss discipline.
- Buy-and-hold is a mandatory baseline.
- A citation or anecdote cannot create quantitative precedent. Independent OOS evidence is required.
- The Core's existing `BenchmarkEngine` still has an empty in-memory repository by default. Do not fabricate trader events to make it appear populated.
- Registry test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42687596491
- Integrated PR: https://github.com/marcodurzov/Rocket_Trader/pull/6

### 7. Walk-forward research v0.6
- Added net-of-cost buy-and-hold comparison, matching the strategy's next-bar-open convention.
- Added circular moving-block bootstrap and stricter holdout gates: at least 30 holdout trades, at least 3 folds with trades, and a positive 5th-percentile bootstrap total return.
- Executed 365 days of Alpaca IEX 5-minute bars for SPY and QQQ.
- SPY: no candidate met the selection criteria.
- QQQ: one candidate was selected for final holdout, but the final holdout had only 6 trades and returned -0.87%; bootstrap sample was insufficient.
- Overall `research_pass=false`. No strategy is approved for Paper.
- Final run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42687909713
- Integrated PR: https://github.com/marcodurzov/Rocket_Trader/pull/7

### 8. Fail-closed news risk
- Disabled the previous keyword-count sentiment heuristic.
- Until point-in-time NLP/news scoring is validated, the NewsEngine returns `UNKNOWN` with zero score, confidence and urgency.
- Unknown news cannot increase conviction or position sizing.
- The explicit negative-news hard lock remains available for a future trusted assessment.
- Test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42688090094
- Integrated PR: https://github.com/marcodurzov/Rocket_Trader/pull/8

## Current blockers before end-to-end Paper Trading

1. **Account and data permissions:** the read-only Alpaca Paper check confirmed account status ACTIVE, crypto status ACTIVE, USD account currency, and BTC/USD, ETH/USD and SOL/USD assets reported tradable=true. No crypto order was submitted. SIP stock-data access remains unverified; current stock research uses IEX, whose coverage is not equivalent to SIP.
2. **Persistent runtime:** implement a long-running service with stock and crypto streams, reconnect logic, market calendars, state recovery and health monitoring. GitHub Actions is not the trading runtime.
3. **Execution safety — partial implementation completed:** PR #14 added AlpacaPaperExecutionAdapter, a SQLite-backed idempotency journal, broker lookup by client_order_id, fail-closed handling for ambiguous submission outcomes, and read-only Paper account verification. The Core now rejects LIVE mode unconditionally, including when ALPACA_LIVE_ENABLED=true. Offline CI passed. This adapter is equity-only and is not yet connected to a persistent runtime or approved strategy. It does not yet provide complete fill/position reconciliation or partial-fill exit management.
4. **Separate execution adapters:** equities and crypto have different supported order types and exit mechanics. Crypto spot requires a dedicated position/exit state machine; do not reuse equity bracket assumptions blindly.
5. **Risk/capital integration:** account equity in USD to MXN FX conversion, shared capital manager, per-market exposure caps and durable milestone state.
6. **Strategy benchmarking:** implement the quantitative references as reproducible baselines on the same dates, data, universe and costs. Do not populate the Core's trader-event repository with fabricated results.
7. **Point-in-time news intelligence:** add source corroboration, article-age logic, event classification, validated NLP, filing/macro data and timestamp-safe replay. News must remain informational until validated.
8. **Crypto strategy research:** obtain multi-year crypto bars, run separate walk-forward tests and apply the crypto fee/spread/slippage model. No crypto strategy has passed.
9. **Realized-P&L ledger and payouts:** monthly net-profit accounting, protected operating capital, 70/10/20 then 50/10/40, reserve tracking and a manual payout email/report if automatic withdrawal is unsupported.
10. **Paper acceptance gate:** require a sustained period of Paper operation, reliable order reconciliation, positive net performance after realistic costs, bounded drawdown, and reproducible results before any separate live-trading authorization.

## Safety boundary

- Paper/research only.
- No live orders.
- No leverage, margin, shorts, options, futures or perpetuals in the initial scope.
- No API secrets in source files or chat.
- Never claim that CI PASS, a model score, a trader anecdote or a small trade sample proves profitability.
