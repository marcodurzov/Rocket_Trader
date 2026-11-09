# Rocket Trader — Project Status v0.1
**Last reviewed:** 2026-11-09  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Primary reference system:** https://github.com/marcodurzov/mdv-ps-jefe-maestro

## Executive status

Rocket Trader has a meaningful research and data foundation, but it is **not yet an autonomous end-to-end Paper Trading service**. Research workflows and read-only Alpaca integrations have been tested. No strategy passed the latest OOS acceptance gate. No orders were submitted by the research, crypto-data, news-ingestion or regression workflows.

Do not interpret a successful GitHub Actions run as evidence of profitability.

## Financial policy — confirmed

- Initial strategy capital: **MXN 1,000**. All user-facing capital, profit, reserve, payout and MXN 100,000 milestone amounts are denominated in MXN. Alpaca's broker account and asset notionals are denominated in USD.
- Before any strategy-driven Paper order is enabled, the MXN ledger must be converted into a USD risk budget using a timestamped, sourced FX quote. Alpaca's virtual Paper buying power must never be treated as the user's funded strategy capital.
- PR #15 added a Decimal-based FX conversion and USD position-budget module. PR #19 wires it into Core position sizing: broker equity/cash/exposure are explicitly USD; strategy capital is separately MXN; a sourced, timezone-aware FX quote no older than 24 hours is required; and USD notional is capped by MXN capital, per-position risk, total exposure, stop-risk and broker cash. Missing/stale/invalid FX and below-minimum orders fail closed. This remains a sizing gate, not a strategy approval or permission to trade.
- **Updated compounding rule (merged in PR #17):** before operating capital first reaches MXN 100,000, 100% of realized net profits is retained/reinvested; personal withdrawals = 0% and separate reserve allocation = 0%. Uninvested cash remains inside operating capital and is not automatically forced into positions.
- Once MXN 100,000 is reached for the first time: the target policy remains 50% reinvestment / 10% reserve / 40% personal distribution. The milestone latches permanently.
- The transition is permanent even if capital later falls below MXN 100,000.
- Distributions must be based on realized net profit after fees, spread, slippage and losses, not on unrealized P&L or gross account balance.
- The MXN 100,000 operating-capital floor is a withdrawal policy, not a guarantee against market losses. After milestone activation, reserve and personal transfers are withheld whenever they would reduce operating capital below MXN 100,000.
- Production `RocketTraderCore` now refuses to start unless `ROCKET_TRADER_CAPITAL_MILESTONE_PATH` or an explicit durable milestone path is configured. The demo Core is exempt for offline tests only.
- After the milestone, the target remains 50/10/40 permanently. If reserve and personal transfers would take operating capital below MXN 100,000, both transfers are withheld and actual allocation becomes 100% reinvestment until there is sufficient headroom. The plan records both target and actual percentages.
- If the state file is corrupt or its threshold differs from configuration, allocation fails closed.
- The Paper account reports USD values. The production ledger must use a timestamped FX conversion source before comparing USD account equity with the MXN threshold or calculating MXN distributions.

## Work integrated into main

### 1. Core capital policy
- Core and Adaptive defaults use 100/0/0 before the first earned-growth milestone and 50/10/40 after it. No reserve or personal distribution is taken before the milestone.
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

### 12. Crypto fee denomination correction
- PR #22 extends FIFO accounting to crypto BUY fees withheld in the credited base asset. For USD-quoted crypto, the acquired quantity is reduced by the base-asset fee; the full USD acquisition cost is allocated over the net quantity actually received. SELL-side USD fees remain in quote currency.
- This avoids overstating crypto inventory and understating cost basis.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42697135231

### 17. Ledger exposes earned growth capital
- PR #28 adds `earned_growth_capital_mxn` directly to `LedgerSnapshot` and monthly close reports.
- This is calculated as original seed capital plus realized net trading P&L. External deposits and withdrawals are excluded from the milestone qualification metric.
- It is the exact value that must be passed into Core's `monthly_distribution_plan`; operating capital remains a separate input for the protected-floor calculation.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42699294872

### 21. First five-year adjusted ETF research report
- Full read-only run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42700263040
- Artifact ID: `13710094727` (`rocket-trader-equity-multiyear-research-v0-1`).
- IEX feed, `Adjustment.ALL`, five-year period; all eight ETFs passed the approximate weekday coverage gate (about 96.16%, maximum calendar gap 4 days).
- Final holdout contains 251 sessions. Cross-sectional top-1 momentum returned +10.79%, but equal-weight buy-and-hold returned +11.18%; top-1 had worse max drawdown (-19.59% vs -9.41%) and a much weaker bootstrap 5th percentile (-31.53% vs -12.22%).
- Best isolated result was GLD Donchian 55/20 at +15.05%, but the bootstrap 5th percentile was -16.42% and there were only two entries. This is not robust evidence.
- No strategy demonstrated a sufficiently robust advantage over its benchmark. All reported bootstrap 5th-percentile holdout returns were negative.
- IEX is a single-exchange feed, not SIP consolidated data. SIP parity remains a required validation before any strategy approval.
- No strategy approved, no Paper orders, no LIVE orders.

### 20. Multi-year adjusted ETF research v0.1
- PR #30 adds five-year daily research for SPY, QQQ, IWM, DIA, TLT, GLD, EFA and EEM.
- Uses Alpaca `Adjustment.ALL` to account for splits, dividends and spin-offs. IEX is the default feed; SIP remains optional and requires the corresponding entitlement.
- Benchmarks 63/126/252-session time-series momentum, 50/200 SMA trend, 55/20 Donchian breakout, volatility-targeted momentum and cross-sectional top-1 momentum against buy-and-hold.
- Uses next-session signal timing, chronological 60/20/20 windows, data-coverage checks, 5 bps per-side base friction and 2x stress.
- Offline CI passed: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42700108435
- Full adjusted daily research is running after the main merge; results have not yet been reviewed. No strategy promotion or Paper approval is enabled.

### 19. First five-year crypto report with coverage gate
- Full read-only run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42699725144
- Artifact ID: `13711705647` (`rocket-trader-crypto-multiyear-research-v0-1`).
- BTC/USD and ETH/USD: 1,825/1,825 daily bars each, 100% calendar coverage, maximum gap 1 day.
- SOL/USD: 1,407/1,825 bars, 77.10% coverage, 418 missing calendar days and a 417-day maximum gap. It is excluded from cross-sectional evidence and its single-asset metrics are diagnostic only.
- BTC 180-day time-series momentum produced +1.89% on the final holdout, but its moving-block bootstrap 5th percentile was -21.79%; it does not pass robustness.
- ETH strategies were negative on the final holdout. Cross-sectional top-1 momentum on the eligible BTC/ETH universe returned -29.85%, versus -34.48% for equal-weight buy-and-hold; bootstrap 5th percentile was -50.20%.
- No strategy passed. `data_quality_pass=false` because SOL history is incomplete. `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_enabled=false`.
- Conclusion: the pipeline correctly identifies that relative outperformance during a falling market is not a positive-return strategy. More independent strategy research and reliable datasets are required before Paper.

### 18. Crypto historical data quality gate
- PR #29 adds calendar coverage, missing-day and maximum-gap checks to daily crypto research.
- A symbol needs at least 95% calendar coverage and no gap longer than 3 days to qualify as strategy evidence.
- Incomplete single-asset histories remain visible as diagnostics but are ineligible for evidence and excluded from cross-sectional tests.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42699567711
- A new full research run is triggered on the latest main merge to regenerate results under this gate.

### 16. Multi-year crypto research v0.1
- PR #26 adds five-year daily research for BTC/USD, ETH/USD and SOL/USD using Alpaca CryptoFeed.US.
- Tests pre-defined time-series momentum (90/180/365 days), 50/200 SMA trend, 55/20 Donchian breakout, volatility-targeted momentum and cross-sectional top-1 momentum against buy-and-hold.
- Uses chronological 60/20/20 train/validation/final-holdout windows, next-bar signal timing, 40 bps per-side base friction assumptions and 2x friction stress.
- Reports CAGR, drawdown, Sharpe, exposure, turnover and moving-block bootstrap diagnostics.
- Offline CI passed: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42698649553
- The scheduled/manual research run has not yet produced a five-year market-data report. No strategy is promoted, and the workflow hard-codes `candidate_promotion_allowed=false`, `paper_approval=false`, and `orders_enabled=false`.

### 15. Core milestone source aligned with the ledger
- PR #25 closes a subtle policy mismatch: Core previously could activate the 100k payout milestone from operating capital, including external deposits.
- Production `monthly_distribution_plan` now requires `earned_growth_capital_mxn` from the ledger. Earned trading growth controls milestone activation; actual operating capital still controls the protected withdrawal floor.
- Regression CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42697870315
- This ensures external deposits cannot turn on personal/reserve distributions before the original MXN 1,000 has grown to the MXN 100,000 milestone.

### 14. Paper position reconciliation gate
- PR #24 adds a read-only reconciliation module comparing broker-reported quantities against the local FIFO ledger.
- Normalizes crypto pair symbols and detects ledger-only, broker-only and quantity-drift positions.
- Requires an active, unblocked USD Paper account and a fresh timestamped FX quote.
- Reports broker cash/equity in USD for diagnostics, but explicitly does not use Paper buying power as strategy capital.
- Any mismatch blocks reconciliation; the module never submits or modifies orders.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42697539973
- Still requires integration with a complete broker activity/fee/corporate-action event stream and persistent runtime before it can gate automated execution.

### 13. Alpaca Paper account activity stager
- PR #23 adds a read-only PAPER-only client for Alpaca Trading API account activities, with ascending pagination, durable cursor, immutable SQLite staging and idempotent redelivery.
- FILL, CFEE and FEE are staged. Unsupported activity types, non-final statuses and malformed fills are marked blocked.
- It deliberately does not post fills to the P&L ledger yet. Alpaca documents that crypto CFEE can be posted end-of-day and may be denominated in the asset received; other fees may be parent-linked or volume-based. Trade corrections/busts and corporate actions also require explicit handling.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42697315589
- No broker order, cancellation or position modification is performed.

### 11. Append-only realized P&L ledger
- PR #21 adds `rocket_trader_realized_pnl_ledger.py`: durable SQLite append-only events for seed capital, deposits, withdrawals and fills.
- Uses FIFO lots for partial exits. Buy-side fees enter cost basis; sell-side fees reduce proceeds. Net realized P&L is converted to MXN using a sourced, timezone-aware FX quote no older than 24 hours at fill time.
- Fill IDs are idempotent; out-of-order arrival is replayed by execution timestamp; long-only SELL inventory is validated before append.
- The MXN 100,000 milestone is measured from initial capital plus realized trading P&L, not later external deposits. This prevents an added deposit from falsely satisfying the goal of growing the original MXN 1,000.
- Implements 100% reinvestment before the milestone and 50% reinvestment / 10% reserve / 40% personal distribution after it, with the MXN 100,000 operating floor. Monthly closes are immutable proposals and never transfer money.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42696899202 (16 offline tests passed).
- **Not connected to Alpaca yet.** The broker activity ingestion layer must map actual commissions/fees, corporate actions, trade corrections and busts; reconcile cash/equity/positions; and persist a resumable event cursor before this ledger can be authoritative for runtime decisions.
- No Paper or LIVE orders are submitted by the ledger.

### 10. Separate crypto Paper execution adapter
- PR #20 adds `AlpacaCryptoPaperExecutionAdapter`, isolated from equity bracket orders.
- Initial supported order scope is deliberately narrow: simple crypto spot MARKET + IOC only. Alpaca supports crypto market, limit and stop-limit orders with GTC/IOC, but Rocket Trader starts with IOC market orders to avoid unattended resting orders.
- BUY entries are USD-notional based; SELL exits require a broker-held crypto quantity and cannot exceed the quantity currently held.
- Requires Paper account ACTIVE, USD account currency, crypto_status ACTIVE, and tradable crypto asset.
- Adds SQLite idempotency, broker lookup by client_order_id, ambiguous-outcome fail-closed handling, order reconciliation and read-only crypto position reconciliation.
- Offline CI passed: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42695001753
- **Not yet connected to Core/runtime.** No automated stop-loss/target lifecycle, durable portfolio position ledger, or order submission in production runtime. No Paper or LIVE orders were submitted by these tests.

### 9. MXN/USD budget wired into Core
- PR #19 integrates the Decimal currency budget into Core position sizing.
- Broker equity, cash and position notionals are explicitly USD; strategy capital is separately MXN.
- The Core requires a timezone-aware, sourced FX quote no older than 24 hours and caps order notional using MXN capital converted to USD, per-position risk, total exposure, stop-risk and broker cash.
- Missing FX, missing MXN ledger capital, stale/future FX and below-minimum notional all fail closed.
- The initial MXN 1,000 under the current novel-risk budget may be below Alpaca's USD 1 minimum order; in that case the correct behavior is no order, not rounding up or using virtual Paper buying power.
- PR #19 also closes a legacy Core adapter gap by blocking fractional equity bracket orders until compatibility and exit lifecycle are verified.
- Capital/FX CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42694328611
- Execution safety CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42694496153

## Current blockers before end-to-end Paper Trading

1. **Account and data permissions:** the read-only Alpaca Paper check confirmed account status ACTIVE, crypto status ACTIVE, USD account currency, and BTC/USD, ETH/USD and SOL/USD assets reported tradable=true. No crypto order was submitted. SIP stock-data access remains unverified; current stock research uses IEX, whose coverage is not equivalent to SIP.
2. **Persistent runtime:** implement a long-running service with stock and crypto streams, reconnect logic, market calendars, state recovery and health monitoring. GitHub Actions is not the trading runtime.
3. **Execution safety — partial implementation completed:** PR #14 added AlpacaPaperExecutionAdapter, a SQLite-backed idempotency journal, broker lookup by client_order_id, fail-closed handling for ambiguous submission outcomes, and read-only Paper account verification. The Core now rejects LIVE mode unconditionally, including when ALPACA_LIVE_ENABLED=true. PR #16 and PR #19 block fractional equity bracket orders in both the standalone Paper adapter and legacy Core Alpaca adapter because published fractional docs do not explicitly confirm bracket compatibility. The adapter is not yet connected to a persistent runtime or approved strategy and does not yet provide complete fill/position reconciliation or partial-fill exit management.
4. **Separate execution adapters — partially complete:** equities and crypto now have isolated Paper order adapters. The crypto adapter currently supports market IOC primitives and owned-quantity SELL checks only. Still required: durable strategy position state, fill-driven entry/exit lifecycle, stop/target triggers, recovery after restart and Core/runtime integration.
5. **Risk/capital integration — partially complete:** PR #19 connects the timestamped MXN/USD position budget to Core sizing. Still required: persistent realized-P&L ledger, authoritative broker-to-ledger reconciliation, one shared exposure/capital manager across equities and crypto, and durable cross-engine state.
6. **Strategy benchmarking:** implement the quantitative references as reproducible baselines on the same dates, data, universe and costs. Do not populate the Core's trader-event repository with fabricated results.
7. **Point-in-time news intelligence:** add source corroboration, article-age logic, event classification, validated NLP, filing/macro data and timestamp-safe replay. News must remain informational until validated.
8. **Crypto strategy research:** obtain multi-year crypto bars, run separate walk-forward tests and apply the crypto fee/spread/slippage model. No crypto strategy has passed.
9. **Realized-P&L ledger and payouts:** monthly net-profit accounting, protected operating capital, 100/0/0 until the earned-growth milestone then 50/10/40, reserve tracking and a manual payout email/report if automatic withdrawal is unsupported.
10. **Paper acceptance gate:** require a sustained period of Paper operation, reliable order reconciliation, positive net performance after realistic costs, bounded drawdown, and reproducible results before any separate live-trading authorization.

## Safety boundary

- Paper/research only.
- No live orders.
- No leverage, margin, shorts, options, futures or perpetuals in the initial scope.
- No API secrets in source files or chat.
- Never claim that CI PASS, a model score, a trader anecdote or a small trade sample proves profitability.
