# Rocket Trader — Master Handoff & Working Rules

**Last updated:** 2026-11-12 (PRs #187–#194 merged; activity, accounting and reconciliation controls hardened)
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Latest main HEAD before this Handoff refresh:** `231332e16b3411cf660f2f5ec1eefdeac493d99d` (PR #194 merged; strategy runtime baseline remains unchanged unless separately evidenced)
**Current progress estimate:** **58%** toward a complete, validated, operational system. This is an engineering/evidence maturity estimate, not a profitability estimate.

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

1. Verify the post-merge historical SIP retrieval on main using the Paper credentials already configured in GitHub Actions. Inspect actual workflow steps and JSON artifacts (not just green status); confirm the 16-minute XNYS completed-session cutoff, full requested-history coverage, all eight symbols, corporate-action adjustments and independent Yahoo parity. The previous recent SIP NOT_ENTITLED probe did not test delayed historical SIP. If SIP returns data, that proves this credential set can access delayed historical SIP; it does not by itself prove source parity or strategy edge. Do not pay for real-time SIP, splice providers or weaken coverage gates.
2. Extend authoritative broker activity reconciliation beyond the now-implemented idempotent FILL ingestion, quantity/weighted-average-price comparison and finite timestamp-tolerance guard. Remaining gaps include end-to-end restart recovery, delayed fee allocation, partial-fill lifecycle transitions, corrections/busts, corporate actions and broker/ledger cash-position parity.
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

Current estimate: **58%**. This represents the combination of architecture, implemented safety/research foundations and verified operating evidence. The project is not 58% profitable, nor does it mean a 58% probability of success.

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
- Alpaca IEX daily history is not SIP/NBBO. It is the configured lower-coverage feed. The previous `NOT_ENTITLED` response came from a recent request ending at current time; historical SIP ending 15+ minutes earlier is a separate free Basic-plan path and still needs a read-only Paper-account test.
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
- Alpaca SIP: the prior `NOT_ENTITLED` result came from a recent/latest query ending at `current`; it did not establish historical SIP entitlement. The read-only historical query must use an end at least 15 minutes old.
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


### PR #106 — completed post-merge Yahoo 10-year research evidence
- Post-merge workflow run `42954130155` completed successfully on 2026-11-11; job `130305073197`; artifact `13826686266` (`rocket-trader-equity-multiyear-research-v0-4`).
- Important: this was the workflow's default **Yahoo Finance** research run, not Tiingo and not a fresh Alpaca IEX/SIP parity run. No Tiingo token was configured, so the new Tiingo adapter was not called.
- Yahoo supplied all 8 requested ETFs (DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT) for the requested 10-year period. Each had 2,511 daily bars, approximate weekday coverage 96.32%, and maximum calendar gap 4 days. The existing data-quality gate passed for all 8.
- Research used close-observed signals and next-session-open execution, with chronological 60% train / 20% validation / 20% final holdout. Base cost assumption remains 5 bps per side (2.5 half-spread + 2.5 slippage, zero commission), a placeholder and **not empirical**.
- Final holdout family: 73 hypotheses, Holm-Bonferroni alpha 0.05, 5,000 centered moving-block bootstrap replicates per hypothesis. **Pre-screen passes: 0/73. Family-wise significant: 0/73.** No candidate qualifies; candidate promotion false; Paper approval false; orders enabled false; orders submitted 0.
- Result is a successful 10-year Yahoo data retrieval and research execution, but a negative strategy-selection result. Do not misstate it as a validated profitable strategy or a successful cross-vendor 10-year comparison.
- The earlier Alpaca IEX comparison still only covered 2020-07-27 onward (about 6.3 years); the separate entitlement probe showed recent/live SIP was `NOT_ENTITLED`. The previous common-window daily-return correlations were high, but cumulative-return differences reached 220.5 bps for SPY. Historical SIP availability is a separate Basic-plan path and still needs verification with the Paper credentials.
- Workflow `42954130244` also passed the post-merge Paper runtime/accounting suite (166 tests). This remains CI evidence, not evidence from a persistent user-host Paper account.
- Artifact SHA256 ZIP digest: `6929f6156d5c55665023fb0bcb007a311962c0c70e5837328a8d72e8656f9d0e`.

**Next research steps**
1. Obtain an independently licensed full-history provider (Tiingo adapter is now available, but no token/subscription has been authorized); compare Yahoo, Tiingo and Alpaca IEX on common dates and corporate actions without splicing.
2. Revisit strategy hypotheses only with a documented research rationale; do not relax the current statistical gates just to obtain a passing strategy.
3. Replace placeholder costs with actual Paper spread/slippage/fill and fee data; test sensitivity to materially higher costs.
4. Extend research to more independent walk-forward periods and multiple market regimes, including stress periods, before considering any candidate.
5. Keep deployment, broker reconciliation and all trading orders separate: no persistent host evidence and no live-order authorization.

**Progress remains 46%.** Ten-year Yahoo history and the negative research result are now verified; Tiingo live history, independent provider parity, empirical costs, strategy edge and Paper runtime remain unresolved.


### PR #110 — verified Yahoo 10-year research result
- Merge commit: `9cc9568567d203297d6fbf5e8ee25ad69fcecbd4`.
- Recorded post-merge run `42954130155`, artifact `13826686266`, and the exact negative result: 8/8 Yahoo ETF histories pass the data-quality gate; 73 holdout hypotheses, 0 pre-screen passes, 0 Holm-Bonferroni significant; no promotion/Paper approval/orders.
- Preserved caveats: costs remain placeholder 5 bps/side, this was Yahoo-only, and prior Alpaca IEX history was only ~6.3 years with unresolved cumulative divergence.

### PR #111 — optional three-source adjusted history audit
- Merge commit: `6a2cfd760d707da9eb8a1ba1f640e8db834a9aab`.
- The read-only Alpaca/Yahoo audit now optionally consumes Tiingo adjusted daily closes when `TIINGO_API_TOKEN` is configured privately as a GitHub Actions secret.
- Produces two separately named comparisons per ETF: Tiingo vs Yahoo and Tiingo vs Alpaca, with session counts, common-session coverage, daily return correlation, absolute return differences, cumulative-return difference direction and diagnostic gates.
- No token means Tiingo is explicitly not requested and the existing two-provider audit runs unchanged. A configured token with missing/malformed history records a Tiingo error; no fallback or history splicing.
- A full 10-year Tiingo-vs-IEX overlap will fail the 95% source-coverage gate while IEX only provides ~6.3 years. This is intentional; the audit must not label partial overlap as 10-year validation.
- Correctness detail: report distinguishes successful data retrieval from diagnostic parity failure. A provider mismatch can be reported with a successful audit run while `all_diagnostic_gates_pass=false`; provider fetch errors remain explicit.
- PR CI run `42954914689`: compile + all 9 cross-check tests passed; live data step skipped on pull_request by design.
- Post-merge audit run `42955004812` completed successfully; artifact `13827085617`. All 8 ETFs were retrieved from Yahoo (2,513 sessions each) and Alpaca IEX (1,582 sessions for 7 symbols; 1,583 for SPY). Common range: 2020-07-27 to 2026-11-10. Yahoo common-session coverage was 62.95%; IEX coverage 100%. Therefore 0/8 passed the full-period 95% coverage gate. Daily return correlations were 0.99835–0.99975, but cumulative-return differences ranged from -0.75 bps (IWM) to +218.90 bps (SPY); QQQ was +89.98 bps and TLT +26.01 bps. High correlation does not erase adjustment divergence. Tiingo token was absent (`tiingo_comparison_requested=false`), so no Tiingo data was fetched.
- Post-merge runtime run `42955004617` completed successfully: all 10 runtime/accounting test modules passed (95 tests in aggregate). This is CI-only evidence, not persistent Paper deployment or actual broker-account reconciliation.
- No Tiingo secret/token or paid plan configured; no vendor spend. No order or Paper approval changes.

**Next steps**
1. To run a real Tiingo comparison, the user must separately decide whether to obtain an eligible plan and configure `TIINGO_API_TOKEN` as a repository secret. Do not ask for the token in chat or incur spend.
3. Reconcile adjustment methodology/corporate actions across sources; keep each provider's time series separate.
4. Strategy work remains research-only: the 10-year Yahoo holdout produced 0/73 pre-screen and 0/73 Holm-significant hypotheses. Do not loosen statistical gates to force a winner.
5. Empirical costs, multi-fold OOS, live Paper deployment and broker evidence remain blockers.

**Progress remains 46%.** PR #111 adds a new independent-source audit path but has not produced Tiingo evidence because no token is configured. It does not improve the strategy-edge evidence.


### PR #111 — post-merge audit result (2026-11-11)
- Audit workflow `42955004812` completed successfully; immutable artifact `13827085617`.
- The standard push run used Yahoo and Alpaca IEX only. `TIINGO_API_TOKEN` was blank, so `tiingo_comparison_requested=false` and zero Tiingo requests were made.
- Eight ETF pairs retrieved successfully: Yahoo 2,513 sessions each; Alpaca IEX 1,582 sessions for DIA/EEM/EFA/GLD/IWM/QQQ/TLT and 1,583 for SPY. Common dates 2020-07-27 through 2026-11-10. Yahoo common coverage 62.95%; Alpaca IEX 100%.
- Full-period coverage diagnostic: 0/8 pass because Yahoo's 10-year period cannot overlap 95% with Alpaca's ~6.3-year IEX history. This is expected and correctly fails closed.
- Daily return correlations 0.99835–0.99975. Yet cumulative return difference (Alpaca minus Yahoo on common period) ranges -0.7507 bps IWM to +218.9025 bps SPY; QQQ +89.9785 bps; TLT +26.0144 bps. This confirms source adjustment differences remain material for some instruments despite high daily correlation.
- Runtime workflow `42955004617` completed successfully; 10 runtime/accounting test modules passed (95 tests aggregate).
- No Tiingo source evidence, no empirical cost validation, no strategy approval, no Paper deployment evidence and no orders.

**Current next best research action:** investigate per-symbol corporate-action/adjustment divergence (especially SPY, QQQ and TLT) using vendor corporate-action records and event-level normalized prices. Do not choose one provider as truth or splice price series until a documented reconciliation exists.


### PR #113 — date-level adjustment divergence diagnostics
- Merge commit: `6ac4caa90de52ad1d1faefedbe301997b2360480`.
- Adds the ten largest absolute daily-return divergences per symbol with exact session date, Yahoo return, Alpaca return and signed Alpaca-minus-Yahoo bps.
- Adds the ten largest normalized adjusted-close path divergences, anchored at the first common session.
- Regression test simulates an adjustment step and verifies the exact session is surfaced. PR CI `42955368774`: all 10 cross-check tests passed; live audit skipped on pull_request by design.
- These dates are diagnostic leads only. No corporate-action attribution, automatic correction, source preference or series splicing is performed.
- Post-merge live audit `42955455037` completed successfully; artifact `13826901809`. Paper runtime suite `42955454994` also passed. The exact outlier dates are now recorded below.
- Current best investigation focus based on prior run: SPY (+218.90 bps cumulative Alpaca-minus-Yahoo divergence), QQQ (+89.98 bps), TLT (+26.01 bps). No Tiingo token; no Tiingo data has been fetched.

**Progress remains 46%.** This improves diagnostics and reproducibility; it does not resolve the source discrepancy or create strategy edge.


### PR #113 — post-merge date-level findings
- Live audit `42955455037` completed; artifact `13826901809`. 10 cross-check tests passed. Tiingo was not requested because no secret was configured.
- Top daily-return outliers:
  - QQQ: 2024-12-24 +99.4639 bps (Alpaca minus Yahoo); 2024-12-23 -96.2569 bps.
  - SPY: 2025-04-09 -116.6651 bps; 2025-04-10 +100.7796 bps.
  - EEM: 2024-12-24 +52.1426 bps.
  - DIA: 2024-12-23 -71.4228 bps.
  - EFA: 2024-12-23 -77.8464 bps.
  - TLT: 2026-11-02 +39.8171 bps.
  - GLD: 2021-06-21 -31.5042 bps.
  - IWM: 2026-06-26 -70.3638 bps.
- QQQ has a documented ex-dividend date on 2024-12-23, with a distribution of $0.83466/share (about 0.16% of the contemporaneous price): https://app.tiingo.com/qqq/dividends. This is a plausible event to inspect, but the distribution amount alone does not explain the roughly 96–99 bps opposite-signed differences across 23–24 December. Do not attribute causality yet.
- SPY's largest discrepancies occur 2025-04-09/10; its documented 2025 Q1 ex-date was 2025-03-21 ($1.6955), not either outlier date: https://learn.snapstock.app/stocks/SPY/. That makes a simple same-day SPY dividend explanation unlikely; inspect source bars and event/corporate-action timestamps before concluding.
- The paired sign reversal across consecutive dates for QQQ and SPY is consistent with a possible adjustment timing/mapping issue, but is not proof. Need inspect unadjusted OHLC, adjusted close, distribution factors and raw provider timestamps for the two sessions around each event.
- Cumulative-return differences remain SPY +218.9083 bps, QQQ +89.9769 bps, TLT +26.0188 bps; 0/8 symbols pass the 95% full-period source coverage gate. Daily correlation remains high and is not sufficient for source acceptance.
- Runtime suite `42955454994` passed all modules. CI does not establish actual Paper host operation.

**Immediate next action:** extend the audit to capture the raw/unadjusted close, adjusted close and per-session adjustment factor around each flagged date; add a separate corporate-action/event comparison when provider APIs expose records. Do not normalize away discrepancies or change research source until reconciled.


### PR #115 — raw-price vs adjustment-factor reconciliation
- Merge commit: `60059a41379b274ae16a8b20426bbcf96178ae7`.
- Adds Yahoo raw `Close` + adjusted `Adj Close` fetch (`auto_adjust=False`, `actions=True`, `repair=False`), Alpaca raw `Adjustment.RAW` fetch, and compares them with the existing adjusted series.
- Computes per-provider adjustment factors (adjusted/raw), normalized relative factor divergence, largest factor-step dates, raw-price return differences and normalized raw-price path divergence.
- This is designed to separate raw underlying price mismatches from corporate-action adjustment differences. It does not assign a cause or auto-correct data.
- PR CI run `42955793577`: compile and all 12 cross-check tests passed; live audit skipped on pull_request by design.
- Post-merge audit run `42955879451` completed successfully; artifact `13825994525`. The run included raw/adjusted fields for all 8 ETFs. Runtime/accounting run `42955879365` also completed successfully.
- No Tiingo token, subscription, strategy approval, Paper approval or orders changed.

**Next steps**
1. Verify post-merge live audit; if no automatic run was triggered, dispatch the existing audit workflow only if a supported dispatch mechanism is available, otherwise use the next scheduled run. Do not claim live raw/adjusted parity before it runs.
2. Inspect the new adjustment-factor step dates for QQQ 2024-12-23/24 and SPY 2025-04-09/10; compare to official distribution/ex-date records. The QQQ 2024-12-23 $0.83466 distribution is a possible lead but too small by itself to explain the observed ~1% opposite-signed daily return differences.
3. Keep provider histories separate and do not loosen the 95% coverage gate.
4. Continue strategy edge, empirical cost and persistent Paper deployment work only after the data lineage blocker is understood.

**Progress remains 46%.** This adds an attribution diagnostic, not a resolution or strategy edge.


### PR #115 — post-merge raw/adjusted factor findings
- Live audit `42955879451` succeeded; artifact `13825994525`; 12 cross-check tests passed. Runtime/accounting run `42955879365` passed.
- Yahoo raw/adjusted and Alpaca RAW/ALL series intersected for 1,582 sessions (SPY 1,583) on the IEX common period.
- Maximum normalized relative adjustment-factor divergence by ETF: DIA 0.0025%, EEM 0.0223%, EFA 0.0124%, GLD 0%, IWM 0.0065%, QQQ 0.3278%, SPY 0.0045%, TLT 0.4223%.
- QQQ's largest factor step was 2022-09-19: +17.6852 bps. QQQ's documented ex-dividend distribution that day was $0.51856/share: https://stockanalysis.com/etf/qqq/dividend/ and https://app.tiingo.com/qqq/dividends.
- TLT's largest factor step was 2026-11-02: +41.7148 bps. iShares official distribution table lists an ex-date and income distribution of $0.343177/share that day: https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf.
- The close magnitude/date alignment is strong evidence that dividend-adjustment handling explains at least these two factor steps. It does **not** yet identify which vendor's factor is correct or prove the whole cumulative-return discrepancy is explained. The report currently normalizes factor ratio to first common session; it does not show before/after raw factor values side-by-side.
- Raw price series still differ: max normalized raw close divergence ranges from 0.2633% TLT to 0.9620% QQQ; p95 absolute raw daily return differences 4.6855–9.9434 bps. This is separate from the adjustment-factor issue and deserves investigation.
- The large QQQ 2024-12-23/24 and SPY 2025-04-09/10 return outliers are not automatically explained by the 2022 QQQ or 2026 TLT factor events. Keep these as separate raw/session anomalies until their raw close fields are checked.
- Tiingo token remains absent. No Tiingo request; no vendor subscription; no strategy/Paper approval or orders.

**Next diagnostic improvement:** include previous-session and current-session provider adjustment factors around each largest factor step, so the audit makes the before/after factor change explicit. Then compare it against the official ex-date cash amount divided by previous raw close. Do not attribute provider fault until this calculation and raw bars are checked.


### PR #106 — optional Tiingo adjusted EOD source
- Merge commit: `775186e104a485bbc07b50a5dcc807723aced240`.
- Adds `TIINGO` as optional research-only provider to the ten-year equity research runner. Uses adjusted OHLCV fields and Token authorization. Requires `TIINGO_API_TOKEN`; no embedded credentials. Default source unchanged; no silent fallback or source splicing; insufficient history fails closed.
- Mocked contract, missing-token, short-history and provider-metadata tests passed. No live Tiingo validation because no token/eligible plan configured. No subscription purchased.
- Corrected Yahoo metadata to reflect actual `repair=False` request.

### 10.11 Ten-year equity research result — 2026-11-11
- Workflow `42954130155` passed. Artifact `13826686266` was downloaded and inspected.
- Yahoo adjusted daily history: 8 ETFs (DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT), 2,511 bars per symbol; approximate weekday coverage 96.32%, max calendar gap 4 days. Weekday denominator includes US market holidays; this is not true exchange-session coverage.
- Multiple-testing family: 73 hypotheses; Holm significant 0; pre-screen passes 0. No candidate promotion, Paper approval or orders.
- Cross-sectional top-1 126-day momentum underperformed equal-weight buy-and-hold over full sample: CAGR 7.65% vs 11.53%, Sharpe 0.48 vs 0.87, max drawdown -35.0% vs -27.0%. Final holdout excess statistically inconclusive (raw bootstrap p=0.399, Holm p=1.0, 5th-percentile bootstrap excess -31.56 pp).
- Costs remain placeholders (5 bps/side, 2x stress, 0 commission), not measured execution costs.

### 10.12 Ten-year Alpaca IEX vs Yahoo crosscheck — 2026-11-11
- Workflow `42955879451` completed SUCCESS at code commit `60059a41379b274ae16a8b20426bbcf96178ae7`. Artifact `13825994525`, SHA-256 `1fe86b053ab4e09916f0f2d002dea162241481773487524b40342d20e247eddd`, downloaded and inspected.
- Request was 10 years, 8 ETFs, Alpaca feed IEX with `Adjustment.ALL`, Yahoo `auto_adjust=True; actions=True; repair=False`. No errors, but Alpaca IEX returned only 1,582–1,583 sessions starting 2020-07-27; Yahoo returned 2,513 sessions. Thus IEX coverage on Yahoo's 10-year sessions was only ~62.95% (not a full decade). This independently confirms the account's IEX history is not sufficient for a ten-year strategy backtest.
- All 8 symbols failed the minimum source-coverage diagnostic; 0/8 passed all gates. On the common period daily return correlation was high (0.99835–0.99975) and p95 absolute daily-return differences 4.69–9.97 bps, but there were notable outliers: maximum daily-return differences 31.5–116.7 bps. Cumulative return differences on common periods: DIA +5.47 bps, EEM +8.82, EFA +1.22, GLD +3.29, IWM -0.75, QQQ +89.98, SPY +218.89, TLT +26.02. These are data-provider differences, not trading P&L.
- No Tiingo comparison was requested/run (`tiingo_comparison_requested=false`, 0 symbols). This run does not validate the newly added Tiingo adapter.
- Research cost assumptions remain unvalidated; fill validation false; candidate promotion false; Paper approval false; orders enabled false; submitted 0.
- Do not treat high correlation as sufficient: coverage gate failed for every ETF, and outlier/cumulative differences need investigation. Do not use IEX as 10-year source; do not splice IEX/Yahoo.

**Next actions**
1. Replace approximate weekday denominator with authoritative exchange-session calendar and test holidays/closures.
2. Investigate outlier dates and corporate actions for QQQ/SPY/TLT and validate adjusted-price conventions; retain raw per-provider series.
3. Run Tiingo adapter against a licensed/eligible account only after a token is configured securely; compare Tiingo vs Yahoo and Alpaca only over common sessions, separately reporting coverage. No subscription/spend without explicit approval.
4. First validate Alpaca's free historical SIP path (end at least 15 minutes old). Only investigate another historical vendor if that read-only Paper test fails; do not assume IEX can substitute for consolidated SIP.
5. Expand strategies only after data-quality remediation; keep the 0/73 negative research result and 0/8 source coverage failures as historical evidence.
6. Continue fee/FX/corporate-action reconciliation, Paper cost collection after persistent deployment, and selector observe-only validation. No strategy approved; LIVE disabled.


### PR #119 — before/after adjustment factor evidence
- Merge commit: `0c3c815437e747f82615b3900cc8cfc7d4ce0066`.
- Each largest factor-step date now shows previous common session, Yahoo and Alpaca adjustment factors and ratio before the event, and the corresponding current-session values.
- PR CI `42956145698`: all 12 cross-check tests passed.
- Post-merge live audit `42956264138` succeeded; artifact `13827440846`; 12 tests passed. Tiingo was not requested because no token is configured.
- QQQ ex-date 2022-09-19: prior session 2022-09-16; Yahoo factor 0.9748652963, Alpaca factor 0.9731318510, ratio 0.9982218617. On ex-date: Yahoo 0.9766172744, Alpaca 0.9766019584, ratio 0.9999843173. Relative factor step +17.6820 bps. QQQ distribution that day was $0.51856/share.
- TLT ex-date 2026-11-02: prior session 2026-10-30; Yahoo factor 1.0000000000, Alpaca factor 0.9958460599, ratio 0.9958460599. On ex-date both factors 1.0000000000. Relative factor step +41.7148 bps. iShares official distribution that day was $0.343177/share.
- In both cases, Alpaca's adjusted/raw factor is lower than Yahoo's on the previous session and converges on the ex-date. This is strong evidence of different dividend adjustment handling, but it does not establish which provider is correct or whether revision timing/methodology/defect is responsible.
- QQQ 2024-12-23/24 and SPY 2025-04-09/10 raw-return outliers remain separate; no cause attributed. Full-period source coverage remains 0/8 because IEX overlaps only 62.95% of Yahoo's 10-year period.
- No Tiingo token, subscription, strategy approval, Paper approval or orders.

**Next:** compare these events with official issuer distribution amounts and prior raw closes, then inspect remaining adjustment-factor and raw-return outlier dates. Do not choose a source or splice history until the data lineage is reconciled.


### PR #124 — event-level cash distribution evidence
- Merge commit: `ca0450287284af014e68bd5e31d05e641b8d110d`.
- Yahoo raw/adjusted fetch now preserves `Dividends` and `Stock Splits` action fields.
- Each top adjustment-factor step includes prior Yahoo/Alpaca raw closes, Yahoo cash distribution and split ratio on the event date, and an approximate cash adjustment scale in bps (distribution / previous Yahoo raw close × 10,000).
- This allows comparison of observed factor changes with the issuer's distribution amount. It is diagnostic only; it does not adjust prices or attribute fault.
- PR CI `42956965526`: compile and all 12 cross-check tests passed; live data step skipped on pull_request by design. The first test run failed only because the assertion precision was tighter than the report's four-decimal rounding; this was corrected and the rerun passed.
- Post-merge live audit has not yet appeared at this handoff update; inspect the next main push run before recording issuer action comparison.
- No Tiingo token, subscription, strategy approval, Paper approval or orders.

**Progress remains 46%.** This improves audit evidence; no strategy edge or live operational evidence is added.


### PR #124 — post-merge cash-action audit results
- Live audit `42957082760` completed successfully; artifact `13827412712`; all 12 cross-check tests passed. Tiingo token was absent; no Tiingo request was made.
- **QQQ, 2022-09-19:** Yahoo reports dividend `0.519` on the event date. Previous Yahoo raw close (2022-09-16) was `289.3200`; implied cash adjustment scale is `17.9386 bps`. The Alpaca/Yahoo adjustment-factor ratio moved from `0.9982217537` on the prior session to `0.9999841026` on ex-date, a `+17.6809 bps` relative step. This is close to one cash distribution scale, but provider attribution is not yet clear: both Yahoo's action feed and its adjustment factor show an event, while the Alpaca factor moves differently. Investigate whether Alpaca applies an additional adjustment or its methodology differs.
- **TLT, 2026-11-02:** Yahoo reports no dividend (`0.0`) for the date. Previous Yahoo raw close (2026-10-30) was `81.8400`. Alpaca/Yahoo factor ratio moved from `0.9958460599` to `1.0000000000`, a `+41.7148 bps` step. iShares official data lists a `$0.343177` cash distribution on the same ex-date. The cash amount relative to the prior close is approximately `41.93 bps`, close to the observed step. This is strong evidence Yahoo's action history/adjustment did not capture the same event as Alpaca; verify exact vendor history before deciding which feed to trust.
- These findings support a concrete hypothesis that at least part of QQQ/TLT cumulative divergence comes from dividend-adjustment handling. They do not prove which vendor is universally correct and do not explain all raw-return outliers.
- Source records: QQQ distribution history https://app.tiingo.com/qqq/dividends and https://stockanalysis.com/etf/qqq/dividend/; official TLT issuer distribution https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf.
- The 95% full-period source coverage gate remains 0/8 due IEX's ~6.3-year available history vs 10 years requested. No source series was spliced. Candidate promotion, Paper approval and orders remain false.

**Next research action:** compare each provider's factor against the issuer's cash amount and prior raw close; inspect QQQ for possible duplicate adjustment and TLT for the missing Yahoo event. Then inspect the remaining top raw-price outlier dates separately.


### PR #120 — ten-year IEX vs Yahoo audit documented
- Merge commit: `d84b9f303896927896801580d7a7b43d797899b7`.
- Recorded the real IEX 10-year coverage failure: 1,582–1,583 IEX sessions vs 2,513 Yahoo sessions, only ~62.95% coverage, 0/8 ETF diagnostic passes. The run had no data-request errors; the limitation is the IEX feed entitlement/history window, not a workflow failure.
- No Tiingo data was included in that audit.

### PR #123 — authoritative XNYS exchange-session data-quality gate
- Merge commit / main SHA: `f408204044fcff449bd615301a0bf2503a4d1db0`.
- Replaced the incorrect weekday denominator (which counted market holidays) with actual XNYS trading-session labels from `exchange-calendars`.
- Quality report now records `expected_exchange_sessions`, `missing_exchange_sessions`, `exchange_session_coverage_pct`, first missing session and max gap measured from observed bars. Existing 95% coverage and 7-calendar-day max-gap gates are unchanged.
- Regression tests cover July 4, 2024 (not an expected session) and missing July 2, 2024 (must fail coverage). Additional fixes found during CI: exchange_calendars requires timezone-naive session labels; calendar bounds must extend beyond input dates; provider error paths must use new metric names. These failed CI attempts were corrected, not ignored.
- PR workflow `42957308114` passed: self-test + 21 regression tests. Main post-merge v0.4 workflow `42957425769` passed all stages (self-test, regression tests, 10-year research, report verification, artifact upload); main runtime workflow `42957425751` passed. Legacy research workflows v0.2 `42957425803` and v0.3 `42957425736` also passed.
- New v0.4 artifact: `13828111119`, SHA-256 `073fd24b92ad89ab55f456eb15c0a0d82876b93275aa338d4bd863f2cb526140`. It reports 2,511 XNYS sessions and 2,511 Yahoo bars for each of the eight ETFs: 100% exchange-session coverage, 0 missing sessions, max observed gap 4 calendar days. This supersedes the earlier approximate 96.32% weekday coverage figure; that earlier figure was a denominator artefact, not missing market data.
- Strategy result did not change: 73 hypotheses, Holm significant 0, pre-screen passes 0, candidate promotion false, Paper approval false, orders disabled, 0 submitted.
- Important distinction: Yahoo now has complete observed exchange-session coverage for this 10-year sample; Alpaca IEX still covers only ~63% of that decade and fails 0/8 cross-provider coverage gates. Tiingo has not yet been live-tested. The 100% Yahoo coverage result does not resolve independent provider corroboration, adjustment discrepancies or licensing.
- The 5 bps/side cost assumption remains hypothetical; no execution cost validation.

**Continuation queue**
1. Investigate large common-period Yahoo/IEX divergence dates (especially SPY +218.89 bps and QQQ +89.98 bps cumulative differences, plus max single-day outliers). Determine whether corporate actions, adjustment methods, bad prints or provider data corrections explain them.
2. Add Tiingo live parity only after an eligible account/token is securely configured; report common-session coverage, adjustments, and discrepancies independently. No paid subscription without explicit approval.
3. Preserve source provenance and never splice/average vendor price histories.
4. Re-run strategy research only with point-in-time data, multiple walk-forward folds and independent holdout; current 0/73 remains a valid negative result.
5. Close remaining accounting fee/FX/corporate-action reconciliation, collect representative Paper execution costs after persistent user-host deployment.
6. Selector remains observe-only/cash-safe. No approved strategy; LIVE disabled.


### 10.13 Provider divergence investigation — artifact 13827412712
Crosscheck run `42957082760` (code commit `ca0450287284af014e68bd5e31d05e641b8d110d`) and artifact `13827412712` was downloaded and re-examined at event level. This is the latest completed IEX/Yahoo comparison before the XNYS-calendar-only change.

**Raw-price divergence vs adjustment-factor divergence**
- Alpaca IEX is not consolidated US market data: Alpaca's official documentation describes IEX as a single exchange (~2.5% of market volume) and SIP as all US exchanges / consolidated tape (~100% volume). Sources: https://docs.alpaca.markets/us/v1.4.2/docs/historical-stock-data-1 and https://docs.alpaca.markets/us/docs/market-data-faq.
- For SPY, cumulative return difference was +218.90 bps, while max relative adjustment-factor divergence was only 0.004489%; raw-price path difference reached 0.8381%. Largest raw daily divergences were 2025-04-09 (-116.75 bps), 2025-04-10 (+100.69 bps), 2024-12-24 (+93.92 bps), and 2024-12-23 (-91.53 bps). This points primarily to raw-price/feed differences rather than dividend-adjustment factors for SPY. It does not prove the exact trade-level cause.
- DIA had +5.47 bps cumulative difference and only 0.002529% max relative factor divergence; EFA +1.22 bps / 0.012368%; GLD +3.29 bps / 0%; IWM -0.75 bps / 0.006514%; EEM +8.82 bps / 0.022271%. Their largest normalized raw-close differences were still material (roughly 0.3–0.72%), so IEX is not a consolidated close substitute.
- QQQ had +89.97 bps cumulative difference and 0.327819% max relative adjustment-factor divergence. On 2022-09-19 Yahoo's action feed recorded a $0.519 distribution; prior Yahoo raw close was $289.32, implying ~17.94 bps. The audit's daily relative factor step was 17.68 bps. This is close in scale to one distribution, but the exact provider-side adjustment mechanism remains unproven. Yahoo history reference: https://finance.yahoo.com/quote/QQQ/history/.
- TLT had +26.02 bps cumulative difference and 0.422290% max relative adjustment-factor divergence. Official iShares distribution table reports a $0.343177 distribution with ex-date 2026-11-02: https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf. On the prior Yahoo raw close of $81.84 this equals ~41.93 bps. The audit capture showed Yahoo dividend cash = $0 and no Yahoo factor step, while Alpaca's relative factor step was 41.7148 bps. The observed Alpaca step is close to the official distribution scale; this is consistent with Yahoo's event/adjustment not yet reflecting the distribution in that capture, but must be re-queried and independently confirmed before attribution.
- These facts show the cross-provider difference is mixed: raw-price/feed differences dominate SPY; corporate-action adjustment mismatches matter for QQQ/TLT; do not apply one blanket explanation.

**Operational conclusion**
- Do not use Alpaca IEX daily bars as a substitute for SIP/consolidated prices in full-market backtests or closing-price validation. The official IEX/SIP coverage difference explains why the IEX series is a diagnostic reference only, not a complete market benchmark.
- Do not blindly treat Yahoo adjusted history as corporate-action ground truth either: the TLT capture missed an issuer-confirmed distribution event. Re-query after vendor updates, compare official issuer events, and preserve raw and adjusted series separately.
- No source is currently certified as a 10-year institutional-grade truth set. Tiingo is integrated but not live-tested; no Tiingo token/plan was used in this artifact.
- Next: re-run TLT after the 2026-11-02 event has propagated; inspect QQQ 2022-09-19 factor step against official Invesco distribution records; compare historical SIP using a request end at least 15 minutes old. The prior recent-SIP 403 does not establish historical ineligibility. No vendor subscription without explicit approval; never splice sources.



---

## 2026-11-10 — Trading research landscape review and adaptive architecture baseline

The user explicitly asked whether Rocket Trader had already surveyed trading from its origins through 2026-11-10, including successful traders, historical cases, academic literature, books, public repositories, Reddit/forums, and advanced adaptive techniques. The honest answer is **no: that end-to-end survey had not been completed before this review**. Prior work covered selected quantitative/ML methods, not a systematic historical and comparative research program.

A new canonical research document was added:
- `TRADING_RESEARCH_LANDSCAPE_AND_ADAPTIVE_ARCHITECTURE.md`
- Includes historical evolution, strategy families, regime estimation, adaptive meta-allocation, online learning/drift controls, news/social/geopolitical evidence handling, system-wide risk, historical failure cases, research standards, trader/institution benchmarks, open-source ecosystem, Reddit/books evidence hierarchy, prior Rocket Trader negative results, current gaps, workstreams, source links and working rules.
- This is a curated evidence-weighted survey and design baseline, **not** an exhaustive crawl of the entire internet or proprietary trading literature. It labels preliminary/practitioner evidence and avoids treating anecdotal returns as audited.

### Key conclusions carried into architecture
1. Use a portfolio of independently tested strategy families, not one universal strategy or a large indicator pile.
2. Estimate regime probabilities from trend, volatility, correlation, liquidity, macro, event and data-health dimensions; compare simple rules, HMM/Markov switching, change-point detection, clustering and online drift monitors.
3. Meta-allocation must include abstention/cash, hysteresis, uncertainty, robust sizing and comparison against a static baseline.
4. Monitor live drift separately from model training. Use frozen champion/challenger, shadow predictions, explicit promotion gates and rollback; no self-modifying model can promote itself.
5. LLM/news/social data are evidence inputs only. Require provenance, timestamps, deduplication, corroboration and incremental OOS tests.
6. Novel ideas may be tested in a quarantined bounded-risk research allocation only; no automatic promotion or real orders.
7. Historical crises translate into concrete controls: crowding/correlation, liquidity stress, stale-data breakers, price collars, order caps, deployment canaries and independent kill switch.

### Historical Rocket Trader results that must not be rerun blindly
- Oct 2026 ML experiment: SPY AUC 0.740/ECE 0.014 and QQQ AUC 0.719/ECE 0.011 were calibration diagnostics only; SPY had zero trades, QQQ PF 0.77 in one configuration; research_pass remained false.
- ETF v0.5: 97 hypotheses, Holm significant 0, pre-screen 0.
- Crypto v0.4: 25 hypotheses, no pass; SOL coverage 77.1%, ineligible.
- Actual v0.4 ten-year Yahoo report (run `42954130155`, artifact `13826686266`): eight ETFs, 2,511 sessions each, 73 hypotheses, Holm significant 0, pre-screen 0, no promotion/Paper approval/orders. Cross-sectional top-1 had +10.18 percentage points vs equal-weight in the final holdout, but bootstrap p=0.3985, Holm p=1.0 and 5th percentile excess -31.56 percentage points. Not significant.
- That v0.4 artifact assumed 5 bps per side (2.5 spread + 2.5 slippage, zero commission); this is hypothetical, not empirically measured. The later XNYS calendar correction gives 100% Yahoo session coverage, superseding earlier weekday approximation. IEX remains short of full decade and dividend adjustment discrepancies (QQQ/TLT) require resolution.

### Sources reviewed for this baseline
Peer-reviewed/history: Lehoczky & Schervish (2018); Hurst/Ooi/Pedersen (2017); Bailey et al. (PBO); Arian et al. (CPCV/DSR comparison); Donnelly (optimal execution); Chen et al. (2026 technical/fundamental/momentum review); Khemka et al. (2026 ML forecasting review); 2025 RL survey; Bayesian online change-point/order-flow work; 2024 social sentiment aggregation and spillover studies.
Primary incident evidence: Federal Reserve History (1987, LTCM), Khandani & Lo/NBER (2007 quant unwind), CFTC/SEC (2010 Flash Crash; 2012 Knight Capital).
Open source: LEAN, NautilusTrader, vectorbt, backtesting.py, Freqtrade, FinRL, hftbacktest, zipline-reloaded and a curated trading-repository index. Reddit/forums are treated only as hypothesis/operational-issue discovery, never audited performance proof.
The new research document contains the source links and evidence-status notes.

### What this does NOT establish
No new strategy is profitable or approved. The research review does not validate a regime classifier, adaptive selector, social signal, RL agent or production execution. No persistent user-host Paper deployment is verified. Tiingo adapter is mocked-only and no paid subscription is authorized. LIVE remains disabled.

### Next actions
1. Create a traceable hypothesis registry and source/evidence ledger from the research document.
2. Resolve Yahoo/IEX corporate-action discrepancies; run Tiingo only after eligible plan/token is separately configured (no spend without approval).
3. Expand point-in-time multi-asset historical tests and multiple walk-forward folds; preserve negative results.
4. Validate regime estimation (HMM, change-point, volatility clustering, rules) for false transitions, detection delay and incremental OOS utility.
5. Test adaptive meta-allocation vs static baseline with uncertainty, hysteresis, abstention and bounded exploration.
6. Test official macro/news/social data for incremental causal value; no LLM direct allocation.
7. Keep ML/RL sandbox-only until simpler baselines, costs and validation standards are robust.
8. Continue Paper deployment/accounting/cost collection and operational fault testing.

**Progress remains 46%.** The research blueprint is now documented; research implementation and empirical validation remain substantial work.


### 2026-11-10 — Reddit practitioner evidence added
- Added dated r/algotrading threads to the canonical research document: regime/HMM uncertainty (Nov 6), backtest-to-live latency and order handling (Apr 22), regime-specific switching and filter overfit (Apr 10), live strategy decay after regime mismatch (Apr 1), and overfitting/cost discussions (Jan 5).
- These are anecdotal self-reports only. They are used to generate testable hypotheses, not establish profitability or validate claimed account returns.


### PR #131 — Tiingo comparison status is now tri-state
- Merge commit / latest code SHA: `097dd10932ed7ed2e993a2b2110cb7f728450d8b`.
- When no `TIINGO_API_TOKEN` is configured, report status is `NOT_REQUESTED` and `tiingo_all_diagnostic_gates_pass=null`, never `true`. It is `PASSED` only when all requested symbols pass both Tiingo-vs-Yahoo and Tiingo-vs-Alpaca; otherwise `FAILED`.
- PR workflow `42958291332` passed compile + offline audit tests. Main runtime workflow `42958406230` passed. Main audit workflow `42958406136` passed and produced artifact `13827124135`.
- Artifact explicitly says `tiingo_comparison_requested=false`, `tiingo_comparison_status=NOT_REQUESTED`, 0 symbols, `tiingo_all_diagnostic_gates_pass=null`. This is absence of evidence, not a Tiingo pass.
- The post-merge audit re-queried TLT's 2026-11-02 distribution nine days after ex-date. Yahoo still returned dividend cash 0 and no adjustment-factor step; Alpaca relative factor step remained 41.7148 bps. Official iShares reports $0.343177, ~41.93 bps vs prior Yahoo raw close $81.84. The mismatch persisted; classify Yahoo corporate-action event as unresolved/likely missing or stale in that capture, not a proven cause. Source: https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf.
- Overall IEX/Yahoo gates remain false; no strategy, Paper or LIVE gate changed.

**Current priority**
1. Do not treat Yahoo adjusted TLT history as verified until the official 2026-11-02 distribution is reflected and a re-query converges.
2. Tiingo comparison remains blocked on a token/eligible plan; no credential or paid subscription configured.
3. If Tiingo is tested later, compare all eight symbols against both Yahoo and Alpaca, require common-session coverage and preserve explicit status.
4. Preserve raw-vs-adjusted event diagnostics; never auto-correct or splice provider histories.


---

## 2026-11-11 — User-confirmed adaptive strategy, full-domain research and event-evidence requirements

The user explicitly reconfirmed four mandatory requirements:
1. Rocket Trader must rotate among different strategies as market regimes and opportunities change; it must not be locked to one strategy.
2. It must maintain a structured, continuously maintained body of knowledge across relevant branches of trading thought, selecting methods only when their assumptions and market/data conditions apply.
3. Financial, political, geopolitical, macroeconomic and social/news information must be validated statistically and temporally for potential price impact and early-warning value. The user's prior project **Jefe Maestro** is the methodological reference for advanced statistical evidence discipline.
4. After these requirements are integrated and documented, continue the remaining engineering and validation stages under existing safety and capital rules.

### Interpretation — what "knows all strategies" means operationally

Do not claim literal perfect knowledge of every strategy ever devised. Maintain a versioned strategy taxonomy and evidence registry that is continuously expanded. For each family record:
- formal hypothesis and mechanism;
- market, instrument, horizon and regime where it may apply;
- required data, timestamp granularity, latency and licensing;
- entry, exit, sizing and execution assumptions;
- known failure modes, capacity, costs and operational dependencies;
- primary sources, evidence grade and reproducibility;
- pre-registered tests, benchmarks, OOS evidence and promotion status.

The registry is a research map, not a menu of live orders. A strategy is eligible only when its assumptions, data and validated net edge match current conditions. Missing evidence means research/shadow mode or abstention.

### Adaptive strategy rotation — mandatory design

Use a hierarchical controller:
1. **Eligibility and safety:** data freshness/coverage, market calendar, tradability, account/reconciliation health, spread/liquidity, event halts, position/portfolio constraints.
2. **Regime posterior:** trend, volatility, correlation, breadth, liquidity, cross-asset stress, macro/event state and data confidence; preserve probabilities and uncertainty, not only a hard label.
3. **Candidate strategies:** independently versioned modules with regime/horizon applicability and validated net-return distributions.
4. **Meta-allocation:** compare candidate conditional net expectancy and uncertainty on common observations; account for correlation, turnover, capacity, costs and drawdown contribution.
5. **Rotation controls:** hysteresis, minimum evidence, switching-cost penalty, cooldown/minimum holding logic where appropriate, and champion/challenger shadow evaluation to prevent noisy flip-flopping.
6. **Risk allocator:** portfolio-level volatility/drawdown/concentration/exposure constraints; uncertainty reduces risk; cash is a first-class allocation.
7. **Execution:** deterministic order state machine; strategy models cannot bypass hard risk controls.

Required comparisons: each strategy standalone, static equal-weight ensemble, simple regime rules, buy-and-hold, cash and risk-matched controls. Demonstrate incremental OOS net utility of adaptation over static alternatives. A regime classifier that predicts labels but does not improve decisions after costs is not useful.

### Jefe Maestro — transferable statistical discipline

The prior Jefe Maestro work is a methodological template, not a source of financial alpha:
- separate production from the research/evidence lab;
- pre-register hypotheses and freeze parameter ranges;
- use strict chronological train/selection/final/prospective splits and walk-forward evaluation;
- compare against random/uniform or economically appropriate null controls;
- preserve immutable evidence logs, data/code fingerprints and reproducible seeds;
- use block bootstrap, permutation/sign inference, confidence intervals and family-wise multiple-testing correction (Holm or defensible alternatives);
- evaluate individual signals and joint/combined portfolios separately;
- distinguish descriptive patterns, predictive evidence and economic utility;
- require prospective evidence before production promotion.

Historical Jefe Maestro lessons to preserve: prior FIX07 did not validate predictive advantage (confidence intervals included zero; adjusted p=1.000); the later broad FIX09 search reported 4,629 hypotheses, 227 nominal p<0.05 and zero surviving Holm correction. These are warnings about selection bias and multiple testing, not evidence about financial markets. A lottery's null model differs from financial returns; adapt the method, never copy the domain assumptions or claim that lottery signals transfer to markets.

### Financial/political/social/news event validation — mandatory design

Build on the existing official RSS, Alpaca/Benzinga and GDELT observers and curated event-assessment pipeline. Raw headlines, social posts, LLM summaries or sentiment scores must never directly allocate capital.

Every event record should preserve:
- source identity/type, URL, source-group independence, author/publisher where available;
- published_at, first_seen_at, retrieved_at, timezone, event_time vs report_time, revisions and content hash;
- entity/asset/geography mapping, event taxonomy, direction-neutral description and causal channel;
- evidence spans/quotes within lawful limits, source credibility and corroboration;
- novelty vs duplicate/recycled story, uncertainty, contradictory evidence and confidence;
- expected horizon, possible transmission channel and expiration/decay assumptions;
- point-in-time feature availability and exact decision timestamp.

Statistical research must test, not assume, whether events anticipate returns:
- define event classes and impact windows before testing (minutes, hours, days, weeks as appropriate);
- construct point-in-time event studies with pre-event baselines and matched non-event controls;
- measure abnormal returns, volatility, spread/liquidity, volume, gap risk and cross-asset spillovers;
- test lead/lag structure without using information unavailable at decision time;
- deduplicate syndicated stories and cluster correlated sources to avoid false corroboration;
- use placebo timestamps, shuffled labels, permutation/block bootstrap and negative-control event classes;
- correct for all tested event classes, assets, horizons and model variants;
- compare text/NLP/social features against simple structured-event baselines and price/volume-only baselines;
- test incremental OOS value after costs, delays, slippage and data-vendor latency;
- monitor source outages, policy/platform API changes, bot/manipulation risk and survivorship of deleted posts.

Political and social content requires neutral, factual event coding. Do not infer market impact from ideological tone or unverified viral claims. Lawful access, terms of service, privacy and licensing are hard constraints. Social data may be excluded if point-in-time availability, provenance or representative coverage cannot be established.

### Research completeness and evidence limits

The historical research landscape and the systematic strategy program are now documented, but neither is an exhaustive inventory of all trading knowledge. Expand them iteratively with source quality labels. Books, forums, Reddit, repositories and famous traders generate hypotheses; only reproducible OOS evidence can promote a method. Verify repository license, maintenance, data assumptions and execution semantics before adoption.

### Next execution sequence
1. Expand the versioned strategy registry to cover every applicable family in the research taxonomy, including required data, horizon, regime, execution, failure modes and evidence status.
2. Implement a hypothesis/event evidence ledger with immutable experiment manifests and family-wise correction.
3. Build point-in-time event datasets and event-study baselines; quantify incremental signal value before any allocation linkage.
4. Validate regime posterior and temporal alignment on real data, including missingness, coverage, uncertainty and transition stability.
5. Compare adaptive rotation against static and simple baselines on identical OOS periods and costs.
6. Connect selector and event overlay in shadow/observe-only mode; no autonomous order path until separate gates pass.
7. Continue reconciliation, execution-cost collection, Paper deployment and independent operational review.
8. Update this Handoff after every meaningful change, including failures, hypotheses rejected, exact artifacts, commit/PR/test evidence and next action.

**Capital boundary unchanged:** research and Paper only; no real-money orders, paid data subscriptions or credential sharing without the user's separate explicit authorization.


### PR #138 — adaptive strategy and event evidence requirements
- Merged to main: `873b26352bdb76f85809b33d1605123e5b301b7e`.
- Added `ADAPTIVE_STRATEGY_AND_EVENT_EVIDENCE_REQUIREMENTS.md`; updated this Handoff and `RESEARCH_HYPOTHESIS_PROGRAM.md`.
- Formalizes adaptive strategy rotation, versioned strategy knowledge registry, regime posterior/uncertainty, hysteresis and champion/challenger controls, benchmark requirements, and point-in-time event/news/social statistical validation.
- Explicitly transfers Jefe Maestro's research discipline (pre-registration, strict chronological OOS/prospective splits, immutable evidence, null controls, bootstrap/permutation inference, Holm correction) while preserving its negative results: FIX07 no validated advantage; FIX09 4,629 hypotheses / 227 nominal p<.05 / zero Holm survivors. Lottery null assumptions are not transferable to financial markets.
- Documentation only. No new strategy/event signal approved; no code execution, live orders or profitability validation.
- Next: expand machine-readable strategy registry; build event-study/experiment ledger; validate regime rotation against static and cash baselines; test news/social incremental OOS value; integrate selector/overlays in shadow mode only.


## 2026-11-10 — Expanded research registry, experiment ledger and Alpaca Paper authorization

The user explicitly authorized tests in their Alpaca **Paper** account, reported to have approximately USD 100,000 simulated equity. This is authorization for Paper-only testing, not live orders. The reported account value is not a risk budget. No Alpaca credentials were provided in chat and none should be requested or committed. The repository contains Paper connection/preflight/smoke workflows, but a repository workflow definition is not proof that the account is connected or that a run submitted orders. Direct account execution remains unverified until a Paper-only workflow run reports account mode, account status, order IDs, fills and reconciliation.

Current safety boundary: research/backtests/shadow are allowed; Paper orders only through explicit Paper-only credentials, strict notional/exposure/daily-loss caps, cash-only and no-short checks, idempotency, durable journal, broker reconciliation and kill switch. Live trading remains prohibited without separate explicit authorization. No paid data or subscriptions are authorized.

### Registry expansion branch

Branch: `feat/adaptive-research-registry-v2`.

Expanded `research/reference_strategy_registry_v0_1.json` from 6 to 24 sourced strategy/reference entries (6 original + 18 new), with structured family, applicable regimes, horizon, inputs, entry/exit/sizing hypothesis, execution assumptions, failure modes, evidence grade and test protocol. Added:
- RSI(2), Bollinger mean reversion.
- Distance/cointegration pairs and pairs reversal/momentum decomposition.
- Volatility-managed exposure, calendar seasonality.
- Post-earnings announcement drift.
- Value, profitability/quality, low-volatility/defensive, 52-week high momentum.
- Intraday reversal, opening-range breakout.
- News/sentiment event hypothesis.
- Risk parity allocation.
- ML/meta-labeling and reinforcement learning as later-stage research only.
- VWAP/TWAP as execution benchmarks, explicitly not alpha strategies.

**Pairs constraint:** pairs trading normally requires a long and a short leg. The current cash-only/no-short policy means pairs are offline/simulation-only; they cannot be submitted to the existing Paper account unless a separate reviewed account-policy change is authorized. No such change has been made.

Added `research/experiment_ledger_schema_v1.json` to require immutable experiment identity, code SHA, data fingerprint, point-in-time policy, split plan, executable timing, costs, benchmark set, multiple-testing family, confidence interval, adjusted p-value, decision and optional Paper order/fill/reconciliation records.

Added `research/strategy_experiment_matrix_v1.json` with nine ordered tranches: corrected baselines; trend/breakout; mean reversion; pairs; allocation/risk overlays; calendar/events; intraday/execution; ML; Paper operational validation. The matrix proposes conservative pre-review Paper caps (USD 100/order, USD 500 gross exposure, USD 25 daily loss, max 3 positions) as a starting safety envelope only; these are not applied to the account and require runtime implementation/verification before any Paper order.

The registry validator now requires structured evidence metadata and explicitly tests that pairs remain research-only and no strategy is automatically Paper-approved. PR/CI outcomes will be recorded after validation; no test result is claimed yet.


## 2026-11-11 — PR #139 merged: strategy registry, evidence ledger, Paper smoke gate

PR #139 merged into main by squash:
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/139
- Merge commit: `f22886f089be444a155f44042eff4cc4e267c591`
- PR head validated: `40b6f42a914a400a1dcd15b57562836a7a836350`
- GitHub Actions `Rocket Trader - Reference Strategy Registry Tests`: **success** on the PR head (run 42960077443); compile and registry validation steps passed.
- Main after merge: `f22886f089be444a155f44042eff4cc4e267c591`. This PR was research metadata, tests and workflow safety; it did not implement adaptive strategy rotation or change the live runtime strategy code. Progress remains **46%** (engineering/evidence maturity, not profitability).

The registry now contains **24** sourced strategy/reference entries with standardized metadata: strategy family, regimes, horizon, inputs, entry/exit/sizing, execution assumptions, failure modes, evidence grade and test protocol. Added RSI/Bollinger mean reversion, pairs/cointegration and pairs decomposition, volatility management, seasonality, earnings drift, value/quality/low-volatility, 52-week high, intraday reversal, opening-range breakout, event sentiment, risk parity, ML/meta-labeling, RL and execution-only VWAP/TWAP. This is a practical taxonomy, not a claim of exhaustive knowledge.

New files:
- `research/experiment_ledger_schema_v1.json`: immutable experiment record schema with code SHA, data fingerprint, point-in-time rules, chronological splits, costs, benchmarks, multiple-testing family, confidence intervals, p-values, decision and optional Paper fills/reconciliation.
- `research/strategy_experiment_matrix_v1.json`: nine ordered research tranches and Paper safety envelope.
- Registry validator now requires structured evidence metadata, tests pair-trading research-only status, checks the ledger schema/matrix and asserts no strategy is automatically Paper-approved.

Paper authorization clarified:
- User explicitly authorized Alpaca **Paper** testing and reports approximately USD 100,000 simulated account equity.
- That figure is not an approved risk budget. The experiment matrix records proposed pre-review caps only: USD 100 per order, USD 500 gross exposure, USD 25 daily loss, maximum 3 open positions, with zero default strategy allocation. These are not account settings and have not been applied.
- The crypto Paper smoke workflow was changed from branch-push-triggered order submission to a manual `workflow_dispatch` with a required boolean `allow_paper_orders` defaulting to false. Read-only connection, cash-only/no-short preflight and asset-permission checks run first. Only when manually set true does it run the fixed USD 10 BTC/USD buy-and-close smoke test.
- **Superseded by the verified 2026-11-11 Paper lifecycle evidence below:** the user manually dispatched workflow run `42962519055`; it completed successfully with a capped USD 10 BTC/USD buy and broker-confirmed close. See the appended execution record. The workflow remains manual and gated; the connector still cannot dispatch it or access credentials.
- Current Paper smoke uses a temporary idempotency journal, appropriate only for a single bounded smoke run; it is not a substitute for the persistent runtime journal. It must not be used as a strategy-performance test.

Pairs trading:
- Standard pairs strategies require long and short legs. Current cash-only/no-short constraints mean pair hypotheses may be tested offline in a simulated long/short backtest only, including borrow, spread, legging and financing assumptions.
- No pair orders can be sent to this Paper account unless a separately reviewed account-policy change is explicitly authorized. No such change is made here.
- Do not change account settings automatically to enable shorts, margin or options.

Next actions:
1. Implement and test a dedicated pairs/cointegration research harness on synchronized, adjusted data, with rolling hedge ratios, stationarity checks, train-only pair selection, entry/exit/stop/time stop, next-open fills, borrow/fees/spread/legging costs and strict OOS splits.
2. Validate the experiment-ledger schema and add append-only experiment run artifacts with dataset/code hashes.
3. Run the manual read-only Alpaca Paper preflight; inspect exact account status, cash-only settings, crypto permissions and current positions before any order smoke.
4. Only then run the explicit capped USD 10 Paper smoke test if preflight passes and no conflicting BTC position exists. Record broker order IDs, fills, fees, residual position and reconciliation.
5. Build offline strategy hypotheses in pre-registered tranches. Keep Paper for operational validation after an offline pre-screen, not for searching parameters or manufacturing statistical significance.
6. Re-run full runtime and subsystem tests on the post-merge main SHA; the PR registry workflow success is not evidence that the whole runtime passed.


## 2026-11-11 — Execution evidence ledger and crypto lifecycle verification

### PR #141 — append-only execution event ledger
- Merged to main: `e486431aa849721ef43e5abd6f40e5ec5fbffc49`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/141
- Added `rocket_trader_execution_event_ledger.py`: broker-agnostic SQLite event store, append-only UPDATE/DELETE guards, canonical finite JSON, timezone-aware timestamps, stable event IDs, SHA-256 hash chaining and chain verification.
- Rejects credential-like fields in payloads. It has no broker/network/order-submission capability.
- PR CI run `43012855089`: success; 11 offline tests passed. Post-merge main run `43012979815`: success.
- Important boundary: module is **not yet integrated into the Alpaca adapter/runtime**. SQLite durability depends on deployment to persistent storage. Hash chaining detects tampering but is not a signed/external immutable audit anchor.

### PR #142 — idempotency correction
- Merged to main: `5d8c78f51fc3066d7f413847c76cc2100449b5b3`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/142
- Fixed retries with omitted `occurred_at`: duplicate event IDs now reuse the original generated timestamp rather than conflicting because a retry has a later ingestion time.
- Added concurrent eight-thread duplicate append coverage.
- PR CI run `43013163224`: success; the expanded ledger suite passed. Post-merge main run `43013213633`: success.

### PR #143 — crypto order lifecycle edge-case tests
- Merged to main: `d9332710721b2e7655cdd8199bf43a5952e5b723`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/143
- Added five offline adapter tests covering restart reconciliation without duplicate submission, unfamiliar broker status preservation, partial fill quantity after cancellation, fill/cancel race resolution, and fail-closed unknown submission across adapter restart.
- CI run `43013254788`: success; 25 offline crypto Paper execution tests passed.
- This is test coverage of existing behavior, not proof of real-broker partial-fill or restart recovery. No Paper/Live orders were sent by these PRs.

### Verified Alpaca Paper smoke — user-dispatched workflow
- Workflow run `42962519055` completed successfully; preflight job `130332150112` and execution job `130332285751`.
- Account preflight reported ACTIVE, PAPER, USD, cash/equity USD 99,999.86, multiplier 1, shorting disabled, trading not blocked, and no account configuration changes.
- One capped BTC/USD buy of USD 10 was broker-reported filled: gross filled quantity `0.000133206 BTC`; broker net position quantity `0.000132872 BTC`.
- One sell was broker-reported filled for `0.000132872 BTC`; final residual `0 BTC`.
- `paper_buy_orders_submitted=1`, `paper_sell_orders_submitted=1`, `live_orders_submitted=0`.
- The `0.000000334 BTC` difference between gross filled and net position is observed, but its exact fee/rounding decomposition was not established. Do not call it a confirmed commission.
- This proves one bounded buy/fill/sell/fill lifecycle only. It does not prove representative execution costs, strategy edge, persistent runtime journaling, broker activity recovery or profitability.

### Current engineering status and next steps
- Progress estimate moves from 48% to **49%** for the merged event-ledger capability and verified offline lifecycle coverage. This is engineering/evidence maturity only.
- PR #145 has now integrated the append-only event ledger into the Paper crypto adapter. The adapter writes deterministic `ORDER_PREPARED`, `BROKER_ORDER_DISCOVERED` and `ORDER_STATE_OBSERVED` events; verifies the hash chain on startup; and fails closed if the ledger is unavailable or corrupt. A write-ahead event is recorded before any broker submission. The mutable order journal is persisted before broker-state events; if the latter write fails after broker acceptance, retry reconciles the broker order instead of resubmitting.
- Alpaca's current public documentation distinguishes order snapshots from account activity evidence: trade activities can contain individual fill records, while crypto fee activity is a separate activity type; the newer Activity SSE includes execution details such as commission. Do not infer fees from gross/net quantity deltas alone. Source documentation: https://docs.alpaca.markets/us/docs/activity-sse and https://docs.alpaca.markets/us/docs/account-activities.
- Before implementing fee recovery, verify the exact supported Paper API endpoint and SDK access path, pagination, activity identifiers, fee currency/amount and delayed-posting behavior. Missing activity or fee evidence must remain UNKNOWN, not zero.
- Next sequence: (1) integrate the append-only event ledger with the adapter using write-ahead/unknown-state semantics; (2) add broker activity/fee reconciliation and idempotent fill ingestion; (3) add partial-exit remainder recovery with strict ownership checks; (4) prove restart recovery on a deterministic fake broker; (5) only then consider a separate, explicitly gated Paper operational test. Keep order cap USD 10 and Live disabled.


### PR #145 — append-only order evidence integrated into Paper crypto adapter
- Merged to main: `d8ff9e49e3e360567ae14acdacf617eedc7c6e11`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/145
- Adapter now creates a separate event database by default at `<order-journal-path>.events.sqlite3`; override with constructor `event_ledger_path` or `ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB`.
- Startup verifies the full event hash chain and blocks adapter initialization if the ledger is corrupt or unavailable.
- Before a new order, writes deterministic `ORDER_PREPARED` evidence. If that write fails, no mutable journal row is inserted and no broker order is submitted.
- After broker responses, persists mutable order state then appends deterministic `ORDER_STATE_OBSERVED` events. A failure in the latter step leaves the mutable journal as the no-resubmit guard; a retry must query the broker and reconcile rather than place a second order.
- `order_events(client_order_id)` exposes the local immutable event history.
- PR CI run `43013593248`: success; 30 offline adapter tests passed. Post-merge run `43013673531` was queued/in progress when this note was written; update after conclusion.
- No Paper/Live orders or account changes were made by this PR.
- Limits: this records order intent and broker order snapshots, not individual account-activity fills/crypto fees/corrections. It does not yet implement automatic partial-exit remainder recovery. Both SQLite files must reside on persistent storage. Hash chaining is not a signed external audit anchor.

**Next implementation sequence**
1. Wire adapter `reconcile()` into the persistent recovery worker/startup sequence so activity reconciliation runs after restart and on ambiguous/pending states.
2. Add persistent activity pagination cursors/watermarks and correction/bust handling; delayed or missing fee records remain UNKNOWN.
3. Match CFEE records to orders only where a documented, tested linkage exists. Otherwise preserve them as unallocated account-level costs; never infer a fee from gross/net quantity differences.
4. Implement safe partial-exit remainder recovery with broker-owned quantity checks, open-order reservations and fill/cancel race handling.
5. Test process restart at every state boundary with deterministic broker fakes before any further Paper smoke.


### PR #146 — read-only Alpaca fill and crypto-fee activity reconciliation
- Merged to main: `04fa7de66e81fd8617f7a7fd787b97abee5f70fa`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/146
- Added `rocket_trader_alpaca_activity_reconciliation.py` and a dedicated offline test workflow.
- Uses Alpaca Trading API Paper GET /v2/account/activities through Alpaca-py's inherited generic GET method. Official API documentation: https://docs.alpaca.markets/us/reference/getaccountactivities-2 and https://docs.alpaca.markets/us/reference/getaccountactivitiesbyactivitytype-1.
- Retrieves individual FILL records by broker order ID with cursor pagination. Validates activity IDs, order ID, symbol, side, positive quantity/price and timezone-aware transaction timestamps. Persists each fill as an idempotent `BROKER_FILL_ACTIVITY` event.
- Compares summed activity quantities with the broker order snapshot and explicitly distinguishes matched, incomplete activity history, overstated activity quantity and cumulative sequence mismatch.
- Retrieves CFEE records over an explicit timezone-aware window and persists amount/currency as `CRYPTO_FEE_ACTIVITY_UNALLOCATED`. Does not allocate fee to an order because the documented non-trade fee schema does not guarantee an order_id; fee posting can be delayed. Missing fee evidence is never treated as zero.
- Initial CI attempts exposed a test-fixture pagination bug: the fake client replayed page one instead of returning an empty terminal page. The fixture was corrected to return an empty page for unknown cursors. Final PR run `43014063435`: success, 14 tests passed. Post-merge main run `43014116074`: success, 14 tests passed.
- No live or Paper API requests, orders, account configuration changes or paid services were involved.
- Scope boundary at PR #146: the reader was a separate component. PR #148 now invokes it through the adapter's explicit `reconcile()` / `reconcile_order_activities()` path. It is not yet scheduled automatically at every process restart or by a persistent recovery worker; it does not yet checkpoint cursors persistently, resolve corrections/busts or allocate delayed fees to individual orders.

**Progress estimate:** 51% (engineering/evidence maturity only). The new component establishes a supported read-only source for fill and crypto-fee activity, but the full recovery pipeline and runtime integration remain incomplete.


### PR #148 — adapter-level broker fill and fee reconciliation
- Merged to main: `7a1e9ceeb3a979ef5142a9348dd1c0a51e412ae0`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/148
- Adapter `reconcile()` now retrieves the broker order snapshot, fetches individual FILL activities by broker order ID, ingests each fill into the append-only event ledger, and records an idempotent order-level reconciliation summary.
- Incomplete activity history is returned explicitly when activity quantity does not yet match the broker order snapshot. Activity API outages are surfaced as reconciliation errors, not treated as zero fills.
- Added `collect_crypto_fee_activities(symbol, after, until)` to retrieve CFEE records over an explicit timezone-aware window. They remain unallocated at account level.
- PR CI run `43014290120`: success; 34 offline crypto adapter tests passed. Post-merge main run `43014362335` was pending/in progress when this note was written; update after conclusion.
- No real Paper API request or order was performed by this PR.
- Important remaining gap: the adapter exposes the reconciliation path, but no persistent recovery worker currently guarantees it is called automatically at every restart/ambiguous state. Pagination checkpoints and correction/bust handling are not implemented.

**Progress estimate:** 52% (engineering/evidence maturity only). The event ledger is now used by the adapter and broker fills can be reconciled when the explicit reconciliation path is invoked. Full unattended recovery, fee attribution, partial-exit automation, durable worker scheduling, live Paper API validation and strategy edge remain unproven.


### PR #150 — prevent overlapping crypto SELL orders
- Merged to main: `e7e26ee89c80568dc50ef05cc423e30027fc6735`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/150
- Before accepting a new SELL, the adapter queries Alpaca open SELL orders for the same crypto symbol using `GetOrdersRequest(status=OPEN, side=SELL, symbols=[symbol], limit=500)`.
- Reserves each open broker order's unfilled remainder (`qty - filled_qty`) against current broker-held position quantity. This prevents the adapter from submitting a second SELL against quantity already committed to a resting/partially-filled SELL.
- Fails closed if the open-order query fails, is malformed/truncated, or lacks quantity/order ID data.
- Uses SQLite `BEGIN IMMEDIATE` around local SELL reservation checks and PREPARED journal insertion, so two adapter instances sharing the same local journal cannot both reserve the same quantity.
- A local PREPARED/unknown/stale SELL order absent from the broker open-order snapshot blocks further SELLs until reconciled. Unknown state is not assumed released.
- Confirmed terminal states release the unfilled reservation; broker position remains the source of current owned quantity. Partial terminal fills rely on broker position state having caught up.
- Enforces separate SQLite files for mutable order journal and immutable event ledger to avoid cross-database lock hazards.
- Initial CI run `43014743048` exposed three test-fixture/assertion issues (accepted-order fill quantity, expected incomplete activity, and error-text matching). These were corrected; final PR run `43014828610`: success, 43 offline tests passed. Post-merge main run `43014917712`: success.
- No Paper or Live API calls or orders were performed by this PR.
- Boundary: this protects concurrent SELL reservations made through Rocket Trader and rechecks broker open orders immediately before submission. It cannot atomically serialize a separate external client placing an order at exactly the same instant. A confirmed terminal partial fill also depends on broker position data being current; any discrepancy must remain blocked and be reconciled.

**Progress estimate:** 53% (engineering/evidence maturity only). The adapter now accounts for broker open SELL orders and serializes local reservation checks. Full recovery scheduling, partial-exit remainder automation, correction/bust ingestion, fee attribution, empirical costs and strategy edge remain unproven.


### PR #152 — manual read-only Paper order/fill/fee audit
- Merged to main: `92e427620a504a55a47b280cc617dcb3a94c2749`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/152
- Added `alpaca_paper_activity_reconciliation_audit.py` and workflow `.github/workflows/rocket-trader-paper-activity-audit.yml`.
- The workflow is manual-only for broker access. PR/push events run static compilation and offline tests; they skip the account-audit job.
- Manual audit explicitly constructs `TradingClient(..., paper=True)`, requires `ALPACA_PAPER=true`, blocks if `ALPACA_LIVE_ENABLED=true`, and read-only verifies ACTIVE/USD/crypto ACTIVE, multiplier 1, shorting disabled, and options level 0.
- It queries orders by symbol and explicit time range, reconciles each broker order's filled quantity against individual FILL activities, and collects CFEE candidates over a separate window.
- It creates a JSON report and SQLite event ledger artifact (14-day retention). No orders are submitted, canceled, replaced or modified; account configuration is not changed.
- Default order window targets the earlier user-dispatched BTC/USD Paper smoke (2026-11-11 04:55–05:05 UTC); default fee window extends to 2026-11-13 to allow delayed fee posting. Both windows are editable in workflow inputs.
- PR CI run `43015558131`: success; 17 offline tests passed. Post-merge main run `43015657332`: success.
- **The actual Paper account-activity endpoint has not yet been queried by this new workflow.** It must be manually dispatched by the user from GitHub Actions. If no CFEE activity appears, the report explicitly leaves fee evidence UNKNOWN; it does not infer zero fees.

**Progress estimate:** 54% (engineering/evidence maturity only). A controlled real-Paper read-only audit is now prepared but awaits user dispatch. Full unattended recovery, persistent activity watermarks, corrections/busts, fee attribution, partial-exit automation, deployment, empirical costs and strategy edge remain open.


### PR #154 — safe diagnostics for read-only Paper activity audit
- Merged to main: `7aa7b8d5acaf0b5247c316842ec4824fb6f9c907`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/154
- The prior manual audit run `43020228954` failed after entering the activity reconciliation step and printed only `AlpacaActivityReconciliationError`.
- Added safe reporting of Rocket Trader's own `ValueError`/`RuntimeError` validation messages, plus a bounded cause-chain containing exception class names and HTTP status codes only. Raw SDK/HTTP exception text remains suppressed.
- Added an offline regression test proving the safe message is emitted without printing the test secret.
- PR CI run `43020664640`: success. Post-merge static CI run `43031972951`: success. The Paper audit job was skipped because this was a push event.
- The failed run's artifact `13853579473` was created before this diagnostic change and contains no underlying cause. **The actual Paper activity failure is still undiagnosed until the user manually dispatches the audit again on the new main.**
- No broker order, cancellation, replacement or account configuration mutation was performed by this PR.

**Progress estimate:** 54% (engineering/evidence maturity only). Diagnostic visibility is improved; live Paper activity reconciliation remains unvalidated.

### PR #155 — explicit read-only recovery of journaled crypto orders
- Merged to main: `829e17343b7073e77ad1fd16ebc2611be2d88641`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/155
- Added `AlpacaCryptoPaperExecutionAdapter.recover_journaled_orders()`: scans all locally journaled orders, re-queries each by client order ID, persists the broker snapshot, and reconciles individual FILL activities.
- Reports `RECONCILED`, `BROKER_ORDER_NOT_FOUND`, `REQUIRES_REVIEW` or `RECONCILIATION_FAILED` with aggregate counts.
- Recovery is read-only with respect to the broker: it never submits, cancels or replaces orders. Missing broker orders and incomplete/mismatched activity remain unresolved; no automatic resubmission is attempted.
- Added offline tests for successful recovery, missing broker order, filled-order activity reconciliation and repeated-run idempotency.
- PR CI run `43032346333`: success. Post-merge main run `43032427138` was still running when this note was drafted; update after conclusion.
- Important boundary: this is an explicit adapter method, **not yet invoked automatically at process startup or by a persistent scheduled worker**. It is not an autonomous execution service and no real Paper order was placed by this PR.

**Progress estimate:** 54% (engineering/evidence maturity only). Explicit recovery logic is implemented and offline-tested; automatic startup scheduling, durable activity watermarks, correction/bust handling, fee attribution, empirical costs, strategy edge and sustained Paper validation remain open.


### PR #157 — one-shot read-only Paper execution recovery runner
- Merged to main: `adab3f2bc29e71be788fa47335f73e0cce9830fc`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/157
- Added `alpaca_paper_crypto_execution_recovery_worker.py` as a one-shot host-side runner for the durable execution journal.
- Requires both the existing mutable order journal and existing immutable event-ledger SQLite files before constructing the adapter. This prevents a missing/incorrect path from silently creating an empty journal and reporting false recovery success.
- Requires explicit Paper environment, rejects LIVE and non-PAPER mode, verifies the account cash-only policy, and calls the PR #155 read-only recovery pass.
- Writes a bounded JSON report when configured. Exit 0 means every journaled order was reconciled; exit 2 means unresolved records; exit 1 means preflight/state/worker failure. Raw SDK exception text and credentials are not printed.
- Added offline tests for Paper-only client construction, refusal of LIVE, missing journal/event-ledger files, and nonzero exit on unresolved recovery. Extended crypto execution CI and documented host-side use in `PAPER_OBSERVER_DEPLOYMENT.md`.
- PR CI run `43032980158`: success. Post-merge main run `43033056053` was pending when this note was drafted; update after conclusion.
- Boundary: this is a one-shot runner, **not yet a persistent loop, scheduled worker, or automatic startup gate**. It must use the same durable DB files as the eventual execution service. No such service has been deployed by this workflow.

**Progress estimate:** 54% (engineering/evidence maturity only). A restart recovery path is now callable and offline-tested, but automatic service integration and live Paper validation remain open.


### PR #159 — fix account-wide CFEE symbol handling
- Merged to main: `60ff6607780f66fb830a0629fd5cb7047c46e7ea`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/159
- Real manual Paper audit run `43034874861` (job `130570956064`) reached Alpaca successfully, passed account cash-only preflight, queried the two BTC/USD smoke orders and reconciled both FILL histories: BUY `0.000133206 BTC` MATCHED and SELL `0.000132872 BTC` MATCHED.
- The run then failed during the account-wide CFEE query with `Activity has an invalid crypto symbol.` The CFEE collector incorrectly assumed every account-level fee record had a valid BASE/USD pair symbol. FILL evidence was already successfully reconciled; the error was isolated to CFEE processing.
- PR #159 changes CFEE handling to preserve all returned CFEE evidence in the append-only ledger and classify it as target-symbol, other-symbol, or unclassified. Incomplete amount/currency/timestamp records are retained and marked incomplete. No fee is assigned to an order without documented linkage.
- The audit JSON and GitHub step summary now expose target, other-symbol, unclassified and incomplete fee evidence. Fill reconciliation status no longer fails merely because an unrelated CFEE symbol is unclassifiable.
- Regression coverage includes account-wide unclassifiable CFEE, other crypto symbols, incomplete fee fields and end-to-end audit success with matched FILLs.
- PR CI: `43035761377` and `43035761387` succeeded. Post-merge runs `43035852426` (activity tests) succeeded; `43035852875` (audit static-check) was still running at handoff update time. Manual Paper audit job is skipped in push/PR CI.
- **Still pending:** user must manually dispatch the read-only Paper activity audit on current main to inspect actual CFEE results. The previous report showed 2/2 fills matched but did not provide successful fee evidence. No new order was submitted by PR #159.
- No Live access, order submission, cancellation, replacement or account mutation occurred.

**Progress estimate:** 55% (engineering/evidence maturity only). Real Alpaca order FILL evidence is now confirmed for both smoke orders and the CFEE failure root cause is corrected in code; actual post-fix CFEE evidence and profitability remain unvalidated.


### PR #161 — enforce CFEE creation-time window locally
- Merged to main: `62a0ac24b52c9057020e6728ca30be5eaebcdc74`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/161
- Manual post-PR #159 Paper audit run `43036761702`, job `130577497509`, succeeded. Account preflight remained `ACTIVE_USD_CASH_ONLY_NO_SHORT`; both BTC/USD smoke orders reconciled exactly against FILL activities (BUY 0.000133206 BTC; SELL 0.000132872 BTC).
- The report returned six CFEE activities. Three were classed as BTC/USD (two created on 2026-11-10 before the configured fee-window start of 2026-11-11 04:55 UTC; one at 2026-11-11 04:57:49 UTC). Three had no classifiable symbol (two before the window; one at 2026-11-11 04:57:52 UTC). All were complete, but unallocated; none contained documented order linkage. Thus the raw report's three BTC/USD CFEE candidates included two out-of-window records.
- PR #161 adds a local strict creation-time check using Alpaca `created_at`, while preserving out-of-window and unverified-timestamp records in the immutable event ledger with distinct event types. Such records no longer enter interval-specific candidate counts. Audit JSON/summary expose out-of-window and unverified counts and exact window bounds.
- Regression tests cover out-of-window target-symbol and unclassified fees, an in-window fee, and records without verifiable `created_at`. PR CI runs `43037441267` (activity tests) and `43037441187` (audit static/offline tests) succeeded. Post-merge runs `43037526916` and `43037526946` are recorded below once final conclusions are confirmed; Paper audit itself is skipped on PR/push CI.
- The in-window BTC-denominated CFEE quantity and in-window USD -0.03 CFEE remain unallocated. No order-level fee attribution or exact net cost is established.
- No order was submitted/canceled/replaced; account settings were not changed; LIVE remains disabled.

**Progress estimate:** 55% (engineering/evidence maturity only). The real FILL path is verified and CFEE time-window integrity is hardened, but the fix still needs a fresh read-only Paper run, durable automatic recovery/cursors, corrections, empirically measured costs, deployment and strategy OOS edge remain open.


### PR #163 — fail-closed Paper crypto execution startup gate
- Merged to main: `a12e69fe1f7fe18f0ed21f99cb4c347de26850fa`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/163
- Adds `PaperCryptoExecutionService`, a process-local orchestration gate for a future Paper crypto execution host. New intents are blocked until the service verifies the account's ACTIVE/USD/crypto ACTIVE/cash-only/no-short/options-disabled configuration and the adapter's read-only recovery reconciles every journaled order.
- `from_existing_storage()` requires pre-existing separate journal and immutable event-ledger files. It opens them read-only before adapter construction, checks the journal schema, event schema, append-only triggers, and requires every journaled order to have matching `ORDER_PREPARED` or `BROKER_ORDER_DISCOVERED` evidence. It requires `ALPACA_PAPER=true`, rejects LIVE, and does not accept an externally injected broker client; the adapter constructs its Alpaca client with `paper=True`.
- The gate stays closed on failed/malformed recovery, unresolved orders, account-preflight mismatch, `stop()`, or any adapter submission exception. A fresh successful recovery pass is required before another intent.
- PR CI `43038167066`: success; 65 offline crypto execution/recovery/startup-gate tests passed. Post-merge main run `43038263626` was running when this note was drafted; update with its conclusion.
- Boundary: this is **not a deployed service** and does not wire itself into the observe-only Compose stack. The low-level adapter remains callable by existing explicit workflows; any future autonomous execution host must use this gate and must not bypass it. No strategy is approved, no strategy-driven orders are enabled, and LIVE remains prohibited.

**Progress estimate:** 55% (engineering/evidence maturity only). Startup recovery now has a tested integration primitive, but persistent host deployment, real Paper restart recovery against the same durable files, activity cursor/backfill/correction handling, empirically calibrated costs and validated strategy edge remain open.


### PR #165 — bounded Paper Activity SSE capability probe
- Merged to main: `7d92fd7aaa352087552129d02c6e4c4bee24b3fd`.
- PR: https://github.com/marcodurzov/Rocket_Trader/pull/165
- Official Alpaca documentation describes the Paper Activity SSE endpoint `/v2beta1/events/activities`, finite historical `since`/`until` queries, replay via `since_id`, stable `ref_id` deduplication, and `previous_id` references for corrections/cancellations. The documented TRD execution types include `fill`, `trade_correct` and `trade_bust`. The docs describe TRD as equity/options; crypto support is not yet established for this account.
- Added `alpaca_paper_activity_sse_probe.py`: bounded, read-only historical request using the user's Paper API headers. It reports activity types, crypto-like TRD symbols, CFEE/FEE counts, correction/bust types, previous_id linkage, duplicates, event ordering anomalies, dropped-message comments and malformed frames.
- The probe does not modify the execution event ledger, maintain/advance a cursor, apply corrections, mutate positions or submit/cancel/replace orders. Unsupported HTTP status and no-event cases are reported as evidence, not treated as proof that crypto is unsupported.
- Integrated the probe into the existing manual-only Paper activity audit workflow. Its JSON is included in the artifact. The query starts at the configured order-window start and ends at the current UTC time, so it is a finite historical query, not a persistent stream.
- PR CI run `43038829544`: success; 32 offline tests passed. Post-merge run `43038939488` is pending its final conclusion. The actual SSE call is skipped on PR/push CI.
- **Next user action:** manually dispatch the read-only Paper activity audit on current main. That single run will validate the CFEE local-window fix and probe whether this Paper account returns crypto TRD/correction events from Activity SSE.
- No new orders or account mutations were made. LIVE remains prohibited.

**Progress estimate:** 55% (engineering/evidence maturity only). The SSE capability is not yet confirmed against the Paper account, and no correction/bust ingestion or P&L adjustment is enabled.


### Paper audit run #43042768582 — Activity SSE crypto evidence confirmed
- Manual workflow run: https://github.com/marcodurzov/Rocket_Trader/actions/runs/43042768582
- Artifact ID: `13866211467`; both `paper-activity-report.json` and `paper-activity-sse-probe.json` inspected.
- Account preflight: `ACTIVE_USD_CASH_ONLY_NO_SHORT`; audit status `SUCCESS`.
- The two known BTC/USD smoke orders both matched the Alpaca FILL activities: BUY `0.000133206 BTC`; SELL `0.000132872 BTC`.
- Activity SSE returned HTTP 200 and six events: 2 TRD, 2 CFEE, 2 JNLC. Both TRD events were BTC/USD fills with order IDs and client order IDs matching the known smoke BUY/SELL. `crypto_trade_event_count=2`, `dropped_message_comment_count=0`, `duplicate_ref_id_count=0`, `event_ordering_anomaly_count=0`, `invalid_event_count=0`, `invalid_frame_count=0`, `orphan_previous_id_count=0`.
- No `trade_correct` or `trade_bust` events were observed in this short historical window. This confirms crypto fill delivery, not correction/bust behavior.
- One in-window BTC/USD CFEE was complete: qty `-0.000000334 BTC`, net amount `0 USD`. One in-window unclassified CFEE was complete: net amount `-0.03 USD`. Both remain `UNALLOCATED`; neither includes documented order linkage. Four out-of-window fee records were excluded from the active interval. No order-level fee attribution or net cost is claimed.

### PR #167 — durable Paper Activity SSE inbox
- Merged: `8e309da4d5f8de88e25838762d780c41fc510811`; PR https://github.com/marcodurzov/Rocket_Trader/pull/167.
- Adds a Paper-only reconnectable SSE consumer. Initial bootstrap uses `since`; subsequent connections use persisted `since_id`.
- Each activity, delivery idempotency record and cursor update commit in a single SQLite transaction. Immutable activity/delivery tables have update/delete triggers; activities are SHA-256 chained. Stable `ref_id` fingerprints exclude publication `event_id`, allowing safe duplicate publication IDs without double-staging the same activity. Conflicting payloads fail closed.
- Reconnects after disconnects, read timeout, dropped-message comments and internal-server-error comments. The cursor advances only after durable staging.
- `previous_id` is preserved; corrections/busts are not applied to positions/cash/P&L. No broker order methods are called.
- PR CI `43043343957` passed 21 tests; post-merge CI `43043417104` succeeded.

### PR #168 — persistent Paper Activity SSE Compose service
- Merged: `31c68fd37b684a915754ff9f14f5f250034096c1`; PR https://github.com/marcodurzov/Rocket_Trader/pull/168.
- Adds a separate `rocket-trader-alpaca-activity-sse` container using the existing named persistent volume and a dedicated SQLite inbox. Explicitly sets `ALPACA_PAPER=true`, `ALPACA_LIVE_ENABLED=false`, and `ROCKET_TRADER_EXECUTION_MODE=PAPER`.
- Adds the consumer to the observer image, a local hash-chain/cursor healthcheck, and safe reconnect logs. CI validated Compose syntax, built the Docker image and compiled the consumer inside the image. Runtime tests also passed.
- The service is **prepared but not deployed**. It requires operator access to the actual host, the existing Paper credentials in a private `.env`, and a deliberately selected `ACTIVITY_SSE_BOOTSTRAP_SINCE`. A GitHub runner is not a persistent host.
- No new orders or account mutations were made by either PR.

**Progress estimate:** 56% (engineering/evidence maturity only). Crypto fill Activity SSE and durable replay primitives are now confirmed/implemented; host deployment and real restart/replay validation, correction/bust behavior, fee allocation, calibrated net costs, and strategy out-of-sample edge remain open.


### PR #170 — keep the published image current
- Merged: PR https://github.com/marcodurzov/Rocket_Trader/pull/170.
- Added `rocket_trader_alpaca_activity_sse_consumer.py` to the Paper observer image publisher's path filters so a future consumer-only change triggers a new image build.
- Post-PR #168 image publication run `43043958882` succeeded. PR #170 also triggered image publication run `43044264217`, which succeeded.

### PR #171 — strictly read-only healthcheck
- Merged: PR https://github.com/marcodurzov/Rocket_Trader/pull/171; merge SHA `8bf6d6a2560806a4b2b2aa04c92f8576c571f094`.
- Corrected a healthcheck flaw: it previously constructed the inbox with schema initialization enabled, so a missing volume/path could create a fresh empty DB and falsely pass.
- Healthcheck now opens an existing DB only, fails without creating a replacement if it is missing, and verifies hash chain, payload hashes, cursor/delivery integrity and all append-only triggers.
- PR CI `43044388062`: 26 offline tests passed. Compose config validation, Docker image build and in-image module compilation passed in `43044387984`. Post-merge consumer tests `43044515041` succeeded; post-merge image publication `43044515119` was still running at this handoff edit.
- This healthcheck validates local DB integrity, not upstream API connectivity. Connection failures are logged as `RECONNECTING`; operators must inspect container logs.

**Progress estimate:** 56% (engineering/evidence maturity only). The persistent service is implemented, packaged and CI-validated but has not been deployed on a user-controlled host or tested through a real process/container restart against a persistent volume.


## 2026-11-11 — User confirms no known persistent deployment host; zero-budget policy

- User confirms the only known platform in use is GitHub for source/workflows and Alpaca for brokerage/API and the USD 100,000 simulated Paper account. User does not know of, and has not identified, any VPS, cloud host or persistent deployment platform.
- **Operational conclusion:** no persistent host is currently evidenced. Treat Rocket Trader as a GitHub-hosted repository with GitHub Actions workflows and Alpaca Paper integration, not as a deployed always-on trading service. GitHub Actions runners are ephemeral and must not be represented as a persistent production host.
- Clarification: Alpaca is the broker/API and Paper trading environment; it is not the compute host for Rocket Trader's long-running processes. A persistent runtime may be needed later for continuous collection/recovery/execution, but it is not a prerequisite for continuing offline research, CI, bounded Paper audits or other workflows that fit GitHub Actions limits.
- **New governing budget rule, explicitly confirmed by user:** target **USD 0** recurring and setup cost wherever technically and operationally viable. Prefer free tiers and existing GitHub/Alpaca capabilities. If no free option meets reliability, security, persistence, runtime and usage requirements, choose the lowest-cost viable option and present the exact cost, limitations and free alternatives before any commitment. No paid hosting, data subscription, API plan, domain, or other service may be activated without explicit user approval. Do not assume a free tier is suitable without checking its current limits and terms.
- No new broker account, provider account, paid service or deployment host is authorized merely by the general development authorization. Research and recommend options first; ask before creating accounts, accepting paid terms or incurring charges.
- User reiterates full authorization to continue Rocket Trader development and Alpaca Paper testing. Existing safety boundary remains: Paper only; no LIVE trading or real-money orders; no leverage, margin, shorting, options or account-policy changes. Existing smoke-order cap and workflow controls remain unchanged.
- **Immediate next step:** inventory current GitHub Actions workflows, Docker/GHCR publication, Compose requirements and Alpaca Paper integration to determine which parts can remain on free GitHub Actions and which genuinely require an always-on host. Compare zero-cost options (including self-hosting on hardware the user already owns, if available) before proposing paid infrastructure. Do not ask the user to buy a server at this stage.
- No deployment was performed and no new broker order was submitted as part of this clarification.

**Progress estimate:** remains **56%** (engineering/evidence maturity, not profitability). The user's deployment uncertainty is now resolved as a documented absence of a known host; it does not itself increase implementation or validation maturity.


## 2026-11-11 — Free infrastructure and scheduled-workflow audit

### Verified repository and cost facts

- Repository visibility is **public**. This matters because GitHub documents standard GitHub-hosted Actions runners as free and unlimited for public repositories; larger runners are excluded from that free guarantee.
- GitHub documents Container Registry image storage and bandwidth as currently free. The publish workflow pushes to GHCR, but package visibility was not independently verified in this audit; check that setting before relying on anonymous pulls. Re-check terms if repository/package visibility changes.
- The existing workflows use standard `ubuntu-latest` runners; no larger runner label was found in the reviewed workflow inventory.
- The repository currently contains 58 workflow files. Ten contain scheduled triggers:
  - ETF Alpaca/Yahoo cross-check: weekly Sunday.
  - Crypto multi-year research v0.1, v0.2, v0.3: weekly Sunday.
  - Equity multi-year research v0.1, v0.2, v0.3, v0.4: weekly Sunday.
  - IEX recent/live market-data health probe: weekly Monday. Historical SIP entitlement is checked separately by the 10-year cross-check.
  - Traditional research v0.2: weekly Sunday.
- The schedules are research/audit jobs, not a continuous trading service. The Activity SSE consumer workflow is push/PR test CI only; it is not scheduled and the Compose consumer is not running on a known persistent host.
- GitHub scheduled workflows are not a reliable always-on runtime: they can be delayed during load and jobs may be dropped; public-repository scheduled workflows can also be automatically disabled after 60 days without repository activity. Minimum supported schedule interval is five minutes, but that does not create a real-time guarantee.
- Therefore, GitHub Actions + GHCR currently provides a **$0 development, CI, bounded research and audit path**, but it is not evidence of an always-on market-data consumer or autonomous trading host.
- No paid service, new account, deployment, or broker order was initiated.

### Workflow history observations

- GitHub API reported 689 workflow runs at audit time.
- Across the 589 older runs reviewed, 10 had the `schedule` event. Nine succeeded and one failed; the failed run was Traditional Research v0.2 on 2026-11-08.
- The failure log shows the workflow stopped at its exact-implementation check because the checked-out historical script began with a literal Markdown YAML fence (`\`\`\`yaml`) and failed `py_compile`. The current `main` version of `rocket_trader_traditional_research_v0_2.py` was inspected and begins with Python source, not that fence. Do not call the old failure a current-main failure; the current script still needs a fresh run to prove end-to-end health.
- The 10 weekly schedules cluster heavily at the top of the hour on Sunday. This is not a direct monetary cost for standard runners on a public repository, but it increases avoidable queue contention. Consider staggering schedule minutes/hours only after reviewing each research pipeline's dependency and data-window assumptions; do not disable versioned research jobs merely to reduce workflow count.

### Stale open PR discovered

- PR #127 (`Compare adjustment factors with Alpaca issuer corporate actions`) remains open but its branch is 104 commits behind `main`, four commits ahead, and GitHub reports it as diverged/non-mergeable.
- Its historical CI run #42957587110 succeeded on its old head, but that does not validate the change against current `main`. Do not merge it as-is. Rebase/port the corporate-action feature onto current `main`, preserve intervening changes (including newer ETF data-quality and Tiingo diagnostic logic), rerun all relevant tests and the audit, then submit a fresh PR.
- The PR's feature is still relevant: independent Alpaca issuer corporate-action records can help diagnose Yahoo/Alpaca adjustment-factor discrepancies. It remains research-only and must not mutate prices or trading ledgers.

### Alpaca free tier and Live eligibility notes

- Alpaca Paper Trading is documented as free and available globally for Paper-only accounts.
- Alpaca Basic is $0. It provides IEX for recent/live equity data, but also permits historical SIP queries when the request end is at least 15 minutes old. The free plan's historical timeframe is listed since 2016, with a 15-minute recency restriction. Keep SIP for historical research and IEX for recent/live data; do not buy Algo Trader Plus.
- Alpaca states international Live brokerage is jurisdiction-dependent and directs users to contact support to confirm supported countries. Do not assume that a successful global Paper-only account guarantees Live brokerage eligibility. Before any future Live activation, verify account-holder tax residence and current eligibility directly with Alpaca, plus all applicable Mexican and US tax/regulatory obligations. No Live transition is authorized now.

### Infrastructure decision

- Keep GitHub Actions + public GHCR as the zero-cost default for CI, tests, research and bounded Paper audits.
- Do not use GitHub-hosted runners as a persistent service; do not run a permanent process on an ephemeral Actions runner.
- Next runtime options to investigate, in order: (1) a computer the user already owns and can leave online, running the Compose service with persistent local storage; (2) a genuinely free persistent host only if its current terms and reliability meet requirements; (3) lowest-cost paid hosting only after explicit user approval.
- Any local/self-hosted GitHub runner or home-host deployment must keep broker credentials in local secret storage, never in the repository or chat; restrict network exposure; enforce PAPER-only endpoints and no order-submission capability in the observer; test restart/recovery and persistent-volume survival.
- A free cloud tier must be checked for sleep/idle suspension, persistent disk availability, egress limits, runtime caps, region, secret management, and terms before being recommended as a continuous host.

**Progress estimate:** remains **56%** (engineering/evidence maturity, not profitability). This is an infrastructure and workflow audit; it does not prove continuous runtime, restart recovery, strategy edge, or profitability.


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
- At the PR #179 stage, equity research v0.1–v0.4 rejected SIP in code/CLI and workflows. This was superseded by PR #181, which restores SIP only for historical requests with a timezone-aware end at least 15 minutes old; workflows default to SIP for historical research and retain IEX for recent/live-compatible requests.
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
- Continue using Alpaca IEX for the authorized Paper connection and bounded recent/current checks, while keeping Yahoo research data segregated and labeled. Do not silently stitch providers or treat Yahoo as an exchange-licensed execution feed.

## 2026-11-11 — Correct zero-budget Alpaca market-data policy: free historical SIP

A review of the current official Alpaca documentation found that the prior blanket SIP block was incorrect.

- Alpaca Basic costs **USD 0/month**. The official Market Data FAQ explicitly states that historical SIP requests are allowed without a paid subscription when the request's `end` parameter is at least 15 minutes old. Recent SIP trades/quotes/bars and the SIP live stream still require Algo Trader Plus. Sources: https://docs.alpaca.markets/us/docs/market-data-faq and https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api
- Alpaca's own support representative states IEX daily bars are only available from 2020, while SIP historical bars are available from 2016. This explains the earlier observed IEX start dates and the 10-year history gap; it was not an unexplained 37% missing-bar rate. Source: https://forum.alpaca.markets/t/cannot-get-historical-bar-data-before-2020/12415
- The correct zero-budget policy is therefore:
  - **Historical equity research/audits:** use SIP by default, but enforce the request end at least 15 minutes before current time. The implementation resolves the latest completed XNYS session and ends Alpaca requests at its actual close, with a 16-minute safety buffer. Yahoo's exclusive end advances one calendar day to include that same session.
  - **Recent/live market data:** IEX only on the free Basic plan. Do not use SIP for the latest 15 minutes or for live SIP streaming.
  - **No paid subscription:** do not enable Algo Trader Plus or any other paid data tier without explicit user approval.
- Updated the ETF cross-check and equity research v0.1–v0.4 to allow SIP only with a timezone-aware historical end that passes the 15-minute rule. The CLI/workflow default is now SIP for historical research; IEX remains selectable for recent/live-compatible checks. Equity research v0.2–v0.4 now defaults its source to Alpaca rather than Yahoo, with Yahoo retained as the independent comparison source.
- The cross-check now sets its historical data end to the safe UTC date boundary before requesting Yahoo/Alpaca daily prices; corporate-action lookup retains the current timestamp and is read-only.
- The scheduled market-data entitlement probe remains intentionally IEX-only because it is a current/live-feed health check, not a historical SIP entitlement test.
- **Not yet proven for this Paper credential set:** a post-merge read-only SIP historical request must return bars from before 2020, ideally for SPY and the full ETF universe. The implementation must not be described as validated until that workflow succeeds. If Alpaca returns an entitlement error, preserve the logs, disable historical SIP for this credential set, retain IEX for recent/live-compatible data, and do not upgrade or pay.



## 2026-11-11/12 — PR #181 deterministic historical-SIP test-clock correction

### Reproduction and diagnosis
- PR #181's first CI head was `520de2312086b6285996cdf15dc46af0960e9fe3`.
- The ETF cross-check offline suite passed (run `43099544972`), and equity v0.1 passed (run `43099545012`).
- Equity research v0.2/v0.3/v0.4 failed one newly added regression each (runs `43099544902`, `43099545017`, `43099545117`). The failing test attempted to prove a SIP request ending 14 minutes before a fixed test clock was rejected before network access.
- Root cause: `fetch_daily_bars()` called `require_zero_budget_feed(...)` without forwarding the test's reference clock. The guard therefore compared the fixed test timestamp against the real system clock. This was a deterministic-test defect, not evidence of a broker entitlement failure. Do not weaken the 15-minute safety guard.

### Correction applied on PR branch
- Added optional timezone-aware `now` injection to `fetch_daily_bars()` in equity research v0.1–v0.4.
- The default remains the actual UTC clock in normal operation. When supplied, the same reference clock is used both to derive the safe historical end and to validate the 15-minute SIP cutoff.
- Updated the recent-SIP rejection tests in v0.2–v0.4 to pass their fixed `now` into `fetch_daily_bars()`. This makes the test deterministic and still asserts zero broker data requests on a rejected recent SIP request.
- No market-data entitlement, strategy promotion, Paper approval, order path or Live configuration was changed.
- Sequential branch commits:
  - v0.1 code: `634ad0c87a844a25d1feef3f8945dfe0c26976c1`
  - v0.2 code: `dffaee1e075a735a993e4d40e085121a0a804159`
  - v0.3 code: `ea565d3516a3dcabe00e7c1e4a9c5614432c2d45`
  - v0.4 code: `a1fe39aded844bac428ffa2bed9b3b4ca33afbe3`
  - v0.2 test: `82367dab6fa84ae16de290685860d66dc9abcf6c`
  - v0.3 test: `09868fbefc6481a84ebdcc1be68106d372956106`
  - v0.4 test / current branch HEAD at note time: `cd119e3d63d76dc716354249c4c44497666d7daf`

### Validation state
- New PR CI was triggered on head `cd119e3d63d76dc716354249c4c44497666d7daf`:
  - ETF cross-check run `43154220272` was in progress.
  - Equity v0.1 run `43154220412` was pending.
  - Equity v0.2 run `43154220268` was pending.
  - Equity v0.3 run `43154220349` was pending.
  - Equity v0.4 run `43154220319` was pending.
- The PR cross-check event skips live broker history retrieval by design. A green PR suite validates only compilation/offline tests. After the code is merged, a separate read-only main-branch run must query historical SIP with the existing Paper credentials and verify pre-2020 bars. Until that succeeds, free historical SIP is documented as an official provider capability but remains unverified for this credential set.
- No paid plan, Tiingo account/token, broker order, Paper order, or Live action was used.

**Progress estimate remains 58%** (engineering/evidence maturity only). The deterministic test correction and pending CI do not prove historical SIP entitlement, strategy edge, execution costs, persistent deployment, autonomous operation or profitability.

### Next action
1. Wait for all five current PR checks to finish; inspect failure logs, not just run conclusions.
2. Fix any new regression failures on this branch and repeat CI.
3. Merge PR #181 only after every required offline check is green and the diff is reviewed.
4. Run the post-merge read-only 10-year SIP/Yahoo cross-check and v0.2–v0.4 research with the free historical SIP path. Preserve artifacts, per-symbol coverage and provider divergences. Do not promote any strategy from data-source success alone.
5. Keep all Paper execution gates false until independent strategy, execution-cost, accounting, risk and persistent-runtime evidence passes; Live remains disabled.


### PR #181 — second diagnostic edge case found and corrected
- During a further code review, the history-window classification was found to compare only each provider's first session. If two sources shared the same first session but one ended earlier, the report could incorrectly label the history windows `COMPARABLE_HISTORY_WINDOWS`.
- Corrected classification to inspect both first and last sessions, distinguishing a later start, earlier end, and a source window contained inside the other. Added signed `alpaca_history_end_lag_days` alongside the start lag and propagated it through provider-name normalization for optional Tiingo comparisons.
- Added regression tests for an earlier end and a window contained inside another, plus a provider-name assertion.
- Code commit: `dfdeed8854e07ed3df34893bdce7bce67c1429d3`; regression tests: `bc6b10cf2a7f74b704b82457b864ccb0ca3e7afe`.
- New checks for these latest commits had not yet appeared in the commit workflow-run query at documentation time. The previously triggered crosscheck run `43154348896` and equity v0.4 run `43154348846` remained in progress at dependency installation; v0.2/v0.3/v0.1 jobs were queued/not yet exposed. The prior PR run `43154220272` did complete successfully for crosscheck offline tests, but it predates this end-boundary correction.
- This correction affects diagnostic labeling only; it does not relax source coverage or overlap-completeness gates, and does not alter strategy returns or orders.

**Next:** obtain fresh green CI for the latest PR head, then merge only after all offline checks pass. Historical SIP entitlement remains unverified until a separate post-merge read-only Paper-credential run succeeds.


### PR #181 — completed-session boundary and final test corrections
- Replaced UTC-midnight date guessing with the XNYS session calendar. `historical_request_end(now)` now returns the actual close timestamp of the latest completed NYSE session, with a 16-minute buffer. This handles normal closes, early closes, weekends and market holidays; if the calendar cannot be loaded or no completed session is found, the code fails closed.
- Alpaca receives that completed-session close timestamp. Yahoo's end parameter is exclusive, so Yahoo adapters advance the end date by one calendar day to include the same completed session. Historical start timestamps are normalized to UTC midnight. Tiingo's date-based end remains the session date.
- Added tests for pre-close vs post-close behavior, Yahoo's exclusive end, and the completed-session end in v0.1–v0.4. v0.1 workflow now installs `requirements-yahoo.txt` because that dependency supplies `exchange_calendars`.
- CI caught and resolved two test-only issues: v0.1 initially lacked the calendar package in its workflow; the Alpaca SDK represents `StockBarsRequest.end` as a naive UTC datetime in the request model, so regression tests now normalize that representation before comparison. The production cutoff remains timezone-aware.
- Confirmed successful latest runs on the pre-final-test head: crosscheck `43154959313` and v0.1 `43154959322`. Later v0.2–v0.4 runs exposed only the naive-vs-aware test assertion and have been corrected in the branch; final-head CI must still be observed.
- The PR event intentionally skips the broker historical retrieval step. No credential-specific SIP data access has yet been demonstrated. After squash-merging, inspect the main-branch push workflows and their immutable artifacts for the 10-year SIP/Yahoo comparison and v0.1–v0.4 research outputs.
- Current branch is a long-lived PR branch with many incremental commits; use **squash merge** after final green checks to keep `main` history clean.
- No live credentials, Live orders, Paper orders, paid feed or strategy promotion were used.

**Current status:** engineering fix is implemented; final CI on the latest PR head and the post-merge read-only SIP market-data run remain open. Strategy profitability remains unproven and no candidate is approved.


### PR #181 — final-head offline validation
Final code/test head `57e2f330c1cd63e0dc14cea560d520fae98b7b6c` passed all five PR workflows:
- ETF Alpaca/Yahoo cross-check offline suite: run `43155404153` — success.
- Equity research v0.1 self-test: run `43155404157` — success.
- Equity research v0.2 self-test and regression tests: run `43155404154` — success.
- Equity research v0.3 self-test and regression tests: run `43155404122` — success.
- Equity research v0.4 self-test and regression tests: run `43155404183` — success.

These are offline PR checks only. The cross-check's live historical retrieval step and each research workflow's market-data step were skipped by their PR-event conditions. Squash-merge PR #181, then verify the main-branch push workflows and inspect their artifacts before claiming historical SIP entitlement or research coverage validated.


## 2026-11-12 — PR #181 merged; post-merge data validation pending

- PR #181 was squash-merged into `main` at `87cd23753dbc644414d7d3e25ed6684dc7589274`.
- Verified `main` now points to that merge commit. The merge includes the historical SIP guard, XNYS completed-session cutoff, Yahoo exclusive-end alignment, provider history-window diagnostics, v0.1–v0.4 workflow/test corrections, and the updated source audit.
- Final PR offline checks all passed: ETF cross-check `43155404153`; v0.1 `43155404157`; v0.2 `43155404154`; v0.3 `43155404122`; v0.4 `43155404183`.
- These were PR-event checks. Their live broker data and research steps were skipped intentionally. The merge should trigger main-branch push workflows for the read-only historical SIP cross-check and v0.1–v0.4 research.
- The available GitHub connector in this session exposes PR-triggered workflow runs, but not the repository-wide push-run listing/artifacts. The merge commit's legacy combined status endpoint currently reports no statuses, so that is not evidence of workflow completion. Do not infer success or failure of the post-merge market-data requests from the offline checks.
- **Required next verification:** open GitHub Actions for the repository, inspect the push-triggered runs for the ETF cross-check and equity v0.1–v0.4, download their JSON artifacts, and confirm: (1) SIP returned data before 2020 for the Paper credentials; (2) all eight ETFs have the requested history and pass data-quality/coverage gates; (3) provider divergences and adjustment-factor events are understood; (4) v0.2–v0.4 reports preserve multiple-testing, holdout and no-promotion gates. If any workflow failed, inspect logs and fix the actual cause; do not buy data or enable Live as a workaround.
- No Paper order, Live order, real-money funding, paid data subscription, or strategy promotion occurred in this work.

**Phase conclusion:** PR #181's engineering change is merged and its offline checks are green. The historical SIP entitlement/coverage phase is not closed until the post-merge Paper-credential artifacts are inspected. Overall Rocket Trader remains at 58% engineering/evidence maturity; profitability, validated costs, persistent runtime and autonomous operation remain unproven.


### 2026-11-12 continuation — PR #181 historical SIP correction and verification gate

- PR #181 was squash-merged into main at `87cd23753dbc644414d7d3e25ed6684dc7589274`. It corrects the prior over-broad IEX-only restriction: Alpaca's official Market Data FAQ states that Basic users may query historical SIP bars when the request end is at least 15 minutes old. Recent/live SIP remains subscription-restricted.
- The implementation uses a 16-minute buffer and the latest completed XNYS session close, rather than UTC midnight, so a daily candle still in progress is not accidentally included. Yahoo's exclusive end is aligned separately to include the same completed session.
- PR offline checks passed: ETF cross-check `43155404153`; equity research v0.1 `43155404157`; v0.2 `43155404154`; v0.3 `43155404122`; v0.4 `43155404183`. These PR-event checks deliberately skipped broker history retrieval and full research calls.
- The main-branch Paper historical-SIP data proof is still pending. A successful offline test is not proof of SIP entitlement, 10-year coverage, Yahoo parity, or strategy profitability. The GitHub connector used in this session does not expose repository-wide push-run listing or workflow dispatch, so do not invent post-merge run IDs or infer results from the empty legacy combined status.
- PR #180's documented equity research outcomes remain negative: v0.2/v0.3/v0.4 family-wise Holm-Bonferroni significant hypotheses = 0 and pre-screen passes = 0. The earlier v0.1 JSON shared in chat was identified as version 0.1 with a five-year requested lookback; the additional percent-separated artifacts have not yet been reliably parsed. Do not merge their metrics into the v0.2–v0.5 results.
- Source reference: Alpaca Market Data FAQ, https://docs.alpaca.markets/us/docs/market-data-faq (historical SIP request end must be at least 15 minutes old).
- No orders were submitted; no Paper approval or LIVE authorization was granted. Progress remains 58%, an engineering/evidence maturity estimate only; this documentation correction does not increase it.

Immediate next gate: obtain and inspect the post-merge main workflow artifacts for the ETF cross-check and equity v0.1–v0.4. Verify each run's commit, completed steps, data source/feed, requested dates, row counts, coverage, report flags and errors. Keep all candidate/paper/order flags false unless their separate acceptance gates pass.


### 2026-11-12 continuation — PR #183 average-fill-price reconciliation

- PR #183 merged to main at `18ad5ba1e1dc3c0897793961a7b882f888f2cef9`.
- Audit gap: the prior read-only activity audit could mark an order MATCHED when individual FILL quantities summed to the broker order's filled quantity, even if their weighted average price disagreed with the order snapshot. It now calculates the activity-weighted average and compares it with Alpaca `filled_avg_price` using Decimal arithmetic and an absolute USD tolerance of 0.00000001.
- The real Paper audit now fails closed for a filled order when the broker average price is missing or does not match. The report records expected/observed average prices, absolute difference and match status. Existing generic reader callers remain compatible unless they require the average-price gate.
- Offline regression coverage includes matching weighted averages, mismatches, and missing broker average prices. Workflow run `43312572979` passed compile plus 37 activity-reconciliation tests. Workflow run `43312573050` passed its static-check job, including 28 offline tests across activity audit/SSE/reconciliation; its `paper-activity-audit` job was skipped on the PR event.
- Therefore, this is unit/offline-tested reconciliation logic, **not** proof from a new live Paper account-activity retrieval. No Paper order, account mutation or Live action occurred. Existing unresolved fee allocation and corrections/busts remain blockers.
- Two non-fatal ResourceWarnings remain in the audit-runner tests because a couple of test reads use bare `open()` without closing the handle. They did not fail either run; clean them up separately.
- Progress remains **58%**. This correctness improvement does not establish empirical cost validity, full accounting completeness, deployed runtime or strategy edge.

**Next accounting gate:** run the read-only Paper activity audit on main with a bounded explicit time window and inspect the JSON artifact. Then prove recovery from broker activities into the durable event ledger and FIFO inbox across restart, including delayed fees and corrections/busts. Keep order submission disabled until these gates are independently demonstrated.


### 2026-11-12 continuation — PR #185 finite reconciliation-tolerance guard

- PR #185 merged to main at `974288523023f7d08879f2fc420ee25f5f58468f`.
- A review found that `timestamp_tolerance_seconds=NaN` was accepted by the staged activity reconciler. Because comparisons against NaN are false, this could silently disable the timestamp-difference check. The function now accepts only numeric, finite, non-negative tolerances and rejects booleans, strings, NaN and infinities before reading either database.
- Added a dedicated workflow because this module previously had no matching workflow trigger. Workflow `43313016633` passed compile and all 9 offline staged-activity reconciliation tests, including the new invalid-tolerance regression.
- Related regression runs after PR #183: workflow `43313016735` passed 28 offline Alpaca activity/audit tests; `43313016757` passed static checks but skipped its live Paper audit job on the PR event; `43313016739` passed the Paper Observer Runtime test suite. No live Paper account-activity request was proven by those PR checks.
- Cleaned the audit-runner tests to close report files and eliminate the ResourceWarnings observed in PR #183's run.
- No broker orders, account mutations, deployments or Live actions occurred. Progress remains **58%** because the improvement is code/offline evidence, not sustained Paper or profitability evidence.

**Next gate:** execute and inspect the read-only Paper audit on main with explicit bounded order/fee windows, then verify the returned real activity records and the durable restart/recovery path. Keep order submission disabled while fee allocation, corrections/busts and full cash/position reconciliation remain incomplete.


### 2026-11-12 continuation — PR #187 activity pagination completeness

- PR #187 merged to main at 875772afba86ba249849194a3213055dd23fee8d.
- The REST Paper activity stager now reports EXHAUSTED, PAGE_LIMIT_REACHED or CURSOR_STALLED, and sets sync_complete/pagination_complete false unless an empty or short page proves exhaustion. It validates max_pages as a positive integer and fails closed on a non-advancing cursor.
- Workflow 43351364962 passed compile and all 19 activity-stager tests. Workflow 43351365053 passed Compose validation, built the Paper Observer image and verified its accounting/runtime modules. Workflow 43351364942 passed compile and 28 offline observer/runtime tests.
- These checks did not query Alpaca or prove complete real Paper activity recovery. No order or account mutation occurred.


### 2026-11-12 continuation — PR #188 fee evidence cannot pass as full audit success

- PR #188 merged to main at `15ee36705909b3a15fb7d722a1d342191422b06e`.
- The read-only audit no longer returns top-level SUCCESS when fill quantities/prices match but fee activities remain unallocated or unknown. It now reports `fill_reconciliation_status=ALL_ORDERS_MATCHED`, `fee_reconciliation_status=UNRESOLVED`, and `status=FILLS_MATCHED_FEES_UNRESOLVED` with exit code 2. A fill mismatch remains exit code 1; preflight/provider failures remain exit code 1.
- Workflow `43351716511` passed 28 activity-reader tests. Workflow `43351716505` passed compile and 37 audit/SSE/reconciliation tests. Its live Paper API audit job was skipped because this was a pull-request event.
- The manual workflow_dispatch remains the only real Paper account audit path. No live Paper query, order, account mutation or Live action occurred in PR checks.


### 2026-11-12 continuation — PR #190 cash-admin persistent-state guard

- PR #190 merged to main at `29b9cd41c0eca876b888a1fb9a0eea34aa60f4d0`.
- The operator CLI now checks both persistent SQLite files through read-only connections before constructing the ledger or activity stager. It requires distinct existing files, expected tables, ledger schema version 1, persisted capital policy values, the initial-capital event and all append-only triggers. Missing or damaged state is rejected without auto-creating or repairing replacement databases.
- Cash bridge workflow `43352311234` passed 12 cash-activity bridge tests, 6 cash-admin state tests and 22 realized-P&L ledger tests.
- Activity audit static-check workflow `43352311258` passed 37 offline audit/SSE/reconciliation tests; its live Paper audit job was skipped on the PR event.
- Durable Activity SSE workflow `43352311255` passed 26 tests and Compose validation. Paper Observer Runtime workflow `43352311322` passed its full multi-module offline suite. Container workflow `43352311333` passed Compose validation, Docker image build and module packaging checks.
- No Paper account activity query, order, broker account mutation, persistent-host deployment or Live action occurred. Progress remains **58%**.

### Current operational blocker

The read-only Paper audit still needs a manual `workflow_dispatch` run on GitHub Actions with the configured Paper secrets and the known bounded order window. Its fee-window end now defaults to the workflow start time in UTC if left blank. The audit is expected to return a review-required status until fees are linked and allocated to individual fills; do not treat matched fill prices as complete P&L accounting.


### 2026-11-12 continuation — PR #192 FX-aware MXN FIFO accounting

- PR #192 merged to main at `b7eb353f11c29158bc79da9f3c603ca6aae21ad1`.
- The ledger now calculates each FIFO BUY lot's MXN cost basis using that fill's entry FX and calculates net SELL proceeds using the SELL fill's exit FX. This correctly captures USD/MXN movement in MXN strategy P&L, while USD trading P&L remains separately reported. Entry fees are included in the BUY cost basis at entry FX; exit fees reduce SELL proceeds at exit FX.
- The ledger exposes `FIFO_MXN_ENTRY_AND_EXIT_FX_V2` as an accounting-method marker. Legacy ledgers with fills or immutable monthly closes are blocked rather than silently restated. The explicit migration utility validates event hashes and fill FX metadata, requires stopped writers, creates/verifies a SQLite backup, checks the source event count did not change, and refuses existing immutable monthly closes.
- PR workflow `43352962052` passed 29 ledger tests. Workflow `43352962165` passed 37 offline Paper activity/audit tests; the live Paper audit job was skipped on the PR event. Workflow `43352962126` passed 29 ledger, 10 fill-bridge and 8 fee-resolver tests. Workflow `43352962149` passed 12 cash-bridge, 7 cash-admin and 29 ledger tests. Workflow `43352962076` passed 26 durable Activity SSE tests. Runtime workflow `43352962320` and container workflow `43352962176` passed. All corresponding post-merge workflows on main completed successfully.
- The Paper Observer image was published to GHCR (not deployed): `ghcr.io/marcodurzov/rocket_trader:b7eb353f11c29158bc79da9f3c603ca6aae21ad1`, digest `sha256:e58d3d4aa6cf9da80e68dbcf3088bb11cddf1af560f0c3ca8252d3872a172a00` (workflow `43353066858`).
- No existing persistent ledger was accessed or migrated. No Paper account activity query, order, account mutation, persistent-host deployment or Live action occurred. Progress remains **58%**.

### Accounting migration and Paper evidence gates

1. Identify the actual persistent ledger path and stop every process writing to it before considering migration. Do not infer the path from the repository or container image.
2. If the ledger has legacy fills but no accounting-method marker and no immutable monthly close, run the explicit migration utility only after reviewing its backup and stopped-writer requirements. If immutable monthly closes exist, stop: a manual restatement/reconciliation plan is required; automatic migration is deliberately prohibited.
3. Run the manual read-only Paper activity audit through GitHub Actions `workflow_dispatch`. The PR/push static checks skip the real Paper query by design. The audit now distinguishes matched fills from unresolved fees and will not claim full reconciliation when fee linkage/allocation is missing.

 
### 2026-11-12 continuation — PR #194 position-only reconciliation status

- PR #194 merged to main at `231332e16b3411cf660f2f5ec1eefdeac493d99d`.
- `AlpacaPaperReconciliationGate` no longer emits `RECONCILED` when only position quantities match. It reports `POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE`, separates position status from cash status, sets `account_reconciliation_complete=false`, and labels broker cash/equity as observations only.
- The observer runtime now keeps the position-comparison component healthy when quantities match but keeps the overall container healthcheck false until full account cash/equity parity is implemented. Position mismatches remain errors.
- Workflow `43353616669` passed all 7 Paper reconciliation tests. Workflow `43353616666` passed the offline runtime/accounting suite: 32 runtime, 10 telemetry, 29 ledger, 10 fill-bridge, 8 fee-resolver, 6 FX provider, 19 activity-stager, 12 cash bridge, 9 Paper activity reconciliation, 7 Paper position reconciliation, 11 regime observer, 11 regime selector, 9 news assessment and 28 ETF cross-check tests. Workflow `43353616693` passed 26 durable SSE tests and Compose validation. Workflow `43353616662` passed Compose, image build and packaging. Workflow `43353616687` passed 37 offline audit tests; its real Paper audit job was skipped on the PR event.
- No broker activity query, order, account mutation, deployment or Live action occurred. Progress remains **58%**.

### Remaining operational gates

- Run the manual read-only Paper activity audit through GitHub Actions `workflow_dispatch` with the configured Paper secrets. A PR or push check is intentionally not a real account query.
- Identify the actual persistent ledger location before any FX-accounting migration. The new accounting method blocks legacy ledgers with fills or immutable monthly closes; no persistent ledger has been accessed or migrated.
- Implement durable USD cash/settlement/fee accounting and broker-to-ledger parity before the Paper observer can report overall health as ready. The current position comparison alone is not enough.


### 2026-11-13 continuation — strategy risk denominators (PR pending)

- Review found the Core used Alpaca broker `equity` (USD) for both the daily-loss limit and persistent max-drawdown guard while position sizing used a separate strategy allocation in MXN. With a large virtual Paper balance, the drawdown denominator could be orders of magnitude larger than the strategy's MXN 1,000 allocation, making the strategy-level loss guards ineffective.
- The proposed change requires `strategy_equity_mxn` and `strategy_daily_pnl_pct` whenever `strategy_capital_mxn` is configured; missing values fail closed. The persistent strategy drawdown guard uses a currency-marked MXN high-water mark and a dedicated `ROCKET_TRADER_STRATEGY_DRAWDOWN_GUARD_PATH`. Broker USD equity floor remains an additional account-level emergency guard.
- No caller currently provides a complete durable strategy-equity/daily-P&L snapshot from matched broker positions, FIFO MXN cost basis and current marks. Until that integration exists, the Core will reject new entries rather than fall back to broker USD equity. No orders or Live actions are authorized.
