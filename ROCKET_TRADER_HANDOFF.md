# Rocket Trader — Operational Handoff

**Updated:** 2026-11-22 (Claude takeover session: first real Paper audits, close-definition resolution, T05 research negative, forward shadow recorder live)  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Default branch:** `main`  
**Last checkpoint SHA:** `5a8c1a2` (PR #249) — re-verify live `main` SHA before every change  
**Progress (recalibrated rubric, section 8):** 44% toward a complete, validated, operating system. Not a probability of profitability.

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

1. **User actions (cannot be done from assistant sessions):** enable `main` branch protection; identify the 4 JNLC journals; choose/provision the persistent host (then `deploy/rocket_trader_deploy.sh install → init-env → genesis → up`); decide the weekend FX policy (item 1b). See the latest assistant reply's "Tareas para Marco".
1b. **DECIDED 2026-11-23 (user: yes) — weekend/holiday FX:** evidence run `45057338539`: provider `stale=false`, `market_session=weekend`, quote 45 h old; provider (45 min), reconciliation gate (24 h) and strategy-equity (24 h) all reject it, so position reconciliation errors every weekend. Proposed (not implemented, awaiting user): accept the last close only when the provider reports a closed session and `stale=false`, up to 72 h, applied consistently in all three places, with the FX source tagged `CLOSED_MARKET_LAST_CLOSE`; otherwise keep failing closed.
2. Classify the 4 JNLC journals and allocate the 6 CFEE crypto fees to their fills (durable fee-allocation path needs the persistent stack, or a new inception-replay audit with historical FX provenance).
3. Resolve QQQ (2020-09-21, 2022-09-19) and SPY (2018-06-15) dividend records against issuer distribution notices. Portfolio-level research already replicates across both vendors, so this is a provenance item, not a research blocker.
4. Deploy the observer stack on the chosen host (observer-only): run the one-time genesis command (`rocket_trader_paper_genesis_admin.py`, runbook "First deployment"), set `ACTIVITY_SSE_BOOTSTRAP_SINCE` from its attestation, create the cash anchor, verify backups/restarts, 72-hour soak, then multi-week Paper evidence for cost telemetry and full-account reconciliation.
5. Review T05 forward shadow records after 12 months (first strict month: 2026-11 record). Do not change T05 rules.
6. New research only via pre-registration with a new experiment ID. Families already exhausted on the 2016–2026 window: single-asset trend/breakout (T02), mean reversion (T03), daily cross-sectional top-1 momentum, monthly allocation T05, turn-of-month calendar T06a. Untested: T04 pairs (needs shorting → simulation only), T06 calendar/event (needs point-in-time data), T07 intraday (needs trade/quote data), T08 ML (only after a simple baseline passes).
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
| Real Paper accounting evidence | 10% | 55% | 5.5 | First full-account reconciliation RECONCILED (cash, equity, fees, positions) against the real Paper account (run 45225687563, zero post-anchor activity); 6/6 historical fills matched; JNLC = simulator seed; weekend FX policy implemented |
| Persistent deployment | 10% | 55% | 5.5 | Full procedure incl. cash anchor rehearsed on ARM64 = Oracle Ampere (runs 45222927425, 45225687563); Spanish step-by-step tutorial; host chosen (Oracle) but not yet provisioned |
| Empirical execution costs | 10% | 15% | 1.5 | Quoted spreads measured for 8 ETFs + 3 crypto (run 45190318213); fees known; slippage/fills still need Paper |
| Validated strategy edge | 25% | 25% | 6.25 | First pre-registered pass: SMA210 trend overlays pass the drawdown-control test on the independent 2005–2016 sample (run 45819942795), consistent with 2016–2026; no return edge; forward evidence pending; no approval |
| Sustained Paper operation + independent review | 15% | 0% | 0.0 | Not started |
| **Total** | 100% | | **44%** | |

Raise a component only with recorded evidence. Documentation alone never raises it.

**Share that depends on user actions (2026-11-23):** of the remaining 62 points, about **7 points are unlocked directly** by user tasks (persistent host ≈5.5 — deployment component; weekend-FX decision ≈1; JNLC identification ≈0.5) and about **35 more are gated behind the persistent host** (empirical fill costs ≈8.5, remaining Paper accounting ≈5, sustained operation + review 15, plus forward strategy evidence). Branch protection carries no points but is a safety control (it would have blocked the PR #257 mistake).

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
- **Dividend provenance lookup (partial):** a secondary aggregator lists SPY ex-date 2018-06-15 cash dividend USD 1.42 (paid 2018-08-10). This is not a primary issuer record; SSGA's distribution notice is still required before closing the SPY flag. QQQ 2020-09-21 / 2022-09-19 not yet resolved.

### 2026-11-22 (continued) — Fresh-volume genesis

- **Blocker found:** a brand-new host could never start the default accounting configuration. The runtime (correctly) refuses missing databases, and the runbook stated there was no approved bootstrap command. Even after the user chooses a host, deployment was impossible.
- **Fix (this PR):** `rocket_trader_paper_genesis_admin.py`, a one-time, explicitly confirmed genesis. Paper-only; read-only broker calls (`get_account`, `get_all_positions`, `get_orders`); refuses unless the account is ACTIVE with no open positions, no open orders and no fill in the last 48 h (delayed crypto fees posted); refuses if any target DB or `-wal`/`-shm` sidecar exists (cannot overwrite/reset); creates MXN ledger (seed 1,000, milestone 100,000), fill inbox and activity stager; writes an attestation whose timestamp becomes `ACTIVITY_SSE_BOOTSTRAP_SINCE`. Pre-genesis simulator smoke trades are deliberately outside the strategy ledger (they were never strategy trades).
- **Tests:** 9 offline tests (+8 subtests) including the key one — state created by genesis passes the exact runtime preflight validators (`_require_existing_state`, `_require_existing_fill_bridge`, `_require_existing_activity_stager`); refusal cases create nothing; a fake client proves no order method is called. Packaged in the Paper Observer image; added to container, publish and runtime-test workflows; runbook updated (correct Compose service name `rocket-trader-paper-observer`).
- **Not done:** genesis has not been run on any real host (none exists). It does not reconstruct pre-genesis history; that remains out of scope by design.
- **First CI attempt FAILED (PR #251, observer-runtime job):** `ModuleNotFoundError: alpaca` — that workflow does not install alpaca-py. Fixed by making the order filters injectable (`alpaca_order_filters` is still the production default); tests now pass with and without alpaca-py installed.
- **PR #251 merged** as `6cedbae`; post-merge CI green (observer-runtime, container, publish, reconciliation, SSE, stager, integration-gate). The published GHCR image now contains the genesis command. Progress: deployment component 20% → 30% (software path complete; host still missing) → total **35%**.

### 2026-11-22 (continued) — Stop weekly reruns of fixed research

- Removed the weekly `schedule` from equity research v0.1–v0.4, crypto research v0.1–v0.3 and traditional research v0.2 (manual dispatch and PR/push tests kept). Rationale: these re-execute already-recorded families on the same data/holdout every Sunday, which the research rules forbid as new evidence and which only adds noise. Kept schedules: ETF cross-check (data audit), SIP close-condition audit, IEX feed probe, T05 forward recorder.
- **PR #252 merged** as `68c9263` (equity/crypto research offline jobs and integration-gate green).

### 2026-11-22 (continued) — Deployment script, backups and ephemeral rehearsal

- **Second deployment blocker found by reading:** Compose interpolation requires `ACTIVITY_SSE_BOOTSTRAP_SINCE` for every command, including the genesis `run` that produces it — the runbook sequence could not work on a new host. Fixed in `deploy/rocket_trader_deploy.sh` (one-run placeholder, then writes the real value) and in the runbook.
- **Added (this PR):** `deploy/rocket_trader_deploy.sh` (install/init-env/genesis/up/status/backup/restore-test; never `down -v`, hidden key entry, `.env` 600), `deploy/sqlite_backup.py` (SQLite online-backup API, single-file rollback-journal copies, SHA-256 manifest, restore into scratch dir + runtime preflight validators), `deploy/sanitize_health.py` (public logs show only booleans/ints), and workflow `rocket-trader-deployment-rehearsal.yml` (manual: genesis with real read-only Paper checks → six services → health → backup/restore → restart survival → second genesis must be refused).
- **Bugs caught by tests before CI:** backup copies inherited WAL mode, so a later change could sit in a `-wal` sidecar invisible to the hash check — copies are now converted to rollback-journal single files; a byte-level "source unchanged" test was wrong because SQLite checkpoints by itself — now compares logical dumps. 5 backup tests pass.
- **Rehearsal attempt 1 FAILED (run `45054097933`, on the PR branch):** `compose build` inside `genesis` also requires `ACTIVITY_SSE_BOOTSTRAP_SINCE` (only the `run` had the placeholder). Exactly the class of host-only bug the rehearsal exists to catch. Fixed by exporting the placeholder for the whole genesis invocation. Genesis itself never ran, so nothing was created and no broker call was made.
- **Rehearsal attempt 2 — PARTIAL (run `45054221033`):** genesis with real read-only Paper checks PASSED (ACTIVE, 0 positions, 0 open orders, 0 fills in 48 h); all 6 services started; 4/6 healthy within 12 min (SSE, regime, Alpaca news, official news); backup of 11 files and restore test with runtime preflight PASSED. Unhealthy: (a) paper-observer — the activity stager pulls the account's *entire* history, so pre-genesis smoke-test activity (6 FILL, 6 CFEE incl. 3 `BLOCKED_INCOMPLETE_CRYPTO_FEE`, 1 JNLC) stayed pending forever; position reconciliation also reported `positions_match=false` (cause not visible because the log sanitizer dropped `status`/`error_type`); (b) gdelt-news (cause to be read next run).
- **Fix (same PR):** explicit genesis boundary stored once in the stager DB (`activity_stager_meta.genesis_at`, set by genesis before any staging, cannot be set late or twice). Activities strictly before it are kept immutably but classified `PRE_GENESIS_EXCLUDED`; date-only rows (JNLC) count as pre-genesis only if their whole UTC day ended before genesis; unparseable timestamps keep normal fail-closed classes. The FILL activity reconciler skips `PRE_GENESIS_EXCLUDED`. Without a boundary, behaviour is unchanged. Sanitizer now also prints enum-like `status`/`error_type` codes. 6 new stager tests (25 total), genesis test asserts the boundary.
- **Rehearsal attempt 3 (run `45055806741`) — boundary confirmed, two more findings:** `pre_genesis_excluded=13` (all smoke-test history excluded explicitly). Paper observer still unhealthy for three distinct reasons: (1) **bug** — account activity syncs every 900 s but health required every component's heartbeat ≤120 s, so it showed `status=HEALTHY, healthy=false` most of the time; fixed with a per-component liveness window (900 + 300 s) and a regression test; (2) `position_reconciliation.error_type=FXProviderError` on a Sunday — likely the USD/MXN quote is older than the 45-minute limit while FX markets are closed; a diagnostic step was added before changing any accounting policy; (3) **by design** the default configuration never reports healthy until the USD cash ledger anchor and full-account reconciliation are enabled on the persistent host (PR #194 decision). GDELT unhealthy — error text now shown (public data only, IDs masked). Backup/restore passed again (11 files).
- **Rehearsal gate changed:** it now gates on deployment mechanics (genesis, backup/restore, restart with 6/6 running, second genesis refused) and reports service health without gating, because full health is unattainable on an ephemeral runner by design.
- **Rehearsal attempt 4 — PASSED (run `45057338539`, PR #253 head):** genesis (real read-only Paper checks) ✓; 6/6 services started; backup (11 files) + restore with runtime preflight ✓; `down` + `up` with 6/6 running ✓; second genesis refused ✓. Health (reported, not gated): account activity now healthy (fix confirmed), `pre_genesis_excluded=13`; regime observer `CASH_ABSTAIN` with `INSUFFICIENT_DATA` right after start (correct). Remaining unhealthy causes, evidenced: **FX** — provider returned `result=success`, `stale=false`, `market_session=weekend`, quote age 45.0 h, rejected by the 45-minute rule (`USD/MXN quote is stale for this fill (162127s)`), so position reconciliation errors every weekend although crypto trades 24/7; **GDELT** — HTTP 429 on all 5 topics from the shared GitHub runner IP (provider rate limit, not a code defect; re-check on the real host); **BLS** — HTTP 403 (official-news still healthy via BEA/Fed). By design the observer also stays unhealthy until the cash ledger anchor/full-account reconciliation is enabled on the persistent host.
- **PR #253 merged** as `0916977`: deploy script, backups, rehearsal, genesis boundary, per-component heartbeat window. Progress: deployment 30% → 45% → total **36%**. Weekend-FX policy left as an explicit user decision (queue item 1b) rather than changed unilaterally.

### 2026-11-23 — Session continued (user away; user tasks still pending)

- **Quoted-spread measurement study pre-registered (this PR):** `COSTS_SPREAD_STUDY_PREREGISTRATION_v0_1.md`, `COSTS-SPREAD-v0.1`. Free SIP historical quotes for the 8 ETFs (40 sessions × 6 NY times) and Alpaca crypto quotes (hourly, 14 days) measure the half-spread a small marketable order faces versus the research assumptions (ETF 2.5 bps, crypto 10 bps per side). Measures the spread component only; fees/slippage/fills still require Paper evidence. 5 offline tests. Result appended after the post-merge run.
- **T06 turn-of-month research pre-registered (separate PR):** `RESEARCH_T06_TURN_OF_MONTH_PREREGISTRATION_v0_1.md`, `T06-TOM-v0.1`. First run of the calendar tranche; post-publication out-of-sample (effect published 1987–88); TOM = last session + first 3 sessions; circular-shift permutation test, Holm family 9 (8 ETFs + basket), fold/holdout/2x-cost criteria, two-source replication. 4 offline tests (mask correctness, planted-effect detection vs null, costs, research-only flags).
- **PR #255 merged** as `d77a33e`. **Spread study run 1 (`45187950954`) — crypto VALID, ETF INVALID (measurement defect):** crypto half-spread median/p90 (bps): BTC/USD 1.35/1.81, ETH/USD 1.33/1.83, SOL/USD 4.42/5.76 (336 hourly samples each, 100% valid) — all far below the 10 bps assumption (`ASSUMPTION_COVERS_P90`). ETF valid shares collapsed for the most liquid funds (SPY 2%, TLT 0%, QQQ 11%) because one multi-symbol request was capped at 10,000 quotes and liquid ETFs exceed that in 60 s. Fixed (this PR): one request per symbol, newest first, limit 100; regression test. ETF numbers from run 1 must not be cited.
- **Weekday rehearsal (run `45187395850`, Monday, main `d77a33e`) — confirms the weekend-FX diagnosis:** FX `market_session=open`, age 0.3 h, `quote_for_fill=OK`; position reconciliation `MATCHED`, `positions_match=true`, status `POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE` (expected until the cash ledger is enabled). Account activity, ledger, crypto, equity and trading components healthy. Genesis, backup/restore, restart and second-genesis refusal all passed again. GDELT still 429 from GitHub IPs; BLS 403 (likely needs an identified contact User-Agent like SEC — candidate small change).
- **PROCESS VIOLATION (assistant) — PR #257 merged with a failing check:** `offline-tests` failed (`ModuleNotFoundError: alpaca` — the spread workflow's offline job installed only the Yahoo requirements, while the new regression test imports alpaca-py), and the merge command did not gate on check conclusions. Merged as `7c33016`. Corrected immediately in the next PR (install alpaca requirements in the offline job). Rule reinforced: merge commands must abort if any check concluded `failure`; branch protection (user task) would have blocked this mechanically.
- **PR #258 merged** as `6917a85` (all checks green; merge now gated by a script that refuses any non-green check).
- **T06 turn-of-month result — NEGATIVE, replicated:** run `45189854623` on `ba17cf5` (Alpaca SIP and Yahoo; window 2016-12-01 → 2026-10-30, holdout from 2024-11-04). **0/9 pre-screen passes on both sources.** Direction is consistent: TOM-minus-other daily mean positive for 8/9 instruments (+1.0 to +12.2 bps/day), holdout difference positive for all 8 equity instruments (+8 to +18 bps), TLT negative. Best Holm p: EEM 0.105 (Alpaca) / 0.112 (Yahoo). TOM-only strategy (19% exposure) cuts max drawdown (basket −9% vs −27%) but has lower Sharpe than buy-and-hold (basket 0.43 vs 0.88). Not an edge under the pre-registered gates; do not re-run with other windows on the same data.
- **Spread study run 2 (`45190318213`, corrected) — VALID:** 100% valid samples for all 11 symbols. Median/p90 half-spread (bps): SPY 0.13/0.21, QQQ 0.20/0.32, IWM 0.18/0.37, DIA 0.29/0.59, GLD 0.29/0.53, EFA 0.48/0.49, TLT 0.62/0.65, EEM 0.80/0.86; BTC 1.35/1.80, ETH 1.33/1.83, SOL 4.44/5.77. All `ASSUMPTION_COVERS_P90`. Research spread assumptions (2.5 / 10 bps) are conservative; the negative research results are therefore not caused by inflated spread costs — the binding constraint is the absence of a robust signal. Slippage beyond the quote and fills remain unmeasured.
- **Progress:** Paper accounting 35% → 40% (position reconciliation MATCHED in rehearsal), execution costs 5% → 15% (quoted spreads measured) → total **38%**.

### 2026-11-23 (afternoon) — User decisions received and acted on

- **Branch protection DONE by user:** repository ruleset "Protect main" (active, no bypass actors) on the default branch: pull request required, `integration-gate` required status check, non-fast-forward and deletion blocked. Verified via `GET /rulesets` (the classic protection endpoint returns 404 because rulesets are used instead). Assistant merges now go through the ruleset as well as `/tmp/safe_merge.sh`.
- **JNLC identified by user:** the Paper dashboard lists a single JNLC: "Journal cash between accounts", +USD 100,000.00, 2026-09-28 — the simulator's opening seed. Classification: **Paper simulator seed, not user capital, not profit.** The four JNLC events seen on the Activity SSE stream were repeated notifications of this single journal (REST staging found exactly 1). It is pre-genesis and already `PRE_GENESIS_EXCLUDED`. Closed.
- **Weekend/holiday FX policy APPROVED by user and implemented (this PR):** the FX provider accepts a quote older than 45 min only if the provider reports `market_session` in {weekend, holiday, closed}, did not flag it stale, and it is ≤72 h old; such quotes are tagged `CLOSED_MARKET_LAST_CLOSE` in the FX source (persisted with every fill). The same tag extends the window to 72 h — and only for tagged quotes — in the position reconciliation gate, strategy-equity metrics and Core position budgeting (`max_fx_age_for` in `rocket_trader_currency.py`). Untagged quotes keep 45 min / 24 h. 10 new tests; integration gate PASS.
- **Hosting decision by user: Option A (Oracle Cloud Always Free, Ampere A1 ARM).** Next: verify the stack builds/runs on ARM64 (rehearsal on a GitHub `ubuntu-24.04-arm` runner) and give the user a step-by-step OCI tutorial. Known risk: Oracle reclaims Always Free instances that look idle for 7 days; mitigation is upgrading the tenancy to Pay As You Go (Always Free usage stays free), never artificial load.
- **Capital analysis REOPENED by user:** to be delivered as `CAPITAL_FEASIBILITY_ANALYSIS_v0_1.md`.
- **PR #260 merged** as `a3a0d87` through the ruleset (10 checks green).
- **ARM64 rehearsal option (this PR):** the deployment rehearsal accepts `runner=ubuntu-24.04-arm` (free for public repositories) to prove the stack builds and runs on the same CPU architecture as Oracle Ampere A1. Result appended after the run.
- **Capital feasibility analysis delivered (this PR):** `CAPITAL_FEASIBILITY_ANALYSIS_v0_1.md` + `research/capital_feasibility_calc_v0_1.py`. Findings: MXN 1,000 ≈ USD 53.8 is operable (no account minimum; USD 1 fractional minimum) but coarse; ~0.22%/yr fixed drag from penny-rounded regulatory fees; precise 8-ETF rebalancing needs ≈MXN 7,500; the MXN 100,000 earned milestone takes 25–94 years from MXN 1,000 at 5–20% net returns (driven by operating capital, not the seed). Options A/B/C presented to the user; no policy change made. Engineering gaps recorded: fractional/notional order path, per-asset minimum checks, penny-fee modelling.
- **ARM64 rehearsal PASSED (run `45222927425`, main `aa5f750`, runner `aarch64` Ubuntu 24.04.5):** genesis ✓, position reconciliation MATCHED ✓, backup (11 files) + restore preflight ✓, restart 6/6 running ✓, second genesis refused ✓. The stack is compatible with Oracle Ampere A1. GDELT still 429 on GitHub IPs.
- **Deploy script gains `anchor` and `enable-cash-ledger` (this PR):** `anchor` refuses unless the Activity SSE service is healthy, then runs the existing read-only cash-anchor admin; `enable-cash-ledger` sets `ROCKET_TRADER_CASH_LEDGER_ENABLED=true` and recreates the observer. The rehearsal now also runs anchor → enable → waits for `account_reconciliation_complete` (interval 120 s in rehearsal) and reports it (not gated). Result appended after the run.
- **Full-account reconciliation RECONCILED for the first time (run `45225687563`, ARM64, main `bd12a91`):** after genesis → up → `anchor` → `enable-cash-ledger`, the observer reported `healthy=True` with `account_evidence_status=RECONCILED`, cash `RECONCILED`, equity `RECONCILED`, fee `RECONCILED` (0 fee activities, 0 pending allocations), positions `MATCHED`, `unsupported_activity_count=0`, `paper_buying_power_used_as_capital=false`. Caveat: zero activity occurred after the anchor, so this proves the chain mechanics end-to-end, not reconciliation of a busy account; that evidence must come from the persistent host over weeks. The only unhealthy service was GDELT (429 on GitHub IPs).
- **Oracle tutorial (Spanish) added:** `DESPLIEGUE_ORACLE_TUTORIAL_ES.md` — account, A1 VM (2 OCPU / 8 GB, Always Free label), Cloud Shell SSH, install → init-env → genesis → up → anchor → enable-cash-ledger, daily backup cron, risks (idle reclamation → PAYG, out of capacity, regenerating Paper keys requires updating GitHub secrets).
- **Progress:** Paper accounting 40% → 55%, deployment 45% → 55% → total **40%**.

### 2026-11-26 — Autonomous session (user tasks still pending: Oracle deployment, capital option)

- **CORRECTION — T06 partially repeated earlier work:** the T06 pre-registration (2026-11-23) stated the calendar tranche had "never been run". That was wrong. On 2026-11-10 the unmerged branch `research/calendar-seasonality-next-open` ran equity research v0.5 (97 hypotheses, including `turn_of_month_last1_first3` — the same −1/+3 window — versus same-asset buy-and-hold on Yahoo 10y; 0 Holm-significant; recorded only in `HISTORY.md` line ~617) and crypto v0.4 (25 hypotheses, 0 pass). T06 differed in statistic (TOM vs non-TOM difference, circular-shift permutation) and added Alpaca replication, and reached the same conclusion, but it was not a new family. **Lesson (mandatory):** before pre-registering, search `HISTORY.md`, this journal and every unmerged `research/*` branch for the hypothesis name/window.
- **Unmerged branches reviewed:** 10 branches have no PR. Notable: `feat/durable-mxn-strategy-equity-snapshots` (11 commits, 72 behind) records a strategy-equity mark into the append-only ledger on every 60 s position reconciliation (~1,400 events/day) — not ported, because current `main` (PR #198) chose a calculator with explicit session baselines; the durable-baseline producer will be built on that design instead. The others are superseded (200+ commits behind) or empty.
- **Branch cleanup blocked for the assistant:** deleting branches via REST (`DELETE git/refs`) and `git push --delete` are both refused by the session proxy. 261 of 273 branches belong to closed/merged PRs (commits stay reachable through `refs/pull/*`). A one-click maintenance workflow for the user is added in a separate PR.
- **T05 independent historical sample pre-registered (this PR):** `RESEARCH_T05_HIST_2005_2016_PREREGISTRATION_v0_1.md` — the never-used window 2005-11 → 2016-11-18 (includes 2008), unchanged T05 rules, plus a pre-registered drawdown-control test for the two SMA210 trend rules (DD ≥10 pp smaller, CAGR ≤3 pp/yr lower, Sharpe ≤0.05 lower). Yahoo only (declared limitation). 4 offline tests.
- **News observer politeness (this PR):** GDELT now stops the current cycle on HTTP 429 instead of firing the remaining topics (they keep their last health and retry next cycle); BLS gets the same identified contact User-Agent as SEC when `SEC_CONTACT_EMAIL` is configured (`init-env` now asks for it, optional). 3 new tests.
- **User-run maintenance workflow (this PR):** `repo-maintenance-delete-merged-branches.yml` — manual, `dry_run=true` by default; deletes only branches of closed/merged PRs with no open PR; never `main`/`forward-evidence`.
- **PR #266 (T05-HIST prereg) and PR #267 (news politeness + cleanup workflow) merged** (`6715841`, `0e8587b`), all checks green.
- **T05-HIST-2005-2016 result — FIRST PRE-REGISTERED PASS (drawdown control), run `45819942795` on `6715841` (Yahoo, evaluation 2006-11-22 → 2016-11-17, holdout from 2014-11-20):**
  - Equal-weight benchmark: CAGR 6.71%, max DD −41.9%, Sharpe 0.49.
  - `sma210_trend_equal_weight`: CAGR 4.7%, max DD −14.5%, Sharpe 0.53 → DD −27.5 pp, CAGR −2.0 pp/yr, Sharpe +0.04 → **PASS**.
  - `sma210_trend_inverse_vol`: CAGR 5.8%, max DD −11.2%, Sharpe 0.665 → DD −30.7 pp, CAGR −0.9 pp/yr, Sharpe +0.175 → **PASS**.
  - Return family (replication of T05): **0/5** pre-screen passes (holdout 2014–2016 trend rules lagged; best holdout excess inverse-vol +0.4%). No return edge.
  - Interpretation: across two independent decades (2006–2016 pre-registered; 2017–2026 observed) the trend overlays roughly cut maximum drawdown by 60–75% at a small CAGR cost — a **risk-control** property consistent with the survival objective, not an alpha source. Status: candidate risk overlay for **forward shadow + Paper validation review**; not approved for orders. Limitations: single vendor (Yahoo) for this window; 0% cash yield assumed (conservative); MXN 1,000 implies fractional orders.
- **Progress:** strategy component 10% → 25% (first pre-registered pass on independent data) → total **44%**.
- **Allocation sleeve executor added (this PR) — Paper only, DRY_RUN by default:** `rocket_trader_allocation_executor.py` + monthly workflow `rocket-trader-allocation-sleeve.yml` (days 1–5, 15:05 UTC). Implements the candidate overlay `sma210_trend_inverse_vol` in an isolated sleeve: stateless, rebuilt from its own filled orders (`client_order_id` prefix `rt-alloc-`) and FEE activities since the sleeve start; fractional DAY market orders (notional buys, quantity sells), USD 1 minimum, sells first, buys capped by sleeve cash, idempotent client IDs per day, hard cap USD 100 sleeve capital, fail-closed on any broker/sleeve inconsistency. It submits only if the user sets repository variables `ROCKET_TRADER_ALLOCATION_MODE=PAPER_EXECUTE` and `ROCKET_TRADER_ALLOCATION_APPROVAL_REF` (this is the explicit Paper-execution approval step; LIVE stays impossible). 10 offline tests (gates, dry-run never submits, idempotency, exits, inconsistency, leverage). This closes the "no small-capital order path" gap for Paper without changing Core's bracket path.
- **PR #269 merged** (`4b98b3f`). **First real dry run** (run `45821039495`, Thanksgiving, market closed): signal 2026-10-30; planned buys DIA 8.80, EFA 8.29, IWM 6.68, QQQ 4.88, SPY 8.78 USD (≈69% invested, 31% cash; EEM/GLD/TLT below trend) — matches the forward-shadow record; `submitted=0`, blocked by `MODE_NOT_PAPER_EXECUTE` and `NO_VALID_APPROVAL_REFERENCE` as designed.
- **Sleeve evidence log (this PR):** each sleeve run appends its public summary (no order IDs) to `forward-evidence/forward/sleeve/<UTC timestamp>.json`, never overwriting, so the monthly record survives artifact expiry.
