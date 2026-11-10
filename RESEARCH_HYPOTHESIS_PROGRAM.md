# Rocket Trader — Systematic Strategy Evidence Program

**Research cut-off:** 2026-11-10  
**Status:** Research plan; no strategy approved; research and Paper only.  
**Objective:** Find robust, implementable positive net expectancy under small-capital constraints, not maximize a historical backtest.

## Non-negotiable research principles

1. Freeze each hypothesis and its parameter ranges before opening its holdout results.
2. Compare strategies on identical point-in-time data, universes, timestamps, capital, execution assumptions, and risk budgets.
3. Use next executable price, never same-close fills when the signal requires that close.
4. Model spread, commissions/fees, slippage, market impact, borrow/funding where applicable, rejected orders, partial fills, and minimum notional.
5. Separate train, validation, walk-forward, and final untouched holdout. Purge overlapping labels and embargo where required.
6. Record every experiment, parameter set, data fingerprint, code commit, benchmark, and failed result. Estimate multiple-testing / backtest-overfitting risk (PBO/CSCV or defensible alternatives).
7. Compare against buy-and-hold, cash, volatility-matched benchmarks and deterministic fixed-schedule controls with identical exits/risk. If a permutation or Monte Carlo diagnostic is justified, use a recorded fixed seed and preserve every draw; never use unseeded randomness or select a winner from repeated random searches. A positive return alone is not evidence of skill.
8. Report net CAGR/return, volatility, Sharpe/Sortino, max drawdown, Calmar, turnover, exposure, hit rate, average win/loss, profit factor, trade count, time in market, capacity, tail loss, and confidence intervals.
9. No leverage, margin, shorting, derivatives, or instruments outside approved spot/equity scope for the first production candidate.
10. Never relax data quality or risk gates to force activity. No edge means no trade.

## Hypothesis families to compare

| ID | Family | Core hypothesis | Primary risks / test |
|---|---|---|---|
| H01 | Time-series momentum / trend | Own past returns predict direction over multi-week/month horizons | Long-only translation, whipsaw, regime concentration; test 1/3/6/12m lookbacks |
| H02 | Breakout / Turtle | Range breakouts capture persistent directional moves | False breaks, gap/slippage; test 20/55-day entries, volatility-scaled sizing, predeclared exits |
| H03 | Cross-sectional momentum / relative strength | Relative winners continue outperforming | Survivorship, universe bias, turnover, concentrated growth regimes |
| H04 | Mean reversion | Short-horizon deviations from fair/rolling value partially reverse | Trend crashes, spread/cost overwhelms edge, short-sale constraints; long-only version separate |
| H05 | Pairs / statistical arbitrage | Related assets temporarily diverge and converge | Structural breaks, unstable cointegration, two-leg execution, borrow/shorting; research-only initially |
| H06 | Volatility targeting / regime allocation | Risk scaling and defensive state reduce drawdown and improve compounding | Lagged regime labels, whipsaw, leverage temptation; test long-only/cash allocation |
| H07 | Event/news reaction | Point-in-time news changes conditional return distribution | Timestamp leakage, source latency, NLP false positives; only official, time-stamped events |
| H08 | Intraday momentum / opening range / VWAP | Intraday order flow and session structure contain short-lived edge | High costs, IEX/SIP feed mismatch, execution latency; requires minute/quote data |
| H09 | ML prediction / meta-labeling | ML improves filtering/position sizing on top of transparent base signals | Leakage, non-stationarity, high degrees of freedom; compare against simple baseline |
| H10 | Reinforcement learning / adaptive portfolio | Sequential policies optimize allocation under costs and risk | Simulator exploitation, reward misspecification, instability; never first-line strategy |
| H11 | Hybrid multi-horizon ensemble (Rocket hypothesis) | Combine a small set of orthogonal, independently validated signals; allocate only when expected net edge exceeds uncertainty and costs | Ensemble overfit/correlation; test ablation, equal-weight and simple-rule controls |
| H12 | Cash / no-trade | Staying out is superior when edge is absent or costs dominate | Opportunity cost; mandatory control and valid decision |

## Original Rocket hypothesis (H11)

Use a **hierarchical decision system**, not an unconstrained AI trader:
- Layer 1: hard eligibility filters (data freshness/quality, tradability, market state, spread/cost, minimum notional, account state).
- Layer 2: independently validated simple signal modules (trend, breakout, relative strength; mean-reversion only in explicitly suitable regimes).
- Layer 3: a conservative meta-selector estimates whether each module has positive *net* expectancy in the current observable regime; it may abstain.
- Layer 4: volatility- and correlation-aware allocation, with portfolio-level drawdown and concentration limits.
- Layer 5: deterministic execution state machine; ML never bypasses the Core risk controls.
- Model uncertainty should reduce size or choose cash, not increase risk. Novel signals begin in shadow mode with no orders.

This hypothesis must compete on identical data with each standalone family and with a simple equal-weight ensemble. If it does not beat those controls out of sample after costs, discard it.

## Pairwise evaluation protocol

- Build a common experiment manifest: universe, asset eligibility, bar frequency, time span, data vendor/version, corporate-action handling, signal timestamp, fill timestamp, cost model, capital, risk limits, and all parameter trials.
- Compare all eligible candidates on the intersection of valid observations first; separately report broader-universe tests so data coverage cannot create a false winner.
- Use chronological walk-forward folds and a final untouched holdout. Use purging/embargo for overlapping holding periods.
- Compare candidate A vs B on the same dates and risk budget using paired daily net returns and paired trade-level outcomes where comparable.
- Use block bootstrap / stationary bootstrap for serial dependence; report confidence intervals and probability of underperformance, not just point estimates.
- Run parameter stability surfaces and sensitivity to 1x/1.5x/2x costs, delayed fills, and adverse slippage.
- Test ablations: remove each filter, feature, market, and module. A complex model must prove the incremental value of each component.
- Correct for multiple testing and publish the total number of trials. Maintain a frozen final holdout that is never used for tuning.
- Strategy selection is a model-confidence problem; do not select the maximum Sharpe among hundreds of trials.

## Candidate libraries and architecture references (not presumed alpha)

- QuantConnect LEAN: https://github.com/QuantConnect/Lean — event-driven research/backtest/live engine and modular brokerage/data models.
- NautilusTrader: https://github.com/nautechsystems/nautilus_trader — deterministic event-driven Rust core, Python strategy control; inspect live/backtest semantic parity and v2 maturity before adoption.
- VectorBT: https://github.com/polakowo/vectorbt — fast vectorized research and parameter sweeps; useful for hypothesis screening, not a substitute for event-driven fill simulation.
- FinRL: https://github.com/AI4Finance-Foundation/FinRL — educational/research DRL pipeline.
- FinRL-X: https://github.com/AI4Finance-Foundation/FinRL-Trading — newer modular ML/DRL trading architecture; published repository backtests and paper results are claims to reproduce, not verified edge.
- Backtrader: https://github.com/mementum/backtrader — event-driven Python backtesting and strategy prototyping.

Do not import a library or framework into production solely because it is popular or has impressive README results. Audit license, maintenance, dependencies, data assumptions, execution semantics, security, and reproducibility first.

## Initial evidence library

- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics: https://doi.org/10.1016/j.jfineco.2011.11.003
- Hurst, Ooi & Pedersen (2017), *A Century of Evidence on Trend-Following Investing*: https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*: https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Gatev, Goetzmann & Rouwenhorst (2006), *Pairs Trading*: https://doi.org/10.1093/rfs/hhj020
- Bailey et al. (2017), *The Probability of Backtest Overfitting*: https://escholarship.org/uc/item/4w1110bb
- Bailey et al. (2014), *Pseudo-Mathematics and Financial Charlatanism*: https://scholarworks.wmich.edu/math_pubs/40
- Open 2026 survey, *Deep Reinforcement Learning for Portfolio Optimization and Algorithmic Trading: A Critical Survey*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7363738
- Open 2026 review, *Systematic review of reinforcement learning for automated equity portfolio management*: https://link.springer.com/article/10.1007/s10791-026-10336-1
- 2026 survey, *Deep Reinforcement Learning for Portfolio Optimization and Algorithmic Trading: A Critical Survey* (SSRN preprint; treat as preprint, not peer-reviewed proof): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7363738
- MIT OpenCourseWare / Finance Theory I (Andrew Lo; free lecture notes, videos, exams and problem sets): https://ocw.mit.edu/courses/15-401-finance-theory-i-fall-2008/
- MIT OpenCourseWare / Investments: https://learn.mit.edu/c/unit/ocw?resource=3912

## Community evidence (low weight)

Reddit practitioner discussions are useful for identifying failure modes and candidate hypotheses, not proving returns. Recurring reports include backtest overfitting, unrealistic slippage/fills, changing regimes, and simple trend/momentum being more robust than elaborate indicator stacks. Every anecdote must be converted into a falsifiable test.
- r/algotrading, overfitting vs slippage/regime discussion (Jan 2026): https://www.reddit.com/r/algotrading/comments/1q4gpu1/is_overfitting_the_1_reason_most_backtested/
- r/algotrading, live survival discussion (Feb 2026): https://www.reddit.com/r/algotrading/comments/1r8rr9s/which_algo_strategy_has_actually_survived_live/
- r/algotrading, trend-following proposal (Oct 2022): https://www.reddit.com/r/algotrading/comments/y1cx72/strategy_1_trend_following/

## Courses and books

- MIT OpenCourseWare Finance Theory I and Investments (free course materials).
- Ernest P. Chan, *Quantitative Trading*, revised 2nd edition (Wiley, 2026): https://www.wiley.com/en-us/quantitative-trading-how-to-build-your-own-algorithmic-trading-business-revised-edition-2nd-edition-p-9781394428229 — commercial book, not assumed open access.
- Ernest P. Chan, *Algorithmic Trading: Winning Strategies and Their Rationale*: https://onlinelibrary.wiley.com/doi/book/10.1002/9781118676998 — bibliographic/publisher reference; access may require purchase/library.

Respect copyright and repository licenses. Use lawful open-access versions, institutional access, or public-domain texts; do not scrape pirated books or redistribute copyrighted material.

## Execution-timing correction and current evidence (2026-11-10)

**Use only the next-open research versions for decisions.** The earlier v0.2 equity and v0.1 crypto backtests applied close-derived signals to close-to-close returns, which could include the close-to-next-open gap before an order could actually execute. Those results are superseded and must not be used for strategy promotion.

The corrected model:
- Computes signals only from completed bar closes.
- Applies the position at the next bar's open.
- Measures open-to-next-open returns.
- Charges turnover at the actual entry/exit boundary.
- Excludes the final bar without a forward open and liquidates at the last available open.
- Preserves the previous-close position when slicing train/validation/holdout windows, so window boundaries do not create artificial entries.

Regression tests include a deliberate 100% overnight gap and verify that a signal entered at the next open earns only the subsequent 10% open-to-open move, not the unavailable gap.

### Corrected equity research v0.3

- 10-year adjusted daily history; Yahoo Finance research-only source.
- 8 ETFs passed data-quality checks: DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT.
- 49 eligible hypotheses in the final-holdout multiple-testing family.
- Holm-Bonferroni significant hypotheses: 0.
- Pre-screen passes: 0.
- Cross-sectional top-1 momentum final holdout: +41.0% total return versus +31.2% equal-weight benchmark, but the 5th-percentile excess was -30.1%, raw p-value 0.392, Holm-adjusted p-value 1.0. This is not robust evidence of alpha.

### Corrected crypto research v0.2

- 5-year daily history from Alpaca CryptoFeed.US.
- BTC/USD and ETH/USD passed; SOL/USD remains excluded for data-quality gaps.
- 13 eligible hypotheses in the final-holdout multiple-testing family.
- Holm-Bonferroni significant hypotheses: 0.
- Pre-screen passes: 0.
- Cross-sectional top-1 momentum final holdout: -29.5% total return; raw p-value 0.427, Holm-adjusted p-value 1.0. No strategy is promoted.

These corrected results remain research-only. Neither asset class has a validated positive net edge. Prior close-to-close results are archived for auditability but superseded for all decisions.

## Mean-reversion tranche (2026-11-10)

The corrected next-open pipelines now include three pre-registered long-only mean-reversion hypotheses:
- RSI(2) below 10 with a 200-day trend filter and 5-day mean/RSI exit.
- Bollinger(20, 2) lower-band entry with middle-band exit.
- Five-day downside z-score below -2 with zero-crossing exit.

Results:
- Equity v0.4: 8 ETFs, 10 years, 73 hypotheses in the Holm family; 0 family-wise significant and 0 pre-screen passes.
- Crypto v0.3: BTC/ETH eligible, SOL excluded; 19 hypotheses; 0 family-wise significant and 0 pre-screen passes.
- Most mean-reversion variants underperformed their same-asset buy-and-hold benchmarks in the final holdout. A few point estimates were positive, but sample counts were low and all Holm-adjusted p-values were 1.0.
- RSI(2) BTC returned +4.57% in its final holdout, but only 4 entries and Holm-adjusted p=1.0; this is not enough evidence.
- TLT Bollinger(20,2) returned +8.83% and exceeded TLT buy-and-hold by +8.95 percentage points, but had 10 entries and Holm-adjusted p=1.0; it is not promoted.

No strategy is approved. The next useful research tranche is a small, pre-registered set of deterministic calendar-seasonality and intraday hypotheses, but intraday strategies must use data granular enough to model the next executable bar. Do not test more parameters simply to search for a positive result.

## Determinism, uncertainty, and reproducibility

Rocket Trader's decision logic must be deterministic and auditable given the same immutable inputs, configuration, code version and execution state:
- No unseeded random decisions in signal generation, portfolio selection, sizing, risk controls or order routing.
- Use timestamped/versioned market data, explicit tie-breaking, stable decimal arithmetic and persisted state transitions.
- Every experiment records code SHA, dataset/version, parameters, costs, seed (if any), and broker execution events.
- Internal simulation may use a pseudo-random generator only for a clearly named diagnostic, with a fixed recorded seed so the run is exactly reproducible.
- Do not infer that an externally observed fill or market path is deterministic merely because the decision code is deterministic. Treat unknown future inputs, latency, partial fills and changing market conditions as uncertainty to be stress-tested.

Alpaca explicitly documents that its Paper simulator may produce partial fills of random sizes 10% of the time when an order is marketable. That is a property of the simulator, not a reason to inject randomness into Rocket Trader's strategy. Record the broker's actual fill events and make the order state machine robust to full, partial, delayed, rejected and cancelled outcomes.

## First experimental sequence

1. Finish the existing 10-year ETF and multi-year crypto data-quality and baseline research.
2. Reproduce a simple long-only trend / time-series momentum baseline.
3. Reproduce a Turtle-style breakout with volatility sizing and explicit execution costs.
4. Add cross-sectional relative strength on a point-in-time survivorship-aware universe.
5. Compare mean-reversion and pairs only where instrument/shorting constraints permit; keep unavailable legs explicitly research-only.
6. Test volatility targeting/regime filter as a risk overlay against the same base signals.
7. Test event/news only after point-in-time timestamp quality is proven.
8. Test ML/meta-labeling and RL only after simple strategies have passed robust baselines.
9. Evaluate H11 hybrid only after its components independently pass; keep cash/no-trade as a full candidate.
10. Promote only a candidate with sufficient independent holdout trades, robust cost stress, stable folds, and subsequent Paper evidence.

## Current constraints

- Starting capital target is MXN 1,000; small notional and broker minimums may make many strategies infeasible. No forced trades.
- Equity data currently includes IEX feed for research; IEX is not SIP. Yahoo is secondary historical research source only.
- Crypto historical gaps (notably SOL/USD) remain excluded when data quality fails.
- Alpaca Paper is the only authorized execution environment for development. No live orders.
- Strategy acceptance thresholds already in the project remain in force until changed by documented evidence; no threshold is weakened merely to get a pass.
