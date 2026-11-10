# Rocket Trader — Operational Readiness v0.2

**Reviewed:** 2026-11-10  
**Repository:** https://github.com/marcodurzov/Rocket_Trader  
**Current main commit:** 724b832a4fba61e76a188e5136f408cf1a9c7b7a

## Executive verdict

Rocket Trader now has a CI-validated, Docker-packaged, read-only Paper observer with durable fill-accounting integration. It is **not yet deployed to a persistent host**, has not completed a live Paper forward-observation period, and is **not an autonomous order-execution system**. No strategy is approved. No orders have been submitted by this work. LIVE remains blocked.

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
- Immutable tag: ghcr.io/marcodurzov/rocket_trader:ba123ae28fa90f5e5184f387f2a02cab0fe19d87
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
5. Research corrections for family-wise multiple testing, independent replication, SIP parity, and realistic cost stress.
6. A strategy that passes the documented out-of-sample acceptance criteria.
7. A separate, explicit Paper execution authorization after the strategy and operational gates pass.

## Safety boundary

- Runtime mode: OBSERVE_ONLY.
- No approved strategy.
- No order submission or cancellation.
- No LIVE credentials or LIVE mode.
- Do not enable trading merely because the container is running or health checks pass.
