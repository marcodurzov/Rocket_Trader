# T05 Monthly Allocation Research — Pre-registration v0.1

**Experiment ID:** `T05-ALLOC-MONTHLY-v0.1`
**Registered:** 2026-11-22, committed before any live-data run of this family.
**Code:** `rocket_trader_allocation_research_t05_v0_1.py` (tests: `rocket_trader_allocation_research_t05_v0_1_test.py`).
**Mode:** research only. No orders, no Paper approval, no candidate promotion from this experiment alone.

## Why this family, and why it is not a repeat

Tranches T02 (single-asset trend/breakout, daily) and T03 (mean reversion) and a daily cross-sectional top-1 momentum were already tested and produced zero Holm-significant candidates. T05 ("allocation and risk overlays") in `research/strategy_experiment_matrix_v1.json` has never been run. It differs materially: portfolio-level, monthly rebalancing, multi-asset diversification, low turnover (more robust to unverified costs). It is registered once; changing any parameter below creates a new experiment ID.

## Fixed design

- **Universe:** DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT (long-only, no leverage; unallocated weight = cash at 0% yield).
- **Data:** 10 years of adjusted daily bars. Run twice, independently: Alpaca historical SIP (`Adjustment.ALL`, end ≥16 min old) and Yahoo (`auto_adjust=True`). Exact-timestamp inner join; each symbol must retain ≥95% of its sessions. XNYS data-quality gate from equity research v0.4 must pass.
- **Clock:** signal from the close of the last session of each month; trade at the next session open; daily open-to-next-open returns; weights drift between rebalances; costs charged on traded weight; final position liquidated at the last available open.
- **Warm-up:** first 253 sessions excluded; no signal may use fewer than 252 sessions of history (fails closed).
- **Benchmark (primary):** equal-weight 8-ETF portfolio, same monthly clock, drift and costs. References reported only: cash (0%), SPY buy-and-hold without costs.
- **Costs:** 5 bps per side base (unvalidated assumption); 2x and 3x stress.

## Hypothesis family (size 5, Holm-Bonferroni, alpha 0.05)

| ID | Rule |
|---|---|
| `inverse_vol_63d` | Weights ∝ 1/σ of 63-day daily returns, fully invested |
| `sma210_trend_equal_weight` | 1/8 per ETF whose close > 210-session SMA, otherwise that slice in cash |
| `dual_momentum_top3_12_1` | Score = return from t−252 to t−21; hold top 3 with score > 0 at 1/3 each; otherwise cash |
| `vol_target_equal_weight_10pct` | Equal weight scaled by min(1, 10% / 63-day annualized EW portfolio vol) |
| `sma210_trend_inverse_vol` | Inverse-vol weights, zeroed for ETFs below their 210-session SMA |

## Test and pass criteria (all required for "pre-screen pass")

1. Final holdout = last 20% of evaluation sessions. One-sided moving-block bootstrap (block 21, 5,000 reps) p-value for positive mean log excess vs benchmark; Holm-adjusted p ≤ 0.05.
2. Holdout excess total return > 0 at 2x costs.
3. Positive excess in at least 4 of 5 equal chronological folds over the full evaluation period.
4. Full-period Sharpe ≥ benchmark Sharpe.
5. **Replication:** criteria 1–4 must hold on both the Alpaca SIP and the Yahoo run.

Passing still does **not** approve Paper trading. It only allows a separate review including the QQQ/SPY dividend-record issues, empirical costs and small-capital feasibility.

## Known limitations declared in advance

- The last ~2 years (holdout) overlap the holdout already observed by earlier families. This family was not tuned on it, but the window is not virgin; treat any pass as weaker evidence and require forward Paper observation.
- 10 years contains few independent bear markets; monthly strategies have few rebalances (~95), so power is low. A negative result is expected to be common and must be recorded, not re-tuned.
- QQQ/SPY show unresolved dividend-record differences (~±1.6–1.8% cumulative over 10 years); the two-source replication requirement exists partly for this reason.
- MXN 1,000 (≈ USD 50–60) would require fractional shares to hold several ETFs; small-capital feasibility is deferred by user decision and is not evaluated here.
