# Capital Feasibility Analysis v0.1 (reopened by the user 2026-11-23)

**Status:** analysis only. It changes no capital policy, authorizes no deposit, order or Live trading, and is not financial advice. Arithmetic is reproducible with `research/capital_feasibility_calc_v0_1.py`.

## 1. Inputs (checked 2026-11-23)

| Input | Value | Source |
|---|---|---|
| Seed capital | MXN 1,000 | Baseline decisions |
| USD/MXN | ≈18.6 (mid-November 2026 averages 18.49–18.63) | eldolar.info daily averages |
| Seed in USD | ≈USD 53.8 | computed |
| Live account minimum (individual, non-US) | none | Alpaca support: no minimum deposit for individual accounts |
| Fractional equities | minimum USD 1 notional per order, market/limit/stop, time-in-force DAY | Alpaca fractional-trading docs/support |
| Crypto minimum | dynamic USD-notional minimum per asset (Alpaca docs show both 1/price and 10/price formulas in different versions — verify per asset via the assets endpoint before any live use) | Alpaca crypto-trading docs |
| Equity regulatory fees | sells only; accrued intraday and charged end of day, total rounded **up** to the next USD 0.01 | Alpaca regulatory-fees docs |
| Crypto commission | Tier 1: 15 bps maker / 25 bps taker per side | `ROCKET_TRADER_CRYPTO_COST_REVIEW_v0_1.md` |
| Quoted half-spreads | ETFs 0.13–0.80 bps median; BTC/ETH ≈1.3 bps; SOL ≈4.4 bps | Spread study run 45190318213 |

## 2. Can MXN 1,000 be operated at all?

| Question | Answer at MXN 1,000 (≈USD 53.8) | Annotation |
|---|---|---|
| Hold the 8-ETF universe | Yes, ≈USD 6.7 per ETF with fractional shares | Requires a fractional/notional order path; Core currently blocks fractional bracket orders (engineering gap) |
| Rebalance precisely | Poorly: a USD 1 minimum order means drifts below ≈15% of a position cannot be corrected | At MXN 7,500 the threshold falls to ≈2% |
| Fixed fee drag | ≈0.22% of capital per year from one penny of rounded regulatory fees on each of ~12 monthly sell days | ≈0.03% at MXN 7,500; ≈0.01% at MXN 25,000 |
| Crypto fee drag | ≈0.6%/year at 20% monthly turnover with taker fees | Independent of size (percentage fee) |
| Spread drag | negligible (sub-bp ETF spreads × low turnover) | Measured, not assumed |

**Conclusion:** MXN 1,000 is technically operable for 1–3 positions or a coarse 8-ETF portfolio, with ~0.2%/yr unavoidable fee drag. A practical floor for a precisely rebalanced 8-ETF portfolio is about **MXN 7,500**. Below that, simplicity (fewer positions) beats diversification.

## 3. Is the MXN 100,000 earned-growth milestone reachable?

Earned growth counts only the seed plus realized net P&L; deposits do not count. With operating capital C (seed + any deposits) compounding at net annual return r, the milestone needs P&L ≥ MXN 99,000, i.e. years = ln(1 + 99,000/C) / ln(1 + r):

| Operating capital C (MXN) | r = 5% | r = 8% | r = 12% | r = 20% |
|---|---|---|---|---|
| 1,000 (seed only) | 94.4 | 59.8 | 40.6 | 25.3 |
| 10,000 | 49.0 | 31.0 | 21.1 | 13.1 |
| 25,000 | 32.8 | 20.8 | 14.1 | 8.8 |
| 50,000 | 22.4 | 14.2 | 9.6 | 6.0 |
| 100,000 | 14.1 | 8.9 | 6.1 | 3.8 |

Context: the tested equal-weight ETF benchmark had a full-period Sharpe of ~0.70 (T05); **no tested strategy has shown a statistically significant edge over it**, so planning on 20%+ net annual returns is not supported by any evidence in this repository.

**Conclusion:** from MXN 1,000 alone the milestone takes decades at market-like returns. The timeline is driven by operating capital, not by the seed. More capital also means more money at risk — losses scale the same way.

## 4. Options for the user (decision is the user's; no recommendation to deposit)

| Option | What it means | Trade-off |
|---|---|---|
| A. Keep MXN 1,000 as a validation stake | Use it to prove the full live pipeline (fills, fees, FX, reconciliation) on real money once Live is separately authorized | Low risk; milestone effectively out of reach; ~0.2%/yr fee drag |
| B. Plan staged capital later | Only after sustained Paper evidence and an approved strategy, consider adding capital in steps (e.g. MXN 7,500 → 25,000) | Faster P&L in absolute terms; proportionally larger possible losses |
| C. Redefine the milestone | e.g. measure success as % return vs benchmark rather than a fixed MXN amount | Changes a binding baseline decision; needs explicit user decision |

## 5. Engineering implications (independent of the decision)

1. Add a fractional/notional equity order path (DAY time-in-force, USD 1 minimum, system-managed exits) before any small-capital live use; keep it default-deny.
2. Enforce per-asset minimum order checks (equity USD 1; crypto per-asset minimum from the assets endpoint).
3. Model the end-of-day penny rounding of regulatory fees in research cost models for small accounts.
4. Prefer few positions below ≈MXN 7,500.

Sources: Alpaca support/docs on minimum deposit, fractional trading, crypto order minimums and regulatory fees; eldolar.info USD/MXN daily averages (2026-11-12 … 2026-11-18).
