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
