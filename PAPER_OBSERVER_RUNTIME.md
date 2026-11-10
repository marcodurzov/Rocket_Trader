# Rocket Trader Paper Observer Runtime

This container is an always-on **OBSERVE_ONLY** market-data recorder. It streams
IEX minute bars for the configured US equities, US crypto minute bars, and
Paper-account trade-update events into a durable SQLite/WAL database.

It does not generate trading signals, submit orders, cancel orders, or modify
positions. It is not the autonomous trading runtime and cannot be promoted to
LIVE. The runtime explicitly rejects any mode other than OBSERVE_ONLY.

## Run

1. Create a local `.env` file (never commit it) containing:
   - `ALPACA_API_KEY=...`
   - `ALPACA_SECRET_KEY=...`
   - `ROCKET_TRADER_RUNTIME_MODE=OBSERVE_ONLY`
2. Start with `docker compose -f docker-compose.paper-observer.yml up -d --build`.
3. Check health with `docker compose -f docker-compose.paper-observer.yml ps`.
4. Logs: `docker compose -f docker-compose.paper-observer.yml logs -f`.

The named Docker volume `rocket_trader_data` persists bars, Paper trade events,
and heartbeats across container restarts. Back it up before changing hosts.

## Important limitations

- Equities use Alpaca IEX data, not SIP.
- Crypto uses Alpaca's US crypto stream and runs continuously, including weekends.
- Equity bars naturally stop outside exchange sessions; a quiet equity stream
  outside market hours is not itself a failure.
- The container uses Alpaca Paper trade updates and never constructs a trading
  client or submits orders.
- No strategy is currently approved. This service is data collection and
  operational groundwork only.
- A later execution runtime must add a strategy approval artifact, the Core
  risk gate, persistent drawdown guard, ledger, broker reconciliation, order
  idempotency, position lifecycle, session/calendar controls, and recovery
  tests before any Paper orders can be enabled.
