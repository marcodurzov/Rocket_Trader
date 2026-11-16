# Rocket Trader — Operational Handoff

**Updated:** 2026-11-15  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Last externally reported main SHA:** `18c65d1409ebc3c8abf03a8b0d1cbf267d938cb6` (re-verify before every change)  
**Engineering/evidence maturity:** 58% as last recorded; this is not a probability of profitability.

## 1. Resume protocol

Before acting, inspect the live default-branch SHA, open PRs, CI, recent workflow artifacts and the exact target files. This handoff can become stale. Read in this order:

1. `ROCKET_TRADER_BASELINE_DECISIONS_v0_2.md` — binding user decisions.
2. `ROCKET_TRADER_PROJECT_STATUS_v0_1.md` — implementation and evidence status.
3. `ROCKET_TRADER_INVESTMENT_RESEARCH_FRAMEWORK_v0_1.md` — research acceptance rules.
4. `PAPER_OBSERVER_DEPLOYMENT.md`, `PAPER_REGIME_OBSERVER.md`, `PAPER_EXECUTION_COST_TELEMETRY.md`, `NEWS_EVENT_ASSESSMENT.md`, `REFERENCE_BENCHMARK_HARNESS.md`.
5. `ROCKET_TRADER_SERVER_DEPLOYMENT_PLAN_v0_1.md` — host requirements and deployment gates.
6. `HISTORY.md` — full archived handoff, experiments, failed approaches and chronology.

Do not ask the user to repeat decisions already recorded here or in the baseline.

## 2. Objective and capital policy

Build an adaptive, research-led, multi-asset system seeking sustainable **net** capital growth while protecting capital and abstaining when no candidate has defensible positive net expected value.

- Initial strategy capital: **MXN 1,000**. The minimum viable operating-capital analysis is explicitly deferred until the user asks to revisit it.
- Before the first earned-growth crossing of MXN 100,000: 100% of realized net profits retained; 0% personal distribution; 0% separate reserve.
- At the first earned-growth crossing: permanently latch 50% reinvestment / 10% reserve / 40% personal target allocation.
- External deposits do not count as earned growth. Unrealized P&L is never distributable. The MXN 100,000 floor is a withdrawal constraint, not a guarantee against losses.
- The authoritative implementation is Core's persistent `ProfitAllocator`. Adaptive modules must not create a second capital-policy implementation.

Markets: US-listed equities/ETFs and crypto spot, with separate market/execution paths and shared portfolio risk. No margin, leverage, shorting, options, futures, perpetuals or leveraged/inverse ETFs.

## 3. Non-negotiable rules

### Truth and evidence
1. Never invent sources, tests, workflow results, account state, deployment or profitability.
2. Distinguish implemented, unit-tested, integration-tested, live-data-validated, deployed and approved.
3. Green offline CI is not proof of live data quality, broker reconciliation, execution costs or profitability.
4. Preserve failed results and immutable artifacts. Never relax gates, change samples or remove symbols to force a pass.
5. Record commit SHA, PR, workflow run, artifact ID/hash and exact result for every material validation.
6. Do not raise the progress estimate for documentation or trivial code changes.

### Engineering
1. Never write directly to `main`; work on a branch.
2. Make the smallest complete fix and add regression coverage.
3. Review the complete diff and CI before merge. Merge only when required checks pass.
4. Verify the actual merge SHA and post-merge CI; then update Handoff and Project Status.
5. Default GitHub Actions permissions to read-only. Keep secrets out of code, artifacts, logs and chat.

### Research
1. Compare every candidate with cash, buy-and-hold and appropriate systematic baselines over identical dates, universe, timing, risk and costs.
2. Use chronological walk-forward/OOS evaluation, purging/embargo where labels overlap, an untouched final holdout, uncertainty analysis and family-wise/multiple-testing correction.
3. Include fees, spread, slippage, liquidity, turnover, market impact, exposure and drawdown. Stress assumptions.
4. Famous investors/traders are sources of hypotheses and process, not trade instructions. Require verifiable, time-appropriate evidence.
5. News/social data cannot directly submit orders or increase exposure. Only corroborated, point-in-time, human-reviewed event assessments may reduce risk or block entries.

### Safety
1. **LIVE trading is not authorized.** Any future Live capability requires a separate explicit authorization after independent safety review.
2. Development is Paper/observe-only. No real-money order, transfer or broker-account modification.
3. Missing/stale data or FX, ambiguous order state, unknown fees, corrupted durable state, broker/ledger mismatch or risk-limit breach must fail closed.
4. Alpaca Paper buying power is not the user's MXN strategy capital. Use fresh sourced FX.
5. Never deploy, migrate or initialize a ledger against an unknown volume. Back up and verify SQLite/WAL state first.

## 4. Verified project state (last recorded 2026-11-15)

### What exists
- Core MXN capital policy, FX-aware sizing and persistent milestone state.
- FIFO realized-P&L ledger, Paper activity staging/reconciliation, durable fill bridge and fee resolver.
- Persistent drawdown guard wired into Core; numeric risk thresholds remain prototypes, not approved policy.
- Read-only Alpaca market-data observers, six-service Docker Compose Paper observer, regime observer, Alpaca/Benzinga, GDELT and official-news collectors.
- Quote-to-fill cost telemetry and strategy/reference registries.
- Default-deny Core execution: execution defaults false and requires Paper approval, a traceable approval reference and strategy allowlist.

### What is not proven or approved
- No strategy has passed the current adjusted OOS research acceptance gate. Previous ETF/crypto families produced zero Holm-significant approved candidates.
- The latest ten-year Alpaca SIP/Yahoo comparison completed retrieval but the overall data-quality gate failed; only TLT passed. Seven other ETFs remain review-required. No source is declared truth and no data series may be spliced.
- SOL/USD's historical coverage is below eligibility.
- Crypto/equity cost assumptions are not empirical approvals. Paper quote telemetry is descriptive until representative fills, sample sizes and confidence gates pass.
- Full broker cash/position/activity/fee reconciliation still requires a real read-only Paper audit and sustained evidence.
- The observer image has been built/published, but no persistent host deployment is evidenced. GitHub Actions is not a 24/7 runtime.
- No Paper strategy is approved; no observer orders have been submitted. LIVE remains blocked.

## 5. Immediate work queue

Work in this order; do not skip safety/data gates to reach order execution.

1. Finish review of the outstanding SIP close-condition audit (55 material outlier sessions). Inspect its artifact and determine whether the daily-bar close definition is consistently explained. Do not select a vendor or relax parity thresholds without evidence.
2. Resolve historical price/corporate-action source integrity for the seven review-required ETFs using primary issuer/exchange evidence or an independently licensed source. Tiingo cross-provider validation is prohibited without a specific written exception; a paid plan alone is insufficient.
3. Audit the actual crypto fee model against the current Alpaca maker/taker tier, then separately model spread, slippage and fee timing. Keep all assumptions explicit; do not call them measured costs.
4. Run the read-only Paper account/activity audit with existing Paper credentials through the manual workflow. Never share credentials in chat.
5. Identify the actual existing host, Docker Compose project, named volume and SQLite databases before any deployment or migration. Preserve `rocket_trader_data`; never run `docker compose down -v`.
6. Select a persistent host only after the user understands cost, uptime, region, ARM/x86 compatibility and account requirements. Deploy observer-only, validate backups/restarts, then complete at least a 72-hour soak before expanding.
7. Collect representative Paper quote/fill/fee evidence; complete fee allocation, corrections/bust handling, restart recovery and full-account reconciliation.
8. Validate regime features and connect the selector in recommendation/observe-only mode. Cash/abstain must remain the default.
9. Register new strategy hypotheses only when pre-registered and not a repeated family/window. Require corrected OOS evidence and realistic net-cost stress.
10. Independent readiness review precedes any separate Paper-execution authorization. Live remains unauthorized.

## 6. Server/deployment boundary

The six-service Compose stack is observer/reconciliation infrastructure, not an autonomous trading runtime. It needs Docker Engine/Compose, persistent SQLite storage, Paper credentials entered privately, health monitoring and verified backups. The current runbook deliberately refuses to create replacement ledgers when expected state is missing.

Do not infer a cloud provider from GHCR publication. No host, persistent volume, migration or deployment is considered complete until it is verified on the actual machine. Deployment does not prove profitability or authorize orders.

## 7. Current audit-remediation work

The audit-remediation branch `fix/audit-hardening-2026-11-15` is being used for:
- Removing Adaptive's duplicate in-memory capital policy and exercising Core's persistent allocator in its self-test.
- Adding an offline Integration Gate for PR/main CI while retaining the credentialed read-only Alpaca check for manual dispatch.
- Standardizing boolean environment parsing for Paper/Live safety flags.
- Adding a root `.gitignore` for secrets, SQLite state and local Python artifacts.
- Removing the unrelated DropNode `navegador.py` module.
- Archiving this former long-form handoff in `HISTORY.md`.

These changes are not merged or validated until the PR's checks and post-merge state are confirmed. Do not claim otherwise.

## 8. Progress reporting

Last recorded estimate: **58% engineering/evidence maturity**. Reassess conservatively after material gates. This number is not expected return, profitability, or probability of success. The most important remaining gates are reliable data provenance, empirical execution costs, full broker/ledger reconciliation, persistent deployment, sustained Paper evidence and a robust OOS strategy edge.
