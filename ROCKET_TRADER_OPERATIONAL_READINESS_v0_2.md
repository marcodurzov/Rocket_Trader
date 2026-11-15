# Rocket Trader — Operational Readiness v0.2

**Reviewed:** 2026-11-15  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Code baseline reviewed:** a8095a767f02377b19b1950a08fd73e154388235 (PR #229 changed Compose configuration and documentation only)

## Executive verdict

Rocket Trader now has a CI-validated, Docker-packaged, read-only Paper observer with durable fill accounting, bounded Activity SSE coverage, fee-to-fill allocation, and an opt-in full-account reconciliation coordinator. It is **not yet deployed to a persistent host**, has not completed a live Paper forward-observation period, and is **not an autonomous order-execution system**. No strategy is approved. No orders have been submitted by this work. LIVE remains blocked.

A successful unit test, image build, or image publication is not evidence of trading profitability or a completed production deployment.

## Integrated changes

| PR | Result | Capability |
|---|---|---|
| #48 | Merged | Market-data freshness diagnostics separate from process heartbeat; future timestamps detected |
| #49 | Merged | Preserve ERROR after unexpected stream worker exit |
| #50 | Merged | Preserve sub-cent fees and partial-fill P&L precision; conservative P&L rounding; protect MXN 100,000 withdrawal floor |
| #51 | Merged | Durable, idempotent Paper fill inbox and retryable FIFO ledger bridge |
| #52 | Merged | Alpaca Activity SSE TRD normalization; trade corrections/busts quarantined for manual review |
| #53 | Merged | Read-only Alpaca Paper CFEE/FEE resolver with exact execution matching |
| #54 | Merged | Timestamped USD/MXN provider with stale/future/look-ahead rejection; persist fill-time FX before delayed fee retries |
| #55 | Merged | Connect Paper trade updates to the MXN ledger; ledger status included in runtime health; retry pending fees |
| #56 | Merged | Validate Compose configuration and build/inspect Docker image in CI |
| #57 | Merged | Add GHCR image publication workflow |
| #58 | Merged | Fix GHCR image path and GitHub Actions expression handling |
| #59 | Merged | Add centered moving-block p-values and Holm-Bonferroni correction to ETF research |
| #60 | Merged | Add the same family-wise correction to crypto research |

## Verified test and build evidence

PR #55 CI passed these offline suites on the integrated runtime revision:

- Runtime: 16 tests
- FIFO ledger: 21 tests
- Fill bridge: 10 tests
- Alpaca fee resolver: 8 tests
- FX provider: 6 tests

PR #56 successfully validated Docker Compose and built the Paper observer image. The image contents compiled inside the container.

The GHCR publication workflow subsequently succeeded:
- Image: ghcr.io/marcodurzov/rocket_trader:latest
- Immutable tag: ghcr.io/marcodurzov/rocket_trader:ba123ae28fa90f5e5184f387d8ad78a554c448f1
- Digest: sha256:df63fc721f570589b9f5328372325c752ea77bef26c70e90a6dbaefe2e3b5290
- Workflow: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42756711127

The image package may require GHCR authentication depending on package visibility. The image is OBSERVE_ONLY.

## Runtime and accounting behavior

The Docker Compose deployment enables the fill ledger bridge with:
- Initial capital: MXN 1,000
- Earned-growth milestone: MXN 100,000
- Separate SQLite/WAL files for observer events, FIFO ledger, and fill inbox on the persistent Docker volume
- Paper trade updates only; no order submission client

For each fill, the runtime persists the event, resolves a timestamped USD/MXN quote, saves that quote before waiting for fees, and records the fill only after fee data is supported. Pending fees are retried every 15 minutes. Unresolved, failed, or manual-review accounting causes the accounting health component to fail.

### Known accounting limitations

1. The USD/MXN source is exchangerate.dev. Its free quotes are delayed and indicative, not settlement rates. Quotes must be at or before the fill and no more than 45 minutes old. If the source is stale or the FX market is closed, the fill cannot be converted and the system fails closed.
2. Alpaca crypto fees may be posted at end of day. Such fills remain pending until the broker activity is available.
3. Unlinked daily regulatory fees (including some equity sell fees) are not yet allocated to individual fills. Those sells remain pending/manual review rather than being assigned guessed costs.
4. Activity corrections and busts are quarantined for manual review; an automatic immutable-ledger correction workflow is not yet implemented.
5. The Paper account's actual fee tier and all fee subtypes still require end-to-end verification against real Paper activity records.

## Statistical research results after multiple-testing correction

### US ETFs — ten-year history

Workflow: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42757291059

- Universe: DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT.
- All 8 symbols passed the configured data-quality gate.
- Family size: 49 strategy-vs-benchmark hypotheses.
- Bootstrap: 5,000 centered moving-block resamples per hypothesis.
- Holm-Bonferroni significant hypotheses: 0.
- Pre-screen passes: 0.
- Candidate promotion and Paper approval: false; orders submitted: 0.

The cross-sectional top-1 momentum holdout had positive raw excess versus equal-weight buy-and-hold, but its 5th-percentile excess was negative and its raw p-value was 0.4213; Holm-adjusted p-value was 1.00. It is not a candidate.

### Crypto — five-year history

Workflow: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42757623220

- BTC/USD: 1,825 daily bars, 100% calendar coverage, maximum gap 1 day.
- ETH/USD: 1,825 daily bars, 100% calendar coverage, maximum gap 1 day.
- SOL/USD: 1,407 bars, 77.10% calendar coverage, 418 missing days, maximum gap 417 days; excluded from the eligible research universe.
- Family size: 13 hypotheses across BTC, ETH and cross-sectional top-1 vs equal-weight.
- Holm-Bonferroni significant hypotheses: 0.
- Pre-screen passes: 0.
- Overall data-quality pass: false because SOL failed; candidate promotion and Paper approval remain false; orders submitted: 0.

BTC 180-day momentum had raw excess over buy-and-hold in the holdout, but only 4 entries, negative 5th-percentile total return, raw p-value 0.1464 and adjusted p-value 1.00. It is not a candidate. Cross-sectional crypto momentum lost 30.1% in the holdout despite positive relative excess versus equal-weight; its adjusted p-value was 1.00.

**Interpretation:** no strategy has demonstrated statistically reliable positive net excess under the current tests. Do not enable orders or lower acceptance thresholds to force a candidate.

## Deployment status

**Container image built and published; persistent service not deployed.**

The remaining infrastructure requirement is a persistent host with a durable mounted volume and secure environment variables for:
- ALPACA_API_KEY (Paper)
- ALPACA_SECRET_KEY (Paper)
- Optional EXCHANGERATE_DEV_API_KEY

GitHub-hosted Actions runners are ephemeral and must not be used as a 24/7 trading host. A persistent host with a durable volume is required; it may be a VPS or managed container platform, but **no hosting provider is currently identified or verified**. Repository inspection found no provider-specific deployment workflow or host identifier, and no evidence of a provisioned cloud project, persistent volume, or running service. Do not assume Railway, Render, or any other provider. The user has not identified the platform, and the repo/GHCR publication cannot establish where (or whether) a runtime currently exists.

## Not yet complete

1. Persistent-host deployment and restart/recovery verification.
2. Real Paper feed observation and broker fill/fee reconciliation over a sustained forward period.
3. Exact allocation of unlinked regulatory fees and automatic handling of trade corrections/busts.
4. Complete broker order/position reconciliation, cancellation, partial-fill exit lifecycle, and recovery handling.
5. Research: independent replication, verified SIP parity, portfolio-level robustness, point-in-time data provenance, and realistic cost stress. Family-wise multiple-testing correction is implemented in the current ETF/crypto research pipelines, but no hypothesis has passed the adjusted OOS acceptance gate.
6. A strategy that passes the documented out-of-sample acceptance criteria.
7. A separate, explicit Paper execution authorization after the strategy and operational gates pass.

## Safety boundary

- Runtime mode: OBSERVE_ONLY.
- No approved strategy.
- No order submission or cancellation.
- No LIVE credentials or LIVE mode.
- Do not enable trading merely because the container is running or health checks pass.


## 2026-11-15 update — full-account Paper evidence coordinator (PR #212)

**Integrated main revision:** `e5bb0fbc6ef13e42fdfa4c4d231156700d45944d`.

The Paper Observer now contains an opt-in `PaperAccountEvidenceCoordinator` that combines:
- Bounded read-only Alpaca Activity SSE replay compared against the durable local inbox.
- Durable cash activity mirror and immutable coverage attestation.
- Exact fee-to-fill allocation audit across cash activities, processed fill bridge and the FX-aware MXN FIFO ledger.
- One time-bounded read-only broker positions/account read set, reconciled against local quantities, USD cash and account equity. Alpaca does not expose an atomic cross-endpoint snapshot.
- Fill bridge and ledger checks before and after the audits and again after final reconciliation; a fill arriving during the final gate blocks the success report.

The feature requires the existing cash ledger, Activity SSE inbox, realized-P&L ledger, fill-bridge inbox and active cash anchor. It is disabled by default and must not be enabled until the actual persistent host, mounted volume, database paths, schemas and anchor have been verified. The coordinator performs read-only broker queries; it does not place, replace or cancel orders. The full-account cycle runs every 900 seconds by default, and healthcheck requires a successful report no older than 1,800 seconds.

Post-merge main CI:
- Paper Reconciliation Gate `43694561871`: 12 + 25 + 26 tests passed.
- Durable Activity SSE `43694561856`: 26 tests and Compose validation passed.
- Runtime Freshness `43694561786`: 37 tests passed.
- Paper Observer Runtime `43694561771`: 250 offline tests across 17 suites passed (includes 7 coordinator tests).
- Paper Observer Container `43694561813`: Compose validation and image build passed.
- GHCR publication `43694561839`: `ghcr.io/marcodurzov/rocket_trader:e5bb0fbc6ef13e42fdfa4c4d231156700d45944d`, digest `sha256:d8bc52d31ccabd6b727c9bb94d7b1e5088fead3c09cac00ce4d1b1c95a8ce0ee`.

**Not evidenced:** persistent-host deployment, actual database/anchor integrity, successful live Paper coverage and fee audit, sustained forward observation, strategy approval or profitability. No Paper orders or Live activity. Current progress remains 58%.


## 2026-11-15 update — deployment runbook and runtime evidence status

- PR #212 integrated the `PaperAccountEvidenceCoordinator` into the Paper Observer runtime. It binds bounded Activity SSE coverage, exact fee-to-fill allocation, the cash anchor, fill bridge, FX-aware MXN ledger, and one time-bounded read-only positions/account observation. Alpaca does not provide an atomic positions-plus-account endpoint; the code uses a bounded read set and repeats ledger checks after final reconciliation.
- PR #217 corrected stale deployment documentation that still said the coverage and fee audits were not wired into runtime. The runbook now reflects the integrated coordinator and explicitly retains the default-disabled setting and host/database verification gate. PR #219 recorded that correction and exact offline CI evidence in the handoff/status docs.
- PR #217 post-merge main runs: Paper Reconciliation Gate `43694984460` and Durable Activity SSE `43694984477` both passed. These were offline tests/Compose validation; the read-only Paper audit job was skipped on PR event. No broker API activity is implied.
- The actual persistent host, volume and existing database files remain unidentified. No deployment, migration, real Paper audit, account mutation, order, or Live action has occurred. The coordinator remains disabled by default and runtime mode remains OBSERVE_ONLY.
- Research status is unchanged: Holm-Bonferroni correction exists in the current ETF/crypto pipelines, but no hypothesis passed the adjusted OOS acceptance gate. Independent replication, verified SIP parity, portfolio-level robustness and point-in-time data provenance remain open.
- Progress remains 58%; this is engineering/evidence maturity, not a probability of profit or completion percentage for live trading.


## 2026-11-15 update — complete packaged-module CI and GHCR publication (PR #222)

The Paper Observer Dockerfile packages 26 Python modules. PR #222 ensures that changes to any packaged source trigger container validation on pull requests and main pushes, compile all 26 modules inside the image, and trigger GHCR publication on main pushes. PR validation `43695204616`, post-merge container validation `43695359960`, and post-merge image publication `43695359959` all passed.

Published image (not deployed): `ghcr.io/marcodurzov/rocket_trader:ea772a07ff69dc0e1c2a684395cee9fa6c4baf87`, digest `sha256:22b004e58feaff4ed33f0b154c9d22538d21d44952bba85c91478a2b51f6a873`.

This closes the CI packaging-trigger gap only. It does not identify or deploy a persistent host, inspect/migrate existing databases, run a real Paper account audit, or approve orders. Runtime remains OBSERVE_ONLY, the cash ledger coordinator remains disabled by default, no strategy passed adjusted OOS acceptance, and profitability remains unproven. Progress remains 58%.


## 2026-11-15 update — persistent accounting startup preflight (PR #227)

The Paper Observer now refuses to construct the realized-P&L ledger, fill-bridge inbox or account-activity stager unless their existing SQLite files pass a read-only integrity/schema check. The ledger must have the configured capital policy, initial-capital event, compatible FX accounting-method marker and append-only triggers. The fill bridge must have the current schema including `fx_json`; the activity stager must have its expected tables, columns and append-only triggers. These three files must be separate. Missing, partial or corrupt state blocks startup; runtime does not create replacements or auto-repair older schemas.

Post-merge validation passed: Runtime Freshness `43695736834`, Paper Observer Runtime `43695736753` (255 offline tests across 17 suites), Container `43695736908`, and GHCR publication `43695736729`. Image published (not deployed): `ghcr.io/marcodurzov/rocket_trader:a8095a767f02377b19b1950a08fd73e154388235`, digest `sha256:9642fe3d80ebb24bd37072238a09426da63bf1ff8b7dbf2851855a4243cc3238`.

Operational consequence: a new/empty persistent volume cannot start with accounting enabled until the account history and initial state have been explicitly reconstructed and verified. A market-data-only mode is available by disabling the ledger and activity stager, but it is not account reconciled. No host/database was accessed, and no real Paper audit or deployment occurred.


## 2026-11-15 update — persistent-state startup gate and Compose overrides (PR #229)

The deployment runbook now requires the existing FX-aware MXN ledger, fill-bridge inbox and activity-stager SQLite files before default accounting startup. Runtime checks them read-only and fails closed on missing, partial, corrupt or incompatible state. Compose exposes explicit ledger/stager overrides; disabling both permits market-data-only observation but does not provide account/fill reconciliation. No empty database bootstrap is approved when prior Paper fills may exist.

Post-merge workflows all passed: Reconciliation `43696040849`, GHCR publication `43696040783`, Container `43696040771`, Observer Runtime `43696040769`, Activity Stager `43696040754`, Durable Activity SSE `43696040739`. The image was published (not deployed) at digest `sha256:33d6f8c4924267b4940bc2fef050ac9b88d8497720ad137b6e32511508405673`.

The manual read-only Paper API audit has not run. The actual persistent host and database volume remain unidentified. No strategy passed adjusted OOS acceptance; no orders or Live actions are approved.
