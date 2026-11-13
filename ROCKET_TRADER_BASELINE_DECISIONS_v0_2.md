# Rocket Trader — Authoritative Baseline Decisions v0.2

**Effective date:** 2026-11-09  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Supersedes conflicting initial planning notes where explicitly stated below.**

## 1. Objective
Build an autonomous, research-led trading system that seeks sustainable net growth through compounding, while preserving capital and refusing trades without validated positive expected value. The goal is to grow the original MXN 1,000 to MXN 100,000 in earned trading capital as efficiently as risk constraints reasonably permit. There is no guaranteed timeline or return.

## 2. Capital and compounding policy
- Initial strategy capital: **MXN 1,000**. All strategy capital, P&L, reserve and payout reporting is in MXN. Alpaca broker cash, equity and order notionals are in USD and require fresh, sourced, timestamped FX conversion.
- Before the first time earned trading growth reaches **MXN 100,000**, retain **100% of realized net trading profits** in operating capital. Personal distributions = 0%; separate reserve distributions = 0%.
- The earned-growth milestone is initial seed capital plus realized net P&L, after fees, spread, slippage and losses. External deposits do not count toward reaching the milestone.
- At the first earned-growth crossing of MXN 100,000, the milestone latches permanently. Target allocation thereafter: 50% reinvestment, 10% reserve, 40% personal distribution.
- After milestone activation, reserve and personal transfers are withheld whenever they would reduce operating capital below MXN 100,000. The actual allocation is then 100% retained until sufficient headroom exists.
- Unrealized gains are not distributable. Monthly close/reporting may propose amounts; it must not move funds without a separately implemented and authorized transfer process.
- The MXN 100,000 floor is a withdrawal rule, not a market-loss guarantee. Cash inside the operating account remains exposed to broker, custody and operational risks; uninvested cash must never be forced into a trade.
- The original draft's MXN 5,000 floor is superseded and must not be used by current code or documentation as the governing milestone.

## 3. Markets and broker scope
- Initial broker and execution environment: Alpaca Paper.
- Scope: US listed equities/ETFs and crypto spot, with separate market engines and execution state machines plus one shared portfolio capital/risk manager.
- Crypto is own-capital spot only. No margin, borrowing, leverage, shorting, futures, perpetuals, options or leveraged/inverse ETFs.
- Paper account permissions do not establish eligibility for live crypto trading from Mexico. Validate separately before any future live review.
- Basic-plan recent/live equity data is IEX; explicit recent SIP requests are subscription-restricted. Alpaca's official Market Data FAQ states that historical SIP bars are available without a subscription when the request end is at least 15 minutes old. Rocket Trader therefore uses IEX for recent/live market data and permits SIP only for historical research with an explicit timezone-aware completed-session end and a 16-minute safety buffer. Do not pay for real-time SIP without a documented expected economic benefit. Historical SIP access and full-history coverage still require a successful read-only request using this account's credentials.

## 4. Research and trader intelligence
- Jefe Maestro contributes engineering/research methods (ensembles, temporal features, walk-forward validation, fingerprints, bootstrap/permutation, multiple-testing correction, attribution and continuity), not lottery datasets or lottery-specific features.
- Successful traders/investors are reference hypotheses and process benchmarks, not instructions. Record source, observation/publication time, regime and availability at decision time. Do not fabricate trader events or treat delayed public filings as real-time signals.
- Compare candidates against buy-and-hold, cash and simple systematic baselines over the same periods, universe, risk and costs. Track all trials and apply multiple-testing correction. Final holdout remains untouched.
- Every candidate must include fees, spread, slippage, liquidity, turnover, exposure, drawdown, uncertainty and benchmark-relative performance. No strategy is currently approved.
- News and social content cannot independently trigger orders. NewsEngine remains UNKNOWN until point-in-time NLP/event evidence is validated.

## 5. Safety and authorization
- Research and Paper execution remain separate. Core risk controls cannot be bypassed by an execution adapter.
- LIVE is disabled. Authorization to continue development and Paper validation is not authorization to place real-money orders. Any future LIVE mode requires a separate explicit authorization after a dedicated safety review.
- Missing/stale FX, data gaps, ambiguous broker order state, ledger/broker mismatch, unknown fees, stale market data, risk-limit breach or corrupted durable state must fail closed.
- No API keys or secrets in source code, files, logs or chat.

## 6. Risk policy still to be engineered and validated
The project has not yet established defensible numeric values for maximum risk per trade, maximum position size, aggregate exposure, daily loss limit, peak-to-trough drawdown stop, concurrent positions, liquidity/slippage thresholds and kill-switch recovery. These must be researched, backtested under stress, implemented centrally and tested through restart/reconciliation scenarios before Paper order enablement. Do not select aggressive numbers merely to force activity.

## 7. Operational state
- GitHub Actions is for CI, research and read-only probes, not the continuous trading runtime.
- The realized-P&L ledger, broker activity stager, reconciliation gate, MXN/USD budget and execution adapters exist as separate components but are not yet wired into a persistent end-to-end Paper service.
- No strategy has passed the current research acceptance gates. No Paper or LIVE orders have been submitted by the research workflows.
- The current blocker list and run evidence are maintained in `ROCKET_TRADER_PROJECT_STATUS_v0_1.md`.


### Risk configuration audit note
The Core currently has prototype defaults (not production-calibrated): 25% maximum position, 80% maximum aggregate exposure, 2% maximum loss per trade, 5% daily loss lock, 2% stop, 4% take-profit, 1.5% trailing-stop parameter, 10 trades/day, 3 consecutive losses and 1% novel-risk budget. These values are code defaults only; they are not an evidence-based approved risk policy. The current Core does not yet implement a persistent peak-to-trough drawdown lock or a complete restart-safe trailing-stop/partial-fill manager. These remain blockers before Paper execution can be enabled.

The reference registry contains six strategy/investor references, not a real-time or point-in-time database of successful traders' verified trades. The default `BenchmarkEngine` repository is empty. A sourced trader-intelligence ingestion and validation system remains to be built; no benchmark events may be fabricated.


### Historical data-source clarification
Alpaca IEX history observed by Rocket Trader starts at 2020-07-27 for most tested ETFs; SPY had an isolated 2018 bar followed by a 634-day gap. A prior NOT_ENTITLED response tested a recent SIP request ending at current time, not delayed historical SIP. Per Alpaca's official FAQ (https://docs.alpaca.markets/us/docs/market-data-faq), Basic users can query historical SIP when the request end is at least 15 minutes old. PR #181 implements historical-only SIP with a 16-minute buffer and latest completed XNYS session close; IEX remains the recent/live feed. This account's actual historical SIP retrieval and full 10-year coverage remain unverified until post-merge Paper workflow artifacts are inspected. Yahoo remains an independent research comparison source; provider histories must never be blended or spliced.


### 2026-11-12 — Historical SIP access clarification (supersedes earlier wording)

Alpaca's official Market Data FAQ explicitly distinguishes recent/live SIP from historical SIP: Basic users may query historical SIP when the request end is at least 15 minutes old; recent SIP endpoints remain restricted without the paid subscription. The prior Rocket Trader HTTP 403/NOT_ENTITLED test used an end at current time and therefore did not establish that historical SIP was unavailable.

PR #181 implements this distinction. For daily research, Rocket Trader resolves the latest completed XNYS session close and applies a 16-minute buffer. The code fails closed if the exchange calendar cannot be resolved or the end is not timezone-aware. The actual Paper-credential historical SIP request still needs post-merge verification. Source: https://docs.alpaca.markets/us/docs/market-data-faq.

This clarification does not authorize a paid plan, does not establish full 10-year coverage, does not certify Yahoo/Alpaca parity, and does not approve any strategy or Paper orders.


## FX-aware realized P&L accounting

Realized P&L is measured in MXN using the FX quote persisted with each fill: each FIFO BUY lot stores its USD and MXN cost basis at entry FX; each SELL converts net USD proceeds at exit FX. This captures both trading-price movement and USD/MXN movement. Fees on entry are included in entry cost basis; exit fees reduce proceeds at exit FX. A flat USD price can therefore produce an MXN gain or loss when FX moves.

Legacy ledger databases are not silently reinterpreted. Existing FILL events without the FX-aware accounting-method marker require the explicit migration utility. Migration is blocked if immutable monthly closes exist, verifies the event hashes and fill-time FX evidence, requires the runtime writers to be stopped, and creates a verified SQLite backup before changing the accounting-method marker. Existing monthly closes require a separate manual restatement process.


## Strategy risk denominators

Broker-side Paper equity/cash are USD and must not be used as the denominator for strategy drawdown or daily loss when the allocated strategy capital is MXN 1,000. The Core now requires explicit `strategy_equity_mxn` and `strategy_daily_pnl_pct` whenever `strategy_capital_mxn` is set; missing metrics block entries. Its persistent strategy drawdown high-water mark is explicitly denominated in MXN and uses a dedicated `ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH`. Do not reuse an old USD guard-state file for MXN; the currency marker makes that mismatch fail closed.


## Strategy risk measurement and drawdown currency

The Core must measure strategy daily loss and persistent drawdown against strategy equity in MXN, not the broker's virtual Paper account equity in USD. When `strategy_capital_mxn` is set, callers must also supply a current `strategy_equity_mxn` and `strategy_daily_pnl_pct` derived from durable ledger state and current broker marks. Missing metrics fail closed. The persistent strategy drawdown state uses `equity_currency=MXN` and the dedicated `ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH`; do not reuse an old USD guard file. The broker USD protected floor remains a separate emergency account-level control.
