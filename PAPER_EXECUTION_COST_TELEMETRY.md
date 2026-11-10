# Paper execution cost telemetry

## Purpose

The Paper runtime now subscribes to quotes alongside minute bars and trade updates. For each fill/partial fill it selects the most recent quote whose timestamp is **at or before** the fill timestamp and stores a compact quote snapshot with the fill. It does not persist every quote tick.

## Measurement rules

- Equities use the IEX quote stream; this is not SIP/NBBO and must not be represented as consolidated market spread.
- Crypto uses Alpaca's US crypto quote feed.
- Maximum quote age: 5 seconds for equities and 10 seconds for crypto.
- Future quotes are never used. Missing/stale quote events are stored but excluded from cost aggregates.
- Per-execution fill price/quantity is preferred. If only a final order average is available, it is included only when no earlier partial-fill event exists; cumulative averages that would double-count partial fills are excluded.
- Full quoted spread is `(ask - bid) / midpoint × 10,000`.
- Fill slippage is signed relative to midpoint: positive means adverse execution cost, negative means price improvement.
- Fees and regulatory charges remain in the separate realized-PnL/fee ledger; this telemetry does not fabricate or duplicate them.

## Query the descriptive report

```bash
python rocket_trader_execution_cost_telemetry.py \
  --db-path /app/data/runtime.sqlite3 \
  --summary
```

The output is always `DESCRIPTIVE_ONLY_NOT_VALIDATED`. It never flips the empirical-cost approval flag. A reviewer must assess sample size, market sessions, symbol/feed coverage, quote freshness, partial fills, outliers and Paper-versus-live differences before a strategy's cost gate can be approved.

## Important limits

Paper fills are not proof of live execution quality. IEX quotes are not the SIP consolidated NBBO. Quote-to-fill midpoint slippage is a diagnostic, not a complete market-impact model. The telemetry also cannot measure unobserved queue position or liquidity consumed beyond the captured top-of-book quote.

No orders are created, modified or cancelled by this module.
