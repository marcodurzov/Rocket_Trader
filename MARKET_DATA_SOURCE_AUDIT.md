# ETF market-data source audit

## Why this exists

The 10-year ETF research runs currently use Yahoo Finance daily history
(`auto_adjust=True`, `actions=True`, `repair=False`). That is useful for
research, but it is not an independent validation against the market-data
provider configured in Rocket Trader.

The current market-data client defaults to Alpaca IEX. The cross-check added
in `rocket_trader_alpaca_yahoo_etf_crosscheck.py` compares the same eight ETF
symbols on common daily sessions:

`DIA EEM EFA GLD IWM QQQ SPY TLT`

- Yahoo: auto-adjusted daily close, actions enabled, `repair=False` (the repair path caused a reproducible read-only-array error in the first live audit).
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


## Live audit update — 2026-11-10

The first live run (42920786498; artifact 13812205814) failed for all symbols because `repair=True` triggered `ValueError: output array is read-only`. PR #96 set `repair=False` and added a regression test. The subsequent live run (42922974687; artifact 13812508089) retrieved all eight ETFs successfully, but only 1,581 common sessions were available (2020-07-27 to 2026-11-09). Yahoo had 2,512 sessions; Alpaca IEX had 1,582. Consequently, 0/8 symbols passed the ten-year source-coverage diagnostic. SIP remains unavailable to this account (`NOT_ENTITLED`). This is a completed retrieval with a failed coverage gate, not a successful 10-year validation.

On the common window, return correlations were high (0.99835–0.99975), but cumulative-return differences ranged from 1.3 bps (DIA) to 220.5 bps (SPY). Do not infer full source parity from correlation alone. Investigate corporate-action/adjustment methodology and consider a licensed full-history source. Do not splice sources or lower the coverage threshold.


## Optional Tiingo EOD research source — implementation status

The equity research runner now supports an optional Tiingo EOD adjusted-history source. It consumes Tiingo's `adjOpen`, `adjHigh`, `adjLow`, `adjClose` and `adjVolume` fields, uses the Authorization Token header, and applies the same full-requested-period, row-count, weekday-coverage and gap checks used by the other providers. The token is read only from `TIINGO_API_TOKEN`; never put it in source, logs or chat.

The default source remains unchanged. Selecting TIINGO requires a valid token and sufficient plan history. A Starter account with only five years cannot pass a ten-year request; no fallback or silent partial-history acceptance occurs. The adapter has mocked contract tests only until a real token and eligible plan are configured. No subscription has been purchased.


## Optional three-source parity audit (Yahoo / Alpaca / Tiingo)

The Alpaca-vs-Yahoo cross-check now accepts an optional `TIINGO_API_TOKEN` GitHub Actions secret. When configured, it fetches Tiingo adjusted daily closes for the same requested dates and adds two independent comparisons per ETF: Tiingo vs Yahoo, and Tiingo vs Alpaca. It reports source session counts, common-session coverage, daily-return correlation, absolute return differences, cumulative-return divergence and diagnostic gates under explicit provider names.

If the token is absent, Tiingo is explicitly marked as not requested and the original Yahoo/Alpaca audit runs unchanged. If a token is present but Tiingo data is missing, malformed, too short, or not sufficiently overlapping, the Tiingo comparison is recorded as an error or a failed coverage gate; the report does not silently pass or splice histories. The current Alpaca IEX history begins in 2020 for this account, so a full 10-year Tiingo-vs-IEX overlap is expected to fail the 95% per-source coverage gate until Alpaca entitlement/history changes. That is intentional: it prevents the system from calling a partial common period a ten-year three-provider validation.

No Tiingo token or subscription is configured by this change. No provider is treated as ground truth merely because its data are adjusted; corporate-action and adjustment methodology still need review.


## Date-level divergence diagnostics

Each two-provider comparison now records the ten largest absolute daily-return differences with exact session date, Yahoo return, Alpaca return and signed Alpaca-minus-Yahoo basis-point difference. It also records the ten largest divergences between normalized adjusted-close paths after anchoring both sources at the first common session.

These are investigation leads, not corporate-action attribution. A large one-day discrepancy can be caused by a split/dividend adjustment, symbol mapping, bad/missing bar or vendor correction; the report does not claim which cause applies. Follow-up must inspect provider corporate-action records and raw/unadjusted bars around each flagged session. Never auto-correct or splice the series from these diagnostics alone.


## Raw-price vs adjusted-price factor reconciliation

The audit now also requests Yahoo raw `Close` and adjusted `Adj Close` (with `auto_adjust=False`, `actions=True`, `repair=False`), plus Alpaca raw daily bars and the existing `Adjustment.ALL` series. On common sessions it computes each provider's adjustment factor (`adjusted_close / raw_close`), normalizes the relative factor ratio at the first common session, and reports the largest daily factor-step changes. It separately compares raw-price daily returns and normalized raw-price paths.

This allows the investigation to distinguish:
- raw underlying price disagreement between providers;
- adjustment-factor divergence (dividend/split/capital-gain treatment or correction);
- a mixture of both.

The output still does not attribute a mismatch to a specific corporate action. Provider action records, ex-dates, amounts and timestamps must be checked independently. The raw and adjusted series are audit evidence only; never auto-repair, overwrite history, or splice providers from this output.
