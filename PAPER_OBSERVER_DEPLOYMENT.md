# Paper Observer deployment runbook

## Scope and safety

This Compose stack runs five separate services on a shared persistent volume:

| Service | Responsibility |
|---|---|
| `rocket-trader-paper-observer` | Alpaca Paper bars, quote streams, account activity, fills and reconciliation |
| `rocket-trader-regime-observer` | Read-only market regime features and cash/abstain decision snapshots |
| `rocket-trader-alpaca-news` | Read-only symbol-linked Alpaca/Benzinga news ingestion |
| `rocket-trader-gdelt-news` | Read-only global/geopolitical news discovery |
| `rocket-trader-official-news` | Official macro/regulatory RSS ingestion |

The stack is forced to `OBSERVE_ONLY`. The regime observer has no approved strategy candidates and must remain 100% cash. News can only reduce risk after a source-verified, human-reviewed assessment. No live trading is enabled.

## 1. Host prerequisites

- Docker Engine and Docker Compose plugin.
- A persistent host directory/volume for Docker data.
- A dedicated Alpaca **Paper** API key and secret, not live credentials.
- Network access to Alpaca, SEC/Federal Reserve/BLS/BEA feeds and GDELT.

Clone/update the repository:

```bash
git pull origin main
```

Create `.env` in the repository root. Never commit it:

```dotenv
ALPACA_API_KEY=YOUR_PAPER_API_KEY
ALPACA_SECRET_KEY=YOUR_PAPER_SECRET_KEY
SEC_CONTACT_EMAIL=your-real-contact-email
ROCKET_TRADER_ALPACA_NEWS_SYMBOLS=SPY,QQQ,IWM,BTCUSD,ETHUSD,SOLUSD
```

`SEC_CONTACT_EMAIL` is optional but enables the SEC feed with an identified contact. The watchlist can be changed, but symbols must be supported by the Alpaca News API.

## 2. Validate and start

```bash
docker compose -f docker-compose.paper-observer.yml config
docker compose -f docker-compose.paper-observer.yml up -d --build
docker compose -f docker-compose.paper-observer.yml ps
```

Inspect logs:

```bash
docker compose -f docker-compose.paper-observer.yml logs --tail=200
```

Follow a specific service:

```bash
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-paper-observer
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-regime-observer
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-alpaca-news
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-gdelt-news
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-official-news
```

The services share the named volume `rocket_trader_data`. Do not use `docker compose down -v` unless intentionally destroying the persisted research, news, fill and reconciliation history.

## 3. Verify cost telemetry

After Paper fills have occurred:

```bash
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-paper-observer \
  python /app/rocket_trader_execution_cost_telemetry.py \
  --db-path /app/data/runtime.sqlite3 --summary
```

The report is descriptive only. It does not validate transaction costs automatically. IEX is not SIP/NBBO, and Paper execution does not prove live execution quality.

## 4. Inspect regime decisions

```bash
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-regime-observer \
  python /app/rocket_trader_regime_observer.py --healthcheck
```

The database `/app/data/regime_decisions.sqlite3` contains per-universe decision snapshots. Insufficient/stale market data must produce CASH/ABSTAIN, not a guessed regime.

## 5. Review news events

Raw news never affects allocation. Only source-verified, human-approved assessments are loaded.

Copy a curated event JSON into the regime container:

```bash
docker compose -f docker-compose.paper-observer.yml cp event.json rocket-trader-regime-observer:/tmp/event.json
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-regime-observer \
  python /app/rocket_trader_news_event_assessment.py \
  --db /app/data/rocket_trader_news_events.sqlite3 \
  --import-event /tmp/event.json
```

Copy and import the separate assessment JSON:

```bash
docker compose -f docker-compose.paper-observer.yml cp assessment.json rocket-trader-regime-observer:/tmp/assessment.json
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-regime-observer \
  python /app/rocket_trader_news_event_assessment.py \
  --db /app/data/rocket_trader_news_events.sqlite3 \
  --import-assessment /tmp/assessment.json
```

Review pending assessments:

```bash
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-regime-observer \
  python /app/rocket_trader_news_event_assessment.py \
  --db /app/data/rocket_trader_news_events.sqlite3 --list-pending
```

Approve or reject using the actual accountable reviewer identity:

```bash
docker compose -f docker-compose.paper-observer.yml exec -T rocket-trader-regime-observer \
  python /app/rocket_trader_news_event_assessment.py \
  --db /app/data/rocket_trader_news_events.sqlite3 \
  --review-assessment ASSESSMENT_ID \
  --reviewer "REAL_REVIEWER_ID" \
  --decision approve
```

Approval checks that article IDs, URLs, provider publication times and first-live-seen times match the persisted official/Alpaca/GDELT ingestion databases. CRITICAL events require two independent source groups and minimum evidence scores. Reviewer names are audit attribution, not cryptographic identity; protect shell access to the host.

## 6. Stop safely

```bash
docker compose -f docker-compose.paper-observer.yml stop
```

This stops services but preserves the volume. Do not delete the volume when stopping or updating.

## 7. What deployment does not mean

A healthy Compose stack proves only that the observer processes and data feeds are operating. It does not prove profitability, strategy validity, live execution costs or readiness for real capital. Before any real-money phase, Rocket Trader still needs verified Paper operation, complete fee/fill reconciliation, empirical cost studies, out-of-sample strategy evidence, drawdown/kill-switch validation and a separate explicit live-capital approval.


## 8. Read-only execution-journal recovery

Before any future execution process is allowed to accept new order intents after a restart, run the one-shot recovery pass against the **same durable SQLite files** used by the execution adapter. This is separate from the observe-only market-data container and must not point at a fresh or temporary database.

Required environment:
- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`: dedicated Paper credentials.
- `ALPACA_PAPER=true`, `ALPACA_LIVE_ENABLED=false`, `ROCKET_TRADER_EXECUTION_MODE=PAPER`.
- `ROCKET_TRADER_CRYPTO_EXECUTION_DB`: existing durable execution journal file.
- `ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB`: existing immutable event-ledger file; if omitted, the adapter's default sibling path is used.

Run from the repository's Python environment on the persistent host:

```bash
python alpaca_paper_crypto_execution_recovery_worker.py
```

The runner verifies that both database files already exist and that the journal has its expected order table **before** constructing the adapter. It verifies the Paper cash-only account policy, then queries each journaled client order ID and reconciles individual FILL activities. It does not submit, cancel, replace or modify broker orders or account settings.

Interpretation:
- `SUCCESS`: every locally journaled order was found and its FILL activity matched the broker snapshot.
- `REQUIRES_REVIEW` (exit code 2): one or more orders were missing at the broker or had incomplete/mismatched fill evidence. Keep new execution blocked.
- Failure (exit code 1): preflight, persistent-state or broker reconciliation error. Do not initialize a replacement database to bypass it.

This remains an **explicit one-shot runner**, not a continuously scheduled service. PR #163 adds a tested process-local startup-gate wrapper for a future execution host, but no persistent execution service currently instantiates that wrapper or is deployed by this repository workflow.


## 9. Fail-closed execution startup gate (not deployed)

A future Paper crypto execution host must not call the low-level adapter directly before recovering its existing durable state. Use `PaperCryptoExecutionService` as the process-local submission gate. The observer Compose stack remains observe-only and must not be repurposed as an execution host.

The service factory requires both existing database files and the expected order-journal table before it constructs the adapter. It also requires `ALPACA_PAPER=true` and rejects LIVE. Example host integration:

```python
from rocket_trader_paper_crypto_execution_service import PaperCryptoExecutionService

service = PaperCryptoExecutionService.from_existing_storage(
    db_path="/persistent/rocket-trader/crypto-execution.sqlite3",
    event_ledger_path="/persistent/rocket-trader/crypto-execution-events.sqlite3",
)
startup = service.start()  # account preflight + read-only reconciliation of every journaled order
if not startup["ready"]:
    raise RuntimeError("Paper execution recovery is not complete")
# Only after start() succeeds may the host pass a validated intent to service.submit(intent).
```

If recovery is missing, malformed, unresolved or failed, `start()` raises and the gate remains closed. A submission exception also closes the process-local gate; run `service.start()` again to perform a fresh recovery pass (or restart the process and call `start()` again) before retrying. `stop()` closes the gate without a broker action. No continuous loop, order strategy, production host, or autonomous trading path is deployed by this module. It is an integration primitive that must be used by the eventual execution process.


## 10. Read-only Activity SSE capability probe

The manual workflow now also runs `alpaca_paper_activity_sse_probe.py` against the Paper Activity SSE endpoint using a finite historical window from `orders_after` through current UTC time. It records whether the account returns TRD, crypto-like symbols, CFEE/FEE, `trade_correct`, `trade_bust` or `previous_id` evidence.

This is a diagnostic probe only. It does not create a persistent SSE consumer, save a replay cursor, modify the execution ledger, reverse fills, change positions or submit orders. A missing crypto event is not proof that Alpaca does not support crypto on this endpoint; it is simply an unconfirmed capability until compared with the known Paper order history or clarified by Alpaca support.


## 11. Optional Paper Activity SSE durable inbox service

The repository now contains a separate read-only Activity SSE consumer. It must be run as its own process/container, not inside the market-data observer loop.

Before enabling it, add the following to the deployment host's private `.env` file (never commit this file):

```dotenv
ALPACA_API_KEY=your_existing_paper_key
ALPACA_SECRET_KEY=your_existing_paper_secret
ACTIVITY_SSE_BOOTSTRAP_SINCE=2026-11-11T04:55:00Z
```

The bootstrap timestamp should be chosen deliberately: it is the first historical business-time boundary to replay. The confirmed BTC/USD Paper smoke fills occurred shortly after 2026-11-11T04:57:47Z. Starting earlier than the first event that must be captured avoids skipping that evidence. On subsequent reconnects, the service uses its SQLite-persisted `since_id` cursor, not the bootstrap timestamp.

The Compose service `rocket-trader-alpaca-activity-sse` is explicitly pinned to `ALPACA_PAPER=true`, `ALPACA_LIVE_ENABLED=false` and `ROCKET_TRADER_EXECUTION_MODE=PAPER`. It uses the shared persistent `rocket_trader_data` volume and a dedicated `rocket_trader_activity_sse.sqlite3` inbox. It does not submit, cancel or replace orders and does not update positions, cash, fees or P&L. Corrections and busts are stored only as evidence.

Deployment commands, after reviewing the environment and backup plan:

```bash
docker compose -f docker-compose.paper-observer.yml build rocket-trader-alpaca-activity-sse
docker compose -f docker-compose.paper-observer.yml up -d rocket-trader-alpaca-activity-sse
docker compose -f docker-compose.paper-observer.yml logs -f rocket-trader-alpaca-activity-sse
```

The container health check opens an already-existing inbox read-only, verifies the local hash chain, delivery hashes, cursor and append-only triggers without contacting Alpaca. If the database file is missing, the health check fails and does not create an empty replacement. Confirm the container is healthy and inspect logs for `STREAM_ENDED_OR_RECONNECTING` / `RECONNECTING` records. Back up the shared volume before upgrading or changing the inbox schema.

**Not deployed by GitHub CI:** these files prepare the service configuration only. A host operator must deploy it on the actual persistent server and verify that the named volume survives container recreation. Do not use a disposable GitHub Actions runner as the persistent event consumer.


## 12. Deployment status after PR #168

The repository now includes the optional `rocket-trader-alpaca-activity-sse` Compose service. PR #168 passed Compose validation, Docker image build/package verification, the durable consumer test workflow and the existing Paper observer runtime test workflow.

The service is not running until deployed on the actual persistent host. After deployment:
1. Confirm `.env` contains the existing Paper API credentials and `ACTIVITY_SSE_BOOTSTRAP_SINCE` is set to a timestamp no later than the first activity that must be captured.
2. Build and start only `rocket-trader-alpaca-activity-sse` initially.
3. Verify container health and reconnect logs.
4. Restart/recreate the container once and verify the SQLite cursor resumes using `since_id`, with no duplicate canonical activities.
5. Preserve the SQLite database and its WAL files together during backup; stop the service or use SQLite's backup API for consistent backups.

Do not enable any downstream P&L/position application until correction/bust semantics and fee allocation are separately validated.


## 13. Cash-activity admin requires existing durable state

The operator CLI `rocket_trader_cash_activity_admin.py` checks that both the realized-P&L ledger and activity-stager SQLite databases already exist and contain their required schema before constructing either component. It refuses to initialize missing or empty files. Do not point the CLI at a fresh path to make a missing database appear healthy; restore the original persistent files and WAL state first.
