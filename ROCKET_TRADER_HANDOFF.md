# Rocket Trader — Master Handoff & Working Rules

**Last updated:** 2026-11-11  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Latest audited code baseline SHA:** `775186e104a485bbc07b50a5dcc807723aced240`  
**Current progress estimate:** **46%** toward a complete, validated, operational system. This is an engineering/evidence maturity estimate, not a profitability estimate.

## 1. How to resume in a new conversation

The user can simply say:

> **“Continúa Rocket Trader. Lee primero ROCKET_TRADER_HANDOFF.md y después los documentos que referencia. Revisa el estado real de main, PRs, CI y artefactos antes de actuar. Sigue las reglas del handoff y continúa desde el siguiente bloqueo.”**

Do not ask the user to repeat the project's objective, prior decisions or working rules if they are in this document or the linked authoritative documents. Always inspect the live repository state before assuming this handoff is still current.

Read in this order:
1. This file — continuity, working rules, historical decisions/results and next actions.
2. `ROCKET_TRADER_BASELINE_DECISIONS_v0_2.md` — authoritative user decisions, capital policy and scope.
3. `ROCKET_TRADER_PROJECT_STATUS_v0_1.md` — detailed implementation, evidence, results and blockers.
4. `ROCKET_TRADER_INVESTMENT_RESEARCH_FRAMEWORK_v0_1.md` — research and benchmark standards.
5. Relevant subsystem documents, especially `PAPER_OBSERVER_DEPLOYMENT.md`, `PAPER_REGIME_OBSERVER.md`, `PAPER_EXECUTION_COST_TELEMETRY.md`, `NEWS_EVENT_ASSESSMENT.md` and `REFERENCE_BENCHMARK_HARNESS.md`.

## 2. User's objective

Build Rocket Trader as an adaptive, research-led, multi-asset autonomous trading system that seeks sustainable **net** capital growth while prioritizing survival and capital protection. The initial strategy capital is **MXN 1,000**; the earned-growth milestone is **MXN 100,000**. No guaranteed return or timeline is assumed.

The system must:
- Select among strategies and assets based on validated market conditions/regimes, not force trades.
- Hold cash when no candidate has defensible positive net expected value.
- Evaluate US equities/ETFs and crypto spot in separate market/execution paths with one shared portfolio-level capital and risk manager.
- Incorporate macroeconomic, financial, geopolitical and (only when lawfully/credibly sourced) social information with strict timestamp, provenance, corroboration and point-in-time controls.
- Compare candidate strategies with credible, source-backed successful-trader/investor practices and quantitative baselines where evidence exists.
- Recognize genuinely novel conditions. Novelty may justify bounded experiments only; it never waives minimum signal quality, risk gates or Paper acceptance.
- Optimize risk-adjusted net outcomes, not gross backtest returns, win rate alone, activity or impressive-looking dashboards.

## 3. Non-negotiable working rules

### Truth and evidence
1. Never invent data, tests, benchmark results, trader performance, sources, deployment state or completed work.
2. Separate **implemented**, **unit-tested**, **integration-tested**, **live-data-validated**, **deployed**, and **approved**. They are different states.
3. A green CI run proves only the checks actually executed. Offline tests do not validate live provider data, execution costs or profitability.
4. Report failures and contradictory evidence directly. Do not lower thresholds, change the sample, remove failed symbols or alter assumptions just to make a run pass.
5. Preserve immutable run artifacts and record workflow IDs, commit SHAs, PRs and exact results.
6. Every user-facing project update must include a conservative completion percentage and what evidence justifies it. Do not increase it for documentation-only work or trivial code changes.

### Engineering workflow
1. Inspect current `main`, open PRs, relevant source, tests and workflow status before editing.
2. Work on a feature branch; do not write directly to `main`.
3. Make the smallest complete change, add regression tests for the failure/risk addressed, and update relevant documentation.
4. Run local/offline tests when available, open a PR, wait for required checks, inspect their results, then merge only when green and the diff is understood.
5. Verify the merge SHA and post-merge CI/workflow. Update this handoff and project status when a meaningful milestone or blocker changes.
6. Never claim a change is merged or validated before GitHub confirms it.
7. Keep secrets out of code, docs, logs, commits and chat. The user must configure credentials privately.

### Investment and strategy research
1. Compare all candidates against cash, buy-and-hold and appropriate systematic baselines over the same dates, universe, timing, risk and costs.
2. Use chronological walk-forward/OOS evaluation, purging/embargo when labels overlap, untouched final holdout, bootstrap/permutation uncertainty and family-wise or other defensible multiple-testing correction.
3. Include fees, spread, slippage, liquidity, turnover, market impact, exposure, drawdown and capacity. Stress costs and assumptions.
4. Do not call a strategy successful because it wins in-sample, has a high win rate, beats a falling benchmark by losing less, or performs well in one small sample.
5. Successful traders/investors are references for hypotheses and process, not trade instructions. Use only credible, verifiable, time-appropriate sources. Do not fabricate personal trades or returns. Delayed public filings must not be treated as real-time knowledge.
6. For genuinely new signals, allow only a small explicit experimental risk budget after the same minimum quality and safety gates. Novelty is not evidence of edge.

### News and alternative data
1. Store source, URL, published time, first-seen time, retrieval time, content hash, revisions and asset/event mapping.
2. Avoid look-ahead bias and revised historical data masquerading as point-in-time data.
3. Corroborate critical events across independent source groups; account for syndication and duplicated reporting.
4. Raw headlines, social sentiment or LLM interpretations must never directly place orders or increase exposure. Only validated, provenance-backed assessments may affect risk, and initially only by reducing risk/blocking entries.
5. Use social sources only with compliant/licensed access and manipulation/bot controls.

### Safety and authorization
1. Development and Paper validation are authorized. **LIVE trading is not authorized.**
2. No real-money order, transfer or broker account modification may be performed without a separate explicit user authorization after a dedicated safety review.
3. Alpaca Paper only during development. No leverage, margin, borrowing, shorting, options, futures, perpetuals or leveraged/inverse ETFs.
4. Missing/stale data or FX, ambiguous order state, broker/ledger mismatch, unknown fees, corrupted durable state or risk-limit breach must fail closed.
5. Never treat Alpaca Paper buying power as the user's strategy capital. Strategy capital is tracked in MXN and broker balances in USD with fresh sourced FX conversion.
6. Do not claim the user's persistent host has been deployed or configured by the assistant. The user must deploy there and enter secrets privately.

## 4. Capital policy — authoritative summary

- Seed strategy capital: **MXN 1,000**.
- Until earned trading growth first reaches MXN 100,000: retain 100% of realized net trading profits; no personal or reserve distributions.
- Earned growth = original seed plus realized net P&L after costs and losses. External deposits do not count.
- At first crossing of MXN 100,000, permanently latch the milestone. Target allocation becomes 50% reinvestment / 10% reserve / 40% personal distribution.
- After the milestone, withhold reserve and personal transfers if they would take operating capital below MXN 100,000.
- Unrealized P&L is never distributable. Reports may propose distributions; they do not transfer money.
- See `ROCKET_TRADER_BASELINE_DECISIONS_v0_2.md` for full governing policy.

## 5. Architecture and current known state

### Implemented foundations (not equivalent to end-to-end readiness)
- Core capital policy, MXN/USD budget conversion and earned-growth milestone controls.
- Append-only realized P&L FIFO ledger and Paper account activity staging/reconciliation components.
- Persistent drawdown guard wired into Core; prototype limits still require calibration.
- Read-only Alpaca market-data adapters and historical research workflows for ETFs and crypto.
- Alpaca/Benzinga, GDELT and official macro/regulatory news observers; human-reviewed event assessment pipeline.
- Observe-only Paper runtime with persistent SQLite/WAL data collection and separate health signals.
- Quote-to-fill spread/slippage telemetry; no empirical cost approval.
- Regime observer and initial portfolio selector; selector is not yet approved or end-to-end connected to trading.
- Reference benchmark harness and source-backed strategy/investor hypothesis registry.

### Confirmed research outcomes
- Previous ETF and crypto research families produced **zero Holm-significant approved candidates**.
- SOL/USD history coverage was 77.1%, below eligibility threshold; it must not be used as qualified evidence.
- ETF estimated 5 bps/side and crypto 40 bps/side are assumptions, not empirically validated costs.
- No strategy is currently approved for Paper orders.
- No orders have been submitted by the observer/research system.

### Operational truth
- The Paper runtime remains observe-only; no autonomous order execution.
- No persistent user-host deployment has been evidenced.
- Paper fill/cost sample is not yet representative.
- Broker activity-to-ledger recovery, delayed fees, partial fills, corrections, restart recovery and full cash/position reconciliation need end-to-end proof.
- LIVE remains disabled.

## 6. Latest known work and immediate blocker

### Historical baseline (superseded)
The previous PR #94/#95 baseline was `a6f1b92136c041af0084bf28d7e686df0d444725`. The current main SHA is recorded in the header. PRs #96–#100 and the 2026-11-11 update are appended below; do not use the historical SHA as current.

- PR #94: regime observer health separates process liveness from market-data readiness and exposes safe-cash/exposure.
- PR #95: actual ETF history crosscheck now triggers on relevant pushes to main, as well as weekly schedule/manual dispatch.
- Workflow run **42920786498** (job **130194785274**) completed with failure on 2026-11-10. Dependency install, compile, offline tests and artifact upload passed; live Yahoo history fetch failed for all eight ETFs with `ValueError: output array is read-only`.
- Log/report proved the executed code still passed `repair=True`, contradicting earlier documentation that claimed `repair=False`. Artifact ID **13812205814** reports zero symbols compared. Do not treat it as historical validation.
- PR #96 merged as `d001fc3f3661b1cae39de535c52b235975f164ae`: adds this handoff, updates README/status, changes Yahoo history to `repair=False`, and adds a regression test that asserts this provider parameter.
- PR #96 offline CI run **42922818287** succeeded: compile and all 6 tests passed. The live comparison step was correctly skipped for `pull_request` events.
- Post-merge live comparison run **42922974687** completed successfully as a retrieval/report job and uploaded artifact **13812508089**. All eight ETFs were retrieved, but **0/8 passed** the full ten-year coverage diagnostic: Yahoo returned 2,512 sessions, IEX 1,582, and common overlap was 1,581 sessions (2020-07-27 to 2026-11-09). Yahoo coverage relative to its own full series was 62.94%; IEX coverage was 99.94%. Correlations were 0.99835–0.99975 and p95 absolute daily return differences 4.69–9.97 bps, but cumulative return differences ranged from 1.3 bps DIA to 220.5 bps SPY. The job's success means retrieval/report generation passed, not the diagnostic gates. Candidate promotion, Paper approval and orders remain false.

## 7. Next actions — ordered

1. Resolve the ETF historical data-source limitation: IEX does not provide the requested full 10-year history for this account. SIP previously returned NOT_ENTITLED. Evaluate a properly licensed full-history source or entitlement upgrade only if economically justified; retain separate overlap-parity and full-period coverage gates. Investigate SPY/QQQ cumulative-return differences before treating providers as interchangeable. Never splice provider series or weaken coverage gates.
2. Fix authoritative broker activity reconciliation so missed fills can be recovered idempotently from broker activities, with explicit handling for delayed fees, partial fills, corrections/busts and corporate actions.
3. Collect enough Paper quote/fill observations to estimate spread/slippage/fees by asset, liquidity, session and order conditions, with minimum sample and confidence gates. Keep approval false until evidence supports it.
4. Validate regime features, freshness, hysteresis, transitions and regime-conditioned performance using point-in-time history.
5. Connect selector to runtime in **recommendation/observe-only** mode first; test abstention, stale data and safe-cash behavior.
6. Expand strategy research and benchmarks, including source-backed trader/process references, multiple-testing correction, OOS and realistic cost stress.
7. Complete shared portfolio risk management, order lifecycle, restart-safe kill switch, daily-loss and drawdown handling, and broker/ledger reconciliation.
8. User deploys the Paper stack on a persistent host with private Paper credentials. Collect representative multi-week operational evidence.
9. Independent readiness review and a separate explicit user authorization are required before any LIVE capability can be enabled.

## 8. Deployment boundary

The runbook is `PAPER_OBSERVER_DEPLOYMENT.md`. The user must execute deployment on their persistent host and set their own Paper credentials privately. Never request secrets in chat. Do not destroy the persistent Docker volume when restarting. A successful deployment is not strategy approval or LIVE authorization.

## 9. Progress measurement

Current estimate: **46%**. This represents the combination of architecture, implemented safety/research foundations and verified operating evidence. The project is not 46% profitable, nor does it mean a 46% probability of success.

Increase the estimate only when a significant gate is completed with evidence. In particular, deployment, empirical execution costs, full accounting reconciliation, robust OOS strategy edge, sustained Paper acceptance and independent LIVE review are major remaining milestones. A complete codebase without real operational validation is not a complete trading system.

## 10. Historical decision and experiment ledger — do not repeat without new evidence

This section preserves material paths already explored, including failures and superseded results. Before launching a new experiment, check whether its hypothesis, data window, timing model and parameter family have already been tested. A repeated run is justified only by a documented change in data, methodology, market regime, code defect correction or a genuinely new pre-registered hypothesis.

### 10.1 Research-method transfer from Jefe Maestro / MDV PS
- Reused: time-ordered validation, temporal features, ensembles only when incremental OOS value is proven, data fingerprints, bootstrap/permutation, global multiple-testing correction, attribution and continuity.
- Explicitly rejected: using lottery draw rows, lottery number frequencies/co-occurrences, draw gaps, lottery entropy assumptions, SMOTE treatment or physical-draw hypotheses as financial features. Financial markets require independent financial definitions and data.
- Historical MDV PS FIX08 evaluated 4,632 hypotheses; 188 raw p-values were below 0.05, but **zero** survived global Holm-Bonferroni correction. This is a methodological caution, not evidence about markets.
- Earlier Rocket Engine audit identified and corrected/blocked: misplaced `novelty_score`; missing purge for forward-label horizon; OOS alignment by tail length instead of original row positions; historical `ret_5` mislabeled as forward expected return; feature similarity incorrectly called precedent; keyword NewsEngine score without validated NLP; classifier-only walk-forward output falsely resembling executable backtest. Treat `UNKNOWN`/zero-confidence news and `passed=False` classifier diagnostics as intentional safety behavior until a validated replacement exists.

### 10.2 Historical strategy research — corrected timing results govern
- **Superseded close-to-close results:** earlier equity v0.2 and crypto v0.1 could include an overnight close-to-open gap that was unavailable to a signal generated at the prior close. These results are invalid for promotion. Do not quote them as current strategy evidence.
- **Corrected execution clock:** completed close signal -> next bar open entry -> open-to-next-open return; costs charged at position changes; final interval handled without inventing a future price; prior position preserved at walk-forward boundaries. Regression test includes a 100% overnight gap and confirms only the subsequent 10% open-to-open return is credited.
- **Corrected ETF v0.3:** 8 ETFs, 49 hypotheses, 0 Holm-significant, 0 pre-screen passes. Cross-sectional top-1 momentum holdout +41.0% vs +31.2% equal-weight buy-and-hold, but excess 5th percentile -30.1%, raw bootstrap p=0.3921, Holm-adjusted p=1.0. Not an edge; single-asset trend/momentum generally underperformed same-asset buy-and-hold.
- **Corrected crypto v0.2:** BTC/ETH eligible; SOL excluded for 77.1% coverage and a 416-day gap. 13 hypotheses, 0 Holm-significant, 0 pre-screen passes. Cross-sectional top-1 momentum holdout -29.5%, raw p=0.4267, Holm p=1.0. No candidate.
- **Mean-reversion tranche ETF v0.4:** 73 total hypotheses, 0 Holm-significant, 0 pre-screen passes. TLT Bollinger(20,2) holdout +8.83%, +8.95 percentage points vs TLT buy-and-hold, but only 10 entries and Holm p=1.0. RSI(2)/SMA200 and five-day downside z-score mostly underperformed. No candidate.
- **Mean-reversion tranche crypto v0.3:** 19 hypotheses, 0 Holm-significant, 0 pre-screen passes. BTC RSI(2) holdout +4.57% on only 4 entries, Holm p=1.0; Bollinger/z-score negative in BTC/ETH. SOL excluded. No candidate.
- Research families and results are recorded in `RESEARCH_EXECUTION_TIMING_CORRECTION_2026-11-10.md` and `RESEARCH_HYPOTHESIS_PROGRAM.md`. Next research must be pre-registered; do not rerun the same indicators/parameters on the same holdout and call it new evidence.

### 10.3 Market data attempts and what was learned
- Alpaca IEX daily history is not SIP/NBBO. It is the configured lower-coverage feed. SIP request previously returned `NOT_ENTITLED`; do not keep retrying SIP unless entitlement changes.
- The initial 10-year Yahoo/Alpaca comparison workflow (run `42920786498`, artifact `13812205814`) failed for all eight ETFs because Yahoo `repair=True` raised `ValueError: output array is read-only`. Logs exposed a mismatch between docs and executed code.
- PR #96 changed the actual provider call to `repair=False` and added a regression test. PR CI run `42922818287` passed all 6 offline tests.
- Post-merge audit run `42922974687`, artifact `13812508089`, successfully retrieved all eight symbols with no provider errors. However, Yahoo returned 2,512 sessions while Alpaca IEX returned 1,582; overlap was 1,581 sessions (2020-07-27 to 2026-11-09). Yahoo common-session coverage was 62.94%, IEX 99.94%, and **0/8** passed the full 10-year coverage gate.
- On the overlap, daily return correlations were 0.99835–0.99975 and p95 absolute daily-return differences 4.69–9.97 bps. Cumulative differences ranged from 1.3 bps DIA to 220.5 bps SPY; investigate adjustment methodology/corporate actions before declaring source parity.
- Meaning: the Yahoo repair crash is fixed, but the ten-year cross-source validation is still not passed. Do not splice Yahoo and IEX histories or relax the 95% coverage gate. Evaluate a licensed full-history source or entitlement change on economic grounds. Keep source provenance separate.

### 10.4 Paper execution and accounting experiments
- Two BTC/USD Paper round trips were performed strictly as capped execution/accounting smoke tests (USD 10 notional cap each), not strategy tests. Both ended with zero residual BTC. First order initially returned `pending_new` then reconciled as filled; hardened second cycle waits for terminal state, cancels if needed, reconciles actual net inventory and sells only what the broker confirms.
- Paper account had simulator seed cash USD 100,000, multiplier 1, no margin multiplier, shorting disabled, options level 0. This is not user capital and does not count toward MXN 1,000 strategy seed or MXN 100,000 earned milestone.
- Read-only post-test check showed USD 99,999.86 cash/equity and no positions. The USD 0.14 balance decline is an observed net change, **not** proven fee-only attribution.
- Four FILL activities were found, plus JNLC cash journal USD 100,000. JNLC/CSD/CSW must remain pending capital reconciliation, not auto-classified as user deposits or profit.
- Crypto fee posting is delayed end-of-day. Same-day missing CFEE/FEE is not zero fee. Match fees to exact execution IDs; do not close realized P&L while fees remain unresolved.
- Prior components PR #48–#55 established market freshness, worker failure health, sub-cent fee precision, durable idempotent fill inbox, TRD activity normalization, exact fee resolver, timestamped FX and retryable FIFO ledger bridge. Corrections/busts remain quarantined for manual review; unlinked regulatory fees remain unresolved/manual.
- Paper execution test evidence: `PAPER_EXECUTION_TEST_REPORT_2026-11-10.md`. These mechanical tests do not prove profitable signals or representative live execution.

### 10.5 Architecture and operational lessons
- PRs #48–#60 established runtime/fill-accounting foundations, Docker CI/image publishing, and first Holm-Bonferroni corrections for ETF/crypto research.
- PR #69 introduced conservative cash journal handling; unknown capital activities must not silently become user capital.
- PRs #77–#95 added staged cash activities/manual confirmation, read-only broker reconciliation, regime selector/observer, official macro news, event overlay, quote-to-fill telemetry, observer runbook, heartbeat separation, health readiness semantics, and main-push live ETF audit.
- Quote telemetry must never refresh bar-stream heartbeat; independent freshness matters.
- A healthy process does not mean market data is ready. Health reports liveness separately from `market_data_ready`, `safe_cash` and exposure.
- Raw news never directly allocates capital. Official/Alpaca/GDELT feeds are observers; critical assessments require source provenance and human review. There is no validated social sentiment model yet.
- Container image publication and green CI do not equal deployment. No persistent user-host Paper deployment has been verified.

### 10.6 Open hypotheses / decisions not yet proven
- Whether a simple long-only regime-aware blend of trend, breakout, relative strength and/or mean reversion can add robust OOS net value over cash, buy-and-hold and simple fixed-schedule controls.
- Whether event/news assessments add incremental, point-in-time predictive value after latency, source quality and transaction costs.
- Whether any successful-trader public evidence can be represented as time-available, verifiable data; otherwise use only qualitative process principles and no numerical trader benchmark.
- Whether the 5 bps/side ETF and 40 bps/side crypto cost assumptions survive empirical Paper measurements. They remain unverified.
- Whether a full-history licensed data source is worth its cost compared with the expected research value.
- Whether novel signals can add value under a capped shadow/experimental budget; novelty alone is not evidence.

### 10.7 Change-log discipline — mandatory for every future change
For each meaningful change, append a dated entry to this Handoff (and synchronize project status when relevant) containing:
1. PR/commit and exact files/components changed.
2. Problem or hypothesis that motivated the work.
3. Prior attempts or related historical runs, and why this attempt is not redundant.
4. Tests/checks actually run and exact outcomes.
5. Live-data/Paper evidence separately from offline CI.
6. Positive results, negative results, errors and known limitations.
7. Decision: accepted, rejected, deferred or needs more evidence.
8. What was learned and what must not be repeated.
9. Next actions, dependencies and explicit stop conditions.
10. Progress percentage with rationale; documentation-only work does not increase it.

Never overwrite the historical truth. Correct stale summaries by explicitly noting the correction and retaining the original failure/result in this ledger. The Handoff is append-oriented; keep prior evidence and mark superseded conclusions rather than deleting them.


### 2026-11-11 continuation — PRs #99 and #100

**PR #99 — historical continuity ledger**
- Merge commit: `ce738f2f0443e7c352c2fa10fc73857f3c3f067e`.
- Expanded this handoff with the historical experiment/decision ledger: Jefe Maestro transfer boundaries, superseded close-to-close timing, corrected ETF/crypto momentum and mean-reversion results, Yahoo/IEX/SIP history, Paper execution smoke tests, delayed fees/JNLC handling, runtime/news lessons and open hypotheses.
- Corrected `MARKET_DATA_SOURCE_AUDIT.md` to document Yahoo `repair=False` and the actual 0/8 full-coverage outcome.
- Documentation-only; no progress percentage increase.

**PR #100 — regime observer timestamp alignment**
- Merge commit: `81be6e8e1fea127641b760a469ede4f7a56cdff9`.
- Root cause: cross-asset return series were previously paired by array position. Missing minute bars in one symbol could cause returns from different UTC times to be correlated, contaminating correlation/stress/regime features.
- Fix: normalize timestamps to UTC instants, intersect exact timestamps across the whole universe, require at least 60 common bars and 95% coverage per symbol, reject common-series gaps over 180 seconds and reject stale/unaligned data. Persist aligned-count/coverage/gap diagnostics.
- Regression tests: one missing bar is aligned correctly; material cross-symbol gaps fail closed; shared multi-minute gaps fail closed.
- CI evidence: regime observer suite 22 tests passed; news-event assessment suite 9 passed. Runtime/accounting/container checks also passed: 156 tests across the runtime/accounting suites, Compose configuration valid, Docker Paper observer image built and contents verified.
- This is input-alignment correctness only. It does not prove regime predictive power, profitability, persistent deployment or order readiness.
- Observer remains read-only, zero approved candidates, 100% cash / abstain, no orders.

**Current continuation point after PR #100**
1. Investigate historical source parity/adjustment divergence and full-history data options without relaxing coverage.
2. Close broker activity-to-ledger reconciliation gaps: delayed fees, partial fills, corrections/busts, unlinked regulatory fees and restart recovery.
3. Validate regime feature stability and predictive usefulness on archived point-in-time data, including hysteresis/transition behavior and matched baselines.
4. Continue empirical Paper cost telemetry only after persistent host deployment; no representative fill sample exists.
5. Maintain the observe-only selector; integrate recommendations only after research acceptance gates pass.
6. Preserve the existing negative research results; pre-register new hypotheses and do not rerun the same family/holdout as if it were new.

**Progress estimate remains 46%.** The timestamp bug fix and expanded tests materially improve data integrity, but no new strategy edge, empirical costs or deployed forward evidence has been demonstrated.


### PR #101 — handoff synchronization after PR #100
- Merge commit: `e265cc92a0eb931031151d963e1d320ced990cf7`.
- Synchronized the canonical handoff and project status with the PR #100 timestamp-alignment fix and its CI evidence.
- The main SHA in this document now reflects PR #101.
- Documentation-only; progress remains 46%.


### PR #102 — handoff audit-truth correction
- Merge commit: `d0b8bfc142729f89a7156ecb378e611a91c2cb77`.
- Corrected the stale pending/queued wording for the completed Yahoo/IEX audit and updated the handoff main SHA after PR #101.
- Documentation-only; no progress increase.

### PR #103 — broker FILL activity to ledger-inbox reconciliation
- Merge commit: `7601ec2b5e1cb66d351703eb1de9d6f1347dd311`.
- Root cause: the runtime staged REST `FILL` activities but did not compare them with the durable fee/FX-aware fill inbox. Account-activity health could therefore be green even if a broker-confirmed fill was absent from the TradingStream/Activity SSE path or remained pending.
- Official Alpaca schema: legacy REST `FILL.id` is `timestamp::execution_uuid`; Activity SSE `ref_id` carries the same execution identifier. Sources: https://docs.alpaca.markets/us/docs/account-activities and https://docs.alpaca.markets/us/docs/activity-sse.
- New read-only reconciliation checks each staged FILL against the inbox by execution UUID, quantity, price, normalized symbol, side, order ID and timestamp (2-second tolerance). The inbox must be `PROCESSED`, meaning fee/FX resolution has allowed ledger posting.
- Missing, mismatched, PENDING or FAILED inbox records now keep account-activity health in ERROR. The module never writes ledger entries or reconstructs fills; the existing fee/FX-aware bridge remains the only posting path.
- Regression evidence: 8 dedicated activity-reconciliation tests passed; 32 runtime tests passed, including matched and missing fill health cases. All 166 tests across the runtime/accounting workflow passed. Compose validation, Docker Paper observer image build/content verification, and post-merge image publication succeeded. Post-merge workflow IDs: `42953433750` (runtime/accounting), `42953433726` (container), `42953434426` (image publication), `42953435784` (runtime freshness).
- This is a stronger accounting completeness check, not a proof of broker statement completeness or strategy profitability. It detects missing events but deliberately does not auto-repair them.
- Paper observer remains OBSERVE_ONLY; LIVE disabled; no orders authorized.

**Current continuation point after PR #103**
1. Monitor the new activity reconciliation on a persistent Paper deployment; verify actual broker FILL IDs and SSE ref IDs match in practice. No user-host deployment has yet been verified.
2. If a real mismatch occurs, inspect the exact Alpaca payload and correct the mapping with a regression fixture; never guess or auto-post a fill.
3. Resolve unlinked daily regulatory fees and trade corrections/busts; they remain manual-review blockers.
4. Investigate full-history ETF source availability and adjusted-return divergence without weakening data gates.
5. Validate regime feature stability/predictive value on point-in-time historical data; timestamp alignment correctness is not alpha.
6. Collect representative Paper spread/slippage/fill costs after user-host deployment.
7. Preserve zero approved strategy candidates until robust net OOS edge, costs and operations pass.

**Progress remains 46%.** This PR closes an important accounting observability gap, but live broker evidence, persistent deployment, representative costs and strategy edge remain absent.


### PR #104 — historical handoff synchronization
- Merge commit: `53a7fc3b4f7c8fd4530a1818e1fd9d31700e5dc1`.
- Recorded PR #103's broker fill activity reconciliation and its exact tests/limits.
- Documentation-only; no progress increase.

### 10.10 Historical ETF data vendor evaluation — 2026-11-11
The goal is a defensible 10-year adjusted daily ETF dataset with provenance and a second independent source, not merely a feed that returns ten calendar years.

**Observed provider constraints**
- Alpaca IEX: available history in this account starts 2020-07-27 for the tested ETF universe; not a full 10-year source. IEX is not SIP/NBBO.
- Alpaca SIP: prior request returned `NOT_ENTITLED`. Do not retry unless account entitlement changes.
- Yahoo Finance: 10-year adjusted history retrieved after setting `repair=False`, but the live overlap audit showed nontrivial cumulative differences from Alpaca IEX (especially SPY); research-only and not yet independently corroborated.

**Official alternatives researched**
- Tiingo EOD documents adjusted and raw OHLCV, dividends and splits, with its adjusted price methodology following CRSP conventions: https://www.tiingo.com/documentation/end-of-day
- Tiingo current individual pricing lists Starter at $0 with 5 years of history and Power at $30/month ($300/year) with 15+ years; API quota is up to 100,000 requests/day on Power. License shown is internal use only: https://www.tiingo.com/pricing and https://www.tiingo.com/about/pricing
- Tiingo product page advertises broad EOD coverage and long historical depth, but the plan-specific history cap still applies: https://www.tiingo.com/products/end-of-day-stock-price-data
- Alpha Vantage documents 25+ years for daily adjusted data, but `TIME_SERIES_DAILY_ADJUSTED` is a premium API function; free usage is limited to 25 requests/day: https://www.alphavantage.co/documentation/ and https://www.alphavantage.co/premium/ and https://www.alphavantage.co/support/

**Current conclusion**
- Best candidate to evaluate for a licensed 10-year EOD cross-check is Tiingo Power, because its stated 15+ year history and published individual price are clear. It is not yet selected, subscribed, or live-tested.
- Alpha Vantage is a secondary candidate, but its adjusted daily endpoint is premium and pricing/entitlement economics are not yet established.
- Do not purchase or start any paid subscription automatically. The user's authorization to develop the repository does not authorize recurring vendor charges.
- Next: implement Tiingo as an optional provider behind `TIINGO_API_TOKEN`, add mocked contract tests and a provider-parity report; live validation requires the user to add a token securely and separately approve any paid plan. Keep Yahoo and IEX histories separate; no series splicing. Re-check licensing if Rocket Trader is ever redistributed or offered as a service.


### PR #106 — optional Tiingo EOD source and metadata correction
- Merge commit: `775186e104a485bbc07b50a5dcc807723aced240`.
- Added optional `TIINGO` source to the ETF research runner. It uses adjusted OHLCV fields, reads credentials only from `TIINGO_API_TOKEN`, and enforces the same minimum requested-history, weekday coverage, gap and staleness gates. No automatic fallback or source splicing.
- Added workflow dispatch option TIINGO and secure GitHub secret mapping. Default research source remains unchanged.
- Fixed a second source-of-truth bug: the v0.4 report metadata claimed Yahoo `repair=True` even though the actual fetch call was `repair=False`. The metadata now reports the actual setting and has a regression test.
- PR CI run `42954001467`: offline self-test and all 19 equity research tests passed. Live provider research was skipped on pull_request as designed.
- Post-merge push run `42954130155` triggered the standard Yahoo 10-year research (not Tiingo). At the time of this handoff update it remained in progress; inspect its final conclusion/artifact before recording a result.
- Post-merge runtime/accounting workflow `42954130244` passed all 166 offline tests, including the new fill reconciliation suite.
- No Tiingo token was supplied/configured, no paid subscription was purchased, and no real Tiingo API request was made. A real 10-year Tiingo validation requires an eligible plan/token configured privately by the user; the free Starter plan's stated 5-year limit cannot satisfy the 10-year gate.
- No strategy approval, Paper approval or order enablement changed.

**Next actions after PR #106**
1. Review the post-merge Yahoo research run `42954130155`; it should reproduce the corrected provider metadata and the previous research family result without changing hypotheses.
2. If a Tiingo token becomes available, run a 10-year Tiingo research/cross-source parity audit and compare Yahoo/Tiingo/IEX on common sessions; no vendor subscription or expense without separate user approval.
3. Continue broker activity reconciliation monitoring after persistent Paper deployment; no host deployment evidence yet.
4. Investigate the adjusted-return cumulative divergence between Yahoo and IEX; high daily-return correlation alone is insufficient.
5. Keep all strategies unapproved until corrected OOS, multiple-testing, empirical costs and Paper acceptance gates pass.

**Progress remains 46%.** The Tiingo adapter and metadata fix improve research source optionality and audit truth, but the adapter has only mocked tests and no live Tiingo evidence; no strategy edge or persistent Paper operation has been established.


### PR #108 — Handoff synchronization after PR #106
- Merge commit: `aaf4cf02c3d04c77925357df7687a1f9946abe2f`.
- Recorded PR #106's optional Tiingo adapter, corrected Yahoo metadata, offline test evidence and no-subscription boundary.

### Post-merge research run after PR #106 — run 42954130155
- Workflow run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42954130155
- Artifact: `13826686266`.
- Yahoo 10-year research completed successfully for all eight ETFs (DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT); data-quality gate passed for all eight.
- Report now truthfully states `auto_adjust=True, actions=True, repair=False`.
- Research family size 73; familywise-significant candidates **0**; pre-screen passes **0**. `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_submitted=0`.
- This is a consistency/regression run of the already-tested v0.4 family after a metadata/provider-source code change, **not a new hypothesis tranche**. It does not justify rerunning the same family again on the same data/holdout.
- The run validates Yahoo data retrieval and quality gates, not independent source parity, realistic transaction costs or profitability.
- Tiingo was not queried: no API token or paid plan is configured. The Tiingo adapter has mocked contract tests only.

**Next continuation point**
1. For a genuine independent 10-year adjusted EOD validation, use Tiingo only after the user configures an eligible plan/token privately; compare all eight symbols and inspect corporate-action/cumulative-return differences. No purchase without separate approval.
2. Do not rerun the same 73-hypothesis v0.4 family on the same Yahoo history/holdout as a new research claim.
3. Continue live Paper operational evidence only after the user's persistent host is deployed.
4. Investigate broker activity reconciliation on actual Paper fills; current tests are synthetic/fixture-based.
5. Validate regime stability and predictive value with point-in-time data and new pre-registered hypotheses.

**Progress remains 46%.** Yahoo retrieval is reproducible with corrected metadata, but strategy evidence remains negative (0/73 familywise significant, 0 pre-screen); no independent Tiingo data or Paper forward validation exists.
