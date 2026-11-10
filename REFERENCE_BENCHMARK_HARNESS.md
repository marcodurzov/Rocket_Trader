# Reference benchmark harness

## Why this exists

Rocket Trader must not judge a strategy in isolation. Every candidate should be compared with relevant, transparent reference families on the same instrument, exact dates and cost assumptions. The registry in `research/reference_strategy_registry_v0_1.json` identifies source-backed hypotheses; this harness turns several of those families into reproducible daily reference curves.

## Input contracts

Prices CSV:

```csv
date,symbol,close
2025-01-02,SPY,590.12
2025-01-03,SPY,591.34
```

Candidate CSV:

```csv
date,symbol,gross_return,turnover
2025-01-02,SPY,0.0000,1.0
2025-01-03,SPY,0.0021,0.0
```

- One row per symbol/date; duplicates are rejected.
- Candidate gross returns and one-way turnover must be point-in-time, long-only, and generated without look-ahead.
- Candidate and price date arrays must match exactly. The harness rejects mismatched windows instead of silently intersecting them.
- Turnover is the absolute one-way change in NAV exposure, bounded to [0, 1]. Cost is charged as turnover × cost_bps_per_side.
- At least 253 daily observations are required to include the 252-day time-series momentum reference.

## Included reference curves

- Cash: zero return, zero turnover.
- Buy-and-hold: same asset and date window, with entry and terminal liquidation costs.
- 252-day time-series momentum: long when trailing 252-day price momentum is positive, otherwise cash.
- 63-day momentum skipping the most recent 21 days: long when the 3-month ex-last-month return is positive, otherwise cash.
- 50/200-day moving-average trend: long when the 50-day average exceeds the 200-day average, otherwise cash.

These are testable adaptations of published momentum/trend research, not a reproduction of the authors' personal portfolios or published fund returns. Qualitative trader stories (for example, Livermore or Buffett) cannot create numerical benchmark records without a verifiable machine-readable trade history.

## Output and interpretation

The report includes compounded return, CAGR, annualized volatility, zero-risk-free Sharpe, maximum drawdown, win rate, turnover and estimated transaction costs for the candidate and each reference. It also reports candidate-minus-reference differences.

The output is always `COMPARISON_ONLY`. It does not calculate statistical significance, approve a strategy, or enable orders. A favorable comparison is necessary context, not sufficient proof of edge. Before promotion, research still requires chronological holdouts, multiple-testing correction, realistic empirical spreads/slippage/fees, robust data-quality controls and Paper validation.

## Example

```bash
python rocket_trader_reference_benchmark.py \
  --prices research/prices_daily.csv \
  --candidate research/candidate_daily_returns.csv \
  --cost-bps-per-side 5 \
  --output research/reference_benchmark_report.json
```

The 5 bps example is illustrative only; use measured costs for the instrument, venue, feed and execution method. Do not treat placeholder costs as empirical validation.
