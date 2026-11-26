# T05 Independent Historical Sample 2005–2016 — Pre-registration v0.1

**Experiment ID:** `T05-HIST-2005-2016-v0.1` · **Registered:** 2026-11-26, before any run · **Code:** `rocket_trader_allocation_research_t05_hist_v0_1.py`
**Mode:** research only; no orders; no promotion.

## Why
Every earlier Rocket Trader experiment used data from 2016-11 onward (checked against `HISTORY.md`, the research program and all `research/*` branches on 2026-11-26). The window **2005-11 → 2016-11-18** has never been used, includes the 2008 crisis, and lets the *unchanged* T05 rules be tested out of sample. The T05 rules were fixed on 2026-11-22 without this window.

## Fixed design
- Universe, rules, parameters, clock, costs (5 bps/side, 2x/3x stress), folds and Holm family: identical to `T05-ALLOC-MONTHLY-v0.1` (no changes).
- Data: Yahoo adjusted daily bars, 11 years ending 2016-11-18; XNYS quality gate; exact-date alignment. Single source (Alpaca historical SIP does not cover this period) — a declared limitation.

## Hypotheses
1. **Return family (replication of T05):** the same 5 hypotheses and pass criteria as T05 (Holm ≤0.05, 2x-cost holdout excess > 0, ≥4/5 positive folds, full-period Sharpe ≥ benchmark).
2. **Drawdown control (primary for risk overlays):** for `sma210_trend_equal_weight` and `sma210_trend_inverse_vol`, versus the equal-weight benchmark over the full window: maximum drawdown at least **10 percentage points smaller**, CAGR at most **3 pp/yr lower**, Sharpe at most **0.05 lower**. All three required.

A drawdown-control pass would support (not approve) a risk-overlay role; it still requires the forward shadow evidence (`RESEARCH_T05_FORWARD_SHADOW_PREREGISTRATION_v0_1.md`), costs from real fills and an independent review. Any parameter change is a new experiment.
