# Rocket Trader — Master Handoff & Working Rules

**Last updated:** 2026-11-10  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Current reviewed main SHA:** `d001fc3f3661b1cae39de535c52b235975f164ae`  
**Current progress estimate:** **46%** toward a complete, validated, operational system. This is an engineering/evidence maturity estimate, not a profitability estimate.

## 1. How to resume in a new conversation

The user can simply say:

> **“Continúa Rocket Trader. Lee primero ROCKET_TRADER_HANDOFF.md y después los documentos que referencia. Revisa el estado real de main, PRs, CI y artefactos antes de actuar. Sigue las reglas del handoff y continúa desde el siguiente bloqueo.”**

Do not ask the user to repeat the project's objective, prior decisions or working rules if they are in this document or the linked authoritative documents. Always inspect the live repository state before assuming this handoff is still current.

Read in this order:
1. This file — continuity, working rules and next actions.
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

### Main as last verified
`a6f1b92136c041af0084bf28d7e686df0d444725`.

- PR #94: regime observer health separates process liveness from market-data readiness and exposes safe-cash/exposure.
- PR #95: actual ETF history crosscheck now triggers on relevant pushes to main, as well as weekly schedule/manual dispatch.
- Workflow run **42920786498** (job **130194785274**) completed with failure on 2026-11-10. Dependency install, compile, offline tests and artifact upload passed; live Yahoo history fetch failed for all eight ETFs with `ValueError: output array is read-only`.
- Log/report proved the executed code still passed `repair=True`, contradicting earlier documentation that claimed `repair=False`. Artifact ID **13812205814** reports zero symbols compared. Do not treat it as historical validation.
- PR #96 merged as `d001fc3f3661b1cae39de535c52b235975f164ae`: adds this handoff, updates README/status, changes Yahoo history to `repair=False`, and adds a regression test that asserts this provider parameter.
- PR #96 offline CI run **42922818287** succeeded: compile and all 6 tests passed. The live comparison step was correctly skipped for `pull_request` events.
- Post-merge live comparison run **42922974687** was triggered by the push to main and was **queued** at the time of this update. Its result is pending; do not treat the fix as live-data-validated until the run completes and its artifact is inspected.

## 7. Next actions — ordered

1. Complete and validate the Yahoo `repair=False` correction; merge only after CI; rerun the actual provider audit and inspect results/artifact. If provider instability persists, diagnose and choose a defensible alternative—never weaken coverage or quality gates.
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
