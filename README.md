[README.md](https://github.com/user-attachments/files/33259974/README.md)
# Rocket Trader — Signal Research v0.3

Research-only update. No trading API/client is imported; this script cannot submit orders.

## Install in the existing repository

1. Replace the repository-root file `rocket_trader_signal_research.py` with the file in this package.
2. Put `.github/workflows/rocket-trader-signal-research.yml` into the same path in the repository.
3. Confirm `rocket_trader_engine.py`, `rocket_trader_market_data.py`, `requirements.txt`, and `requirements-alpaca.txt` remain at repository root and are the working versions already used by Rocket Trader.
4. Commit and push.
5. Open GitHub Actions → `Rocket Trader - Signal Research v0.3` → `Run workflow`.

## What changed

- Signal at bar close, entry at next bar open.
- Exit at the close of the fifth holding bar by default.
- Non-overlapping long-only positions.
- Training labels are constrained to data inside each training fold.
- Threshold chosen using only the earlier OOS selection segment; final later OOS segment is held out from threshold selection.
- Round-trip transaction friction plus slippage charged on both entry and exit.
- Holdout must pass minimum trade/fold, profit factor, drawdown, and same-window buy-and-hold checks to get `research_pass=true`.
- Writes `rocket_trader_signal_research_results.json`, uploaded by Actions as an artifact.

## Important

A workflow that completes successfully means the code ran, not that the strategy is profitable. A research pass is not authorization to trade live. Keep execution disabled and continue paper testing before considering any live trading.
