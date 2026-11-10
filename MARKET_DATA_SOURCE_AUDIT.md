# ETF market-data source audit

## Why this exists

The 10-year ETF research runs currently use Yahoo Finance daily history
(`auto_adjust=True`, `actions=True`, `repair=True`). That is useful for
research, but it is not an independent validation against the market-data
provider configured in Rocket Trader.

The current market-data client defaults to Alpaca IEX. The cross-check added
in `rocket_trader_alpaca_yahoo_etf_crosscheck.py` compares the same eight ETF
symbols on common daily sessions:

`DIA EEM EFA GLD IWM QQQ SPY TLT`

- Yahoo: auto-adjusted daily close, actions and repair enabled.
- Alpaca: daily close with `Adjustment.ALL`, using the explicitly selected
  `IEX` or `SIP` feed.
- The comparison reports source coverage, daily-return correlation, mean/p95/
  maximum absolute return differences, normalized close divergence and
  cumulative-return divergence.
- Missing or malformed history is reported per symbol; no missing data is
  silently filled.

Alpaca's API defaults historical bars to raw (unadjusted) prices unless an
adjustment is requested. Its documentation defines `all` as split, dividend
and spin-off adjustments. The feed is also material: IEX is the Investors
Exchange feed, while SIP represents all US exchanges.

References:
- https://docs.alpaca.markets/us/reference/stockbars
- https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html

## Diagnostic thresholds

The initial audit labels a symbol as diagnostically consistent only if all
these conditions hold:

| Metric | Initial threshold |
|---|---:|
| Common daily sessions | >= 1,000 |
| Common coverage in each source | >= 95% |
| Daily-return correlation | >= 0.995 |
| 95th percentile absolute daily-return difference | <= 20 bps |

These are source-consistency diagnostics, not strategy-performance acceptance
criteria. They are deliberately visible in the JSON output. A diagnostic pass
does not approve a strategy or authorize Paper orders.

## Costs remain a separate unresolved gate

The current ETF research assumptions are:

- Commission: 0 bps per side.
- Half-spread: 2.5 bps per side.
- Slippage: 2.5 bps per side.
- Base modeled cost: 5 bps per side.
- Stress scenario: 2x modeled cost.

The source cross-check does **not** validate those assumptions. It does not
measure historical bid/ask spreads, market impact, commissions, queue position,
partial fills or realized execution slippage.

Before any ETF strategy can pass the cost gate, Rocket Trader must compare
time-stamped executable bid/ask data with order arrival and actual Paper fills,
then calculate realized implementation shortfall and fees by fill. The 5 bps
assumption must remain labeled as unverified until that evidence exists.

## What this audit does not prove

- IEX daily bars are not a full-market consolidated feed. If the account has
  SIP entitlement, run the same workflow with `feed=SIP` as a separate source
  comparison.
- Alpaca historical bars are market-data records, not the broker's execution
  ledger.
- Matching adjusted close returns does not establish that intraday prices,
  quotes, spreads or fill prices match.
- This audit cannot establish profitability, out-of-sample robustness or
  permission to promote a strategy.

## Running the audit

GitHub Actions -> **Rocket Trader - Alpaca vs Yahoo ETF History Audit** ->
Run workflow. The default is ten years and IEX. SIP can be selected only if the
Alpaca account is entitled to that feed. The workflow uploads the JSON report
as an artifact and never creates or modifies orders.
