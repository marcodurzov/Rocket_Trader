# T05 Forward Shadow Test — Pre-registration v0.1

**Registered:** 2026-11-22, before the first forward record exists.
**Recorder:** `rocket_trader_t05_forward_shadow.py`, workflow `rocket-trader-t05-forward-shadow.yml`.
**Evidence store:** append-only branch `forward-evidence`, files `forward/t05/YYYY-MM.json` (one per completed month, never overwritten; each carries a SHA-256 of its content).
**Mode:** shadow only. No orders, no Paper approval.

## Why

The historical T05 run (`T05-ALLOC-MONTHLY-v0.1`, run `45051199433`) produced 0/5 passes on both Alpaca SIP and Yahoo. A secondary, *not pre-registered* observation was that the 210-session SMA trend rules cut full-period maximum drawdown from about −27% (equal weight) to about −11%, with lower CAGR and similar Sharpe. Re-labelling that as a pass would be post-hoc. The only clean way to test it is on data that did not exist when the rules were fixed: forward months.

## Fixed design

- Rules and parameters exactly as `T05-ALLOC-MONTHLY-v0.1` (5 rules + equal-weight benchmark, same universe). No changes; any change is a new experiment.
- Each record: signal = close of the last session of the completed month; weights take effect at the next session open.
- Forward returns are computed later from subsequent prices (same open-to-open clock, 5 bps/side, 2x stress).

## Hypotheses evaluated at the first review (no earlier than 12 recorded months; final at 24)

- **F1 (primary, risk):** `sma210_trend_equal_weight` has a smaller maximum drawdown than the equal-weight benchmark over the forward period, with forward CAGR no worse than benchmark CAGR minus 3 percentage points per year.
- **F2 (return):** any of the 5 rules beats the benchmark net of 2x costs; Holm-adjusted across 5.

A forward period without a material market drawdown makes F1 uninformative; record that outcome as "not testable yet", not as a pass.

## Limits

12–24 monthly observations have low statistical power. A pass here is necessary but not sufficient for any Paper approval; costs, small-capital feasibility and an independent review are still required.
