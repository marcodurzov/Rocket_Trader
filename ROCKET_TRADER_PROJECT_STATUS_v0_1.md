# Rocket Trader — Project Status v0.1
**Last reviewed:** 2026-11-12  
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

### 23. SIP probe result and cost decision
- Read-only run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42700787964
- IEX SPY daily bars: `AVAILABLE` (5 bars returned).
- Recent SIP SPY daily-bars probe: `NOT_ENTITLED` (HTTP 403) because PR #31 queried `end=current` over the last 14 days; this tested the recent-data restriction, not historical SIP access.
- Current Alpaca individual Trading API documentation lists Basic as free/IEX and Algo Trader Plus at USD 99/month for full US-exchange coverage. Given the initial strategy capital of MXN 1,000, paying for SIP now is economically unjustified. Continue discovery with IEX, keep the limitation explicit, and revisit SIP only when the strategy/capital scale supports the recurring data cost. <https://docs.alpaca.markets/us/docs/about-market-data-api>
- Do not confuse IEX-only historical research with consolidated market coverage.

### 22. SIP entitlement probe
- PR #31 adds a read-only SPY daily-bar test against both IEX and SIP using the connected Alpaca market-data credentials.
- It reports availability/entitlement status without exposing credentials or accessing account balances.
- The result determines whether equity research can be repeated on consolidated SIP data. IEX results remain preliminary until this is verified.
- CI: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42700647281
- Main-merge probe is running; entitlement result is pending.

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


## Audit update — 2026-11-09 (PRs #27–#32)

### Repository state verified
- Current `main` commit at audit: `6130575819bccef9067a77bd4071c7859f921684` (PR #32).
- PRs #27–#32 are merged. No open pull requests were found at the time of this audit.
- PR #27 runs crypto multi-year research after main merges.
- PR #28 exposes `earned_growth_capital_mxn` from the ledger. External deposits/withdrawals do not count toward the MXN 100,000 earned-growth milestone.
- PR #29 adds a 95% calendar-coverage and maximum-three-day-gap gate for crypto. The five-year run had BTC and ETH at 100% coverage; SOL at 77.10% with 418 missing days and a 417-day maximum gap. SOL is ineligible for evidence; the overall crypto dataset fails quality.
- PR #30 adds five-year adjusted daily ETF research across SPY, QQQ, IWM, DIA, TLT, GLD, EFA and EEM. No strategy showed robust excess return over the matching benchmark.
- PR #31 tested recent market-data entitlement: IEX available; SIP returned NOT_ENTITLED (HTTP 403) because the request ended at `current`. It did not test historical SIP ending 15+ minutes earlier. IEX is not consolidated SIP data. Do not pay for real-time SIP.
- PR #32 adds a ten-year ETF research path and benchmark-relative moving-block bootstrap. Its offline tests pass, but the first main-branch data run failed closed: every requested ETF returned only 1,581 daily bars (SPY 1,582), below the 1,638 minimum for ten-year evidence. No research result or strategy approval was produced. Run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42701564813.

### Important documentation reconciliation
The original project-start document still says the first permanent floor is MXN 5,000 and lists risk controls as undecided. Those statements are superseded by the later explicit user decision recorded in this repository: initial capital MXN 1,000; 100% of realized net trading profits retained until earned-growth capital first reaches MXN 100,000; then target allocation 50% reinvestment / 10% reserve / 40% personal. This later policy governs Rocket Trader. The MXN 100,000 floor is a withdrawal restriction, not a guarantee against market loss.

### Current blockers (not completed)
1. Diagnose why the ten-year IEX request returns only ~1,581 bars and record exact first/last dates, weekday coverage and maximum gaps. Do not lower the ten-year threshold just to make the workflow green.
2. Resolve crypto historical coverage using a point-in-time-safe, documented source; never splice different exchanges/providers into one price series without explicit source identity and market comparability controls.
3. Complete broker activity reconciliation before posting fills into the P&L ledger, including crypto fees in base/quote currency, corrections/busts, corporate actions and duplicate/reordered events.
4. Connect ledger, account activity stager, position reconciliation, MXN/USD budget, both execution adapters and a shared portfolio risk manager in one persistent runtime. They are currently separate components/gates, not an autonomous end-to-end system.
5. Define and test explicit risk limits: per-trade risk, maximum position and aggregate exposure, daily loss lock, peak-to-trough drawdown lock, maximum concurrent positions, liquidity/slippage constraints and restart-safe kill switch. Do not invent these from a successful backtest.
6. Build point-in-time benchmark and trader-intelligence data. Famous traders/investors provide hypotheses and process references, never live order instructions. Quantitative comparisons must be reproducible, same-period and net of costs.
7. Keep news ingestion informational until point-in-time classification, source corroboration and predictive value pass independent validation.
8. Deploy a persistent Paper runtime with reconnect/recovery, order-state and partial-fill handling, monitoring and durable state. GitHub Actions is for CI/research, not continuous trading.
9. Establish Paper acceptance criteria and sustained Paper evidence before any separate LIVE safety review. LIVE remains disabled.

### Diagnostic improvement in this audit branch
PR #33 adds the returned date range, approximate weekday coverage, missing weekday count and maximum calendar gap to the ten-year history failure message. This makes the next read-only run diagnostic rather than merely reporting a bar-count mismatch. It does not weaken the evidence gate or enable orders.


### Core risk audit — 2026-11-09
- A code audit found that the `DecisionEngine` applied the minimum signal score/confidence check only to precedent-backed signals. The `NOVEL_RISK` branch bypassed it, so sufficiently funded low-quality novel signals could proceed under the reduced novelty budget. PR #34 applies the same minimum gate to all signals and adds regression checks for low score and low confidence.
- Current `RiskConfig` contains prototype numeric defaults: maximum position 25%, total exposure 80%, maximum loss per trade 2%, daily loss lock 5%, stop 2%, take-profit 4%, trailing-stop parameter 1.5%, maximum 10 trades/day, maximum 3 consecutive losses, and novel-risk budget 1%. These are not calibrated or approved production limits.
- The current Core does not implement a persistent peak-to-trough drawdown lock. The trailing-stop percentage is configured but there is no complete durable trailing-stop/partial-fill position manager. Daily loss state and kill-switch recovery are not yet connected to a persistent runtime.
- `BenchmarkEngine` defaults to an empty in-memory repository. The six-entry reference registry contains academic/institutional strategy hypotheses and qualitative investor references; it is not a live database of successful traders or their verified trades. No trader events may be fabricated. Building a source-backed, point-in-time trader-intelligence feed remains open work.
- The novel-signal path is intentional for genuinely new market regimes, but it must remain smaller-risk and quality-gated; novelty does not waive minimum signal quality or the broader Paper acceptance process.


### Ten-year equity data-source diagnosis — 2026-11-09
The post-PR #33 diagnostic run established the actual IEX coverage boundary:
- DIA, EEM, EFA, GLD, IWM, QQQ and TLT returned 1,581 bars from 2020-07-27 through 2026-11-09, with approximately 96.34% weekday coverage. They do not contain ten years of IEX history.
- SPY returned 1,582 bars, but its first bar was an isolated 2018-11-01 observation followed by a 634-calendar-day gap; overall approximate weekday coverage was 75.59%.
- The IEX source limitation is consistent with Alpaca support material stating IEX historical bars begin in 2020, while SIP history reaches earlier. The old recent-SIP probe returned NOT_ENTITLED (403); it did not test historical SIP, so the ten-year workflow should now test historical SIP rather than assume IEX can cover ten years.
- Do not lower the 10-year evidence threshold or use IEX data as if it were consolidated market history. PR #36 adds a separate Yahoo Finance research-only provider using adjusted daily OHLC, corporate-action metadata and explicit data-quality gates. Yahoo data is not an execution feed and must not be silently spliced with Alpaca IEX. The strategy report remains research-only and must pass data quality before its metrics are considered.


### Yahoo historical provider correction — 2026-11-09
The first live Yahoo workflow failed for every ETF inside yfinance's optional `repair=True` processing with `ValueError: output array is read-only`. Offline regression tests had passed but could not expose this provider-runtime incompatibility. The source now requests auto-adjusted OHLC and corporate-action metadata with `repair=False`; data-quality checks remain mandatory. This avoids the failing repair transformation rather than weakening history coverage or performance acceptance. A fresh live workflow run is required before treating Yahoo history as usable.


### Crypto history gap diagnostics — 2026-11-09
The existing five-year crypto run reports SOL/USD at 77.10% calendar coverage, 418 missing calendar days and a 417-day maximum gap. Summary metrics alone do not show whether this is a missing listing-history period or a provider outage. PR #38 adds first/last timestamps and the 20 largest exact gap intervals per symbol. The source remains Alpaca CryptoFeed.US; no provider series are blended. The existing 95% coverage and maximum-three-day-gap eligibility gate is unchanged.


### Adjusted OHLC precision diagnosis — 2026-11-09
The ten-year Yahoo history now reaches all eight ETFs, but EFA and TLT failed normalization on one row each. Diagnostics show only floating-point differences of approximately 1e-14 between adjusted close and high/low, not material candle corruption. A tiny relative tolerance (1e-10 of price scale) is applied; material candle inconsistencies still fail closed. No invalid rows are silently discarded.


### Operational readiness update — 2026-11-10

- PR #42 merged: introduced `PersistentDrawdownGuard`, with atomic durable JSON state, a persisted high-water mark, sticky max-drawdown lock, configuration-integrity checks, and offline regression tests.
- PR #43 merged: wired the guard into `RocketTraderCore`. Production Core now requires `ROCKET_TRADER_DRAWDOWN_GUARD_PATH`; a breached lock returns `KILL_SWITCH` with zero quantity, and invalid/unreadable state returns `SAFE_MODE`. The guard blocks new entries; it does not liquidate positions or block exit/reconciliation paths.
- All six PR #43 CI checks passed: Core risk, Paper execution safety, crypto Paper execution, capital policy, earned-growth milestone, and engine/capital regression.
- The max-drawdown default is currently a provisional 15% parameter, not empirically calibrated or approved for LIVE. Production deployment must configure a durable path and review this limit against strategy-level adverse scenarios.
- Ten-year adjusted ETF research completed successfully after PR #41. All eight research ETF histories passed the current approximate weekday-coverage gate (about 96.3%); the strategy evaluation covers SPY, QQQ, and IWM with eight hypotheses. The report explicitly keeps `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_enabled=false`, and `orders_submitted=0`. Family-wise multiple-testing correction, SIP parity, independent replication, and sustained Paper validation remain open gates.
- The historical report is research-only and uses Yahoo Finance adjusted daily bars. It is not an execution feed and does not establish that a strategy has a tradable edge after live-market costs.
- No continuous trading runtime has been deployed. GitHub Actions remain CI/research only. Crypto is 24/7; US equities are restricted to exchange sessions. A persistent Paper runtime, strategy approval, order/fill lifecycle integration, and broker/ledger reconciliation are still required before unattended Paper operation.


### Persistent Paper observer runtime — 2026-11-10

- PR #46 merged: adds a containerized, always-on OBSERVE_ONLY service.
- It records Alpaca IEX minute bars for US equities, Alpaca US crypto minute bars (24/7), and Paper trade-update events into SQLite/WAL.
- The runtime persists its database in a Docker named volume, exposes a heartbeat health check, rejects any mode other than OBSERVE_ONLY, and contains no order-submission code.
- Offline runtime tests pass in GitHub Actions. No broker connection or orders were used in CI.
- Deployment assets: `Dockerfile.paper-observer`, `docker-compose.paper-observer.yml`, and `PAPER_OBSERVER_RUNTIME.md`.
- This is an always-on data observer, not yet an autonomous trading bot. It does not train/approve strategies, generate trading decisions, place Paper orders, or reconcile fills into the realized-P&L ledger. Deployment to a persistent host still needs to be completed and monitored.
- GitHub Actions remain CI/research only; they are not used as a 24/7 trading host.


---

## Audit update — 2026-11-10 (PRs #82–#92)

**Main commit after this update:** `492138ddfc91b1aaa8820e9d257b9352393b7162`.

### Integrated and verified

- **PR #82 — official macro/regulatory news observer:** Federal Reserve, BLS, BEA and optional SEC RSS ingestion. Article publication time and first live observation are stored separately. Observe-only.
- **PR #83 — news risk expiry and relevance:** stale critical events expire after six hours; low-confidence critical headlines cannot create a permanent hard block.
- **PR #84 — regime observer:** reads persisted minute bars and derives trend, breadth, volatility percentile, cross-asset correlation, stress and data-quality features separately for equity ETFs and crypto. It persists auditable regime decisions. The candidate set is intentionally empty, so it remains 100% cash.
- **PR #85 — reference benchmark harness:** same-symbol, exact-date and same-cost daily comparison against cash, buy-and-hold, 252-day time-series momentum, 63-day momentum skipping 21 days, and 50/200-day trend. Output is comparison-only; it does not calculate statistical significance or promote strategies.
- **PR #86 — Alpaca/Benzinga news observer:** per-symbol read-only news ingestion with overlap, deduplication, revisions and per-symbol health.
- **PR #87 — GDELT global/geopolitical news observer:** discovery coverage for conflict/sanctions, energy security, shipping, macro policy and natural disasters. Stores metadata, language, country, topic association and first observation. No social-platform scraping.
- **PR #88 — human-reviewed news event assessment:** source IDs, URLs, publication timestamps and first-live-seen timestamps must match the durable official/Alpaca/GDELT article ledgers before approval. Assessments remain PENDING until a named reviewer approves/rejects them. CRITICAL requires two independent source groups, credibility/relevance >=0.75, novelty >=0.50 and point-in-time evidence. Assessments are filtered by active universe; news can only reduce risk or block new entries.
- **PR #89 — Paper quote-to-fill cost telemetry:** subscribes to IEX equity and Alpaca US crypto quotes; records fill-associated quote snapshots; calculates spread and signed midpoint slippage; excludes future/stale quotes and avoids double-counting cumulative partial-fill averages. The empirical-cost approval flag remains false.
- **PR #90 — scheduled ETF history crosscheck:** weekly 10-year Alpaca IEX vs Yahoo adjusted daily history audit, with manual IEX/SIP dispatch and immutable JSON artifact. PR CI passed, but the live comparison step was skipped in the PR/push run; the first scheduled Sunday run is still pending.
- **PR #91 — quote/bar heartbeat isolation:** quote events cannot refresh the independent bar-stream heartbeat. Quote ingestion errors are recorded separately. Regression tests pass.
- **PR #92 — deployment runbook:** documents Paper-only credentials, Compose deployment, persistent volume handling, service health, cost report and human-reviewed news workflow.

### CI and deployment evidence

- PR #84 passed regime observer tests, runtime regression and container validation; the Paper Observer image was published.
- PR #86 passed news regression and container validation; image build/publish completed.
- PR #87 passed GDELT/news tests and container validation.
- PR #88 passed regime, news-assessment, runtime and container regression.
- PR #89 passed cost telemetry/runtime tests and container validation; image was published.
- PR #91 passed runtime freshness, runtime regression and container validation; the updated Paper Observer image was published.
- PR #90 offline crosscheck tests passed. No ten-year market-data artifact has yet been reviewed.
- PR #92 is documentation-only.
- These CI results validate code/build behavior, not live data quality, profitability or deployment on the user's host.

### Current operating state

- The runtime remains `OBSERVE_ONLY`; no order-submission code is enabled.
- The regime observer has no approved strategy candidates and stays at 0% exposure / 100% cash.
- Official, Alpaca/Benzinga and GDELT news collectors are implemented as separate services, but have not yet been deployed and observed on the user's persistent host.
- News-to-risk integration requires human-reviewed, source-verified event assessments. There is no automatic LLM sentiment or event classifier, and no social-media source.
- Execution cost telemetry is implemented, but no representative Paper fill sample has yet been collected; empirical cost validation remains false.
- The daily reference benchmark harness is separate from the existing intraday signal-research workflow. It does not yet provide a complete same-frequency benchmark suite for every intraday candidate.
- The successful-investor registry remains a source-backed hypothesis/process reference, not a database of verified personal trading histories. Do not fabricate trader performance or treat qualitative anecdotes as quantitative benchmarks.

### Remaining blockers — ordered by importance

1. **Deploy and observe the Paper stack:** run `PAPER_OBSERVER_DEPLOYMENT.md` on a persistent host with dedicated Alpaca Paper credentials. Verify all five services, persistent volume, reconnect/restart behavior, data freshness and source health. The repository cannot deploy to the user's host by itself.
2. **Collect real Paper evidence:** accumulate representative quote/fill observations, reconcile all fills and delayed fees, test partial fills, restart recovery, cash movements and broker-vs-ledger positions. Paper fills do not prove live execution quality.
3. **Run and review the 10-year ETF crosscheck:** wait for the scheduled artifact; manually dispatch SIP only if entitlement is available. IEX is not SIP/NBBO.
4. **Complete strategy research and benchmarking:** no strategy is approved. The previous ETF/crypto family research produced zero Holm-significant candidates. Expand the intraday reference comparisons, chronological holdouts, block bootstrap, multiple-testing correction and empirical-cost stress before any Paper strategy approval.
5. **Calibrate market regimes:** the initial regime features are descriptive heuristics, not validated predictors. Test stability, hysteresis, regime-conditioned performance and false transitions on archived point-in-time data.
6. **Validate news intelligence:** build event studies for relevance/credibility/novelty and impact horizons; verify independent source ownership/syndication; add social sources only with compliant licensed access. Do not let raw headline volume or tone drive exposure.
7. **Complete portfolio/risk integration:** durable cross-asset position state, authoritative fill/fee/cash reconciliation, shared exposure manager, per-trade and aggregate risk limits, daily-loss lock, drawdown guard, restart-safe kill switch and exit lifecycle.
8. **Paper acceptance:** require sustained multi-week operation and predeclared acceptance thresholds for net performance, drawdown, turnover, data completeness and reconciliation. No single CI pass or small sample can satisfy this gate.
9. **Separate LIVE review:** LIVE remains disabled. Any future live phase requires a separate explicit authorization after independent review of all prior gates, with capital, max loss, drawdown, kill switch and emergency-stop limits fixed in advance.

**Conclusion:** Rocket Trader now has a materially stronger observe-only research and safety stack. It is not yet a profitable or autonomous trading system, and it is not ready to receive real money. The next highest-value action is to deploy the Paper stack and gather real, auditable operating evidence—not to loosen strategy gates or force trades.


---

## Continuity update — 2026-11-10 (PRs #94–#95 and live audit diagnosis)

**Main baseline reviewed:** `a6f1b92136c041af0084bf28d7e686df0d444725`.

### PR #94 — regime observer readiness semantics
- Health output now distinguishes process/decision liveness from actual market-data readiness.
- Reports `market_data_ready`, `safe_cash` and exposure separately.
- A live process with stale/missing market data is not treated as ready; safe cash remains explicit.
- Regression tests cover stale/missing and fresh-but-cash-only conditions.

### PR #95 — trigger the actual historical audit on main pushes
- The ETF history crosscheck now runs on relevant pushes to `main`, as well as weekly schedule and manual dispatch.
- Offline tests passing is not equivalent to the real provider comparison passing.

### Live audit result — workflow run 42920786498
- Run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42920786498
- Job `130194785274` completed with **failure** at the live 10-year comparison step; dependency installation, compilation, offline tests and artifact upload succeeded.
- All eight symbols (DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT) failed in Yahoo retrieval with `ValueError: output array is read-only`.
- Crucial discrepancy: the executed code still used `yfinance.Ticker(...).history(..., repair=True)`, despite the earlier diagnosis/documentation saying repair had been disabled. The report itself records `repair=True`. This is a source-of-truth mismatch and must be fixed in code, not merely described in docs.
- Artifact ID: `13812205814`. It contains a failure report with zero symbols compared; it is not usable historical evidence.
- No candidate promotion, Paper approval or orders were enabled; `orders_submitted=0`.
- PR #96 merged as `d001fc3f3661b1cae39de535c52b235975f164ae`; it changes the provider call to `repair=False`, updates README/status, adds `ROCKET_TRADER_HANDOFF.md`, and adds a regression test asserting the provider parameter. PR CI run 42922818287 passed all 6 offline tests. The post-merge live-data run 42922974687 was queued; its actual result and artifact review are pending.

### Current continuation point
1. Merge the repair correction only after PR checks pass.
2. Trigger/observe a fresh live crosscheck and inspect the artifact; record actual coverage, overlap and discrepancies. If Yahoo remains unstable, isolate provider/version behavior and choose a defensible alternative source rather than weakening data gates.
3. Close broker activity-to-ledger fill recovery with idempotent reconciliation, including delayed fees, corrections and partial fills.
4. Continue empirical Paper execution-cost collection and confidence/coverage thresholds.
5. Validate regime features and connect the selector in observe-only mode.
6. Complete OOS research, multiple-testing controls and same-period trader/strategy benchmarks.
7. Deploy the Paper stack on the user's persistent host only with the user operating their own secrets; deployment evidence is still absent.

**Progress estimate at this checkpoint: 46%.** This is a conservative engineering/evidence maturity estimate, not a probability of profit. It must increase only when a meaningful end-to-end milestone is implemented and evidenced.



### PR #96 merged — continuity handoff and Yahoo repair correction
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/96
- Merge commit: `d001fc3f3661b1cae39de535c52b235975f164ae`.
- Added `ROCKET_TRADER_HANDOFF.md` as the canonical continuity and working-rules document. README now points new conversations to it first.
- Yahoo historical retrieval now explicitly uses `repair=False`; report metadata reflects the actual setting.
- Added a regression test that mocks Yahoo and asserts `repair=False`, `auto_adjust=True` and `actions=True`.
- PR workflow run 42922818287: compile and all 6 offline tests passed. Live comparison was skipped on pull_request by design.
- Post-merge push run 42922974687 completed successfully as a retrieval/report job. Its diagnostic result is recorded below: all eight ETFs were retrieved, but zero passed the full 10-year coverage gate because Alpaca IEX history begins in 2020 for this account.


### Post-merge live ETF history audit — 2026-11-10 (run 42922974687)
- Run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42922974687
- Artifact: `13812508089` (`rocket-trader-alpaca-yahoo-etf-crosscheck`).
- Yahoo retrieval succeeded after `repair=False`; all eight symbols returned data, with zero provider errors. Workflow job completed successfully.
- This is **not** a full 10-year source parity pass: Yahoo returned 2,512 daily sessions; Alpaca IEX returned 1,582; common sessions were 1,581 from 2020-07-27 to 2026-11-09. Yahoo common-session coverage relative to its full series was 62.94%; IEX was 99.94%. Thus the full-period coverage gate correctly failed for all eight ETFs (0/8 diagnostic passes).
- On the overlap, daily return correlations were 0.99835–0.99975; p95 absolute daily-return differences were 4.69–9.97 bps. However cumulative-return differences ranged from 1.3 bps (DIA) to 220.5 bps (SPY); SPY/QQQ/TLT differences need source-adjustment investigation before providers can be treated as interchangeable.
- The job's green conclusion means data retrieval and report generation completed, **not** that the diagnostic gates passed. The report keeps candidate promotion, Paper approval and orders disabled; zero orders were submitted.
- Interpretation: Alpaca IEX's available history is the binding 10-year limitation. The prior `NOT_ENTITLED` result applied to a recent SIP request ending at current time, not historical SIP. Do not reduce the coverage threshold or splice Yahoo and IEX as if they were one homogeneous series.
- Next: evaluate full-history source alternatives/entitlement economics and separately formalize (a) overlap parity and (b) full-period coverage. Investigate cumulative adjusted-return divergence, especially SPY, before strategy research uses any cross-source history.


---

## Historical continuity ledger added — 2026-11-10
See `ROCKET_TRADER_HANDOFF.md` section 10 for the canonical experiment/decision history, including:
- Jefe Maestro methodology transfer and explicitly excluded lottery-specific features.
- Superseded close-to-close timing research and corrected next-open model.
- Corrected ETF/crypto momentum and mean-reversion results (all 0 Holm-significant candidates).
- IEX/SIP/Yahoo source limitations, Yahoo repair failure and subsequent corrected run.
- BTC Paper execution smoke tests, simulator seed cash, unresolved/delayed fees and JNLC journal handling.
- Lessons from fill ledger, quote/bar heartbeat isolation, market-data readiness, news provenance and observer-only deployment.
- Mandatory append-only change-log template and rules for every future meaningful code or research change.

The canonical Handoff was expanded to prevent repeating failed or superseded experiments. Documentation synchronization does not increase project completion percentage.

PR #101 merged as `e265cc92a0eb931031151d963e1d320ced990cf7`, synchronizing the Handoff and status after PR #100.


---

## 2026-11-11 — PR #100 regime timestamp alignment
- PR #100 merged: https://github.com/marcodurzov/Rocket_Trader/pull/100
- Merge SHA: `81be6e8e1fea127641b760a469ede4f7a56cdff9`.
- Root cause: the observer paired cross-asset returns by array position, not timestamp; missing minute bars could misalign observations and corrupt correlations/regime features.
- Fix: exact UTC timestamp intersection, >=60 common aligned bars, >=95% aligned coverage per symbol, maximum common-series gap 180 seconds, fail-closed on insufficient/stale/unaligned data, and diagnostics persisted.
- Tests: 22 regime observer tests passed; 9 news assessment tests passed; 156 runtime/accounting tests passed; Compose config and Docker image build/content checks passed.
- No allocation/order capability added. Observer remains observe-only and cash-only.
- Predictive value of regime features remains unvalidated; historical point-in-time stability and regime-conditioned performance research are still open.
- The canonical historical experiment ledger is in `ROCKET_TRADER_HANDOFF.md` section 10.


---

## 2026-11-11 — PR #103 broker fill activity reconciliation
- PR #103 merged: https://github.com/marcodurzov/Rocket_Trader/pull/103
- Merge SHA: `7601ec2b5e1cb66d351703eb1de9d6f1347dd311`.
- The runtime now compares staged REST `FILL` activities with the fee/FX-aware ledger inbox using the documented execution UUID identity and checks quantity, price, symbol, side, order ID and timestamp.
- An absent, mismatched, PENDING or FAILED inbox row keeps account-activity health in ERROR; no automatic ledger posting or fill reconstruction was added.
- CI: 8 dedicated reconciliation tests and 32 runtime tests passed; all 166 tests in runtime/accounting workflow passed. Compose/Docker build and post-merge image publication passed.
- Official Alpaca schema mapping documented in `PAPER_OBSERVER_RUNTIME.md` and `ROCKET_TRADER_HANDOFF.md`.
- Actual Paper account/host validation remains pending; no strategy approval or LIVE authorization.
- Handoff main SHA updated to current main `7601ec2b5e1cb66d351703eb1de9d6f1347dd311`.


---

## 2026-11-11 — PR #104 and data vendor evaluation
- PR #104 merged as `53a7fc3b4f7c8fd4530a1818e1fd9d31700e5dc1`; Handoff now records PR #103 fill reconciliation.
- Official provider research: Tiingo Starter lists 5-year history free; Power lists 15+ years at $30/month or $300/year for individuals, with internal-use license. Tiingo documents adjusted OHLC and CRSP-style split/dividend adjustments. Alpha Vantage lists 25+ years adjusted daily but the adjusted endpoint is premium and free API quota is 25 requests/day.
- No subscription or vendor expense authorized/performed. Tiingo is the best candidate for an optional provider adapter, subject to secure token configuration and separate approval for any paid plan.
- Canonical Handoff contains source links, provider constraints and next actions. See section 10.10.


---

## 2026-11-11 — PR #106 optional Tiingo source
- PR #106 merged: https://github.com/marcodurzov/Rocket_Trader/pull/106
- Merge SHA: `775186e104a485bbc07b50a5dcc807723aced240`.
- Added optional Tiingo adjusted EOD source to ETF research, secure token via `TIINGO_API_TOKEN`, strict history/coverage checks, and workflow source option. No fallback or splicing.
- Corrected stale Yahoo report metadata from `repair=True` to actual `repair=False`.
- PR workflow 42954001467: self-test and 19 offline equity tests passed. Live research skipped on PR.
- Post-merge Yahoo research run 42954130155 was in progress at this update; no Tiingo request was run because no token/paid plan is configured.
- Post-merge runtime/accounting run 42954130244 passed all 166 offline tests.
- No subscription purchased; no strategy approvals or orders.


---

## 2026-11-11 — PR #108 and post-merge v0.4 consistency run
- PR #108 merged as `aaf4cf02c3d04c77925357df7687a1f9946abe2f`; Handoff synchronized after PR #106.
- Post-merge research run 42954130155, artifact 13826686266: Yahoo 10-year data retrieval and quality passed for all 8 ETFs; report metadata correctly records `repair=False`.
- This repeated the existing v0.4 research family as a regression/consistency check, not a new hypothesis. Family size 73, Holm-significant 0, pre-screen 0, candidate promotion false, Paper approval false, orders 0.
- No Tiingo API call or subscription; only mocked contract tests. Independent cross-source validation remains open.
- No progress percentage increase.


---

## 2026-11-11 — post-merge 10-year Yahoo research result
- Workflow `42954130155` succeeded; artifact `13826686266`; 10-year Yahoo data returned for all 8 ETFs.
- 2,511 daily bars per symbol, approximate weekday coverage 96.32%, maximum gap 4 days; data-quality gate passed all 8.
- 73 final-holdout hypotheses; pre-screen pass 0; Holm-Bonferroni significant 0. No candidate promoted; Paper approval false; orders disabled; zero orders submitted.
- Research cost assumption remains placeholder 5 bps per side, not empirical. The run used Yahoo, not Tiingo or Alpaca; it does not resolve prior IEX cumulative adjustment divergence (up to 220.5 bps SPY).
- Artifact SHA256: `6929f6156d5c55665023fb0bcb007a311962c0c70e5837328a8d72e8656f9d0e`.
- Paper runtime/accounting post-merge CI `42954130244` passed 166 tests; no persistent user-host Paper evidence.
- Main baseline SHA at this update: `aaf4cf02c3d04c77925357df7687a1f9946abe2f`; progress unchanged at 46%.


---

## 2026-11-11 — PR #111 optional three-source audit
- PR #111 merged: https://github.com/marcodurzov/Rocket_Trader/pull/111
- Main SHA: `6a2cfd760d707da9eb8a1ba1f640e8db834a9aab`.
- Optional Tiingo adjusted close source added to the existing read-only Yahoo/Alpaca audit. If configured, emits Tiingo-vs-Yahoo and Tiingo-vs-Alpaca reports; no token means no Tiingo call.
- Strict coverage gate intentionally rejects 10-year Tiingo/IEX parity while Alpaca IEX has only ~6.3 years; no splicing or fallback.
- CI run `42954914689`: all 9 cross-check tests passed. Live data skipped on PR.
- Post-merge runs `42955004812` (data audit) and `42955004617` (Paper runtime) pending at update time.
- No token/subscription, no order changes. Progress remains 46%.


---

## 2026-11-11 — PR #111 post-merge results
- Audit run `42955004812` succeeded; artifact `13827085617`. Tiingo token absent, so no Tiingo request was made.
- Yahoo: 2,513 sessions per ETF; Alpaca IEX: 1,582 sessions (SPY 1,583). Common period 2020-07-27 to 2026-11-10; Yahoo common coverage 62.95%, IEX 100%; 0/8 pass the 95% full-period coverage gate.
- Daily return correlation 0.99835–0.99975 but cumulative return difference Alpaca minus Yahoo: -0.75 bps IWM to +218.90 bps SPY; QQQ +89.98 bps; TLT +26.01 bps. Provider adjustment divergence remains unresolved.
- Runtime CI `42955004617`: 10 test modules passed, 95 tests aggregate.
- No Paper deployment evidence, empirical costs, strategy approval or orders. Progress 46%.


---

## 2026-11-11 — PR #113 date-level divergence diagnostics
- PR #113 merged: https://github.com/marcodurzov/Rocket_Trader/pull/113
- Main SHA: `6ac4caa90de52ad1d1faefedbe301997b2360480`.
- Audit now records top 10 daily-return divergence dates and top 10 normalized adjusted-close path divergence dates per symbol.
- CI `42955368774`: 10 cross-check tests passed; live data skipped on PR.
- Post-merge audit `42955455037` and runtime suite `42955454994` pending at update time.
- No provider correction, Tiingo request, strategy approval or orders. Progress remains 46%.


---

## 2026-11-11 — PR #113 post-merge outlier dates
- Live audit `42955455037` succeeded; artifact `13826901809`; 10 cross-check tests passed.
- Largest daily return differences (Alpaca minus Yahoo): QQQ 2024-12-24 +99.46 bps / 2024-12-23 -96.26 bps; SPY 2025-04-09 -116.67 bps / 2025-04-10 +100.78 bps; EEM 2024-12-24 +52.14 bps; DIA 2024-12-23 -71.42 bps; EFA 2024-12-23 -77.85 bps; TLT 2026-11-02 +39.82 bps; GLD 2021-06-21 -31.50 bps; IWM 2026-06-26 -70.36 bps.
- QQQ 2024-12-23 is a documented $0.83466 ex-dividend date (Tiingo history). This event is only a hypothesis for follow-up; amount does not fully explain observed ~1% differences. SPY outlier is 2025-04-09/10; its Q1 2025 ex-date was 2025-03-21. No cause assigned.
- Opposite-signed adjacent-session outliers could indicate timing/adjustment mapping, but not proven.
- Cumulative divergences: SPY +218.91 bps, QQQ +89.98 bps, TLT +26.02 bps. 0/8 pass full-period coverage due IEX 6.3-year limit. No Tiingo token configured.
- Runtime suite `42955454994` passed. Progress remains 46%.


---

## 2026-11-11 — PR #115 raw/adjusted factor reconciliation
- PR #115 merged: https://github.com/marcodurzov/Rocket_Trader/pull/115
- Main SHA: `60059a41379b274ae16a8b20426bbcf96178ae7`.
- Added Yahoo raw/adjusted close and Alpaca RAW/ALL bar comparison; calculates adjustment factors, factor step changes, and separate raw-price divergence.
- PR CI run `42955793577`: all 12 cross-check tests passed. Live data step skipped on PR.
- No post-merge live workflow run yet surfaced for merge SHA; pending verification.
- No attribution or data correction, no Tiingo token, no strategy approvals or orders. Progress remains 46%.


---

## 2026-11-11 — PR #115 post-merge raw/adjusted factor audit
- Live audit `42955879451` succeeded; artifact `13825994525`; 12 cross-check tests passed. Runtime suite `42955879365` succeeded.
- Common raw/adjusted history: 1,582 sessions (SPY 1,583).
- Max normalized adjustment-factor divergence: QQQ 0.327844%, TLT 0.422290%; others <=0.022282%.
- Largest QQQ factor step: 2022-09-19 +17.6852 bps, same date as documented $0.51856 distribution. Largest TLT step: 2026-11-02 +41.7148 bps, same date as iShares official $0.343177 distribution.
- This strongly suggests dividend adjustment handling contributes to these two factor divergences, but does not prove which vendor is right or explain all discrepancies.
- Raw price series still diverge: max normalized raw close difference QQQ 0.9620%, SPY 0.8381%, TLT 0.2633%; p95 absolute raw daily return difference 4.69–9.94 bps.
- Tiingo token absent; no Tiingo comparison. No strategy approval or orders. Progress remains 46%.


---

## 2026-11-11 — Ten-year Alpaca IEX vs Yahoo crosscheck
- Workflow `42955879451` succeeded; artifact `13825994525` downloaded and inspected.
- Ten-year request, 8 ETFs. Alpaca IEX only 1,582–1,583 sessions since 2020-07-27 vs Yahoo 2,513; common-session IEX coverage approx. 62.95%. All 8 symbols failed minimum source coverage; 0/8 passed all diagnostic gates.
- Common-period daily return correlation high (0.99835–0.99975), but p95 absolute daily-return differences 4.69–9.97 bps and max outliers 31.5–116.7 bps. Cumulative differences (bps): DIA +5.47, EEM +8.82, EFA +1.22, GLD +3.29, IWM -0.75, QQQ +89.98, SPY +218.89, TLT +26.02.
- No Tiingo comparison run (0 symbols); this does not validate PR #106 adapter. No errors in workflow, but diagnostic failed because IEX lacks full decade.
- No strategy promotion, Paper approval or orders. Research costs still unvalidated.
- Next: exchange-session calendar, investigate outlier corporate-action dates and provider adjustments, perform Tiingo live validation only with token/eligible plan and explicit no-spend approval, preserve separate provider series.


---

## 2026-11-11 — PR #119 live adjustment factor result
- PR #119 merged: https://github.com/marcodurzov/Rocket_Trader/pull/119; main code SHA `0c3c815437e747f82615b3900cc8cfc7d4ce0066`.
- Live audit `42956264138` succeeded; artifact `13827440846`; all 12 cross-check tests passed. No Tiingo token configured.
- QQQ 2022-09-19: factor ratio Alpaca/Yahoo 0.9982218617 on prior session, 0.9999843173 on ex-date; +17.6820 bps. Distribution $0.51856/share.
- TLT 2026-11-02: factor ratio 0.9958460599 on prior session, 1.0000000000 on ex-date; +41.7148 bps. iShares distribution $0.343177/share.
- Both suggest dividend adjustment handling differences; no provider declared correct. Full 10-year coverage gate 0/8. No approvals or orders. Progress 46%.


---

## 2026-11-11 — PR #124 cash-action comparison
- PR #124 merged: https://github.com/marcodurzov/Rocket_Trader/pull/124
- Main SHA: `ca0450287284af014e68bd5e31d05e641b8d110d`.
- Yahoo action fields (dividends/splits) and prior raw closes are now included around top adjustment-factor step dates; report computes approximate cash-dividend scale in bps for comparison.
- CI `42956965526`: 12 cross-check tests passed after correcting an overly precise assertion; live data skipped on PR.
- Post-merge live audit pending. No vendor attribution, Tiingo token, orders or approvals. Progress 46%.


---

## 2026-11-11 — PR #124 live event-level dividend audit
- Live audit `42957082760` succeeded; artifact `13827412712`; 12 cross-check tests passed. Tiingo not requested (no token).
- QQQ 2022-09-19: Yahoo action `$0.519`; previous raw close `$289.32`; expected cash adjustment scale 17.9386 bps. Relative Alpaca/Yahoo factor ratio moved 0.9982217537 -> 0.9999841026 (+17.6809 bps). This is close to one dividend factor but the difference direction requires checking whether Alpaca applies an extra adjustment.
- TLT 2026-11-02: Yahoo action feed reports $0.00; previous raw close $81.84; Alpaca/Yahoo factor ratio 0.9958460599 -> 1.0000000000 (+41.7148 bps). iShares official issuer record lists $0.343177 distribution that date, equivalent to ~41.93 bps of prior price. Strong evidence Yahoo action/adjustment history misses or differs on this event.
- 0/8 full-period coverage gate still passes; no Tiingo data, no source splicing, no strategy/Paper approvals or orders.
- Progress remains 46%.


---

## 2026-11-11 — PR #123 XNYS calendar correction and post-merge validation
- PR #123 merged as `f408204044fcff449bd615301a0bf2503a4d1db0`.
- Replaced weekday counting with the actual XNYS session calendar. Quality report uses expected/missing exchange sessions and exchange-session coverage; existing 95% and 7-day thresholds unchanged.
- Tests explicitly prove July 4, 2024 is not an expected session and missing July 2 is detected. PR CI passed self-test + 21 regression tests.
- Main v0.4 workflow `42957425769` passed full ten-year research and uploaded artifact `13828111119`; main runtime workflow `42957425751` passed. Legacy research workflows v0.2 `42957425803` and v0.3 `42957425736` also passed.
- Actual v0.4 Yahoo data: 8 ETFs, 2,511 XNYS sessions each, 2,511 observed bars, 100% coverage, zero missing sessions, max gap 4 days. Earlier approximate weekday coverage 96.32% is superseded and was caused by counting market holidays.
- Research result unchanged: 73 hypotheses, Holm significant 0, pre-screen 0, no strategy promotion, no Paper approval, no orders.
- Alpaca IEX 10-year coverage still only ~63%, 0/8 cross-provider coverage passes. Tiingo not live-tested.
- Next: investigate IEX/Yahoo adjustment outliers; live Tiingo parity only if eligible token/plan is separately configured; no source splicing; preserve all negative strategy results.


---

## 2026-11-11 — Event-level IEX/Yahoo divergence findings
- Re-examined artifact `13827412712` from run `42957082760`.
- Official Alpaca docs distinguish IEX (single exchange, approx. 2.5% volume) from SIP (all US exchanges/consolidated tape). IEX is therefore not suitable as a full-market close proxy.
- SPY cumulative difference +218.90 bps, but max adjustment-factor divergence only 0.004489%; raw normalized-close divergence max 0.8381%. Largest raw return differences: 2025-04-09 -116.75 bps; 2025-04-10 +100.69; 2024-12-24 +93.92; 2024-12-23 -91.53. Likely raw feed price mismatch, exact trade cause not proven.
- QQQ adjustment-factor max divergence 0.327819%; 2022-09-19 Yahoo action feed shows $0.519 dividend and relative factor step 17.68 bps (~17.94 bps implied by distribution/prior raw close). Exact provider mechanism unproven.
- TLT adjustment-factor max divergence 0.422290%; official iShares reports $0.343177 ex-distribution 2026-11-02. Prior Yahoo raw close $81.84 implies ~41.93 bps; audit shows Yahoo cash action 0 and no factor step, while Alpaca relative factor step is 41.7148 bps. Consistent with Yahoo event adjustment not yet reflected in that capture; must re-query.
- Conclusion: mixed provider issues; raw-price differences dominate SPY, adjustment-factor mismatches matter for QQQ/TLT. Neither IEX nor Yahoo alone is certified as institutional-grade truth. Tiingo not live-tested. No subscriptions/spend approved.


---

## 2026-11-10 — Historical trading research and adaptive architecture baseline
- Added canonical document: `TRADING_RESEARCH_LANDSCAPE_AND_ADAPTIVE_ARCHITECTURE.md`.
- Corrected project-history statement: the complete historical/practitioner/academic/open-source/community survey had not previously been done. Earlier work tested selected ML/technical methods and strategy families only.
- Document covers history through 2026-11-10, strategy taxonomy, regime detection, meta-allocation, online adaptation, news/social/geopolitical evidence, risk, historical failures, successful trader/institution benchmarking, GitHub ecosystem, books/forums, research gates, source map and working rules.
- Research conclusion: architecture should be regime-aware and multi-strategy, with cash/abstention, robust sizing, hysteresis, drift monitoring, challenger testing and strict bounded experimentation. No single model should self-promote or trade from raw LLM/news text.
- Preserved prior negative results: Oct ML/SPY/QQQ experiment, ETF v0.5 (0/97), crypto v0.4 (0/25; SOL data 77.1%), and v0.4 ten-year ETF report (0/73 significant; 0 pre-screen).
- v0.4 live run 42954130155 artifact 13826686266: 8 ETFs, 2,511 Yahoo bars each, 73 tests; Holm significant 0, pre-screen 0, no promotion/Paper/orders. Top-1 cross-sectional excess looked positive but bootstrap p=0.3985, Holm p=1.0, q05 excess -31.56pp. Cost assumption 5 bps/side is not measured.
- Research is curated, not an exhaustive internet crawl; preliminary and practitioner evidence is labeled. Public claims are not treated as independently audited performance.
- No new strategy approval, no paid data subscription, no live deployment or orders. Progress remains 46%.
- Next: hypothesis registry; source adjustment audit; wider point-in-time OOS tests; regime model comparison; adaptive selector validation; news/social incremental tests; Paper cost/accounting and fault validation.


- 2026-11-10 follow-up: added specific dated r/algotrading threads on regime/HMM uncertainty, backtest-to-live execution failures, regime switching, strategy decay and overfitting. Evidence class: anecdotal only; no profitability claims accepted.


---

## 2026-11-11 — PR #131 and post-merge audit rerun
- PR #131 merged as `097dd10932ed7ed2e993a2b2110cb7f728450d8b`.
- Tiingo status is tri-state: with no token, `NOT_REQUESTED`, `tiingo_all_diagnostic_gates_pass=null`, zero symbols. Absent data is not a pass.
- PR audit workflow `42958291332` passed offline tests. Main runtime `42958406230` passed. Main crosscheck `42958406136` passed; artifact `13827124135` inspected.
- Re-run still reports Yahoo dividend action = 0 and no Yahoo factor step for TLT on 2026-11-02, nine days after official iShares ex-distribution $0.343177; Alpaca factor step 41.7148 bps vs ~41.93 bps implied by official distribution/prior raw close. Persistent unresolved Yahoo corporate-action discrepancy.
- Overall IEX/Yahoo gates false; no strategy promotion, Paper approval or orders. Tiingo not compared.


---

## 2026-11-11 — Paper activity diagnostics and journal recovery

### PR #154 — safe audit diagnostics
- Merged: `7aa7b8d5acaf0b5247c316842ec4824fb6f9c907`; PR CI `43020664640` and post-merge static CI `43031972951` succeeded.
- The manual Paper audit run `43020228954` failed in the activity audit. Before PR #154, the CLI suppressed the safe validation detail. The fix reports safe internal validation text and bounded exception class/HTTP status metadata, never raw SDK exception text.
- The failed-run artifact is `13853579473`; it predates the fix and does not identify the underlying cause. The actual Paper activity API failure remains pending a new manual dispatch.

### PR #155 — explicit read-only journal recovery
- Merged: `829e17343b7073e77ad1fd16ebc2611be2d88641`; PR CI `43032346333` succeeded. Post-merge CI `43032427138` pending at the time of this update.
- Added `recover_journaled_orders()` to scan the execution journal, re-query broker state by client order ID, and reconcile FILL activity for every discovered broker order.
- Missing broker orders, incomplete/mismatched fill activity and exceptions remain unresolved. The method never submits, cancels or replaces orders.
- Four offline recovery tests cover successful zero-fill reconciliation, missing broker order, filled-order FILL matching and repeat-run idempotency.
- This is an explicit recovery method only. Automatic process-startup invocation, continuous scheduling, durable activity cursors and correction/bust ingestion are not implemented.

### Current verified boundary
- Main HEAD: `829e17343b7073e77ad1fd16ebc2611be2d88641`.
- Progress remains **54%**; no increase for a method that is not yet wired into a persistent runtime.
- No strategy is approved, no autonomous strategy order execution is enabled, and LIVE remains prohibited.


---

## 2026-11-11 — One-shot execution recovery runner (PR #157)
- Merged: `adab3f2bc29e71be788fa47335f73e0cce9830fc`; PR CI `43032980158` succeeded. Post-merge run `43033056053` pending at documentation time.
- New runner `alpaca_paper_crypto_execution_recovery_worker.py` uses the existing durable execution journal and immutable event ledger, checks both files exist before adapter construction, verifies Paper cash-only policy, and invokes read-only recovery for all journaled orders.
- It does not submit, cancel, replace or modify broker account configuration. Unresolved broker orders or fill activity cause a nonzero exit and require review.
- Added offline runner tests and CI coverage; deployment runbook documents the explicit one-shot host command.
- This is not yet a continuous worker or automatic startup gate. The eventual persistent execution service must call it before accepting new intents and share the same durable DB files.
- No live Paper endpoint was called by this PR; no strategy approval or autonomous trading was enabled.
- Progress remains **54%**.


---

## 2026-11-11 — Real Paper FILL reconciliation and CFEE correction (PR #159)
- Manual run `43034874861`, job `130570956064`, reached Alpaca Paper and passed ACTIVE/USD/crypto ACTIVE/cash-only/no-short preflight.
- Two actual smoke orders were found and matched against broker FILL activities: BUY 0.000133206 BTC; SELL 0.000132872 BTC. Both activity quantities matched the broker order snapshots.
- The audit then failed in account-wide CFEE processing because a fee activity had a symbol that was not parseable as BASE/USD. This was a collector bug, not an Alpaca connection or FILL reconciliation failure.
- PR #159 merged `60ff6607780f66fb830a0629fd5cb7047c46e7ea`. CFEE records are now preserved as unallocated evidence and classified target/other/unclassified; incomplete fields are flagged, never assumed zero. FILL status remains separate from fee evidence quality.
- PR checks `43035761377` and `43035761387` succeeded. Post-merge activity CI `43035852426` succeeded; post-merge static audit CI `43035852875` pending at this note.
- Manual post-fix Paper audit remains required. Fees are not yet attributed to the buy/sell order and remain unverified.
- No new order was submitted; Live remains prohibited.
- Progress: **55%** (engineering/evidence maturity, not profitability).


---

## 2026-11-11 — Paper audit result and CFEE window hardening (PR #161)

- Manual Paper run `43036761702` completed successfully on main SHA `57ea51c95df7c2660027f26c2136e6c9490f78b5`.
- Account preflight: `ACTIVE_USD_CASH_ONLY_NO_SHORT`.
- Both actual BTC/USD smoke orders matched their broker FILL activity quantities: BUY `0.000133206 BTC`; SELL `0.000132872 BTC`. There were no unmatched orders.
- The audit returned three target-symbol CFEE records and three unclassified CFEE records. Two target-symbol records and two unclassified records had `created_at` timestamps before the requested fee-window start (2026-11-11 04:55 UTC). The remaining in-window records were one BTC-denominated quantity `-0.000000334 BTC` and one unclassified USD amount `-0.03 USD`, both unallocated and without documented order linkage. No exact order-level cost was established.
- PR #161 merged as `62a0ac24b52c9057020e6728ca30be5eaebcdc74`. CFEE evidence is now checked locally against broker `created_at` and requested `after`/`until` bounds. Out-of-window and unverified records remain in the append-only ledger but are excluded from interval-specific candidate counts. The audit report and summary expose these counts and window boundaries.
- PR checks: `43037441267` and `43037441187` succeeded. Post-merge checks: `43037526916` and `43037526946` are to be finalized after their workflow conclusions are available. Live Paper audit job is intentionally skipped on push/PR.
- **Next verification:** manually dispatch the read-only Paper activity audit again using the same BTC/USD order window and fee window. Expect the two earlier target CFEE and two earlier unclassified CFEE records to appear as out-of-window, not as in-window candidates. Do not infer attribution of the remaining BTC and USD CFEE records.
- No new order, cancellation, replacement, or account configuration mutation occurred. LIVE remains prohibited.
- Progress remains **55%** (engineering/evidence maturity, not profitability).


---

## 2026-11-11 — Fail-closed Paper execution startup gate (PR #163)

- PR #163 merged as `a12e69fe1f7fe18f0ed21f99cb4c347de26850fa`.
- Added `PaperCryptoExecutionService`, which keeps process-local submission readiness closed until account cash-only preflight and read-only reconciliation of every journaled order succeed.
- The storage factory refuses missing files, checks the existing journal schema, event-ledger schema and append-only triggers, and verifies that each journaled order has immutable preparation/discovery evidence before adapter construction. It requires Paper mode and creates the adapter without an injected broker client so the adapter's `TradingClient(..., paper=True)` path is used.
- Any malformed/unresolved recovery, account-policy mismatch, stop, or adapter submission exception closes the gate. The host must run a fresh successful recovery pass before accepting another intent.
- Offline tests cover the gate, durable-state requirements, Paper-only preflight, unresolved/malformed recovery, error closure and idempotent startup. PR CI `43038167066` passed 65 tests; post-merge CI `43038263626` pending at documentation time.
- No broker orders were submitted by PR #163. The module is not deployed or integrated into the observe-only Compose stack; no strategy-driven execution is enabled.
- Next: use this wrapper in a separately deployed persistent Paper execution host only after the user deploys/configures the durable journal and event ledger. Validate restart recovery on that host. Keep the next manual read-only CFEE-window audit outstanding.
- Progress remains **55%** (engineering/evidence maturity, not profitability).


---

## 2026-11-11 — Alpaca Paper Activity SSE capability probe (PR #165)

- PR #165 merged as `7d92fd7aaa352087552129d02c6e4c4bee24b3fd`.
- Added a bounded read-only historical probe of `/v2beta1/events/activities` to the manual Paper activity audit. It uses the configured Paper API credentials and queries from the order-window start through current UTC time.
- The probe reports activity type counts, crypto-like TRD records, CFEE/FEE counts, fill/correction/bust execution types, `previous_id` links, duplicate refs, event ordering anomalies, dropped-message comments and malformed frames.
- It does not maintain a cursor, change the event ledger, apply trade corrections/busts, mutate positions or submit orders.
- Official Alpaca documentation describes the endpoint's replayable `event_id` cursor, `ref_id` deduplication and `previous_id` correction link. However, the published TRD schema is described as equity/options; crypto support for this Paper account must be verified empirically before implementing a production consumer.
- PR CI `43038829544` passed 32 offline tests. Post-merge CI `43038939488` pending final conclusion. The Paper endpoint job remains manual-only.
- Next: user dispatches the updated read-only Paper activity audit once. Inspect both `paper-activity-report.json` and `paper-activity-sse-probe.json`. Only after actual crypto TRD/correction evidence is confirmed should cursor ingestion or accounting reversal logic be designed.
- Progress remains **55%** (engineering/evidence maturity, not profitability).


---

## 2026-11-11 — Paper Activity SSE confirmed and durable service prepared

### Real Paper evidence — run 43042768582
- Account preflight: `ACTIVE_USD_CASH_ONLY_NO_SHORT`; 2/2 BTC/USD smoke order FILLs matched.
- Activity SSE HTTP 200 returned six events: 2 TRD, 2 CFEE, 2 JNLC. Both TRD fills were BTC/USD and matched the known BUY and SELL broker/client order IDs.
- No dropped messages, duplicate refs, event-order anomalies, malformed events/frames or orphan previous IDs. No corrections/busts observed in this small window.
- One in-window CFEE: `-0.000000334 BTC` with `0 USD`; one unclassified CFEE: `-0.03 USD`. Both complete but unallocated. Four out-of-window CFEE records excluded. No order-level attribution is established.

### PR #167 — durable Activity SSE inbox
- Reconnectable Paper-only consumer with atomic SQLite event/delivery/cursor transaction, immutable evidence tables, SHA-256 chain, stable-ref idempotency, conflict detection, dropped-message replay and `since_id` recovery.
- Corrections and busts are staged only, not financially applied.
- PR CI 21 offline tests passed; post-merge CI succeeded.

### PR #168 — Compose deployment preparation
- Separate Paper-only Activity SSE service on the shared persistent Docker volume, dedicated DB, Docker image packaging, healthcheck, and reconnect logs.
- Compose config validation, Docker image build/package verification, and observer runtime tests passed on the PR.
- Not deployed. Actual host access and private Paper credentials remain an operator deployment step.
- No broker orders or account configuration changes.

**Progress: 56%** (engineering/evidence maturity, not profitability).


---

## 2026-11-11 — Activity SSE deployment hardening

- PR #170 merged: publisher path filters now rebuild the observer image when the Activity SSE consumer source changes. GHCR image publication after PR #168 succeeded; PR #170 publication run `43044264217` succeeded.
- PR #171 merged as `8bf6d6a2560806a4b2b2aa04c92f8576c571f094`. Healthcheck no longer initializes a missing DB. It opens an existing DB without creating a replacement, checks append-only triggers, hash chain, payload fingerprints, delivery consistency and cursor ordering.
- PR #171 CI `43044388062` passed 26 offline tests; Compose validation, Docker build and in-image compilation succeeded in `43044387984`. Post-merge consumer tests `43044515041` passed; image publication `43044515119` was pending at note time.
- Healthcheck covers local persistence integrity only, not API connectivity; reconnect errors are emitted to container logs.
- **Deployment remains pending:** no server has been connected/deployed from this session. Actual durable-volume restart test is required before claiming persistent recovery works in production.
- Progress remains **56%** (engineering/evidence maturity, not profitability).


## 2026-11-11 — Alpaca corporate-action parity and 10-year ETF audit findings

### Merged engineering changes

- PR #173 merged: records user's USD 0 target, Paper-only boundary and absence of a known persistent host.
- PR #174 merged: audits free GitHub Actions/GHCR options, schedule limits, Alpaca Basic IEX limitations and Live jurisdiction caveat.
- PR #175 merged: ports Alpaca issuer corporate-action reconciliation onto current ETF cross-check code while preserving current Tiingo/data-quality logic. PR #127 was closed as superseded, not merged from its stale branch.
- PR #176 merged: corrects the documented Alpaca response envelope. Corporate-action arrays are nested under top-level `corporate_actions`; parser now validates the envelope and fails closed if missing.
- PR #177 merged: retains corporate-action IDs and prevents aggregation when multiple cash-dividend records exist for the same symbol/ex-date. It reports `MULTIPLE_RECORDS_REQUIRES_REVIEW` rather than inventing a total.
- Offline ETF audit tests passed successively: 17 tests in PR #175, 18 in PR #176, 19 in PR #177. Post-merge observer runtime/accounting tests also passed in run `43078281988`.

### Real read-only Paper data audit after PR #177

- Workflow run `43078282153` completed successfully. It queried the 10-year window 2016-11-11 through 2026-11-11 for DIA, EEM, EFA, GLD, IWM, QQQ, SPY and TLT using Alpaca IEX and Yahoo adjusted daily history.
- Alpaca Corporate Actions returned **410 records** and the response envelope was valid; no API error occurred. Tiingo comparison was `NOT_REQUESTED`; no paid data source was called.
- **0 of 8 ETF symbols passed the overall 10-year source-overlap diagnostic.** All eight passed minimum common sessions, daily-return correlation and the p95 return-difference threshold, but all eight failed the minimum full-history-overlap gate because Alpaca returned a shorter date range.
- Common sessions represented approximately **62.98% of Yahoo's full 10-year returned sessions** and **99.94% of Alpaca IEX's returned sessions**. The key limitation is a shorter Alpaca history horizon, not evidence of a 37% daily-bar omission rate inside the available IEX window. For seven ETFs Alpaca begins 2020-07-27; SPY begins 2018-11-01. Within the shared date window, the observed session sets are almost identical. Do not treat IEX as a 10-year history source for this account, but do not label the 37% horizon difference as missing daily bars.
- The audit is not a strategy test and does not validate the 5 bps/side ETF cost placeholder, fills, market impact, or profitability. `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_enabled=false`, `orders_submitted=0`.
- Useful issuer-action examples: EEM 2023-06-07 returned one cash-dividend record at USD 0.310139; TLT 2026-11-02 returned one at USD 0.343177. QQQ 2022-09-19 returned two distinct Alpaca IDs, both USD 0.51856, with different process/payable dates (2022-09-23 and 2022-10-31). The report now flags this as ambiguous and does not sum it. Resolve against the issuer's official distribution notice before using it as a reference.
- The first run after PR #175 incorrectly returned zero actions because the parser read arrays from the wrong response level. PR #176 fixed the envelope; the corrected run returned 410 records. Do not cite the earlier zero-count result as evidence of no issuer actions.

### Next data-source decision

- Keep Alpaca Basic IEX as the zero-cost Paper execution/data connection, but do not use its observed sparse history as the sole source for long-horizon ETF backtests.
- Evaluate free historical sources (Yahoo and other genuinely free, legally usable sources) for complete adjusted daily bars; cross-validate dates, actions, splits, dividends and survivorship/adjustment conventions. Use issuer records as the reference for declared distributions.
- Recent/live SIP streaming and SIP data inside the latest 15 minutes require the paid Algo Trader Plus plan and remain unauthorized. Historical SIP ending at least 15 minutes ago is available on Basic at $0. Tiingo paid plan remains unauthorized. Do not activate or consume any paid provider without explicit approval.
- Before any candidate can pass, the data gate must require adequate coverage from the actual primary backtest source and a second independent reference; missing sessions must be measured by date and reason, not hidden by inner joins.
- The continuous Activity SSE service remains undeployed. No persistent host has been identified; continue with GitHub Actions for bounded tests/research and do not represent it as a 24/7 runtime.

**Progress estimate: 57%** (engineering/evidence maturity, not profitability). The increase from 56% reflects a working, schema-validated corporate-action data path and a completed 10-year coverage audit; it does not mean any strategy passed or that trading is ready.


## 2026-11-11 — Zero-budget provider hardening and statistical ETF research

### PR #179 merged

- PR #179 merged at main commit `31923c5b6d8e57e1525ad5e3d3d6500df4a74e34`.
- PR #179 initially restricted research to IEX under the assumption that SIP required a paid plan. That restriction is superseded by the historical-SIP correction below: Alpaca Basic permits SIP for historical requests whose `end` is at least 15 minutes old.
- Equity research v0.1–v0.4 now reject SIP in code and CLI. Their GitHub Actions workflows no longer offer SIP.
- Public equity research v0.4 no longer offers Tiingo as a primary source and no longer receives `TIINGO_API_TOKEN`.
- The public ETF cross-check workflow does not inject Tiingo credentials and does not opt in. Its optional Tiingo comparison is disabled unless a local/programmatic caller explicitly sets `include_tiingo` and supplies a token; the zero-cost Starter comparison is limited to five years. No Tiingo account was created and no Tiingo request was made.
- The scheduled entitlement probe is now an IEX-only health probe. Its successful run `43080158991` returned IEX `AVAILABLE` (5 bars); SIP was intentionally not queried because this workflow checks the recent/live free feed. Historical SIP is separately allowed only with a 15-minute-safe end.
- Repository audit identified the four ETF research workflows, the ETF cross-check workflow and the entitlement probe as the relevant SIP/Tiingo workflow surfaces. Those public paths have now been hardened.
- Post-merge workflow runs for the IEX probe, ETF cross-check and research versions 0.1–0.4 all completed successfully: `43080158991`, `43080158893`, `43080158810`, `43080158982`, `43080158898`, and `43080158764`.

### Actual research outputs (read-only; no orders)

- ETF cross-check run `43080158893`: 10-year window, 8 ETFs, Alpaca IEX vs Yahoo adjusted daily bars. The audit returned `ok=true` but `all_diagnostic_gates_pass=false`; all eight symbols failed the 10-year history-overlap gate. Common sessions were 62.98% of Yahoo's full history and 99.94% of Alpaca IEX's returned sessions. This reflects Alpaca's later first available date (seven ETFs 2020-07-27; SPY 2018-11-01), not a demonstrated 37% internal IEX missing-session rate.
- Equity research v0.1 run `43080158810`: 5-year Alpaca IEX, 8 ETFs; data quality passed for all eight. This version is exploratory and does not apply the later family-wide multiple-testing test; no candidate was promoted or Paper-approved.
- Equity research v0.2 run `43080158982`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Holm-Bonferroni family size 49, 5,000 centered moving-block bootstrap replicates per hypothesis, alpha 0.05. Family-wise significant hypotheses: 0; pre-screen passes: 0.
- Equity research v0.3 run `43080158898`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Same 49-hypothesis Holm-Bonferroni framework; family-wise significant hypotheses: 0; pre-screen passes: 0.
- Equity research v0.4 run `43080158764`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Expanded family size 73 with additional RSI(2), Bollinger and z-score mean-reversion variants; 5,000 centered moving-block bootstrap replicates per hypothesis; family-wise significant hypotheses: 0; pre-screen passes: 0.
- The v0.2–v0.4 methodology uses chronological 60% train / 20% validation / 20% final holdout; signals from completed daily close and next-session execution assumptions; long-only, no leverage/shorts/options/futures; base cost placeholder 5 bps per side and a 2x stress case. The 5 bps assumption remains a placeholder, not broker-validated execution cost.
- All four research artifacts explicitly report `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_enabled=false`, `orders_submitted=0`. The ETF cross-check artifact reports the same no-promotion/no-order state. No order was placed by these runs.
- The honest conclusion is that none of the tested ETF hypotheses currently qualifies for promotion. This does not prove that no profitable strategy exists; it means this tested family did not produce statistically defensible candidates under these data, costs and validation gates.

### Next work

1. Continue research without paid feeds: improve date-level data completeness diagnostics, identify an independently usable free adjusted-history source, and validate its adjustment methodology and terms before use.
2. Expand strategy families only with a pre-registered hypothesis budget and multiple-testing control; avoid data-mining the same holdout repeatedly.
3. Add independent replication and additional chronological/walk-forward regimes before any strategy can be considered for Paper observation.
4. Keep all strategy promotion, Paper approval and order submission disabled until the data, statistical, execution-cost, risk and operational gates pass.
5. Continue investigating a persistent host that costs USD 0 and is already available to the user. GitHub Actions is for bounded CI/research, not a 24/7 trading runtime. No host has been identified or deployed.

**Progress estimate: 58%** (engineering/evidence maturity, not profitability). The increase from 57% reflects merged zero-budget safeguards and completed statistical research workflows. It does not indicate strategy success, production deployment, Paper approval or readiness for Live.

## 2026-11-11 — Correct interpretation of Alpaca IEX vs Yahoo history coverage

The earlier wording that described Alpaca IEX as the "sparse side" or implied a 37% internal missing-bar rate was inaccurate and is superseded by this correction.

The artifact from run `43080158893` shows:
- Seven ETFs: Yahoo 2,512 sessions; Alpaca IEX 1,583; common 1,582; first common session 2020-07-27.
- SPY: Yahoo 2,512 sessions; Alpaca IEX 1,584; common 1,583; first common session 2018-11-01.
- The 62.98% ratio is common sessions divided by Yahoo's full 10-year history. The 99.94% ratio is common sessions divided by Alpaca's returned history. These ratios describe unequal history horizons.
- The data do not show that IEX omitted roughly 37% of daily sessions during the period it returned. Within the shared period, almost all returned sessions align between sources.
- The 10-year audit still correctly fails its full-history-overlap gate: Alpaca's available history for this account does not extend back to the requested 2016 start. It is therefore unsuitable as the only 10-year research source, even though its overlap with Yahoo is highly complete.
- The code now reports each provider's first/last session, the Alpaca history-start lag, overlap-window session completeness, and a classification distinguishing a later history start from internal gaps. The old `minimum_source_coverage` field remains as a backward-compatible alias; a new explicit `minimum_requested_history_overlap` field explains what it tests.

### Free provider screening (official documentation checked 2026-11-11)

- Alpha Vantage free access is 25 requests/day, but its full daily history (`outputsize=full`) is Premium-only and its split/dividend-adjusted daily endpoint is explicitly Premium. The free daily endpoint is limited to the latest 100 observations. It is not a usable free 5–10-year adjusted OHLC source for this project. Sources: https://www.alphavantage.co/support/api-key/ and https://www.alphavantage.co/documentation/
- Financial Modeling Prep Basic advertises $0 and 250 calls/day, with a free-use limit of five years of stock history, but its Personal Use license is narrowly non-business/non-commercial. Its Terms prohibit use on behalf of an entity, sharing/integrating data into tools accessible to third parties, and copying/downloading content without prior written approval. Do not wire FMP into Rocket Trader's public repository/workflows or cache its data unless FMP confirms in writing that this specific private personal automated-trading use and storage are permitted. Sources: https://site.financialmodelingprep.com/how-to/how-to-create-a-financial-modeling-prep-account and https://site.financialmodelingprep.com/developer/docs/terms-of-service
- FMP is therefore not automatically accepted just because its plan is free. Price is only one gate; licensing and intended use must also pass.
- Continue using Alpaca IEX for the authorized Paper connection and bounded current/history checks, while keeping Yahoo research data segregated and labeled. Do not silently stitch providers or treat Yahoo as an exchange-licensed execution feed.

## 2026-11-11 — Correct zero-budget Alpaca market-data policy: free historical SIP

A review of the current official Alpaca documentation found that the prior blanket SIP block was incorrect.

- Alpaca Basic costs **USD 0/month**. The official Market Data FAQ explicitly states that historical SIP requests are allowed without a paid subscription when the request's `end` parameter is at least 15 minutes old. Recent SIP trades/quotes/bars and the SIP live stream still require Algo Trader Plus. Sources: https://docs.alpaca.markets/us/docs/market-data-faq and https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api
- Alpaca's own support representative states IEX daily bars are only available from 2020, while SIP historical bars are available from 2016. This explains the earlier observed IEX start dates and the 10-year history gap; it was not an unexplained 37% missing-bar rate. Source: https://forum.alpaca.markets/t/cannot-get-historical-bar-data-before-2020/12415
- The correct zero-budget policy is therefore:
  - **Historical equity research/audits:** use SIP by default, but enforce request end at least 15 minutes before current time. The implementation chooses UTC midnight for the latest date safely older than the cutoff, which also avoids including an incomplete current daily candle.
  - **Recent/live market data:** IEX only on the free Basic plan. Do not use SIP for the latest 15 minutes or for live SIP streaming.
  - **No paid subscription:** do not enable Algo Trader Plus or any other paid data tier without explicit user approval.
- Updated the ETF cross-check and equity research v0.1–v0.4 to allow SIP only with a timezone-aware historical end that passes the 15-minute rule. The CLI/workflow default is now SIP for historical research; IEX remains selectable for recent/live-compatible checks. Equity research v0.2–v0.4 now defaults its source to Alpaca rather than Yahoo, with Yahoo retained as the independent comparison source.
- The cross-check now sets its historical data end to the safe UTC date boundary before requesting Yahoo/Alpaca daily prices; corporate-action lookup retains the current timestamp and is read-only.
- The scheduled market-data entitlement probe remains intentionally IEX-only because it is a current/live-feed health check, not a historical SIP entitlement test.
- **Not yet proven for this Paper credential set:** a post-merge read-only SIP historical request must return bars from before 2020, ideally for SPY and the full ETF universe. The implementation must not be described as validated until that workflow succeeds. If Alpaca returns an entitlement error, preserve the logs and revert to IEX-only; do not upgrade or pay.



## 2026-11-12 — Historical SIP correction and PR #181 test follow-up

PR #181 corrects the interpretation of Alpaca IEX's short history and implements the documented free Basic historical SIP path (only when the request end is at least 15 minutes old). The first CI attempt exposed a deterministic-test bug: the fixed test clock was not forwarded through `fetch_daily_bars()` into the SIP guard, so v0.2–v0.4 each failed the recent-SIP rejection test while v0.1 and the ETF cross-check passed. The code now accepts an optional `now` reference and forwards it consistently; normal runtime still defaults to UTC system time. Tests now pass the same fixed clock to the fetcher.

Correction commits are on `fix/classify-historical-window-coverage`; latest known head: `cd119e3d63d76dc716354249c4c44497666d7daf`. New CI runs `43154220272`, `43154220412`, `43154220268`, `43154220349`, `43154220319` were pending/in progress at documentation time. Do not merge until all required checks pass.

The PR event skips live broker data retrieval. Post-merge validation must separately query read-only historical SIP using the existing Paper credentials and confirm bars before 2020. No paid feed, Tiingo account, Paper order or Live action was used. Strategy approval, Paper approval and orders remain disabled. No profitability claim is supported.

**Progress estimate remains 58%** (engineering/evidence maturity, not profitability). Historical SIP availability is documented by Alpaca, but credential-specific entitlement is not yet verified.


Further review of PR #181 found that the new source-window label compared only first dates. This could mislabel a provider that ended earlier but started on the same date as the other source. The comparison now evaluates both first and last dates, reports `alpaca_history_end_lag_days`, and has regression tests for early-end and contained-window cases. Code commit `dfdeed8854e07ed3df34893bdce7bce67c1429d3`; test commit `bc6b10cf2a7f74b704b82457b864ccb0ca3e7afe`. Fresh CI for this latest code was not yet visible. Prior crosscheck offline run `43154220272` passed, but predates this second correction. No data entitlement, strategy or execution approval changed.


## 2026-11-12 — Completed XNYS session boundary

Historical end timestamps now resolve from the XNYS calendar to the latest completed session close (16-minute buffer), rather than UTC midnight. Alpaca requests end at that close; Yahoo's exclusive end advances to the next calendar date so both providers include the same last completed session. Start dates are UTC midnight. This avoids partial daily bars during market hours and keeps free historical SIP requests outside the 15-minute restriction. The v0.1 workflow now installs `requirements-yahoo.txt` for the calendar dependency.

Latest pre-final-test successes: ETF crosscheck `43154959313`, equity v0.1 `43154959322`. v0.2–v0.4 exposed a test-only timezone representation mismatch (the Alpaca SDK model returns a naive UTC end); tests now normalize it. Final latest-head checks are still required. PR #181 must be squash-merged only after all offline checks pass. Post-merge read-only SIP access and pre-2020 coverage remain unverified; no Live/Paper orders or strategy approval.


## 2026-11-12 — PR #181 final offline CI passed

Final code/test head `57e2f330c1cd63e0dc14cea560d520fae98b7b6c` passed:
- ETF cross-check offline suite `43155404153`
- Equity research v0.1 `43155404157`
- Equity research v0.2 `43155404154`
- Equity research v0.3 `43155404122`
- Equity research v0.4 `43155404183`

The PR workflows skip actual broker history retrieval and all live research requests. Next action is squash-merge PR #181, then verify the main-branch push workflows' read-only historical SIP outputs. This status does not assert that SIP entitlement, pre-2020 coverage or strategy profitability has been proven.


## 2026-11-12 — PR #181 merged; Paper historical-data proof remains open

PR #181 was squash-merged into `main` at `87cd23753dbc644414d7d3e25ed6684dc7589274`. The final PR offline checks all passed (crosscheck `43155404153`, v0.1 `43155404157`, v0.2 `43155404154`, v0.3 `43155404122`, v0.4 `43155404183`). PR checks intentionally skipped all actual broker history/research calls.

Main-branch push workflows should now run read-only SIP history and v0.1–v0.4 research with existing Paper credentials. The GitHub connector available in this session does not expose repository-wide push-run listing or artifacts; combined legacy commit status is empty and cannot establish whether those workflows completed. The historical SIP phase therefore remains pending until the GitHub Actions run logs and JSON artifacts are inspected. No orders or Live actions were used.

**Progress remains 58%** (engineering/evidence maturity, not profitability). No strategy is approved; execution costs and persistent runtime remain unvalidated.


## 2026-11-12 — PR #183: broker weighted-average fill-price reconciliation

PR #183 (`18ad5ba1e1dc3c0897793961a7b882f888f2cef9`) closes a correctness gap in the read-only Alpaca Paper activity audit. Previously, a sum-of-fill-quantity match could be reported as `MATCHED` even when the individual fill prices produced a weighted average different from the broker order snapshot.

The activity reader now calculates `fill_notional / fill_qty`, compares the result with the broker order's `filled_avg_price` using Decimal arithmetic and an absolute USD tolerance of 1e-8, and reports both values, their absolute difference and a boolean match. The actual Paper audit requires the broker average price for any filled order and fails closed when it is absent or mismatched.

Validation:
- Workflow `43312572979`: success; compile and 37 offline activity-reconciliation tests passed.
- Workflow `43312573050`: success; static-check and 28 offline tests passed. Its separate `paper-activity-audit` job was skipped on the PR event, so no new live Paper API evidence was generated by this PR.
- No Paper order, account mutation, paid provider, deployment or Live action occurred.

Remaining accounting gaps: live Paper activity evidence, durable restart recovery, delayed fee allocation, correction/bust handling, partial-fill lifecycle and full broker/ledger cash-position parity. Progress remains 58% engineering/evidence maturity; this offline correctness fix does not increase it.


## 2026-11-12 — PR #185: finite timestamp-tolerance guard for staged activity reconciliation

PR #185 (`974288523023f7d08879f2fc420ee25f5f58468f`) fixes a fail-open edge case: a NaN timestamp tolerance made `time_delta > tolerance` evaluate false for every fill pair, bypassing the intended timestamp comparison. The reconciler now rejects non-numeric, boolean, negative and non-finite tolerances before opening the read-only databases.

Validation:
- Workflow `43313016633`: success; compile and 9 offline staged-activity reconciliation tests passed.
- Workflow `43313016735`: success; 28 offline Alpaca activity/audit tests passed.
- Workflow `43313016757`: static-check success; live Paper audit job skipped on the PR event.
- Workflow `43313016739`: Paper Observer Runtime test suite success.
- No broker orders, account mutations, deployments or Live actions occurred.

Progress remains 58% engineering/evidence maturity. The next unresolved gate is actual read-only Paper activity evidence, followed by durable restart recovery, delayed fee allocation, correction/bust handling and complete broker/ledger reconciliation.


## 2026-11-12 — PR #187 activity stager pagination completeness

A code review identified that `AlpacaPaperActivityStager.sync(max_pages=...)` could stop at the configured page cap with a full final page without reporting that more activities might remain. This risks confusing a deliberately bounded scan with complete recovery.

PR #187 added explicit `pagination_complete`, `sync_complete` and `sync_status` fields. Only an empty page or a short page marks the scan `EXHAUSTED`; hitting the page cap while the last page is full reports `PAGE_LIMIT_REACHED`; a non-advancing cursor reports `CURSOR_STALLED`. Invalid `max_pages` types/values are rejected. Regression tests cover these cases.

This is not evidence of a successful real Paper API pull. No order, broker account mutation or Live action is introduced.

 
## 2026-11-12 — PR #187: explicit Paper activity pagination completeness

PR #187 (875772afba86ba249849194a3213055dd23fee8d) prevents a bounded account-activity scan from being mistaken for a complete history retrieval. The stager now differentiates EXHAUSTED, PAGE_LIMIT_REACHED and CURSOR_STALLED; only an empty/short page proves pagination exhaustion.

Validation: workflow 43351364962 passed all 19 activity-stager tests; 43351365053 successfully validated Compose, built the Paper Observer image and verified packaged modules; 43351364942 passed 28 offline runtime tests. No live Paper API activity query was executed by these PR checks. Progress remains 58%.


## 2026-11-12 — PR #188: fee-unknown audit is review-required

PR #188 (`15ee36705909b3a15fb7d722a1d342191422b06e`) removes a misleading top-level SUCCESS state when all order fills match but account fee evidence is not allocated to executions. The audit now reports fill status and fee status separately; matched fills with unresolved fees produce `FILLS_MATCHED_FEES_UNRESOLVED` and exit code 2. A fill mismatch remains a distinct review failure.

Validation: workflow `43351716511` passed 28 activity-reader tests; workflow `43351716505` passed compile and 37 audit/SSE/reconciliation tests. The actual Paper API audit job was skipped on PR events. Progress remains 58%.


## 2026-11-12 — PR #190 cash activity admin persistent-state guard

The cash activity admin CLI previously could initialize a fresh empty ledger or activity-stager database when a configured persistent file was missing. PR #190 now checks existing files and required schema via read-only SQLite before constructing the components, and refuses missing/empty/invalid state without creating replacement files. Offline tests cover missing files, empty databases and a valid pre-existing state. No broker API call or account mutation is added.


## 2026-11-12 — PR #190: fail-closed cash-admin persistent state

PR #190 (`29b9cd41c0eca876b888a1fb9a0eea34aa60f4d0`) prevents the cash-activity admin CLI from silently creating a fresh ledger or activity-stager database when the configured persistent files are missing or damaged. It now validates existing database files, required tables, schema version, capital-policy metadata, initial-capital event and append-only triggers using read-only SQLite connections before constructing either component.

Validation:
- Cash bridge workflow `43352311234`: 12 cash-activity bridge tests, 6 cash-admin tests and 22 ledger tests passed.
- Paper audit workflow `43352311258`: 37 offline tests passed; live Paper API job skipped on PR event.
- Durable Activity SSE workflow `43352311255`: 26 tests and Compose validation passed.
- Paper Observer Runtime workflow `43352311322`: multi-module offline suite passed.
- Paper Observer Container workflow `43352311333`: Compose validation, image build and module packaging passed.

No real Paper query, order, account mutation, persistent-host deployment or Live action occurred. Progress remains 58%.

The next evidence gate is a manual read-only Paper audit dispatch. Fill reconciliation and fee reconciliation are now reported separately; a missing fee record remains unknown rather than being treated as zero.


## 2026-11-12 — PR #192 FX-aware MXN realized P&L methodology

The prior formula converted USD realized P&L at the exit FX only. PR #192 corrected this: each BUY lot's cost basis is stored in MXN at entry FX and net SELL proceeds are converted at exit FX, with entry/exit fees included at their respective FX rates. For a USD 1,000 BUY at 18 MXN/USD followed by a USD 1,000 SELL at 20 MXN/USD, USD P&L is zero but MXN P&L is +2,000.

Legacy ledger databases are protected by an accounting-method marker and explicit migration. Migration is refused when immutable monthly closes exist; it validates event hashes and fill FX metadata, requires stopped writers, and creates a verified SQLite backup. No deployed/persistent database was accessed or migrated. This PR does not authorize orders or Live trading.


## 2026-11-12 — PR #192: FX-aware MXN FIFO realized P&L

PR #192 (`b7eb353f11c29158bc79da9f3c603ca6aae21ad1`) corrects the ledger's currency accounting. The previous formula converted USD P&L only at the SELL FX rate, omitting FX movement on the BUY cost basis. The new method stores FIFO BUY cost basis in MXN at entry FX and converts net SELL proceeds at exit FX. This records both market P&L and USD/MXN movement in the MXN capital ledger.

A version marker (`FIFO_MXN_ENTRY_AND_EXIT_FX_V2`) prevents silent reinterpretation of legacy ledgers. The explicit migration verifies event hashes and FX metadata, requires stopped writers and a verified SQLite backup, and refuses immutable monthly closes.

Validation: 29 ledger tests passed; 37 Paper audit offline tests passed (real Paper audit skipped on PR event); fill-ledger bridge passed 29 ledger + 10 bridge + 8 fee tests; cash bridge passed 12 + 7 admin + 29 ledger tests; durable SSE passed 26 tests; observer runtime and container builds passed. Post-merge CI passed, and the Paper Observer image was published to GHCR at digest `sha256:e58d3d4aa6cf9da80e68dbcf3088bb11cddf1af560f0c3ca8252d3872a172a00`. This is image publication, not deployment.

No persistent ledger was accessed/migrated and no real Paper query, order, account mutation or Live action occurred. Progress remains 58%.
 
## 2026-11-12 — PR #194 Paper position reconciliation status correction

The Paper reconciliation gate previously returned RECONCILED when positions matched, despite not reconciling broker USD cash/equity to a local USD cash ledger. The proposed output explicitly distinguishes position match from full account reconciliation and reports cash reconciliation as not implemented. Full cash/equity/P&L parity remains a blocker. No broker query, order or account mutation is added.


## 2026-11-12 — PR #194: position match is not full account reconciliation

PR #194 (`231332e16b3411cf660f2f5ec1eefdeac493d99d`) removes the misleading `RECONCILED` status from the Paper position gate. Matching broker position quantities now produce `POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE`; broker cash/equity are observations only, and full account reconciliation remains false. The runtime healthcheck keeps overall readiness false until USD cash/settlement/fee parity is implemented, while still distinguishing a healthy position comparison from a position mismatch.

Validation: 7 Paper reconciliation tests passed; observer runtime/accounting suites passed (including 32 runtime tests, 29 ledger tests, 19 activity-stager tests and 28 ETF cross-check tests); 26 durable SSE tests passed; container build/packaging passed; 37 offline audit tests passed. The actual Paper audit job was skipped on PR events. No real Paper query or order occurred. Progress remains 58%.


## 2026-11-13 — Strategy risk denominators (PR pending)

The Core previously used broker Paper equity in USD as the denominator for daily-loss and persistent drawdown protection even though the strategy allocation and sizing budget are in MXN. A large virtual Paper account could make those limits ineffective relative to the strategy's MXN 1,000 seed. The proposed guard requires strategy equity and daily P&L metrics in MXN, fails closed when absent, and stores a currency-marked MXN drawdown high-water mark. No current runtime integration supplies a complete durable strategy-equity snapshot yet, so entries remain blocked until that integration is implemented.


## 2026-11-13 — MXN strategy risk denominators (PR pending)

Core daily-loss and persistent drawdown controls previously used Alpaca broker equity in USD even though strategy sizing used an allocated capital balance in MXN. A large virtual Paper balance could make those percentage limits ineffective relative to the MXN 1,000 strategy. The proposed correction requires explicit current strategy equity and daily P&L metrics in MXN, fails closed when missing, and marks the persistent drawdown state currency as MXN. The existing USD broker floor remains an additional emergency control. No current runtime integration supplies the required durable strategy risk metrics, so entries remain blocked until that integration is complete.
