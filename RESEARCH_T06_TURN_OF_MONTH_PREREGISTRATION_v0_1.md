# T06 Turn-of-Month Calendar Research — Pre-registration v0.1

**Experiment ID:** `T06-TOM-v0.1` · **Registered:** 2026-11-23, before any run · **Code:** `rocket_trader_calendar_research_t06_v0_1.py`
**Mode:** research only; no orders; no promotion from this run alone.

## Why this, and why it is not a repeat
Tranche T06 (calendar/event) has never been run. The turn-of-month (TOM) effect was published in 1987–1988 (Ariel; Lakonishok & Smidt), so 2016–2026 data are out-of-sample relative to its discovery. The schedule is known in advance (no look-ahead). Holding only ~4 sessions per month (~19% exposure) fits the survival/capital-protection objective if the effect is real and survives costs.

## Fixed design
- Universe: DIA, EEM, EFA, GLD, IWM, QQQ, SPY, TLT, plus a daily equal-weight basket (reference). Family size **9**.
- Data: 10 years adjusted daily bars; two independent runs, Alpaca SIP and Yahoo; XNYS quality gate; exact-timestamp alignment. First and last partial months excluded.
- TOM days: the last session of each month and the first **3** sessions of the next. Each TOM day earns open(t)→open(t+1) (held from the open of day −1 to the open of day +4). Other days: cash at 0%.
- Primary statistic: mean daily return on TOM days minus non-TOM days, full window; one-sided **circular-shift permutation** p-value (all shifts ≥5 sessions), Holm-Bonferroni at alpha 0.05.
- Costs: 5 bps/side per entry and exit (≈ 24 round trips per year), 2x/3x stress.

## Pass criteria (all required, and on **both** sources)
1. Holm-adjusted p ≤ 0.05.
2. Positive TOM − non-TOM difference in ≥4 of 5 chronological folds.
3. Positive difference in the final 20% holdout.
4. Net mean return per TOM day > 0 at 2x costs.

A pass permits only a separate review (costs from real Paper fills, small-capital feasibility, forward observation); it never enables orders. Parameters (window −1/+3, 5 bps) are fixed; any change is a new experiment ID.

## Declared limitations
Ten years give ~120 month-ends; daily open-to-open returns approximate the classic close-to-close window; dividends are in adjusted prices; Paper fills may differ around month-end flows.
