# Rocket Trader — Project Status v0.1
**Last reviewed:** 2026-11-10  
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
- SIP SPY daily bars: `NOT_ENTITLED` (HTTP 403).
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
- PR #31 verifies market-data entitlements: IEX available; SIP returned NOT_ENTITLED (HTTP 403). IEX is not consolidated SIP data. Paying for SIP is not justified at the current MXN 1,000 starting capital.
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
- The IEX source limitation is consistent with Alpaca support material stating IEX historical bars begin in 2020, while SIP history reaches earlier. This account's SIP probe returned NOT_ENTITLED (403), so the ten-year workflow must not keep treating IEX as a ten-year source.
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
- Interpretation: Alpaca IEX's available history is the binding 10-year limitation for this account. SIP entitlement was previously NOT_ENTITLED. Do not reduce the requested coverage threshold or splice Yahoo and IEX as if they were one homogeneous series.
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
