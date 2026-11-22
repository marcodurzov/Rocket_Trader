# Rocket Trader — Operational Handoff

**Updated:** 2026-11-22 (Claude takeover session: first real Paper audits, close-definition resolution, T05 research negative, forward shadow recorder live)  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Last checkpoint SHA:** `5a8c1a2` (PR #249) — re-verify live `main` SHA before every change  
**Progress (recalibrated rubric, section 8):** 34% toward a complete, validated, operating system. Not a probability of profitability.

## 1. Resume protocol

Before acting, inspect the live default-branch SHA, open PRs, CI, recent workflow artifacts and the exact target files. This handoff can become stale. Read in this order:

1. `ROCKET_TRADER_BASELINE_DECISIONS_v0_2.md` — binding user decisions.
2. `ROCKET_TRADER_PROJECT_STATUS_v0_1.md` — implementation and evidence status.
3. `ROCKET_TRADER_INVESTMENT_RESEARCH_FRAMEWORK_v0_1.md` — research acceptance rules.
4. `PAPER_OBSERVER_DEPLOYMENT.md`, `PAPER_REGIME_OBSERVER.md`, `PAPER_EXECUTION_COST_TELEMETRY.md`, `NEWS_EVENT_ASSESSMENT.md`, `REFERENCE_BENCHMARK_HARNESS.md`.
5. `ROCKET_TRADER_SERVER_DEPLOYMENT_PLAN_v0_1.md` — host requirements and deployment gates.
6. `ROCKET_TRADER_HOSTING_OPTIONS_v0_1.md` — current zero-budget/low-cost provider review.
7. `ROCKET_TRADER_CRYPTO_COST_REVIEW_v0_1.md` — Alpaca fee schedule and all-in crypto cost methodology.
8. `HISTORY.md` — full archived handoff, experiments, failed approaches and chronology.

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

## 5. Immediate work queue (refreshed 2026-11-22)

Done this session (see journal): SIP close-condition review (resolved as close-definition difference); crypto cost-model reconciliation (already decomposed correctly); first real read-only Paper audits (6/6 fills matched); T05 allocation research (negative, replicated); forward shadow recorder (live, monthly).

1. **User actions (cannot be done from assistant sessions):** enable `main` branch protection; choose/provision the persistent host; download and keep the private Paper audit artifacts. See the latest assistant reply's "Tareas para Marco".
2. Classify the 4 JNLC journals and allocate the 6 CFEE crypto fees to their fills (durable fee-allocation path needs the persistent stack, or a new inception-replay audit with historical FX provenance).
3. Resolve QQQ (2020-09-21, 2022-09-19) and SPY (2018-06-15) dividend records against issuer distribution notices. Portfolio-level research already replicates across both vendors, so this is a provenance item, not a research blocker.
4. Deploy the observer stack on the chosen host (observer-only), verify backups/restarts, 72-hour soak, then multi-week Paper evidence for cost telemetry and full-account reconciliation.
5. Review T05 forward shadow records after 12 months (first strict month: 2026-11 record). Do not change T05 rules.
6. New research only via pre-registration with a new experiment ID. Families already exhausted on the 2016–2026 window: single-asset trend/breakout (T02), mean reversion (T03), daily cross-sectional top-1 momentum, monthly allocation T05. Untested: T04 pairs (needs shorting → simulation only), T06 calendar/event (needs point-in-time data), T07 intraday (needs trade/quote data), T08 ML (only after a simple baseline passes).
7. Independent readiness review precedes any separate Paper-execution authorization. Live remains unauthorized.

## 6. Server/deployment boundary

The six-service Compose stack is observer/reconciliation infrastructure, not an autonomous trading runtime. It needs Docker Engine/Compose, persistent SQLite storage, Paper credentials entered privately, health monitoring and verified backups. The current runbook deliberately refuses to create replacement ledgers when expected state is missing. Current zero-budget candidate: OCI Always Free Ampere A1 (2 OCPU / 12 GB total allowance), subject to home-region capacity and documented idle-instance reclamation; see `ROCKET_TRADER_HOSTING_OPTIONS_v0_1.md`. For reliable continuous uptime, OVHcloud advertises VPS-1 from USD 4.54/month (2 vCPU/4 GB/40 GB, disk below our 60 GB estimate) and VPS-2 from USD 8.50/month (4 vCPU/8 GB/75 GB, safer fit). Confirm checkout, region and tax; do not use OVH Local Zone because its current page says Docker is unsupported there.

Do not infer a cloud provider from GHCR publication. No host, persistent volume, migration or deployment is considered complete until it is verified on the actual machine. Deployment does not prove profitability or authorize orders.

## 7. Current audit-remediation state

PR #245 was squash-merged into `main` as `3d032e6fd5da9babfdab1cb958871e1b66987ec3`. Its latest PR head passed nine workflow jobs: Engine and Capital Regression, Paper Execution Safety, static checks, Paper Observer Runtime Tests, Integration Gate (offline), Docker Container Build/non-root checks, Durable Activity SSE tests, Capital Policy Tests and Runtime Freshness Tests. The Paper Activity Audit job was skipped by its event condition; no broker account audit was run. No order, account mutation, credential access, host deployment or volume migration occurred.

The merged changes include:
- Removing Adaptive's duplicate in-memory capital policy and exercising Core's persistent allocator in its self-test.
- Adding an offline Integration Gate for PR/main CI while retaining the credentialed read-only Alpaca check for manual dispatch.
- Standardizing boolean environment parsing for Paper/Live safety flags.
- Adding a root `.gitignore` for secrets, SQLite state and local Python artifacts.
- Removing the unrelated DropNode `navegador.py` module.
- Adding `ROCKET_TRADER_HOSTING_OPTIONS_v0_1.md` with current OCI/Hetzner/Google Cloud comparison and deployment prerequisites.
- Adding `ROCKET_TRADER_CRYPTO_COST_REVIEW_v0_1.md` to separate published Alpaca fees from spread/slippage/impact assumptions.
- Renaming the extensionless traditional-research guide to `.md`.
- Archiving this former long-form handoff in `HISTORY.md`.

The separate PR #244 close-condition audit branch had its identical weekly schedule removed; it now runs only on relevant PR/push changes or manual dispatch. This avoids repeating a fixed historical sample every Sunday. Its 55-target diagnostic still requires its own artifact review. The target file contains 55 rows across seven symbols; no PR #244 audit artifact/run has been verified yet.

The first PR #245 CI attempt caught a malformed import, an outdated `CapitalPolicy` test import and a stale positive-news assertion. All three were corrected; the latest nine workflow jobs passed. The post-merge commit's full push-triggered workflow status has not yet been verified. Do not infer a successful post-merge run from the PR checks.

## 8. Progress reporting

From 2026-11-22 progress uses this fixed rubric (weight × completion). The earlier 58% measured engineering maturity only and is superseded; do not mix the two scales.

| Component | Weight | Completion | Points | Evidence |
|---|---|---|---|---|
| Safety, capital policy, accounting code foundation | 20% | 90% | 18.0 | Default-deny execution, MXN ledger, drawdown guard, fail-closed state, 574+ tests |
| Data provenance | 10% | 75% | 7.5 | SIP history, close-definition resolved (run 45038550878), 6/8 ETFs cumulative parity; QQQ/SPY dividends open |
| Real Paper accounting evidence | 10% | 35% | 3.5 | Runs 45050365468/45050961817: 6/6 fills matched; fees unallocated; JNLC unclassified |
| Persistent deployment | 10% | 20% | 2.0 | Image published, runbook and host options; no host |
| Empirical execution costs | 10% | 5% | 0.5 | Telemetry code only; no representative fills |
| Validated strategy edge | 25% | 10% | 2.5 | Research infrastructure + forward recorder; 0 approved candidates |
| Sustained Paper operation + independent review | 15% | 0% | 0.0 | Not started |
| **Total** | 100% | | **34%** | |

Raise a component only with recorded evidence. Documentation alone never raises it.

## 9. Change journal — append every attempt, success or failure

Each entry: date, owner, PR/run IDs, what was tried, exact result, decision, and what must not be repeated.

### 2026-11-22 — Claude session takeover (other assistant on standby)

- **Repository state at takeover:** `main` = `24a1f54`. Nine commits after PR #245 (`d745f8d` … `24a1f54`, docs/handoff/hosting updates) were pushed **directly to `main` without a PR**, contrary to Engineering rule 1. Content reviewed; no code was changed by them. Do not repeat: every change goes through a PR.
- **Branch protection attempt — FAILED (environment limit):** `PUT /branches/main/protection` (require PR + `integration-gate` check, enforce admins) returned HTTP 403 "Write access to this GitHub API path is not permitted through this proxy". Assistant sessions cannot configure protection; the user must do it in GitHub settings. Until then the no-direct-push rule is honor-system only.
- **First real read-only Paper account audit — RAN:** workflow `rocket-trader-paper-activity-audit.yml` dispatched by the assistant (admin token can dispatch) on `main` `24a1f54`, run `45050365468`, inputs BTC/USD, orders window 2026-11-11T04:55Z–05:05Z, fee window 2026-11-11T04:55Z → run start. Exit code 2 = by design "query completed, fills matched, fees unresolved" (code path `return 2 if fills_matched`). Activity SSE probe over 2026-11-11T04:55Z → 2026-11-22T17:36Z: HTTP 200, 6 events (TRD 2 fills, CFEE 2, JNLC 2), 0 corrections, 0 busts, 0 dropped-message comments. The second JNLC journal was not in earlier notes and remains pending capital classification (never auto-treat as deposit/profit). Detailed per-order report is only in the artifact/step summary, which this environment cannot download (artifact blob host blocked by the session proxy). No order, cancel or account mutation occurred.
- **SIP close-condition audit (55 material-outlier sessions) — RESOLVED as close-definition difference:** scheduled run `45038550878` on `24a1f54`, artifact `14761025480` (sha256 `083da9d5…f23b`): `ok=true`, 55/55 results, 0 errors; `CLOSES_AGREE` 10, `POSTMARKET_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED` 42, `PRE_CLOSE_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED` 3; `all_close_gaps_have_observed_preclose_or_official_close_pattern=true`. Interpretation: Alpaca SIP daily-bar close can be the last eligible post-market/pre-close trade, while Yahoo uses the official closing price. The single-day raw divergences are a definition mismatch, not corrupted bars. This does not designate either vendor as truth.
- **10-year ETF cross-check re-run — same verdict, better understood:** scheduled run `45035686786`, artifact `14758674899` (sha256 `c5bf76be…ac63`), window 2016-11-20 → 2026-11-20, SIP, 408 corporate actions. `all_diagnostic_gates_pass=false`, TLT passes. DIA/EEM/EFA/GLD/IWM fail only single-day/normalized-close gates while **10-year cumulative adjusted-return difference is −3.1 to +0.0 bps** — consistent with the close-definition finding. Remaining genuine issues: QQQ cumulative +176.9 bps with unresolved dividend records; SPY −158.0 bps with unresolved dividend record plus close-definition spikes. Gates were NOT relaxed.
- **Crypto cost model reconciliation — VERIFIED, no code change:** crypto research v0.1–v0.3 already decompose cost as 25 bps taker fee + 10 bps half-spread + 5 bps slippage = 40 bps/side all-in, matching `ROCKET_TRADER_CRYPTO_COST_REVIEW_v0_1.md`. The label is correct; the components remain assumptions, not measurements.
- **Evidence durability fix (this PR):** artifacts had 14/30-day retention, so immutable evidence from 2026-11-10/11 would expire in December, violating Truth rule 4. All upload steps now keep 90 days (GitHub maximum for public repos). The Paper audit now prints an aggregate-only `ROCKET_TRADER_PAPER_AUDIT_SUMMARY` JSON line to the public log (no order/activity/account IDs) so results survive and can be read without artifact access. Regression test added.
- **Inconsistency noted:** the previous entry says PR #244's weekly close-audit schedule was removed, but `rocket-trader-sip-close-condition-audit.yml` on `main` still has `cron: "30 7 * * 0"` (it ran today). Left as is for now; the audit is cheap and its result is now resolved.
- **PR #246 merged** as `dc9a466` (all 13 triggered PR checks green; Paper audit job skipped by design on PR).
- **T05 monthly allocation research pre-registered (this PR):** `RESEARCH_T05_ALLOCATION_PREREGISTRATION_v0_1.md`, experiment `T05-ALLOC-MONTHLY-v0.1`, family of 5 (inverse-vol, 210-SMA trend EW, dual momentum top-3 12-1, 10% vol-target EW, trend + inverse-vol) vs drifting monthly equal-weight benchmark, Holm alpha 0.05, 2x/3x cost stress, 4/5 fold consistency, mandatory two-source replication (Alpaca SIP and Yahoo). Registered in git before any live run. Offline tests: 9 passed locally (no-lookahead, history guard, drift, costs, no leverage, fail-closed coverage). Results will be appended after the post-merge `workflow_dispatch` run; do not re-tune parameters on the result.
- **PR #247 merged** as `6f6f1d4`; checks green (offline-tests, integration-gate, static-check).
- **T05 historical result — NEGATIVE, replicated:** run `45051199433` on `6f6f1d4` (both matrix jobs green). Evaluation 2017-11-24 → 2026-11-19, holdout from 2025-02-04. Equal-weight benchmark: holdout +21.9%, full Sharpe 0.70, full max DD −27.3%. Holdout excess / Holm p / positive folds (Alpaca SIP): dual momentum +1.4% / 1.000 / 3; inverse-vol −0.8% / 1.000 / 2; SMA210 trend EW −3.9% / 1.000 / 1; trend+inverse-vol −5.7% / 1.000 / 1; vol-target −7.7% / 1.000 / 1. **0/5 pre-screen passes on Alpaca and 0/5 on Yahoo**; figures match to ±0.1 pp across sources, which also shows the QQQ/SPY vendor differences are immaterial at portfolio level. Secondary (not pre-registered, not a pass): SMA210 trend rules cut full-period max DD to about −11% (vs −27.3%) with CAGR about 6.5% and Sharpe 0.70–0.72 (benchmark 0.70). **Do not rerun T05 with new parameters on this window.**
- **Forward shadow test started (this PR):** `RESEARCH_T05_FORWARD_SHADOW_PREREGISTRATION_v0_1.md`; monthly scheduled recorder writes immutable month-end target weights to the append-only `forward-evidence` branch. First review after 12 records. This is the zero-cost way to accumulate genuinely out-of-sample evidence without a persistent host.
- **Second real Paper audit (wider window):** run `45050961817` on `dc9a466`, BTC/USD orders 2026-11-10 → 2026-11-22: `order_count=6`, `matched_order_count=6`, `fill_reconciliation_status=ALL_ORDERS_MATCHED`, `fee_activity_count=3` (all `UNCLASSIFIED` account-wide CFEE candidates), `fee_reconciliation_status=UNRESOLVED`, status `FILLS_MATCHED_FEES_UNRESOLVED`. Activity SSE since 2026-11-10: 16 events (TRD 6 fills, CFEE 6, JNLC 4), 0 corrections/busts/drops. Open questions: classify the 4 JNLC journals; allocate the 6 CFEE to fills via the durable fee-allocation path.
- **Idea evaluated and deferred:** reconstructing the full accounting chain from account inception in an ephemeral runner. Not supported by current design (cash anchor = current snapshot; historical fills need timestamp-valid USD/MXN FX). It would be a new feature (inception replay + historical FX provenance); not started.
- **PR #248 merged** as `8f20b3b`. **First recorder dispatch FAILED:** run `45051631543`: `DIA: only 753 daily bars; minimum 900 for 3 requested years` — `fetch_daily_bars()` has a 900-session floor, so a 3-year request can never pass. Fixed by requesting 4 years (~1,004 sessions) plus a regression test (this PR). Nothing was written to `forward-evidence` by the failed run.
- **PR #249 merged** as `5a8c1a2`. **Recorder re-run SUCCEEDED:** run `45051862454` wrote `forward/t05/2026-10.json` (signal session 2026-10-30, record sha256 prefix `fdaa2f3bae7c2d17`) to the new orphan branch `forward-evidence`. Weights at that signal: dual momentum EEM/IWM/QQQ 1/3 each; SMA210 trend EW holds DIA/EFA/IWM/QQQ/SPY (37.5% cash; EEM, GLD, TLT below trend); vol-target EW 86.6% invested. Because this record was written on 2026-11-22 (mid-November), the strict forward evaluation starts with the 2026-11 record; the 2026-10 record is kept but flagged as written late.
- **Progress rubric introduced (section 8): 34%.** The prior 58% scale is retired, not "lost progress".
