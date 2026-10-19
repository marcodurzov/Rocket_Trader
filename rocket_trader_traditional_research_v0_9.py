
#!/usr/bin/env python3
"""Rocket Trader Traditional Research v0.9
Independent audit of research reports and trade ledgers.
Research only: never connects to a broker or submits orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "0.9.0"
FORBIDDEN_LIVE_KEYS = {
    "orders_submitted", "live_orders_submitted", "real_orders_submitted"
}
TIME_KEYS = (
    "signal_timestamp", "signal_time", "signal_at",
    "entry_signal_timestamp", "entry_signal_time",
    "entry_timestamp", "entry_time", "entry_at",
    "exit_signal_timestamp", "exit_signal_time",
    "exit_timestamp", "exit_time", "exit_at",
)
PRICE_KEYS = {
    "entry": ("entry_price", "entry_fill_price", "buy_price"),
    "exit": ("exit_price", "exit_fill_price", "sell_price"),
}
RETURN_KEYS = ("return_pct", "trade_return_pct", "net_return_pct", "pnl_pct")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO timestamps; normalize timezone-aware values to UTC."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        # Naive timestamps are ambiguous: retain them as naive, not guessed UTC.
        return result
    return result.astimezone(timezone.utc)


def normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    normalized = {normalized_key(k): v for k, v in row.items()}
    for name in names:
        value = normalized.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def walk_json(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        yield path, obj
        for key, value in obj.items():
            yield from walk_json(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk_json(value, f"{path}[{index}]")


class Auditor:
    def __init__(self, input_dir: Path):
        self.input_dir = input_dir
        self.findings: list[dict[str, Any]] = []
        self.files_scanned = 0
        self.trade_rows_scanned = 0
        self.reports_scanned = 0
        self.summary: dict[str, Any] = {}

    def add(self, severity: str, code: str, message: str, file: str = "",
            row: int | None = None) -> None:
        item = {"severity": severity, "code": code, "message": message}
        if file:
            item["file"] = file
        if row is not None:
            item["row"] = row
        self.findings.append(item)

    def audit_json(self, path: Path) -> None:
        self.reports_scanned += 1
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            self.add("ERROR", "JSON_UNREADABLE", str(exc), str(path))
            return

        for location, obj in walk_json(data):
            lower = {normalized_key(k): v for k, v in obj.items()}

            # Any reported order count above zero is a safety violation for this
            # research-only package. Missing fields are not interpreted as zero.
            for key in FORBIDDEN_LIVE_KEYS:
                value = numeric(lower.get(key))
                if value is not None and value > 0:
                    self.add(
                        "ERROR", "LIVE_ORDER_COUNT_NONZERO",
                        f"{location}.{key} reports {value}; research must submit zero orders.",
                        str(path),
                    )

            enabled = lower.get("orders_enabled")
            if enabled is True or str(enabled).strip().lower() in ("true", "1", "yes"):
                self.add(
                    "ERROR", "ORDERS_ENABLED",
                    f"{location}.orders_enabled is enabled in a research-only report.",
                    str(path),
                )

            # Collect reported strategy performance without treating it as proof.
            symbol = lower.get("symbol") or lower.get("ticker")
            strategy = lower.get("strategy") or lower.get("strategy_name")
            ret = None
            for key in ("total_return_pct", "return_pct", "total_return",
                        "net_return_pct"):
                ret = numeric(lower.get(key))
                if ret is not None:
                    break
            trades = None
            for key in ("trades", "trade_count", "number_of_trades",
                        "total_trades"):
                trades = numeric(lower.get(key))
                if trades is not None:
                    break
            if symbol is not None and (ret is not None or trades is not None):
                self.summary.setdefault("reported_results", []).append({
                    "file": str(path),
                    "path": location,
                    "symbol": symbol,
                    "strategy": strategy,
                    "reported_return": ret,
                    "reported_trades": trades,
                    "independently_verified": False,
                })

    def audit_csv(self, path: Path) -> None:
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames:
                    self.add("WARN", "CSV_NO_HEADER", "CSV has no header.", str(path))
                    return
                fields = {normalized_key(k) for k in reader.fieldnames}
                rows = list(reader)
        except (OSError, csv.Error) as exc:
            self.add("ERROR", "CSV_UNREADABLE", str(exc), str(path))
            return

        # Ignore unrelated CSVs unless they look like a trade ledger.
        has_trade_fields = (
            any(k.startswith("entry") for k in fields)
            and any(k.startswith("exit") for k in fields)
        )
        if not has_trade_fields:
            return

        self.trade_rows_scanned += len(rows)
        seen_ids: set[str] = set()
        previous_entry: datetime | None = None

        for index, raw in enumerate(rows, start=2):
            row = {normalized_key(k): v for k, v in raw.items() if k is not None}

            trade_id = first_value(row, ("trade_id", "id", "order_id"))
            if trade_id is not None:
                trade_id = str(trade_id).strip()
                if trade_id in seen_ids:
                    self.add("ERROR", "DUPLICATE_TRADE_ID",
                             f"Duplicate trade identifier: {trade_id}",
                             str(path), index)
                seen_ids.add(trade_id)

            entry_raw = first_value(row, PRICE_KEYS["entry"])
            exit_raw = first_value(row, PRICE_KEYS["exit"])
            entry_price, exit_price = numeric(entry_raw), numeric(exit_raw)
            if entry_price is not None and entry_price <= 0:
                self.add("ERROR", "INVALID_ENTRY_PRICE",
                         f"Entry price must be positive; got {entry_price}.",
                         str(path), index)
            if exit_price is not None and exit_price <= 0:
                self.add("ERROR", "INVALID_EXIT_PRICE",
                         f"Exit price must be positive; got {exit_price}.",
                         str(path), index)

            # Check timestamps only where explicit fields exist.
            time_values: dict[str, datetime] = {}
            for key in TIME_KEYS:
                value = first_value(row, (key,))
                if value is not None:
                    parsed = parse_timestamp(value)
                    if parsed is None:
                        self.add("ERROR", "INVALID_TIMESTAMP",
                                 f"Cannot parse {key}={value!r}.", str(path), index)
                    else:
                        time_values[key] = parsed

            signal = (
                time_values.get("entry_signal_timestamp")
                or time_values.get("entry_signal_time")
                or time_values.get("signal_timestamp")
                or time_values.get("signal_time")
                or time_values.get("signal_at")
            )
            entry = (
                time_values.get("entry_timestamp")
                or time_values.get("entry_time")
                or time_values.get("entry_at")
            )
            exit_signal = (
                time_values.get("exit_signal_timestamp")
                or time_values.get("exit_signal_time")
            )
            exit_time = (
                time_values.get("exit_timestamp")
                or time_values.get("exit_time")
                or time_values.get("exit_at")
            )

            if signal and entry:
                if signal.tzinfo is None and entry.tzinfo is not None:
                    self.add("WARN", "MIXED_TIMEZONES",
                             "Signal and entry timestamps mix naive and aware timezones.",
                             str(path), index)
                elif signal.tzinfo is not None and entry.tzinfo is None:
                    self.add("WARN", "MIXED_TIMEZONES",
                             "Signal and entry timestamps mix aware and naive timezones.",
                             str(path), index)
                elif entry < signal:
                    self.add("ERROR", "ENTRY_BEFORE_SIGNAL",
                             "Entry execution precedes the recorded signal timestamp.",
                             str(path), index)

            if exit_signal and exit_time:
                if exit_signal.tzinfo == exit_time.tzinfo and exit_time < exit_signal:
                    self.add("ERROR", "EXIT_BEFORE_SIGNAL",
                             "Exit execution precedes the recorded exit signal.",
                             str(path), index)

            if entry and exit_time:
                if entry.tzinfo == exit_time.tzinfo and exit_time < entry:
                    self.add("ERROR", "EXIT_BEFORE_ENTRY",
                             "Exit execution precedes entry execution.",
                             str(path), index)

            if entry:
                if previous_entry and entry.tzinfo == previous_entry.tzinfo:
                    if entry < previous_entry:
                        self.add("WARN", "LEDGER_OUT_OF_ORDER",
                                 "Trade ledger entries are not chronological.",
                                 str(path), index)
                previous_entry = entry

            reported_return = numeric(first_value(row, RETURN_KEYS))
            if entry_price and exit_price and reported_return is not None:
                # Assumes a simple long-only return, before fees/slippage.
                gross_pct = (exit_price / entry_price - 1.0) * 100.0
                if abs(gross_pct - reported_return) > 0.25:
                    self.add(
                        "WARN", "RETURN_RECONCILIATION_MISMATCH",
                        f"Reported return {reported_return:.4f}% vs simple gross "
                        f"price return {gross_pct:.4f}%. This may be valid if the "
                        "ledger uses fees, sizing, or another return convention.",
                        str(path), index,
                    )

            qty = numeric(first_value(row, ("quantity", "qty", "shares")))
            if qty is not None and qty <= 0:
                self.add("ERROR", "INVALID_QUANTITY",
                         f"Quantity must be positive; got {qty}.",
                         str(path), index)

    def run(self) -> dict[str, Any]:
        if not self.input_dir.exists():
            self.add("ERROR", "INPUT_DIR_MISSING",
                     f"Input directory does not exist: {self.input_dir}")
        else:
            files = sorted(
                p for p in self.input_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in (".json", ".csv")
            )
            for path in files:
                self.files_scanned += 1
                if path.suffix.lower() == ".json":
                    self.audit_json(path)
                elif path.suffix.lower() == ".csv":
                    self.audit_csv(path)

        counts = Counter(item["severity"] for item in self.findings)
        error_count = counts["ERROR"]
        warning_count = counts["WARN"]
        self.summary.update({
            "version": VERSION,
            "audit_status": "FAIL" if error_count else (
                "PASS_WITH_WARNINGS" if warning_count else "PASS"
            ),
            "scope": "existing JSON reports and CSV trade ledgers only",
            "input_directory": str(self.input_dir),
            "files_scanned": self.files_scanned,
            "reports_scanned": self.reports_scanned,
            "trade_rows_scanned": self.trade_rows_scanned,
            "error_count": error_count,
            "warning_count": warning_count,
            "orders_enabled": False,
            "orders_submitted": 0,
            "strategy_profitability_verified": False,
            "strategy_promotion_enabled": False,
            "findings": self.findings,
            "limitations": [
                "A clean audit does not prove a strategy is profitable.",
                "Reported returns are not independently reproduced from market bars.",
                "Return reconciliation is a simple long-only diagnostic, not a full accounting engine.",
                "Timezone-naive timestamps cannot be safely compared to timezone-aware timestamps.",
                "Missing timestamps or accounting fields limit what can be validated.",
            ],
        })
        return self.summary


class AuditTests(unittest.TestCase):
    def test_parse_iso_z(self):
        result = parse_timestamp("2026-05-22T18:05:00Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_parse_invalid(self):
        self.assertIsNone(parse_timestamp("not-a-date"))

    def test_simple_return(self):
        self.assertAlmostEqual((110 / 100 - 1) * 100, 10.0)

    def test_nonfinite_numeric(self):
        self.assertIsNone(numeric("nan"))
        self.assertIsNone(numeric("inf"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="research_artifacts",
                        help="Folder containing report JSON and trade-ledger CSV files")
    parser.add_argument("--output", default="research_artifacts/v0_9_audit_report.json",
                        help="Path to write the audit report")
    parser.add_argument("--run-tests", action="store_true",
                        help="Run built-in unit tests and exit")
    args = parser.parse_args()

    if args.run_tests:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(AuditTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1

    auditor = Auditor(Path(args.input_dir))
    report = auditor.run()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "audit_status": report["audit_status"],
        "files_scanned": report["files_scanned"],
        "reports_scanned": report["reports_scanned"],
        "trade_rows_scanned": report["trade_rows_scanned"],
        "error_count": report["error_count"],
        "warning_count": report["warning_count"],
        "report_path": str(output),
        "orders_enabled": False,
        "orders_submitted": 0,
        "strategy_profitability_verified": False,
    }, indent=2))
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
