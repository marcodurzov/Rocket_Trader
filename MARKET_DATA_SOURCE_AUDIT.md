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


## Before/after adjustment-factor evidence

For each largest adjustment-factor step, the report now includes the previous common session, both providers' adjustment factors on the previous session, their factor ratio, and the same fields on the event session. This makes it possible to compare the exact observed factor step with a fund's declared ex-date distribution divided by the previous raw close.

The ratio is still normalized to the first common session for the cumulative divergence metric. Before/after factor fields are the unnormalized provider factors and ratio for those exact sessions. They are diagnostic evidence only; corporate-action attribution still requires checking the issuer's official event record and source raw bars.


## Event-level cash distribution cross-check

Yahoo raw/adjusted history now also retains its `Dividends` and `Stock Splits` action fields. For each largest adjustment-factor step, the report includes the prior raw close from both providers, the Yahoo cash distribution and split ratio recorded on the event session, and a first-order implied cash-distribution adjustment in basis points (`cash distribution / prior Yahoo raw close × 10,000`).

This lets the audit compare the observed provider factor step with the issuer's declared cash distribution scale. The calculation is a diagnostic approximation, not an adjustment formula to apply to prices. It does not replace official issuer action records or explain provider-specific methodology, taxes, return-of-capital, capital gains, special distributions, or correction timing. No automatic adjustment is applied.


## 2026-11-11 — Event-level investigation of IEX/Yahoo divergence

Latest inspected crosscheck artifact: workflow `42957082760`, artifact `13827412712`.

### Feed semantics
Alpaca documents IEX as one exchange (~2.5% of market volume) and SIP as all US exchanges / consolidated tape (~100% coverage):
- https://docs.alpaca.markets/us/v1.4.2/docs/historical-stock-data-1
- https://docs.alpaca.markets/us/docs/market-data-faq

Therefore IEX daily bars are not an acceptable substitute for consolidated closing prices in full-market research.

### Raw price vs adjustment factors
- SPY: cumulative return difference +218.90 bps; max relative adjustment-factor divergence 0.004489%; max raw normalized-close divergence 0.8381%. Largest raw return differences were 2025-04-09 (-116.75 bps), 2025-04-10 (+100.69 bps), 2024-12-24 (+93.92 bps), 2024-12-23 (-91.53 bps). The mismatch is primarily raw-price/feed-related in this sample; exact trade-level cause remains unknown.
- QQQ: cumulative difference +89.97 bps; max adjustment-factor divergence 0.327819%. On 2022-09-19 Yahoo recorded $0.519 cash distribution; prior raw close $289.32 implies ~17.94 bps, while the relative factor step was 17.68 bps. This is distribution-scale evidence, not conclusive provider attribution. Yahoo history: https://finance.yahoo.com/quote/QQQ/history/.
- TLT: cumulative difference +26.02 bps; max adjustment-factor divergence 0.422290%. Official iShares records $0.343177 ex-date 2026-11-02: https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf. Prior Yahoo raw close $81.84 implies ~41.93 bps. Audit recorded no Yahoo dividend event/factor step, while Alpaca relative factor step was 41.7148 bps. This is consistent with a missing/late Yahoo event adjustment in that capture; re-query before attribution.
- DIA, EEM, EFA, GLD, IWM: smaller factor divergences, but raw normalized close differences still reach roughly 0.3–0.72%.

### Decision
- The mismatch is mixed: raw-price/feed effects dominate SPY; adjustment-factor effects matter for QQQ and TLT.
- Never splice or average provider histories. Keep raw and adjusted series separate.
- Re-query TLT after the 2026-11-02 distribution has propagated; verify QQQ's 2022-09-19 event against official Invesco records; compare SIP only if entitled, otherwise Tiingo only after secure token/eligible plan and explicit approval for any cost.
- No vendor currently certified as institutional-grade 10-year ground truth; no strategy promotion, Paper approval or LIVE authorization from this audit.


## 2026-11-11 rerun after TLT distribution event

Workflow `42958406136`, artifact `13827124135`, code SHA `097dd10932ed7ed2e993a2b2110cb7f728450d8b`.

- The same TLT 2026-11-02 discrepancy persisted on a second audit capture (Nov 11): Yahoo dividend action = 0.0 and Yahoo adjustment factor stayed 1.0 from prior session to ex-date. Alpaca adjustment factor stepped 41.7148 bps.
- Official iShares record remains $0.343177; divided by prior Yahoo raw close $81.839996 gives ~41.93 bps. The provider divergence is close to the official cash distribution scale.
- Interpretation remains unresolved but stronger: Yahoo's action/adjustment series in these captures has not reflected the issuer's ex-date distribution; do not use Yahoo adjusted TLT total-return history as validated until corrected/reconciled. Do not auto-apply the dividend to historical prices.
- Tiingo was not requested: `tiingo_comparison_status=NOT_REQUESTED`, `tiingo_all_diagnostic_gates_pass=null`, 0 symbols. This is explicitly not a pass.
- Overall IEX/Yahoo diagnostic remains false; no candidate promotion, Paper approval or orders.
