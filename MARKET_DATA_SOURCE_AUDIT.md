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

The first live run (42920786498; artifact 13812205814) failed for all symbols because `repair=True` triggered `ValueError: output array is read-only`. PR #96 set `repair=False` and added a regression test. The subsequent live run (42922974687; artifact 13812508089) retrieved all eight ETFs successfully, but only 1,581 common sessions were available (2020-07-27 to 2026-11-09). Yahoo had 2,512 sessions; Alpaca IEX had 1,582. Consequently, 0/8 symbols passed the ten-year source-coverage diagnostic. The earlier SIP `NOT_ENTITLED` result came from a recent request ending at current time; it did not test historical SIP with an end 15+ minutes old. This is a completed IEX retrieval with a failed 10-year coverage gate, not a successful 10-year validation.

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

- TLT 2026-11-02 discrepancy persisted in the Nov 11 capture: Yahoo dividend action = 0.0 and Yahoo adjustment factor stayed 1.0 from prior session to ex-date; Alpaca adjustment factor stepped 41.7148 bps.
- Official iShares record: $0.343177; divided by prior Yahoo raw close $81.839996 gives ~41.93 bps. The Alpaca step is close to the official distribution scale.
- Interpretation remains unresolved but stronger: Yahoo's action/adjustment series in these captures has not reflected the issuer's ex-date distribution. Do not auto-apply a dividend to historical prices.
- Tiingo was not requested: `tiingo_comparison_status=NOT_REQUESTED`, `tiingo_all_diagnostic_gates_pass=null`, 0 symbols. This is explicitly not a pass.
- Overall IEX/Yahoo diagnostic remains false; no candidate promotion, Paper approval or orders.


## Alpaca issuer corporate-action reconciliation

The audit now queries Alpaca's official market-data Corporate Actions endpoint for the same ETF universe and period (with a 60-day process-date padding, because the endpoint filters/sorts by `process_date`, not solely by `ex_date`). It preserves event type, symbol, ex-date, cash rate, capital-gain rates, split fields, process date, payable date and other relevant metadata.

For each largest adjustment-factor step, the report now shows Alpaca corporate actions on the event date and previous session, the sum of Alpaca cash dividends on the event date, and the difference versus Yahoo's `Dividends` field. This can distinguish:
- an issuer cash distribution present in Alpaca's corporate-action feed but absent from Yahoo's action field;
- an event present in both feeds but with different amounts;
- an event present in Yahoo but absent from Alpaca's corporate-action feed;
- a factor-step discrepancy without a matching cash dividend (which may instead involve capital gains, splits, spin-offs, timing, or bad price data).

The official endpoint is `GET https://data.alpaca.markets/v1/corporate-actions`. Alpaca warns that corporate-action records can be delayed and does not guarantee when records are created; absence from this API is not proof that no issuer event exists. Issuer records remain the authority for declared distributions. This endpoint is read-only and does not change account positions or submit orders.

References:
- https://docs.alpaca.markets/us/reference/corporateactions-1
- https://alpaca.markets/sdks/python/api_reference/data/corporate_actions/historical.html
- https://www.ishares.com/us/products/239454/ishares-1020-year-treasury-bond-etf

**Response-envelope validation note (2026-11-11):** Alpaca's documented response groups all action-type arrays under the top-level `corporate_actions` object, with `next_page_token` beside it. The parser now validates that envelope and fails closed if it is absent or malformed. Offline pagination fixtures mirror this exact documented shape. The first post-merge run returned zero events because the initial parser incorrectly read the action arrays from the response root; that run must not be interpreted as evidence that Alpaca had no issuer actions.

**Multiple-record handling:** The report now preserves corporate-action IDs and identifying metadata. If more than one Alpaca cash-dividend record exists for the same symbol/ex-date, it does not sum them or calculate a Yahoo-vs-Alpaca amount difference; it marks the total `MULTIPLE_RECORDS_REQUIRES_REVIEW` until identity/version semantics are resolved. This prevents duplicate or revised issuer records from inflating the cash distribution.

## Zero-budget provider guards (2026-11-11)

- PR #179 initially restricted the ETF cross-check to IEX. This was too restrictive: Alpaca's official Market Data FAQ states that Basic users may query historical SIP bars when the request `end` is at least 15 minutes old. The correction below restores free historical SIP while keeping recent/live SIP blocked.
- Tiingo is an optional comparison only. The code ignores any Tiingo token unless `--include-tiingo` is explicitly supplied, requires a token when opted in, and blocks a window longer than five years for the zero-cost Starter tier.
- The public GitHub Actions workflow no longer injects `TIINGO_API_TOKEN` at all. This prevents accidental quota use or exposure of internal-use-only Tiingo-derived reports from public workflow runs.
- Tiingo's published Starter tier is listed at $0/month, with 5 years of history, 500 unique symbols/month, 50 requests/hour, 1,000 requests/day, 1 GB/month and an internal-use-only license. It is a candidate for a personal 5-year cross-check only after the user creates the free account and confirms its terms. Do not create the account or add a token on the user's behalf without explicit approval. Do not publish raw Tiingo data or use it for redistribution.
- Alpha Vantage's free 25-request/day allowance does not unlock its full historical daily-adjusted endpoint; the full adjusted daily endpoint is premium. Stooq is not selected for automated production because its current access/automation reliability and adjustment documentation are insufficient.

## Equity research workflow zero-budget hardening (2026-11-11)

- PR #179 initially applied an overly broad IEX-only guard to equity research v0.1–v0.4. PR #181 supersedes it: historical SIP is allowed only when the request end is at least 15 minutes old; IEX remains the recent/live option.
- Removed SIP from all four GitHub Actions workflow selectors.
- Removed Tiingo as a selectable primary source from public equity research v0.4 and removed the Tiingo token from that workflow's environment. The Tiingo fetcher remains covered by offline tests but is not reachable from public workflow selection.
- The optional Tiingo comparison in the dedicated ETF cross-check remains local/programmatic only and requires explicit `--include-tiingo`; the public GitHub Actions workflow does not inject the token or opt in.
- The $0 Tiingo Starter plan is only a potential personal 5-year cross-check; account creation and token setup remain user-controlled. No provider account was created and no Tiingo API request was made.

- The weekly market-data entitlement probe has also been converted to an IEX-only health probe. It makes one IEX request, reports SIP as `DISABLED_BY_ZERO_BUDGET_POLICY` with `request_made=false`, and the self-test asserts that no SIP request is issued.
- Repository-wide workflow scan found no other SIP or Tiingo token usage outside the four equity research workflows, the ETF cross-check workflow, and this entitlement probe. The four equity workflows and cross-check are being hardened in this change; this probe is now IEX-only.


## 2026-11-11 — Zero-budget provider hardening and statistical ETF research

### PR #179 merged

- PR #179 merged at main commit `31923c5b6d8e57e1525ad5e3d3d6500df4a74e34`.
- PR #179 initially restricted research to IEX under the assumption that SIP required a paid plan. That restriction is superseded by the historical-SIP correction below: Alpaca Basic permits SIP for historical requests whose `end` is at least 15 minutes old.
- Equity research v0.1–v0.4 now reject SIP in code and CLI. Their GitHub Actions workflows no longer offer SIP.
- Public equity research v0.4 no longer offers Tiingo as a primary source and no longer receives `TIINGO_API_TOKEN`.
- The public ETF cross-check workflow does not inject Tiingo credentials and does not opt in. Its optional Tiingo comparison is disabled unless a local/programmatic caller explicitly sets `include_tiingo` and supplies a token; the zero-cost Starter comparison is limited to five years. No Tiingo account was created and no Tiingo request was made.
- The scheduled entitlement probe is now an IEX-only health probe. Its successful run `43080158991` returned IEX `AVAILABLE` (5 bars) and marked SIP `DISABLED_BY_ZERO_BUDGET_POLICY`, `request_made=false`. The self-test asserts that the broker client was called only for IEX.
- Repository audit identified the four ETF research workflows, the ETF cross-check workflow and the entitlement probe as the relevant SIP/Tiingo workflow surfaces. Those public paths have now been hardened.
- Post-merge workflow runs for the IEX probe, ETF cross-check and research versions 0.1–0.4 all completed successfully: `43080158991`, `43080158893`, `43080158810`, `43080158982`, `43080158898`, and `43080158764`.

### Actual research outputs (read-only; no orders)

- ETF cross-check run `43080158893`: 10-year window, 8 ETFs, Alpaca IEX vs Yahoo adjusted daily bars. The audit returned `ok=true` but `all_diagnostic_gates_pass=false`; all eight symbols failed the 10-year history-overlap gate. Common sessions were 62.98% of Yahoo's full history and 99.94% of Alpaca IEX's returned sessions. This reflects Alpaca's later first available date (seven ETFs 2020-07-27; SPY 2018-11-01), not a demonstrated 37% internal IEX missing-session rate.
- Equity research v0.1 run `43080158810`: 5-year Alpaca IEX, 8 ETFs; data quality passed for all eight. This version is exploratory and does not apply the later family-wide multiple-testing test; no candidate was promoted or Paper-approved.
- Equity research v0.2 run `43080158982`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Holm-Bonferroni family size 49, 5,000 centered moving-block bootstrap replicates per hypothesis, alpha 0.05. Family-wise significant hypotheses: 0; pre-screen passes: 0.
- Equity research v0.3 run `43080158898`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Same 49-hypothesis Holm-Bonferroni framework; family-wise significant hypotheses: 0; pre-screen passes: 0.
- Equity research v0.4 run `43080158764`: 10-year Yahoo adjusted daily history, 8 ETFs; data quality passed. Expanded family size 73 with additional RSI(2), Bollinger and z-score mean-reversion variants; 5,000 centered moving-block bootstrap replicates per hypothesis; family-wise significant hypotheses: 0; pre-screen passes: 0.
- The v0.2–v0.4 methodology uses chronological 60% train / 20% validation / 20% final holdout; signals from completed daily close and next-session execution assumptions; long-only, no leverage/shorts/options/futures; base cost placeholder 5 bps per side and a 2x stress case. The 5 bps assumption remains a placeholder, not broker-validated execution cost.
- All four research artifacts explicitly report `candidate_promotion_allowed=false`, `paper_approval=false`, `orders_enabled=false`, `orders_submitted=0`. The ETF cross-check artifact reports the same no-promotion/no-order state. No order was placed by these runs.
- The honest conclusion is that none of the tested ETF hypotheses currently qualifies for promotion. This does not prove that no profitable strategy exists; it means this tested family did not produce statistically defensible candidates under these data, costs and validation gates.

### Next work

1. Continue research without paid feeds: improve date-level data completeness diagnostics, identify an independently usable free adjusted-history source, and validate its adjustment methodology and terms before use.
2. Expand strategy families only with a pre-registered hypothesis budget and multiple-testing control; avoid data-mining the same holdout repeatedly.
3. Add independent replication and additional chronological/walk-forward regimes before any strategy can be considered for Paper observation.
4. Keep all strategy promotion, Paper approval and order submission disabled until the data, statistical, execution-cost, risk and operational gates pass.
5. Continue investigating a persistent host that costs USD 0 and is already available to the user. GitHub Actions is for bounded CI/research, not a 24/7 trading runtime. No host has been identified or deployed.

**Progress estimate: 58%** (engineering/evidence maturity, not profitability). The increase from 57% reflects merged zero-budget safeguards and completed statistical research workflows. It does not indicate strategy success, production deployment, Paper approval or readiness for Live.

## 2026-11-11 — Correct interpretation of Alpaca IEX vs Yahoo history coverage

The earlier wording that described Alpaca IEX as the "sparse side" or implied a 37% internal missing-bar rate was inaccurate and is superseded by this correction.

The artifact from run `43080158893` shows:
- Seven ETFs: Yahoo 2,512 sessions; Alpaca IEX 1,583; common 1,582; first common session 2020-07-27.
- SPY: Yahoo 2,512 sessions; Alpaca IEX 1,584; common 1,583; first common session 2018-11-01.
- The 62.98% ratio is common sessions divided by Yahoo's full 10-year history. The 99.94% ratio is common sessions divided by Alpaca's returned history. These ratios describe unequal history horizons.
- The data do not show that IEX omitted roughly 37% of daily sessions during the period it returned. Within the shared period, almost all returned sessions align between sources.
- The 10-year audit still correctly fails its full-history-overlap gate: Alpaca's available history for this account does not extend back to the requested 2016 start. It is therefore unsuitable as the only 10-year research source, even though its overlap with Yahoo is highly complete.
- The code now reports each provider's first/last session, the Alpaca history-start lag, overlap-window session completeness, and a classification distinguishing a later history start from internal gaps. The old `minimum_source_coverage` field remains as a backward-compatible alias; a new explicit `minimum_requested_history_overlap` field explains what it tests.

### Free provider screening (official documentation checked 2026-11-11)

- Alpha Vantage free access is 25 requests/day, but its full daily history (`outputsize=full`) is Premium-only and its split/dividend-adjusted daily endpoint is explicitly Premium. The free daily endpoint is limited to the latest 100 observations. It is not a usable free 5–10-year adjusted OHLC source for this project. Sources: https://www.alphavantage.co/support/api-key/ and https://www.alphavantage.co/documentation/
- Financial Modeling Prep Basic advertises $0 and 250 calls/day, with a free-use limit of five years of stock history, but its Personal Use license is narrowly non-business/non-commercial. Its Terms prohibit use on behalf of an entity, sharing/integrating data into tools accessible to third parties, and copying/downloading content without prior written approval. Do not wire FMP into Rocket Trader's public repository/workflows or cache its data unless FMP confirms in writing that this specific private personal automated-trading use and storage are permitted. Sources: https://site.financialmodelingprep.com/how-to/how-to-create-a-financial-modeling-prep-account and https://site.financialmodelingprep.com/developer/docs/terms-of-service
- FMP is therefore not automatically accepted just because its plan is free. Price is only one gate; licensing and intended use must also pass.
- Continue using Alpaca IEX for the authorized Paper connection and bounded current/history checks, while keeping Yahoo research data segregated and labeled. Do not silently stitch providers or treat Yahoo as an exchange-licensed execution feed.

## 2026-11-11 — Correct zero-budget Alpaca market-data policy: free historical SIP

A review of the current official Alpaca documentation found that the prior blanket SIP block was incorrect.

- Alpaca Basic costs **USD 0/month**. The official Market Data FAQ explicitly states that historical SIP requests are allowed without a paid subscription when the request's `end` parameter is at least 15 minutes old. Recent SIP trades/quotes/bars and the SIP live stream still require Algo Trader Plus. Sources: https://docs.alpaca.markets/us/docs/market-data-faq and https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api
- Alpaca's own support representative states IEX daily bars are only available from 2020, while SIP historical bars are available from 2016. This explains the earlier observed IEX start dates and the 10-year history gap; it was not an unexplained 37% missing-bar rate. Source: https://forum.alpaca.markets/t/cannot-get-historical-bar-data-before-2020/12415
- The correct zero-budget policy is therefore:
  - **Historical equity research/audits:** use SIP by default, but enforce request end at least 15 minutes before current time. The implementation chooses UTC midnight for the latest date safely older than the cutoff, which also avoids including an incomplete current daily candle.
  - **Recent/live market data:** IEX only on the free Basic plan. Do not use SIP for the latest 15 minutes or for live SIP streaming.
  - **No paid subscription:** do not enable Algo Trader Plus or any other paid data tier without explicit user approval.
- Updated the ETF cross-check and equity research v0.1–v0.4 to allow SIP only with a timezone-aware historical end that passes the 15-minute rule. The CLI/workflow default is now SIP for historical research; IEX remains selectable for recent/live-compatible checks. Equity research v0.2–v0.4 now defaults its source to Alpaca rather than Yahoo, with Yahoo retained as the independent comparison source.
- The cross-check now sets its historical data end to the safe UTC date boundary before requesting Yahoo/Alpaca daily prices; corporate-action lookup retains the current timestamp and is read-only.
- The scheduled market-data entitlement probe remains intentionally IEX-only because it is a current/live-feed health check, not a historical SIP entitlement test.
- **Not yet proven for this Paper credential set:** a post-merge read-only SIP historical request must return bars from before 2020, ideally for SPY and the full ETF universe. The implementation must not be described as validated until that workflow succeeds. If Alpaca returns an entitlement error, preserve the logs and revert to IEX-only; do not upgrade or pay.

