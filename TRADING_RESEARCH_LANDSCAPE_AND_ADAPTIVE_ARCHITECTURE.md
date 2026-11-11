# Trading Research Landscape & Adaptive System Blueprint
**Research cut-off:** 2026-11-10  
**Status:** curated research baseline; implementation and empirical validation are separate gates.  
**Progress impact:** none by itself. Research coverage is not trading performance.

## 1. Executive conclusion

The earlier Rocket Trader work did not complete a systematic survey of the full history and current state of trading. It did implement selected quantitative/ML components and test limited strategy families, but the broader historical, practitioner, open-source, academic and community review had not been assembled into one evidence-backed program. This document starts that program and is the durable continuation point.

The correct design is not to collect every indicator or deploy the newest AI technique. It is to build a regime-aware portfolio of independently tested strategy families, with a decision layer that can allocate, reduce risk, rotate, experiment within strict limits, or abstain. The system must be allowed to decide that no trade is best.

A method is not accepted because a famous trader used it, a GitHub project has many stars, a Reddit thread praises it, an academic paper reports a high Sharpe, or an LLM describes it convincingly. It must survive reproducible, leakage-safe, cost-aware tests on the instruments and time horizons Rocket Trader can actually trade.

## 2. Historical evolution — what changed and what remains useful

This is a practical chronology, not a claim that every trading tradition began at a single date.

### 2.1 Discretionary price reading and market craft
- Exchange trading evolved from human negotiation, floor signals, broker networks, order books and ticker/tape dissemination. Japanese rice-market charting is an important early source in technical-analysis history; Charles Dow's market theory and later tape-reading traditions shaped modern price analysis.
- Jesse Livermore and other tape readers emphasized price/volume behavior, market leadership, patience, cutting losses and allowing exceptional trends to run. Historical accounts are not independently verified modern alpha guarantees.
- Richard Wyckoff emphasized supply/demand, accumulation/distribution and large-operator behavior. These ideas are useful only when translated into objective, timestamped features rather than subjective chart labels.
- Enduring lessons: price is the final clearing signal; liquidity and crowd behavior matter; process discipline matters. Weakness: discretionary accounts are vulnerable to hindsight, survivorship and selective storytelling.

### 2.2 Systematic trend and rule-based trading
- Dow Theory, moving-average rules, breakouts and channel systems formalized trend-following.
- Richard Dennis and William Eckhardt's Turtle experiment (1983) is a notable example of teaching explicit rules to novice traders. The useful lesson is repeatability, position sizing and loss control—not blind copying of old parameters or unverified profit claims.
- Hurst, Ooi and Pedersen studied 67 markets across four asset classes back to 1880 and reported positive average time-series momentum across decades, with meaningful dependence on correlation and macro environments. This supports testing trend as a family, not assuming it will work in every instrument or implementation.

### 2.3 Portfolio mathematics and financial economics (1950s–1980s)
- Markowitz mean-variance construction (1952), CAPM, factor models, stochastic-process theory, random-walk research and the Efficient Market Hypothesis reframed the problem from selecting one winning security to balancing expected return, covariance and risk.
- The practical implication: model the portfolio as a whole. Correlated positions, factor concentration, volatility, tail loss and capital usage matter more than each strategy's standalone Sharpe.
- Returns are heavy-tailed and non-Gaussian; normal-volatility assumptions alone are inadequate for crisis control.

### 2.4 Statistical arbitrage, factors and derivatives (1980s–2000s)
- Pairs trading, cointegration, mean reversion, cross-sectional momentum, value, quality, carry and statistical arbitrage became more formal as historical databases and compute improved.
- A signal can be statistically predictive yet economically useless after turnover, borrow, spread, market impact, financing and capacity.
- The 1998 LTCM episode shows convergence relationships can diverge together during a liquidity/flight-to-quality event. Leverage, crowded positions, counterparty exposures and forced liquidation can dominate model elegance.
- The August 2007 quant unwind shows apparently diversified quantitative books can become one crowded trade. Common factor exposures and synchronized deleveraging can create correlation spikes when diversification is most needed.

### 2.5 Electronic and algorithmic markets (1970s–2010s)
- Automated order routing developed with electronic order-handling systems such as DOT; decimalization, electronic venues, Reg NMS and fragmentation changed execution economics.
- Market microstructure became central: bid/ask spread, depth, queue position, adverse selection, latency, auction dynamics, market impact, fill probability and venue rules.
- High-frequency trading is specialized, not a generic advantage. Without tick/order-book data, low-latency infrastructure and credible queue/fill models, Rocket Trader should not pretend to compete in HFT.
- Execution algorithms are part of the strategy. A signal whose assumed fills are impossible is not a viable strategy.

### 2.6 ML, alternative data and adaptive models (2010s–2026)
- Tree ensembles, regularized regression, SVMs, neural networks, LSTM/GRU, CNNs, attention/Transformers, graph models, NLP and reinforcement learning have expanded the toolbox.
- Recent reviews cover classical ML through multimodal, graph and RL approaches. They also stress non-stationarity, inconsistent validation, omitted transaction costs and weak comparability. Forecast error improvements do not prove positive net tradable returns.
- RL is promising for sequential allocation and execution but faces noisy rewards, partial observability, simulator mismatch, unstable training and overfitting. It belongs in a research sandbox until it beats simpler policies out of sample and under realistic costs.
- LLMs can parse documents, extract evidence and classify events. They are not a trusted price oracle, must not invent probabilities, and must not place trades directly from unverified prose.

## 3. Strategy families to research

Each family needs its own hypothesis, eligible assets, horizon, expected regime, benchmark, failure conditions, cost model and independent evidence record.

1. Trend/time-series momentum: moving-average trend, Donchian breakouts, volatility-scaled and multi-horizon trend, trailing exits. Potentially useful in persistent directional markets; vulnerable to whipsaw and reversals.
2. Cross-sectional momentum/relative strength: rank a defined universe and rotate toward stronger assets. Vulnerable to momentum crashes, crowding, universe changes and turnover.
3. Mean reversion: short-horizon oversold/overbought, residual/z-score, pairs and cointegration. Requires stationarity diagnostics and structural-break detection; dangerous in genuine repricing trends.
4. Carry/term structure/yield: futures curve, funding, basis, FX carry and bond/ETF carry where permitted and data exists. Can carry crash risk and may not be available in the user's account.
5. Value/quality/fundamentals: valuation, earnings quality, profitability, balance sheet and revisions. Requires point-in-time fundamentals and publication timestamps; never use restated data as if known earlier.
6. Volatility/risk premia: realized/implied volatility, volatility targeting and defensive overlays. Options strategies remain out of scope unless separately authorized and risk-tested; volatility prediction is not directional alpha.
7. Event-driven/macro: scheduled releases, central-bank actions, earnings, regulation, corporate actions and geopolitical shocks. Model event time, surprise vs consensus, revisions, source reliability and decay horizon.
8. Liquidity/microstructure: spread/depth imbalance, order flow, trade imbalance, auctions and execution timing. Requires quote/trade or L2 data and realistic fills; daily bars cannot establish order-book alpha.
9. Statistical arbitrage/relative value: cointegration, residual models, factor-neutral portfolios and cross-asset relationships. Stress correlation breakdown, borrow and financing where applicable.
10. Crypto spot: momentum, mean reversion, volatility/liquidity, exchange-specific microstructure and event signals. User scope is spot only, own capital; no margin, loans, leverage, futures/perpetuals or shorting.
11. Novel/emergent hypotheses: new market structures or signals absent from the literature. Explore only in a quarantined experiment with a small pre-defined risk budget, hard loss cap, no auto-promotion and explicit evidence requirements.

Do not activate all families simultaneously. Build a hypothesis registry. Only families supported by the instrument universe, feed granularity, account permissions and measured costs can proceed.

## 4. Regime intelligence and adaptive decision architecture

### 4.1 State estimation — multiple independent views
Estimate probabilities, not brittle one-hot labels. Candidate state dimensions:
- Trend: direction, persistence, breadth and cross-sectional dispersion.
- Volatility: realized volatility at multiple horizons, volatility-of-volatility, gaps and tail indicators.
- Correlation: average/tail correlation, dispersion, factor concentration and correlation spikes.
- Liquidity: spread, depth, turnover, volume surprise, quote staleness and market impact.
- Macro: inflation/growth/rates/credit/liquidity states and release surprises, using point-in-time vintages.
- Event risk: known calendar, source-verified surprise, novelty, confidence, affected instruments and decay.
- Market structure: session, auction/open/close, halts, limit states, venue health and feed integrity.

Compare, do not assume superiority:
- Transparent rules and volatility scaling as robust baselines.
- Hidden Markov/Markov-switching models for probabilistic latent states.
- Change-point detection and Bayesian online change-point detection for abrupt structural breaks.
- Clustering of volatility/return/liquidity distributions.
- Supervised regime classifiers trained only on labels available at decision time.
- Online/continual learning with drift alarms, bounded update rates and rollback.
- Ensemble disagreement and predictive uncertainty as reasons to lower exposure.

Regime labels should include persistent trend, range/mean-reverting, high-volatility stress, low-liquidity/dislocated, transition/uncertain and data-unhealthy. These are descriptive states; no strategy is presumed to work in them until tested.

### 4.2 Meta-allocation / strategy selection
- Maintain candidate strategies with separate performance, uncertainty, costs, drawdown and regime-conditional records.
- Compare constrained/robust optimization, volatility/risk parity, Bayesian shrinkage, hierarchical risk budgeting, contextual bandits and meta-labeling.
- Include abstention/cash. If net-edge lower confidence bound is non-positive, regime uncertain, costs unvalidated, data stale or drawdown breached, allocate zero to that candidate.
- Avoid hard switching on one noisy observation. Use hysteresis, transition probabilities, cooldowns and minimum evidence.
- Keep a stable baseline portfolio and compare every adaptive improvement against it; adaptation itself can overfit.
- Optimize beyond Sharpe: CAGR, max drawdown, expected shortfall, tail loss, turnover, capacity, recovery time, profit factor, exposure and benchmark-relative performance.

### 4.3 Online adaptation without self-destruction
- Separate monitoring from learning. A live performance change triggers diagnosis; it does not automatically retrain and deploy.
- Use shadow predictions, frozen champion models, challenger models, rolling validation and pre-registered promotion criteria.
- Drift detection may reduce exposure, quarantine a strategy or request research. It cannot lower gates to make a strategy pass.
- Preserve immutable model/data/version lineage, training windows, features, hyperparameters, source timestamps, predictions, allocations and execution outcomes.
- Roll back to a tested safe policy on failed health checks; if no policy is valid, hold cash.
- Novel strategies get only explicitly capped exploratory budgets after paper simulation, never unlimited live allocation.

### 4.4 News, social and geopolitical signals
- Every item needs publisher, URL, publication/event/ingestion timestamps, source group, credibility, confidence, novelty, affected assets, causal channel, expected horizon and corroboration.
- Distinguish primary sources (central banks, regulators, issuers, official statistics) from newswires, specialist media, analyst commentary, social posts and anonymous forums.
- Deduplicate syndicated content and repost cascades. Count independent source groups, not repeated copies.
- Separate sentiment, attention, factual event surprise and market reaction. Social sentiment can lag/echo volatility and can be manipulated or botted.
- Use NLP/LLMs to extract candidate events, with schema validation and human review for critical events. An LLM summary alone never changes allocation.
- Test incremental value against price/volume/macro baselines with point-in-time data, event windows, placebo dates and decay tests.
- Geopolitical scenarios map plausible transmission channels (energy, shipping, FX, rates, sanctions, supply chain, risk premium), not guessed price direction from headlines.

## 5. System-wide risk management
- Hard account-level limits: gross/net exposure, per-asset concentration, correlated-cluster exposure, daily/weekly loss, peak-to-trough drawdown, order notional, turnover, open orders and strategy loss budget.
- No leverage or short exposure under current user scope; crypto is spot-only with own capital.
- Pre-trade checks: market status, tradability, spread, quote freshness, price collars, cash/buying power, duplicate-order idempotency, order rate, symbol eligibility and justified event blackout.
- Runtime safety: independent kill switch, cancel-all path, read-only degraded mode, watchdog, stale-data circuit breaker, broker connectivity checks and persisted state recovery.
- Reconcile broker orders, fills, fees, dividends, splits, cash, corrections/busts, corporate actions and FX. Never auto-reconstruct a fill from ambiguous evidence.
- Stress replay: 1987, 1998, 2000–02, 2007, 2008, 2010, 2015, 2018, 2020, 2022 and later episodes; synthetic gap/liquidity shocks, correlated liquidation, halts, stale quotes, API outage and partial-fill races.
- Keep risk controls outside the strategy/LLM process so a faulty model cannot disable its own guardrails.

## 6. Historical failures become engineering requirements

| Episode | Failure mode | Rocket Trader control |
|---|---|---|
| 1987 Black Monday | Portfolio-insurance feedback loops amplified selling | Stress correlated exits; do not assume liquidity remains in drawdowns |
| 1998 LTCM | Convergence trades diverged together; leverage/crowding threatened fire-sale contagion | No leverage; concentration/correlation/liquidity stress; tail scenarios beyond normal VaR |
| Aug 2007 quant unwind | Crowded factor books deleveraged; market-making capital withdrew | Monitor factor crowding proxies, strategy correlation, capacity and liquidity |
| May 2010 Flash Crash | Interconnected markets and large automated sell flow interacted with fragile liquidity | Price collars, volatility halts, outlier/stale quote filters, order-rate and kill controls |
| Aug 2012 Knight Capital | Software error sent millions of erroneous orders; losses exceeded $460m | Canary deploy, feature flags, order caps, pre-trade controls, rollback and independent kill switch |
| 2020 COVID shock | Volatility, gaps, correlations and liquidity changed rapidly | Regime uncertainty, reduced risk, gap/impact stress and cash fallback |

## 7. Research standards — how to decide what is true

Every candidate record must contain:
1. Hypothesis and causal mechanism, instrument universe, horizon, decision timestamp and expected regime.
2. Source lineage/license; corporate-action policy; point-in-time data and survivorship-safe universe.
3. Baselines: cash, buy-and-hold, equal weight, simple trend and relevant market/factor benchmark.
4. Chronological train/validation/test; multiple rolling/expanding walk-forward folds; untouched final holdout.
5. Purging/embargo where labels overlap; CPCV/CSCV and Probability of Backtest Overfitting where appropriate; Deflated Sharpe/multiple-testing corrections.
6. Realistic next-event fills, spread, slippage, fees, market impact, latency, partial fills, borrow/funding and capacity.
7. Robustness across assets, subperiods, regimes, parameter neighborhoods, 2x cost stress and alternative vendors.
8. Uncertainty intervals, effective independent sample size, turnover and trade count. Tiny samples cannot establish edge.
9. Ablations: prove each feature/news source/ML layer adds value over a simple baseline.
10. Reproducible artifacts, immutable run IDs, source versions, parameters and explicit pass/fail reasons.

AUC, accuracy, F1, forecast RMSE or directional hit rate are diagnostics—not profitability. Advance only on net, executable, out-of-sample portfolio evidence.

## 8. Successful trader and institution benchmarking

Benchmark methods, not celebrity mythology:
- Jesse Livermore/tape reading: trend, patience, loss discipline; historical narrative evidence is weak and survivorship-prone.
- Richard Dennis/Turtles: systematic breakout, volatility-based sizing and explicit risk rules; test rules, not legend.
- Ed Thorp: probability, statistical edge, sizing and risk of ruin; do not assume historical opportunities remain.
- George Soros/reflexivity: feedback between beliefs, positioning and fundamentals; a scenario lens, not deterministic signal.
- Jim Simons/Renaissance: statistical pattern extraction, diversification of small edges, research discipline and infrastructure; exact Medallion methods/returns are proprietary and cannot be replicated from anecdotes.
- AQR/managed futures: published trend/factor research and diversified risk-balanced portfolios; account for fees, capacity and research-house perspective.
- Market makers/execution specialists: microstructure, inventory risk, adverse selection and execution quality; relevant only if data and infrastructure support it.

Prefer public, investable, timestamped records and peer-reviewed methods. Never infer proprietary rules from headline CAGR or claim access to private books.

## 9. Open-source ecosystem to inspect — do not import blindly

| Project | What to learn | Caution / fit |
|---|---|---|
| QuantConnect LEAN — https://github.com/QuantConnect/Lean | Event-driven portfolio construction, risk and execution architecture | Check dependency footprint and broker/data fit |
| NautilusTrader — https://github.com/nautechsystems/nautilus_trader | Shared backtest/sandbox/live event model, realistic execution and reconciliation | Large architectural change; pin API/version and test maturity |
| vectorbt — https://github.com/polakowo/vectorbt | Fast vectorized hypothesis screening and parameter research | Not a substitute for event-driven execution simulation |
| backtesting.py — https://github.com/kernc/backtesting.py | Simple strategy prototypes and readable baselines | Limited multi-asset/live infrastructure |
| Freqtrade — https://github.com/freqtrade/freqtrade | Crypto spot operations, strategy testing, protections and hyperopt | Check defaults carefully; do not import leverage/futures scope |
| FinRL — https://github.com/AI4Finance-Foundation/FinRL | RL research environments and benchmark patterns | Research/education is not proof of profitable live deployment |
| hftbacktest — https://github.com/nkaz001/hftbacktest | Queue position, latency and order-book fill simulation | Only relevant with L2/L3 data and microstructure objectives |
| zipline-reloaded — https://github.com/stefan-jansen/zipline-reloaded | Historical factor research and pipeline concepts | Verify maintenance, data assumptions and compatibility |

The awesome-open-source-trading index (https://github.com/WallStreetPete/awesome-open-source-trading) is a discovery index, not an authority. Inspect upstream activity, releases, issues, tests, license, security, fill assumptions and dependency maintenance before adoption. Stars do not establish quality.

## 10. Forums, Reddit and books — evidence weight

- Reddit communities such as r/algotrading can surface hypotheses and operational failures. Recent threads reviewed for this baseline: regime definitions and HMM uncertainty (Nov 6, 2026: https://www.reddit.com/r/algotrading/comments/1xppwoi/regime_definition/); backtest-to-live latency/order handling/low-liquidity failures (Apr 22, 2026: https://www.reddit.com/r/algotrading/comments/1ssh4lq/what_broke_first_when_i_moved_from_backtesting_to/); regime-specific strategy switching and overfitting risk (Apr 10, 2026: https://www.reddit.com/r/algotrading/comments/1shgpyf/improved_my_algo_again_and_adapted_to_gold/); strategy decay after regime mismatch (Apr 1, 2026: https://www.reddit.com/r/algotrading/comments/1s9hp40/spent_3_months_building_an_algo_took_1_week_live/); and the tendency for extra filters to overfit (Jan 5, 2026: https://www.reddit.com/r/algotrading/comments/1q4gpu1/is_overfitting_the_1_reason_most_backtested/). These are anecdotal self-reports, not audited returns. They reinforce questions to test—regime uncertainty, execution realism, feature bloat and drift—but do not establish a trading edge. Convert useful claims into hypotheses; never treat upvotes or screenshots as audited performance.
- Books to use as structured references: A Random Walk Down Wall Street (Malkiel), Options, Futures, and Other Derivatives (Hull), Advances in Financial Machine Learning and Machine Learning for Asset Managers (López de Prado), Algorithmic Trading (Ernest Chan), Following the Trend (Andreas Clenow), Systematic Trading (Robert Carver), Trading and Exchanges (Larry Harris), The Science of Algorithmic Trading and Portfolio Management (Robert Kissell), and Adaptive Markets (Andrew Lo).
- Books explain frameworks and historical practice; current profitability claims require current tests. Copyright-protected books will be referenced, not copied.

## 11. Evidence already in Rocket Trader — preserve negative results

### Earlier ML/technical experiment (Oct 2026; project conversation history)
- Implemented OHLCV features, RSI/MACD/ATR/Bollinger, Logistic/XGBoost/LightGBM ensembles, Platt calibration, novelty, walk-forward and signal-quality components.
- Calibration diagnostics were respectable in that experiment (SPY AUC 0.740 / ECE 0.014; QQQ AUC 0.719 / ECE 0.011).
- That did not validate economic edge: SPY produced 0 trades; QQQ profit factor 0.77 in one 10% configuration; research gate remained false. Preserve this as insufficient/negative evidence, not proof ML works.

### Equity research v0.4 — actual 10-year Yahoo run
- Workflow 42954130155; code commit under test 775186e104a485bbc07b50a5dcc807723aced240; artifact 13826686266; ZIP SHA-256 6929f6156d5c55665023fb0bcb007a311962c0c70e5837328a8d72e8656f9d0e.
- Eight ETFs: DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT. Yahoo adjusted daily OHLCV, 2016-11-14 through 2026-11-10; 2,511 bars per ETF. The later XNYS exchange-session gate established 100% coverage (2,511/2,511).
- Hypotheses: buy-and-hold; 63/126/252-day time-series momentum; SMA 50/200; Donchian 55/20; volatility-targeted momentum; RSI(2)/SMA exit; Bollinger exit; 5-day z-score; cross-sectional top-1 momentum.
- 73 strategy-vs-benchmark hypotheses; 5,000 moving-block bootstrap replicates per hypothesis; Holm-Bonferroni alpha 0.05. Family-wise significant: 0. Pre-screen passes: 0.
- Cross-sectional top-1 final holdout return was 40.32% vs equal-weight buy-and-hold 30.13%, but excess bootstrap p=0.3985, Holm-adjusted p=1.0, and 5th percentile excess was -31.56 percentage points. Not statistically persuasive.
- All candidates remain unpromoted; candidate promotion false, Paper approval false, orders disabled, zero submitted.
- Costs are assumptions, not measurements: 5 bps/side (2.5 half-spread + 2.5 slippage), zero commissions; 2x stress. Do not call these empirical costs.
- Earlier IEX/Yahoo audit showed IEX lacks full-decade history (~63%) and SIP is not entitled. Later source-factor analysis identified likely dividend-adjustment differences (QQQ and TLT); resolve them before treating Yahoo as independently corroborated.
- XNYS calendar correction replaced approximate weekdays with actual exchange sessions and tested both market holiday and genuinely missing session. The 100% Yahoo exchange-session result supersedes the old 96.32% weekday estimate.

### Other prior research
- ETF v0.5: 97 hypotheses; Holm significant 0; pre-screen passes 0.
- Crypto v0.4: 25 hypotheses; no strategy passed; SOL data coverage 77.1%, ineligible.
- Do not rerun exact research families without a methodological or data improvement. Preserve artifacts and compare deltas.

## 12. Current implementation status vs blueprint

**Implemented in part**
- Regime observer and portfolio selector foundations; cash-safe and market-data readiness.
- News ingestion from Alpaca/Benzinga, GDELT and official macro/regulatory RSS; human-reviewed event assessment and expiring risk overlay.
- Paper quote-to-fill cost telemetry; bar/quote heartbeat separation.
- Paper broker/account reconciliation and staged cash activities; PR #103 adds REST FILL activity to fee/FX-aware ledger-inbox completeness checks.
- Multi-year ETF research, multiple-testing correction, source audit and XNYS exchange-session gate.
- Handoff and status docs with history and rules.

**Not established**
- No strategy approved or demonstrated profitable after representative live-like costs.
- No persistent user-host Paper deployment verified.
- Paper execution costs lack representative sample and confidence bounds.
- Regime selector not validated as incremental allocator across multiple historical regimes and not authorized to place orders.
- Social/news signals have not shown incremental causal OOS net value.
- No full independent benchmark study of famous traders/managers completed; public evidence for proprietary strategies is limited.
- Tiingo adapter is optional and mocked only; no live validation and no paid plan authorized.
- No production/live order execution authorized.

## 13. Parallel workstreams and sequence

1. Build hypothesis registry: source, evidence tier, assets, horizon, regime, baseline, failure mode, implementation cost and status. Include null/negative findings.
2. Resolve Yahoo/IEX corporate-action factor discrepancies; evaluate Tiingo only with secure token/eligible plan; never splice sources.
3. Expand classical strategy evidence beyond eight ETFs and one fixed split using point-in-time survivorship-safe universes and multiple walk-forward folds. Prioritize trend, relative strength, mean reversion, defensive/cash and diversified baselines.
4. Compare simple rules, HMM/Markov switching, change-point and volatility clustering; measure stability, detection delay, false transitions and conditional net performance.
5. Test robust allocation, shrinkage, risk parity, bandit/meta-learning and abstention against a static diversified baseline. Do not use the same data to choose and validate.
6. Test official macro/event data first, then licensed news/social sources. Measure incremental value over price-only baseline and account for latency, duplication and manipulation.
7. Only then test ML/RL against simple baselines with CPCV/PBO/DSR, calibration, uncertainty and drift monitoring. RL remains sandbox-only.
8. Deploy persistent Paper, collect representative spread/slippage/fees/partial fills, reconcile fills/fees/corporate actions/cash, and run fault-injection/kill-switch drills.
9. Independent audit all candidate promotion evidence, risk limits and operations before any separate user decision on live capital.

## 14. Working rules — copy forward into every Handoff

- User authorizes repository inspection, research, coding, tests, simulations, pull requests and merging safe changes after checks pass. Continue without asking permission for ordinary engineering steps.
- This does not authorize paid subscriptions, recurring charges, capital transfers, LIVE API keys, real-money orders, leverage, shorting, margin, loans, futures/perpetuals or expansion of product scope.
- Crypto is spot only, own capital; no leverage, borrowed funds, futures/perpetuals or shorting.
- Preserve existing functionality. Inspect before changing; no speculative patches or silent behavior changes. Prefer small, testable PRs with exact test evidence.
- For code: inspect current main, branch, change, add regression tests, run relevant workflows, merge only after green checks, verify post-merge main CI.
- Never claim tests passed unless logs prove it. Record failed CI attempts, causes, corrections and final evidence.
- Every assistant response reports completion percentage. It is a conservative engineering/evidence maturity estimate, not a probability of profit.
- Every substantive repo change updates ROCKET_TRADER_HANDOFF.md and ROCKET_TRADER_PROJECT_STATUS_v0_1.md with change, rationale, tests, outcomes, failures/lessons, blockers and next actions. Handoff is the single continuity entry point.
- Preserve negative results, rejected hypotheses, historical experiments and source limitations to avoid repeating dead ends.
- Benchmark successful traders/institutions only with credible source-backed methods/performance evidence. Never invent returns or imply access to proprietary strategies.
- Novel opportunities are quarantined research with bounded experimental budget, explicit loss cap, no auto-promotion and no live orders.
- No strategy approved on attractive backtest returns alone. Require point-in-time data, independent OOS, realistic costs, multiple-testing control, robustness and Paper evidence.
- News/social/LLM output is evidence input, not direct trade instruction. Critical events require provenance, corroboration and risk review.
- If data is stale, incomplete, inconsistent, unlicensed or market state uncertain, fail closed and prefer cash.
- Do not claim perfect, finished, profitable or production-ready without evidence. Do not activate real capital; require separate explicit authorization after all gates.

## 15. Primary references and source map (cut-off 2026-11-10)

### History, systematic strategies and trader cases
- Lehoczky & Schervish (2018), Overview and History of Statistics for Equity Markets: https://doi.org/10.1146/annurev-statistics-031017-100518
- Chen (2012), The Story of Technical Analysis: https://doi.org/10.1002/9781119204213.ch2
- Hurst, Ooi & Pedersen (2017), A Century of Evidence on Trend-Following Investing: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
- TurtleTrader, Original Turtle Trading Rules (practitioner source): https://www.turtletrader.com/rules/
- Federal Reserve History, Near Failure of LTCM: https://www.federalreservehistory.org/essays/ltcm-near-failure
- Khandani & Lo (2008/2011), What Happened to the Quants in August 2007?: https://www.nber.org/papers/w14465
- Federal Reserve History, 1987 Stock Market Crash: https://www.federalreservehistory.org/essays/stock-market-crash-of-1987
- CFTC, Flash Crash report context: https://www.cftc.gov/PressRoom/SpeechesTestimony/chiltonstatement100710
- SEC, Knight Capital market-access enforcement: https://www.sec.gov/newsroom/press-releases/2013-222

### Backtest validity, execution and microstructure
- Bailey et al. (2017), Probability of Backtest Overfitting: https://doi.org/10.21314/JCF.2016.322
- Arian et al. (2024), Backtest overfitting in the ML era: https://doi.org/10.1016/j.knosys.2024.112477
- Donnelly (2023), Optimal Execution: A Review: https://doi.org/10.1080/1350486X.2022.2161588
- Nevmyvaka et al., Electronic Trading in Order-Driven Markets: https://www.cis.upenn.edu/~mkearns/papers/optexec.pdf

### Adaptive regimes, ML, RL and social signals
- Chen et al. (2026-07-20), Technical, fundamental and momentum strategy review: https://doi.org/10.1007/s11156-026-01540-7
- Khemka et al. (2026-09-03), ML in stock market forecasting review: https://doi.org/10.1007/s10791-026-10491-5
- Evolution of Reinforcement Learning in Quantitative Finance survey (2025): https://doi.org/10.1145/3733714
- Bayesian online change-point detection for order flow (2024): https://doi.org/10.1080/14697688.2024.2337300
- Liu & Son (2024), Methods for aggregating investor sentiment from social media: https://doi.org/10.1057/s41599-024-03434-2
- Cookson et al. (2025 draft), Market Signals from Social Media (preliminary, not peer-reviewed): https://www.business.rutgers.edu/sites/default/files/documents/tony-cookson.pdf
- Yang et al. (2024), Social sentiment and volatility spillovers: https://doi.org/10.1016/j.irfa.2024.103643

### Open-source projects
- QuantConnect LEAN: https://github.com/QuantConnect/Lean
- NautilusTrader: https://github.com/nautechsystems/nautilus_trader
- vectorbt: https://github.com/polakowo/vectorbt
- backtesting.py: https://github.com/kernc/backtesting.py
- Freqtrade: https://github.com/freqtrade/freqtrade
- FinRL: https://github.com/AI4Finance-Foundation/FinRL
- hftbacktest: https://github.com/nkaz001/hftbacktest
- zipline-reloaded: https://github.com/stefan-jansen/zipline-reloaded
- Curated discovery index: https://github.com/WallStreetPete/awesome-open-source-trading

### Books (bibliographic references; not a claim of exhaustive full-text review)
- Burton Malkiel, A Random Walk Down Wall Street.
- John Hull, Options, Futures, and Other Derivatives.
- Marcos López de Prado, Advances in Financial Machine Learning; Machine Learning for Asset Managers.
- Ernest Chan, Algorithmic Trading.
- Andreas Clenow, Following the Trend.
- Robert Carver, Systematic Trading.
- Larry Harris, Trading and Exchanges.
- Robert Kissell, The Science of Algorithmic Trading and Portfolio Management.
- Andrew Lo, Adaptive Markets.

## 16. Research limitations and update policy

This is a curated, evidence-weighted starting survey, not an exhaustive crawl of the entire internet, all repositories, every Reddit thread, every book, or proprietary trading desks. Some sources are practitioner-produced, preliminary or promotional; their evidence status is labeled. Publicly reported performance is not treated as independently audited unless it is.

The research landscape changes continuously. Recheck source dates, repository activity, academic publication status, broker/data entitlements and regulations before adoption. Update this document whenever a method is assessed, recording claim, source, evidence tier, implementation decision, tests, outcome and reason for acceptance/rejection. Never overwrite historical conclusions; append dated updates.
