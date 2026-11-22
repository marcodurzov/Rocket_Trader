# Rocket Trader — Server Deployment Plan v0.1

**Status:** Procedure rehearsed end-to-end on an ephemeral runner with real Paper credentials (2026-11-22, run `45057338539`: genesis, six services, backup/restore, restart). No VPS has been selected, provisioned or deployed.
**Operating mode:** Paper / observe-only. Live is disabled.
**Last reviewed:** 2026-11-15

## 1. Current reality

- GitHub is the source repository and CI system. GitHub Actions runners are temporary and are not a 24/7 server.
- GHCR stores published Docker images. Publishing an image does not deploy or run it.
- The current Compose file defines six observer services sharing one persistent named volume.
- The six services ingest Alpaca Paper market/account activity, durable Activity SSE, market regime features, Alpaca/Benzinga news, GDELT news and official news feeds.
- This Compose stack is an observer/reconciliation stack. It is not yet the autonomous order-execution runtime.
- The Core's Paper execution path is default-deny and requires explicit Paper approval plus a strategy allowlist. No strategy is approved and no Paper order is currently authorized.
- The current Compose file builds the image locally from the checked-out repository; it does not yet pin and pull the published GHCR digest.
- The current Dockerfile previously ran as root. PR #241 changes it to fixed non-root UID/GID 10001 and adds a container CI check.

## 2. Recommended initial host (estimate, not load-tested)

For the six observer services and SQLite workloads:

- Ubuntu Server 24.04 LTS
- 2 vCPU
- 4 GB RAM
- 60 GB SSD/NVMe
- Region: US East, subject to latency and provider availability checks
- Docker Engine and Docker Compose plugin
- Static public IP is convenient but not required for outbound-only data collection

For a future integrated research/execution runtime, reserve the option to move to 4 vCPU / 8 GB RAM / 100 GB SSD. These are conservative engineering starting estimates, not measured capacity guarantees. Run a soak/load test and inspect memory, CPU, disk growth and API latency before choosing a final plan.

A VPS is preferable to shared web hosting or a serverless function because the observers maintain long-lived streams, poll schedules and local persistent state. No HFT-grade latency is assumed; correctness, uptime, persistence and controlled restart behavior matter more.

## 3. Target topology

1. GitHub main: reviewed source and tests.
2. GitHub Actions: compile, offline tests, integration checks and Docker image build.
3. GHCR: immutable image tag and digest.
4. VPS: pulls a pinned image digest (deployment Compose must be updated from local build to image-by-digest before production deployment).
5. Docker Compose: six observer containers with healthchecks and restart policies.
6. Named persistent volume: SQLite ledgers, activity inboxes, market/news events and runtime state.
7. Alpaca Paper API: read-only/observer credentials and account activity.
8. Monitoring: container health, stale data, missing sessions, reconciliation mismatches, disk, memory, CPU and backup status.

No inbound market-data or trading API port should be exposed publicly. Services communicate through the internal Docker network. Administrative access should be SSH only, preferably through a VPN or restricted source IP.

## 4. Security baseline

- Dedicated non-root container identity UID/GID 10001.
- Dedicated Linux host user for deployment; no routine root SSH.
- SSH keys only; disable password authentication.
- Host firewall allows SSH from a restricted source and denies unsolicited inbound traffic.
- Docker daemon and OS security updates maintained.
- Paper API credentials only; never place Live keys on the initial observer host.
- Store .env outside version control with restrictive file permissions; never bake secrets into image layers or build args.
- Keep ALPACA_LIVE_ENABLED=false, ROCKET_TRADER_RUNTIME_MODE=OBSERVE_ONLY and ROCKET_TRADER_EXECUTION_MODE=PAPER.
- Pin deployment to an immutable GHCR digest, not the mutable latest tag.
- Configure log rotation and resource limits after observing actual service usage.

## 5. Persistence and recovery

The Compose named volume rocket_trader_data contains persistent SQLite databases. It must survive container recreation, host reboot and image updates.

Before full startup, verify the existing ledger, fill inbox and activity stager files, schema versions, accounting-method marker, capital-policy metadata and append-only triggers. The runtime deliberately fails closed if expected state is absent or incompatible. Never create replacement empty files to get a green healthcheck.

Backups:
- Use SQLite's online backup API or a coordinated stopped-writer snapshot.
- Encrypt backups at rest and transfer them off-host.
- Retain daily backups plus periodic longer-term snapshots.
- Test restoration to a separate temporary volume before any upgrade.
- Record backup hashes and restore-test results.

The non-root image initializes a new volume with UID/GID 10001. An existing volume from an older root-running image may need a carefully reviewed ownership migration. Stop all writers and verify a backup first; do not blindly chown an unknown ledger volume.

## 6. Deployment gates

Do not provision/deploy until:
1. The user chooses a provider, region and monthly cost ceiling.
2. The exact deployment Compose is updated to pin the GHCR digest.
3. ~~The persistent database initialization/restore plan is validated from broker evidence.~~ Done: `rocket_trader_paper_genesis_admin.py` (flat-account checks, genesis boundary) — PR #251/#253.
4. ~~The volume ownership and restore procedure are tested.~~ Done in rehearsal: `deploy/rocket_trader_deploy.sh backup` / `restore-test` (runtime preflight on restored copy).
5. Paper-only secrets and environment settings are verified.
6. All six services pass healthchecks and a minimum 72-hour observer soak.
7. Read-only Paper activity, fill and fee reconciliation is complete.

This plan does not authorize server purchase, account funding, Paper order submission or Live trading.

## 7. One-command procedure (added 2026-11-22)

On a fresh Ubuntu 22.04/24.04 host, from a clone of the repository: `deploy/rocket_trader_deploy.sh install`, log out/in, then `init-env`, `genesis`, `up`, `status`. Schedule `backup` daily (cron) and copy backups off-host; run `restore-test` after upgrades. Gate 2 (pinning a GHCR digest) is replaced by deploying a pinned git commit and building locally; record the commit SHA with each deployment.
