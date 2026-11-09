# Rocket Trader

Autonomous trading research and execution project. Current stage: **research + safety infrastructure; not yet an autonomous Paper Trading service**.

## Governing decisions
- Authoritative user decisions: `ROCKET_TRADER_BASELINE_DECISIONS_v0_2.md`.
- Current implementation and blockers: `ROCKET_TRADER_PROJECT_STATUS_v0_1.md`.
- Investment research standards: `ROCKET_TRADER_INVESTMENT_RESEARCH_FRAMEWORK_v0_1.md`.
- Jefe Maestro methodology transfer: `ROCKET_TRADER_JEFE_MAESTRO_TRANSFER_SPEC_v0_1.md`.

## Capital policy
Initial capital is MXN 1,000. Retain 100% of realized net trading profits until earned trading growth first reaches MXN 100,000; only then does the target 50/10/40 reinvestment/reserve/personal allocation activate. Deposits do not count as earned growth. The MXN 100,000 floor is a withdrawal policy, not a guarantee against market losses.

## Safety
- Alpaca Paper only during development.
- LIVE orders disabled.
- No leverage, margin, shorts, options, futures or perpetuals.
- Research pass is not Paper approval; Paper approval is not LIVE authorization.
- GitHub Actions is not a continuous trading runtime.

## Research
All strategies must be evaluated out of sample, net of realistic costs, against same-period benchmarks and under data-quality, uncertainty and multiple-testing controls. Famous traders/investors provide hypotheses, not automatic trade signals. No strategy is currently approved.

## Current status
See `ROCKET_TRADER_PROJECT_STATUS_v0_1.md` for merged work, research results, latest CI evidence and remaining blockers.
