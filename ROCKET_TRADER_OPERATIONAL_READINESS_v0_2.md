# Rocket Trader — Operational Readiness v0.2

**Reviewed:** 2026-11-15  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Code baseline reviewed:** e5bb0fbc6ef13e42fdfa4c4d231156700d45944d

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

GitHub-hosted Actions runners are ephemeral and must not be used as a 24/7 trading host. A persistent Railway/Render/VPS service is required. Railway connection was suggested in ChatGPT but is not confirmed connected; no cloud project, volume, or running service has been created.

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


### Snapshot consistency limitation

The full-account coordinator pairs two read-only Alpaca responses (positions, then account cash/equity); these are separate API calls, not an atomic broker snapshot. The local UTC timestamp captured immediately after `get_account()` defines the Activity SSE replay upper bound. Ledger stability, exact activity coverage, cash, equity and position reconciliation reduce inconsistency risk and fail closed on detected differences, but they do not convert separate broker endpoints into an atomic transaction. Keep the host clock synchronized to UTC and retain this limitation in any operational or performance claim.
