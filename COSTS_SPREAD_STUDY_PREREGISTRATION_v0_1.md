# Quoted-Spread Measurement Study — Pre-registration v0.1

**Study ID:** `COSTS-SPREAD-v0.1` · **Registered:** 2026-11-23, before any run · **Code:** `rocket_trader_spread_study.py`
**Mode:** measurement only; read-only market data; no orders.

## Question
Do the half-spread components assumed by research (ETF **2.5 bps/side**, crypto **10 bps/side**) cover the quoted spreads a small marketable order actually faces?

## Design (fixed)
- **ETFs:** DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT. Alpaca historical **SIP** quotes (free; request end ≥16 min old). Last **40** completed XNYS sessions; six New York times per session: 09:35, 10:30, 12:00, 13:30, 15:00, 15:55 (times at/after an early close are skipped). Sample = latest valid quote in the 60 s window ending at the sample time.
- **Crypto:** BTC/USD, ETH/USD, SOL/USD. Alpaca historical crypto quotes (Alpaca venue, where orders would execute). Hourly over the last **14** days; latest valid quote in the 5-minute window.
- **Metric:** half-spread = (ask − bid) / 2 / midpoint, in bps. Locked/crossed/missing quotes are excluded (never counted as zero).
- **Verdicts per symbol:** `ASSUMPTION_COVERS_P90` (p90 ≤ assumption), `ASSUMPTION_COVERS_MEDIAN_ONLY`, `ASSUMPTION_TOO_LOW` (median > assumption), `INSUFFICIENT_DATA` (<80% valid samples).

## What it does not establish
Fees (crypto taker 25 bps/side are separate), slippage beyond the quote, latency, partial fills, market impact, or auction/odd-lot effects. `cost_assumptions_validated` stays false; only real Paper fills can complete the cost gate. If an assumption is too low, research must be re-run with a corrected (higher) cost — never lowered to pass.
