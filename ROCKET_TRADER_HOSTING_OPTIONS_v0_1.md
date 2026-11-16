# Rocket Trader — Hosting Options and Zero-Budget Deployment Plan v0.1

**Reviewed:** 2026-11-15  
**Status:** Research only. No provider selected, account created, instance provisioned or deployment performed.

## 1. Recommendation

### Zero-dollar option: Oracle Cloud Infrastructure Always Free

The strongest zero-monthly-cost cloud candidate for the current six-service observer is an OCI Ampere A1 Flex VM:

- 2 OCPUs total and up to 12 GB RAM under the current Always Free allowance.
- Up to 200 GB Always Free block-volume storage across the tenancy.
- Ubuntu Server ARM64 image.
- Initial proposed allocation: 2 OCPUs, 8 GB RAM, 50 GB boot volume.
- The VM must be created in the tenancy's home region and the resource must be explicitly labelled Always Free.

Official documentation:
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm
- https://docs.oracle.com/en/learn/cloud_free_tier/

**Important limitations:**
1. Oracle's free A1 capacity is not guaranteed in every home region. An "out of host capacity" response may require waiting; Always Free compute is limited to the home region.
2. Oracle documents reclaiming idle Always Free compute when, over a seven-day period, CPU utilization at the 95th percentile is below 20%, network utilization is below 20%, and (for A1) memory utilization is below 20%. A low-activity observer may be at risk of reclamation. Do not generate artificial load to evade this policy.
3. Account signup usually requires a phone number and payment card for verification. Oracle says the card is not charged unless the account is upgraded; a temporary verification hold may appear.
4. Free Tier accounts must remain active; Oracle's documentation says free accounts remain available while used within the previous 60 days.
5. This is suitable for development and a supervised observe-only soak, not a contractual uptime guarantee.

### Low-cost paid fallback: OVHcloud VPS

The current OVHcloud VPS listing advertises:
- **VPS-1: from USD 4.54/month**, 2 vCores, 4 GB RAM, 40 GB NVMe, daily backup and unlimited traffic.
- **VPS-2: from USD 8.50/month**, 4 vCores, 8 GB RAM, 75 GB NVMe, daily backup and unlimited traffic.

Official listing: https://www.ovhcloud.com/es/vps/

For Rocket Trader, VPS-1 is the cheapest entry but its 40 GB disk is below the current 60 GB resource estimate in the deployment plan. Do not select it for the full six-service stack until data retention and disk growth are measured. **VPS-2 is the safer low-cost paid choice** because its 75 GB disk and 8 GB RAM exceed the current estimate. These are advertised starting prices; confirm checkout price, taxes, region and availability.

Choose a standard datacenter VPS, not an OVHcloud Local Zone: OVH's page currently states that Local Zone VPS instances are not compatible with Docker. The selected region should be near the Alpaca endpoints if available, but this observer is not a high-frequency latency-sensitive system.

Hetzner's CX23 price reference is USD 6.49/month before VAT/IPv4, but its current cost-optimized product page marks CX23 unavailable. Treat it as unavailable unless checkout proves otherwise:
- https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- https://www.hetzner.com/cloud/cost-optimized/

### Not recommended for this stack

Google Cloud's always-free Compute Engine offer is one non-preemptible e2-micro VM in selected US regions, with 1 GB RAM and 1 GB/month outbound transfer. That is too constrained for the current six-container Compose stack plus SQLite state and is not a better fit than OCI A1.

Official reference: https://docs.cloud.google.com/free/docs/free-cloud-features

## 2. What the server is and why Rocket Trader needs it

A server is a computer in a data center that stays powered and connected to the internet. Rocket Trader's observer processes need to maintain long-lived Alpaca streams, poll news sources, persist minute bars and account activities, evaluate market-regime features, run health checks and recover after process/host restarts.

GitHub Actions is not the server: its runners are temporary jobs and do not preserve a continuously running process or local SQLite volume.

The current six-service Compose stack is **observe-only**. It does not establish a profitable strategy and does not autonomously submit orders. A healthy server proves process/data collection uptime only.

## 3. Resource and architecture fit

The existing deployment plan estimates 2 vCPU, 4 GB RAM and 60 GB SSD as a starting point for six services; this is an engineering estimate, not a load-test result. OCI's 2 OCPU / 8 GB proposed allocation is within its current Always Free ceiling. A paid 2-vCPU / 4-GB VPS is a lower-cost starting point, but memory, disk and API latency must be monitored during a soak.

The Compose file currently builds the image locally. The Dockerfile uses Python 3.12 slim and the observer services share the named volume `rocket_trader_data`. Before choosing ARM64, verify a full local image build and all six service healthchecks on the actual ARM host; do not assume an AMD64 GHCR image is multi-architecture.

## 4. Critical pre-deployment blocker: existing databases

Do not deploy the full default Compose stack onto an empty volume.

The runbook requires existing, valid persistent SQLite files for the MXN realized-P&L ledger, fill-bridge inbox and activity stager. The startup preflight intentionally refuses missing, partial, corrupt or incompatible state. A new empty database could omit prior Paper fills, fees and accounting history.

The actual prior host, Docker volume and database paths have not been identified. Before deployment:
1. Discover whether any previous host/volume exists.
2. Identify the exact Compose project, volume and all SQLite/WAL/SHM files.
3. Back up and verify them before migration or transfer.
4. If no valid ledgers exist, reconstruct from bounded broker Paper activity evidence and review the initialization procedure; do not create empty files merely to make healthchecks pass.

A temporary market-data-only observer can be considered with ledger/stager features explicitly disabled, but it is not full accounting or account-reconciliation readiness.

## 5. Security baseline

- Paper credentials only; never place Live keys on the host.
- Store credentials in a private `.env` file with mode 600; never commit or send them in chat.
- Use SSH keys, disable password SSH and restrict port 22 to the operator's source IP.
- No inbound application, market-data or trading ports are needed; services use outbound connections.
- Host firewall denies unsolicited inbound traffic.
- Keep the containers non-root (UID/GID 10001) and preserve the persistent volume.
- Use log rotation, encrypted off-host backups and tested SQLite restore procedures.
- Never run `docker compose down -v` against the production volume.

## 6. User setup steps

1. Create an OCI Free Tier account at https://www.oracle.com/cloud/free/ if accepting the account-verification requirement.
2. Choose the home region carefully; Always Free compute is restricted to it. Prefer the closest available region with A1 capacity, but do not assume capacity is available.
3. Create an Ampere A1 Flex instance with Ubuntu ARM64, 2 OCPUs, 8 GB RAM and a 50 GB boot volume. Confirm the console labels it Always Free before creating it.
4. Upload an SSH public key generated on the user's own computer. Keep the private key local.
5. Configure a VCN/security list to allow SSH only from the user's IP. Do not expose service ports.
6. Record the public IP, region, shape, OS architecture and boot-volume size. Share only those non-secret details for the deployment plan; never share the private SSH key or Paper credentials in chat.

After that, perform the existing-host/database discovery and backup gate before starting Compose. Do not start the six services merely because the VM is available.

## 7. Deployment acceptance

A deployment is not complete until:
- The source commit and image architecture are pinned/recorded.
- The six services start in OBSERVE_ONLY mode.
- The correct persistent volume is mounted and existing databases are verified.
- Healthchecks, stale-data alerts and disk/memory monitoring work.
- Restart and host-reboot tests preserve SQLite state and event cursors.
- Backups restore successfully to a separate test volume.
- At least 72 hours of observer soak evidence is recorded.
- No orders are submitted and LIVE remains disabled.

A successful deployment does not approve any strategy or authorize trading.
