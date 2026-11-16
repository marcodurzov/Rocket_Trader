# Rocket Trader — Crypto Execution Cost Review v0.1

**Reviewed:** 2026-11-15  
**Status:** Fee schedule independently checked; model-to-code reconciliation and empirical cost approval remain open. No cost assumption is approved.

## 1. Verified Alpaca crypto fee schedule

Alpaca's current public crypto documentation lists volume-tiered maker/taker fees. For Tier 1 (USD 0–100,000 crypto trading volume over 30 days):

- Maker: **15 bps per executed side (0.15%)**.
- Taker: **25 bps per executed side (0.25%)**.

Official sources:
- https://docs.alpaca.markets/us/docs/crypto-trading
- https://docs.alpaca.markets/us/docs/crypto-fees
- https://alpaca.markets/support/crypto-maker-taker-gmt-faq

The actual Paper account's 30-day tier and execution classifications have not been independently confirmed from account records. Use Tier 1 taker as the conservative published commission baseline until verified.

## 2. What the 40 bps/side assumption means

A 40 bps per-side assumption is **not** Alpaca's published Tier 1 commission.

For two executed legs:
- Maker + maker: 30 bps commission round trip.
- Taker + taker: 50 bps commission round trip.
- One maker + one taker: 40 bps commission round trip.

Therefore, if the historical model applies 40 bps on each side (80 bps round trip), it is not a literal Tier 1 fee schedule. It may still be a deliberately conservative **all-in friction** assumption if the additional 15 bps per side is explicitly intended to cover spread, slippage or market impact. The repository must not label that composite as a broker fee.

A maker classification is not guaranteed merely because an order is a limit order. Whether an order adds or removes liquidity depends on whether it rests on the book or executes immediately. A market or marketable-limit order normally removes liquidity and should be costed as taker unless actual execution evidence proves otherwise.

## 3. Required all-in cost decomposition

Every crypto backtest and candidate evaluation must separate:

1. **Broker commission:** maker/taker bps by actual execution leg and applicable 30-day tier.
2. **Spread:** use a timestamp-valid bid/ask quote. A buy at ask and a sell at bid incur approximately one full quoted spread over the round trip relative to midpoint, not two full spreads.
3. **Slippage:** signed fill-price deviation from the valid midpoint at each fill. Adverse and favorable fills must both be retained; do not clip unfavorable observations.
4. **Market impact/liquidity:** stress by order notional, displayed depth, volatility and trading session. Paper top-of-book data is not a full impact model.
5. **Fee denomination:** Alpaca may charge crypto fees in the credited asset. Convert asset-denominated fees to USD and MXN using timestamp-valid, sourced conversion evidence.
6. **Fee timing:** Alpaca documents that crypto fees may be posted at end of day. A missing same-day CFEE/FEE event is pending evidence, not a zero fee.

The runtime's quote-to-fill telemetry is descriptive. It must not be described as an empirical cost approval until representative observations, coverage, sample size and uncertainty gates pass.

## 4. Minimum research protocol before any crypto strategy approval

- Reconcile every fill with its exact broker activity and fee record; quarantine unmatched fees, corrections and busts.
- Classify maker/taker from actual execution evidence where available; otherwise use taker cost as the conservative default.
- Measure spread and signed slippage from quotes at or before the fill timestamp, excluding stale/future quotes.
- Report median, mean, p90/p95 and confidence intervals by symbol, order type, liquidity and session.
- Stress each strategy at base, 2x and 3x observed all-in costs, and compare against cash and same-period buy-and-hold.
- Apply chronological OOS evaluation and family-wise multiple-testing correction after costs.
- Keep candidate promotion, Paper approval and orders disabled until all independent gates pass.

## 5. Current conclusion

The audit is correct that assumed costs can erase a small gross edge and that no empirical cost approval exists. However, the 40 bps/side figure must be interpreted carefully: it is not Alpaca's published Tier 1 commission. The actual published Tier 1 fee is 15 bps maker or 25 bps taker **per side**. A separate spread/slippage/impact component is still required and may make the all-in round-trip cost materially higher.

No crypto strategy has passed the current adjusted OOS acceptance gate. This review does not approve any strategy, order or Live capability, and it does not address the deferred minimum-capital question.
