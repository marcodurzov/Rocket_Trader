# Research execution-timing correction — 2026-11-10

## Why this correction was necessary

The prior equity v0.2 and crypto v0.1 research pipelines computed signals from completed daily closes, shifted the signal one bar, and then applied it to close-to-close returns. A close-derived signal cannot normally execute at that same close. Applying the next signal to the following close-to-close return can include the close-to-next-open gap before the order could fill.

This is a timing inconsistency, not a minor formatting issue. It can distort returns in either direction. All previous close-to-close results are superseded for strategy-selection purposes.

## Correct execution model

For each bar (t):
1. Compute the signal using information available at the completed close of bar (t-1).
2. Enter/adjust at the open of bar (t).
3. Measure the held interval from open (t) to open (t+1).
4. Apply transaction costs when the position changes at open (t).
5. Liquidate the final held interval at the last available open; do not invent a forward return beyond the dataset.

The evaluation preserves the actual position immediately before each train/validation/holdout boundary. It does not charge an artificial new entry at every window boundary.

Regression test: with opens [100, 200, 220, 242] and a signal entered at the second open, the strategy earns 10% from 200 to 220, not the unavailable 100% overnight gap from 100 to 200.

## Corrected equity results — v0.3

Source: Yahoo Finance adjusted daily OHLC, research-only. Universe: DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT.

- Data quality: pass for all 8 ETFs.
- Final-holdout multiple-testing family: 49 hypotheses.
- Holm-Bonferroni significant: 0.
- Pre-screen passes: 0.
- Cross-sectional top-1 momentum final holdout: +41.0% versus +31.2% for equal-weight buy-and-hold.
- Cross-sectional excess 5th percentile: -30.1%.
- Raw bootstrap p-value: 0.3921.
- Holm-adjusted p-value: 1.0.

The cross-sectional point estimate is positive, but its uncertainty is wide and the statistical test does not support an edge. The single-asset momentum/trend candidates generally underperformed their same-asset buy-and-hold benchmarks in the final holdout. No candidate is promoted.

Workflow: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42890328376

## Corrected crypto results — v0.2

Source: Alpaca CryptoFeed.US, five years. BTC/USD and ETH/USD pass data quality; SOL/USD remains excluded due to its coverage gap.

- Data quality: fail for the full requested universe because SOL/USD is excluded.
- Eligible final-holdout multiple-testing family: 13 hypotheses.
- Holm-Bonferroni significant: 0.
- Pre-screen passes: 0.
- Cross-sectional top-1 momentum final holdout: -29.5%.
- Raw bootstrap p-value: 0.4267.
- Holm-adjusted p-value: 1.0.

The eligible BTC/ETH trend and momentum candidates did not establish a statistically reliable positive edge. No candidate is promoted.

Workflow: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42890334990

## Reproducibility and determinism

- Signals, weights, costs and return alignment are deterministic for identical input data, code and parameters.
- Bootstrap diagnostics use fixed, recorded seeds; they do not influence strategy selection by maximizing a random search.
- The corrected timing regression test explicitly covers the overnight-gap case.
- External broker fills remain observed events; the backtest does not assume every order fills at a single idealized price.

## Decision

**No strategy approved.** The next research tranche should test pre-registered long-only mean-reversion hypotheses and regime filters using this corrected next-open execution model, with the same chronological holdout, realistic costs, 2x cost stress, bootstrap uncertainty and Holm correction. ML/RL remains deferred until simple hypotheses produce reproducible out-of-sample evidence.


## Mean-reversion tranche — corrected next-open v0.4/v0.3

Three fixed long-only mean-reversion hypotheses were added: RSI(2)/SMA200, Bollinger(20,2), and five-day downside z-score. They use the same next-open execution model, costs, chronological holdout and Holm correction.

Equity:
- 8 ETFs, 73 hypotheses, 0 Holm-significant, 0 pre-screen passes.
- TLT Bollinger(20,2) holdout return +8.83%, excess over TLT buy-and-hold +8.95 pp, 10 entries, Holm-adjusted p=1.0.
- RSI2 and z-score variants mostly underperformed their same-asset buy-and-hold benchmarks.

Crypto:
- BTC/USD and ETH/USD eligible; SOL/USD excluded for the 416-day gap.
- 19 hypotheses, 0 Holm-significant, 0 pre-screen passes.
- BTC RSI(2) holdout +4.57%, only 4 entries, Holm-adjusted p=1.0.
- Bollinger and z-score variants were negative in BTC and ETH holdouts.

These are exploratory results only. No strategy is promoted.

Workflows:
- Equity v0.4: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42892147119
- Crypto v0.3: https://github.com/marcodurzov/Rocket_Trader/actions/runs/42892147177
