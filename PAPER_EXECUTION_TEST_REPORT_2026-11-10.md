# Paper execution and capital-control evidence — 2026-11-10

## Executive result

**Execution mechanics: passed for a capped BTC/USD Paper round trip. Strategy profitability: not tested and not approved.**

Rocket Trader has not demonstrated a profitable strategy. The two Paper round trips below were execution and accounting tests only, each capped at USD 10 notional. They must not be represented as strategy results.

## Account safety configuration

Verified against the Alpaca Paper API after configuration hardening:

| Setting | Verified value |
|---|---:|
| Paper cash before tests | USD 100,000.00 |
| Account multiplier | 1 |
| Maximum margin multiplier | 1 |
| Shorting enabled | false |
| no_shorting | true |
| Options level | 0 |
| LIVE orders | 0 |

The initial USD 100,000 Paper balance appeared in Account Activities as a JNLC cash journal. Alpaca describes JNLC as a cash journal entry; its Paper account documentation says the default initial Paper balance is USD 100,000. This balance is a simulator seed, not a user contribution, not trading-generated capital, and not the MXN 100,000 earned-growth milestone.

The activity stager now leaves JNLC, CSD and CSW pending capital reconciliation. None is automatically booked as a user deposit, withdrawal or trading profit. Unresolved capital movements keep the observer's account-activity health state unhealthy.

## Paper execution cycles

### Cycle A — initial smoke test, subsequently reconciled

- Buy: 0.000133809 BTC at USD 73,281.80.
- Net broker position after base-asset fee/adjustment: 0.000133474 BTC.
- Sell: 0.000133474 BTC at USD 73,232.53.
- Final residual BTC position: 0.

The first order response initially returned `pending_new`; the order later reconciled as filled. The recovery workflow then closed only the net broker-confirmed position.

### Cycle B — hardened lifecycle smoke test

- Buy notional cap: USD 10.00.
- Buy: 0.000133709 BTC at USD 73,346.83.
- Net broker position after base-asset fee/adjustment: 0.000133374 BTC.
- Sell: 0.000133374 BTC at USD 73,279.20.
- Final residual BTC position: 0.

The hardened smoke test waits for terminal order states, cancels an order that remains pending, reconciles the broker position, sells only net inventory actually held, and verifies zero residual position.

## Account reconciliation after tests

Read-only post-test preflight:

- Cash: USD 99,999.86.
- Equity: USD 99,999.86.
- Open positions: 0.
- Cash-only configuration: still safe.
- Orders submitted by the preflight: 0.

The USD 0.14 decline is the account's observed net balance change over the two mechanical test cycles. It is not a strategy P&L estimate. Do not attribute it solely to fees without the end-of-day fee activities and full fill/fee reconciliation.

## Fees and accounting

Alpaca documents crypto taker fees of 25 bps at the lowest 30-day volume tier and states that fees on BTC/USD buys are charged in the credited crypto asset, while sell fees are charged in USD. The observed gross-fill to net-position differences are consistent with a 25 bps base-asset fee, but the Paper account audit on the same trading day returned no CFEE/FEE activities. Alpaca says crypto fees are calculated and posted at end of day, so same-day absence is expected.

Therefore:
- Do not close the ledger or declare realized P&L until the end-of-day CFEE/FEE activity is available and matched to each execution.
- The fee resolver must match each fee to its exact execution identifier.
- Unknown or delayed fees remain pending; they must not be silently treated as zero.

## Activity audit

The read-only audit retrieved four FILL activities from the two round trips and one JNLC cash journal for USD 100,000 dated 2026-09-28. The JNLC record is staged as pending capital reconciliation. It is not treated as a user deposit.

## Determinism policy

- Strategy decisions, signal selection, sizing, risk controls and order-state transitions must be deterministic for identical versioned inputs and state.
- No unseeded random choices in the trading logic.
- If an internal diagnostic uses pseudo-randomness, record a fixed seed and all generated inputs so the run is reproducible.
- External market data and broker execution events are observed inputs. The system must tolerate partial, delayed, rejected and cancelled fills rather than assuming a single deterministic fill.
- Alpaca's Paper simulator itself documents that marketable orders may receive partial fills of random sizes 10% of the time. This is simulator behavior; Rocket Trader does not inject that randomness into its strategy.

## Evidence links

- Cash-only account configuration: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42886767872
- Capped Paper crypto smoke test: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42888046127
- Prior smoke-order recovery: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42887604404
- Read-only post-test account check: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42888781248
- Read-only account activity audit: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42888357128
- Capital journal handling and runtime health: https://github.com/marcodurzov/Rocket_Trader/pull/69

## Next gates

1. Re-run the activity audit after end of day and confirm CFEE/FEE activities for both crypto buys and sells.
2. Verify exact execution-to-fee matching and post the fills through the Paper ledger bridge.
3. Test cancellation/reconciliation methods as adapter-owned operations rather than smoke-script-only operations.
4. Add equity bracket lifecycle tests after verifying order legs, cancellation, and cash-only sizing.
5. Resume strategy research. No strategy can be promoted until it passes the unchanged out-of-sample, cost-stress and Paper evidence gates.
