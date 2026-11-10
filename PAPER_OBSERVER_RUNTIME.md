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

## Paper fill accounting

The Compose deployment enables the read-only Paper fill ledger bridge. On each
Alpaca Paper fill update it:

- Persists the raw trade update in the observer database.
- Resolves a timestamped USD/MXN quote and stores it with the fill before fee
  retries, preventing a later retry from substituting a newer FX rate.
- Looks up actual Alpaca Paper CFEE / FEE activities by execution ID.
- Records the fill in the immutable FIFO MXN ledger only when both FX and fees
  are adequately supported.
- Retries pending fee resolution every 15 minutes. The activity query is cached
  for 15 minutes to limit API requests.

The initial ledger capital defaults to MXN 1,000 and the growth milestone to
MXN 100,000. These values are persisted. Changing either value after the ledger
has been initialized causes startup to fail; do not delete or recreate the
ledger to change policy.

The USD/MXN provider is exchangerate.dev. Its free quotes are delayed by about
15 minutes and are indicative, not settlement rates. The bridge accepts only a
quote whose effective_at is at or before the fill and no more than 45 minutes
old. There is no fallback. A stale/closed FX market can therefore leave a fill
unaccounted and make the accounting health check fail.

Crypto fees may be posted by Alpaca at end of day; fills remain pending until
the fee activity is available. Daily regulatory fees without exact execution
linkage (notably some equity sell fees) are not allocated by guesswork and
remain pending/manual-review. The runtime health check reports this as
unhealthy rather than presenting incomplete accounting as clean.

Optional .env entry:
- EXCHANGERATE_DEV_API_KEY=... (the public endpoint can be queried without a
  key; a key may be used according to the provider's plan and limits).

## Account activity staging

The runtime can optionally enable a read-only Alpaca Paper account-activity stager
with `ROCKET_TRADER_ACTIVITY_STAGER_ENABLED=true`. It stores fills, fees and cash
credits/debits durably and idempotently. Cash movements remain pending capital
reconciliation; they are never automatically classified as user deposits or
withdrawals because broker activity codes can also represent returned transfers.
A failed sync marks the account-activity health component unhealthy and is retried
every 15 minutes. This stager never posts to the capital ledger or submits orders.

Set `ROCKET_TRADER_ACTIVITY_STAGER_DB` to a durable path if the default path
beside the runtime database is not suitable.

## Important limitations

- Equities use Alpaca IEX data, not SIP.
- Crypto uses Alpaca's US crypto stream and runs continuously, including weekends.
- Equity bars naturally stop outside exchange sessions; a quiet equity stream
  outside market hours is not itself a failure.
- The container uses Alpaca Paper trade updates for accounting only. It
  constructs no order-submission client and never submits, cancels, or modifies
  orders.
- No strategy is currently approved. This service is data collection and
  operational groundwork only.
- No strategy is approved and no order execution is enabled. A separate
  execution runtime must still integrate the Core risk gate, persistent
  drawdown guard, broker order/position reconciliation, order idempotency,
  partial-fill exits, session/calendar controls, and recovery tests before
  any Paper orders can be enabled.
