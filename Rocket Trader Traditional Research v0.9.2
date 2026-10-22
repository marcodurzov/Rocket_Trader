# Rocket Trader Traditional Research v0.9.2

## Scope and safety

Research-only artifact auditor. It does not connect to a broker, fetch market data, submit orders, or promote strategies. The audit's `PASS` status means only that implemented file-level checks found no issues; it is not proof of profitability. Live trading remains disabled.

## Workflow behavior

GitHub Actions performs:
1. Python syntax compilation.
2. Unit/regression tests.
3. Creates `research_artifacts/` if missing.
4. Audits available JSON reports and CSV ledgers.
5. Uploads the audit JSON and writes a GitHub Actions summary.

The workflow can be green when status is `NO_DATA`, because absence of research files is not a software/test failure. The summary makes `NO_DATA` explicit: it is **not** an audit pass and cannot justify strategy promotion. Actual audit errors still fail the workflow. A run with no original ledger data cannot verify performance or trade chronology.

## Inputs

Place original JSON reports and trade-ledger CSV files in `research_artifacts/`. Keep original evidence unchanged. Generated `v0_9_audit_report.json` is excluded from the audit input set.

Suggested CSV columns:

`trade_id,symbol,entry_signal_timestamp,entry_timestamp,entry_price,exit_signal_timestamp,exit_timestamp,exit_price,quantity,return_pct`

The auditor checks recognized timestamp ordering, duplicate trade IDs, invalid prices and quantities, malformed JSON/CSV, order-enabled flags, and simple gross-return discrepancies. Return reconciliation is a warning because costs and accounting conventions can explain differences.

## Run locally

```bash
python -m py_compile rocket_trader_traditional_research_v0_9.py
python rocket_trader_traditional_research_v0_9.py --run-tests
python rocket_trader_traditional_research_v0_9.py --input-dir research_artifacts --output research_artifacts/v0_9_audit_report.json
```

Add `--strict-no-data` only when deliberately requiring input files; it returns exit code 2 for `NO_DATA`. Exit codes: `0` for `PASS`, `PASS_WITH_WARNINGS`, or non-strict `NO_DATA`; `1` for `FAIL`; `2` for strict `NO_DATA`.

## Limitations and next validation step

This tool does not reproduce reported performance from original market bars, validate all market-session gaps, adjust corporate actions, or establish the TSLA SMA 20/100 result. That requires original price bars, strategy rules, fill model, costs, and full trade ledger. No strategy is promoted automatically and no orders are submitted.
