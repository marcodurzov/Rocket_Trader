#!/usr/bin/env python3
"""Rocket Trader Traditional Research v0.9 — fail-closed artifact auditor.
Research-only. No broker integrations, network calls, or order submission.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.9.2"
ORDER_COUNT_KEYS = ("orders_submitted", "live_orders_submitted", "real_orders_submitted")
TIME_ALIASES = {
    "signal": ("entry_signal_timestamp", "entry_signal_time", "signal_timestamp", "signal_time", "signal_at"),
    "entry": ("entry_timestamp", "entry_time", "entry_at", "entry_execution_timestamp", "entry_execution_time"),
    "exit_signal": ("exit_signal_timestamp", "exit_signal_time"),
    "exit": ("exit_timestamp", "exit_time", "exit_at", "exit_execution_timestamp", "exit_execution_time"),
}
PRICE_ALIASES = {
    "entry": ("entry_price", "entry_fill_price", "buy_price"),
    "exit": ("exit_price", "exit_fill_price", "sell_price"),
}
RETURN_ALIASES = ("return_pct", "trade_return_pct", "net_return_pct", "pnl_pct")


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def norm_row(row: dict[str, Any]) -> dict[str, Any]:
    return {norm(k): v for k, v in row.items() if k is not None}


def first(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = row.get(norm(alias))
        if value is not None and str(value).strip() != "":
            return value
    return None


def number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def timestamp(value: Any) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed


def compare_times(a: datetime, b: datetime) -> int | None:
    """Return -1/0/1; None if one timestamp is naive and the other aware."""
    if (a.tzinfo is None) != (b.tzinfo is None):
        return None
    return -1 if a < b else (1 if a > b else 0)


class Audit:
    def __init__(self, input_dir: Path, exclude_paths: set[Path] | None = None):
        self.input_dir = input_dir
        self.exclude_paths = {x.resolve() for x in (exclude_paths or set())}
        self.findings: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.files_scanned = self.reports_scanned = self.trade_rows_scanned = 0
        self.json_files = self.csv_files = 0

    def finding(self, severity: str, code: str, message: str,
                file: str | None = None, row: int | None = None) -> None:
        item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
        if file:
            item["file"] = file
        if row is not None:
            item["row"] = row
        self.findings.append(item)

    def audit_json(self, path: Path) -> None:
        self.json_files += 1
        self.reports_scanned += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            self.finding("ERROR", "JSON_UNREADABLE", str(exc), str(path))
            return
        for location, obj in self.walk(data):
            row = norm_row(obj)
            enabled = row.get("orders_enabled")
            if enabled is True or (isinstance(enabled, str) and enabled.strip().lower() in {"true", "yes", "1"}):
                self.finding("ERROR", "ORDERS_ENABLED", f"{location}.orders_enabled is true", str(path))
            for key in ORDER_COUNT_KEYS:
                val = number(row.get(key))
                if val is not None and val > 0:
                    self.finding("ERROR", "ORDER_COUNT_NONZERO", f"{location}.{key}={val}", str(path))
            symbol = row.get("symbol", row.get("ticker"))
            strategy = row.get("strategy", row.get("strategy_name"))
            ret = next((number(row.get(k)) for k in ("total_return_pct", "return_pct", "total_return", "net_return_pct") if number(row.get(k)) is not None), None)
            trades = next((number(row.get(k)) for k in ("trades", "trade_count", "number_of_trades", "total_trades") if number(row.get(k)) is not None), None)
            if symbol is not None and (ret is not None or trades is not None):
                self.results.append({"file": str(path), "path": location, "symbol": symbol,
                                     "strategy": strategy, "reported_return": ret,
                                     "reported_trades": trades, "independently_verified": False})

    @staticmethod
    def walk(obj: Any, path: str = "$"):
        if isinstance(obj, dict):
            yield path, obj
            for k, v in obj.items():
                yield from Audit.walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from Audit.walk(v, f"{path}[{i}]")

    def audit_csv(self, path: Path) -> None:
        self.csv_files += 1
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames:
                    self.finding("ERROR", "CSV_NO_HEADER", "CSV has no header row", str(path))
                    return
                headers = {norm(x) for x in reader.fieldnames}
                rows = list(reader)
        except (OSError, csv.Error) as exc:
            self.finding("ERROR", "CSV_UNREADABLE", str(exc), str(path))
            return
        looks_like_ledger = any(x.startswith("entry") for x in headers) and any(x.startswith("exit") for x in headers)
        if not looks_like_ledger:
            self.finding("INFO", "CSV_SKIPPED_NON_LEDGER", "CSV lacks recognizable entry/exit columns; not treated as a trade ledger", str(path))
            return
        self.trade_rows_scanned += len(rows)
        if not rows:
            self.finding("ERROR", "EMPTY_TRADE_LEDGER", "Trade ledger has headers but no trade rows", str(path))
            return
        seen_ids: set[str] = set()
        previous_entry: datetime | None = None
        for line, raw in enumerate(rows, start=2):
            row = norm_row(raw)
            tid = first(row, ("trade_id", "id", "order_id"))
            if tid is not None:
                tid = str(tid).strip()
                if tid in seen_ids:
                    self.finding("ERROR", "DUPLICATE_TRADE_ID", f"Duplicate trade identifier {tid!r}", str(path), line)
                seen_ids.add(tid)
            prices: dict[str, float | None] = {k: number(first(row, v)) for k, v in PRICE_ALIASES.items()}
            for key, val in prices.items():
                if val is not None and val <= 0:
                    self.finding("ERROR", f"INVALID_{key.upper()}_PRICE", f"{key} price must be positive; got {val}", str(path), line)
            times: dict[str, datetime] = {}
            for role, aliases in TIME_ALIASES.items():
                raw_time = first(row, aliases)
                if raw_time is not None:
                    parsed = timestamp(raw_time)
                    if parsed is None:
                        self.finding("ERROR", "INVALID_TIMESTAMP", f"Cannot parse {role} timestamp {raw_time!r}", str(path), line)
                    else:
                        times[role] = parsed
            for earlier_role, later_role, code, msg in (
                ("signal", "entry", "ENTRY_BEFORE_SIGNAL", "Entry execution precedes recorded signal"),
                ("exit_signal", "exit", "EXIT_BEFORE_SIGNAL", "Exit execution precedes recorded exit signal"),
                ("entry", "exit", "EXIT_BEFORE_ENTRY", "Exit execution precedes entry execution"),
            ):
                if earlier_role in times and later_role in times:
                    order = compare_times(times[earlier_role], times[later_role])
                    if order is None:
                        self.finding("WARN", "MIXED_TIMEZONES", f"Cannot safely compare naive and timezone-aware {earlier_role}/{later_role} timestamps", str(path), line)
                    elif order > 0:
                        self.finding("ERROR", code, msg, str(path), line)
            entry_time = times.get("entry")
            if entry_time:
                if previous_entry:
                    order = compare_times(previous_entry, entry_time)
                    if order is None:
                        self.finding("WARN", "MIXED_TIMEZONES", "Cannot verify ledger order because timestamps mix naive and aware formats", str(path), line)
                    elif order > 0:
                        self.finding("WARN", "LEDGER_OUT_OF_ORDER", "Ledger rows are not chronological by entry timestamp", str(path), line)
                previous_entry = entry_time
            qty = number(first(row, ("quantity", "qty", "shares")))
            if qty is not None and qty <= 0:
                self.finding("ERROR", "INVALID_QUANTITY", f"Quantity must be positive; got {qty}", str(path), line)
            reported = number(first(row, RETURN_ALIASES))
            ep, xp = prices["entry"], prices["exit"]
            if ep is not None and xp is not None and reported is not None:
                gross = (xp / ep - 1) * 100
                if abs(gross - reported) > 0.25:
                    self.finding("WARN", "RETURN_RECONCILIATION_MISMATCH",
                                 f"Reported return {reported:.4f}% vs simple gross long return {gross:.4f}%; fees/sizing may explain difference", str(path), line)

    def run(self) -> dict[str, Any]:
        if not self.input_dir.exists():
            self.finding("ERROR", "INPUT_DIR_MISSING", f"Input directory does not exist: {self.input_dir}")
        elif not self.input_dir.is_dir():
            self.finding("ERROR", "INPUT_PATH_NOT_DIRECTORY", f"Input path is not a directory: {self.input_dir}")
        else:
            paths = sorted(p for p in self.input_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".csv"} and p.resolve() not in self.exclude_paths)
            for path in paths:
                self.files_scanned += 1
                if path.suffix.lower() == ".json":
                    self.audit_json(path)
                else:
                    self.audit_csv(path)
            if self.files_scanned == 0:
                self.finding("NO_DATA", "NO_SUPPORTED_FILES", "No JSON or CSV files found in input directory (generated output files are excluded)")
            elif self.trade_rows_scanned == 0:
                self.finding("NO_DATA", "NO_TRADE_LEDGER_ROWS", "No recognizable trade-ledger rows were audited; performance and trade chronology remain unverified")
        counts = Counter(x["severity"] for x in self.findings)
        errors, warnings, no_data = counts["ERROR"], counts["WARN"], counts["NO_DATA"]
        if errors:
            status = "FAIL"
        elif no_data or (self.files_scanned == 0):
            status = "NO_DATA"
        elif warnings:
            status = "PASS_WITH_WARNINGS"
        else:
            status = "PASS"
        return {
            "version": VERSION, "audit_status": status,
            "input_directory": str(self.input_dir), "files_scanned": self.files_scanned,
            "reports_scanned": self.reports_scanned, "csv_files_scanned": self.csv_files,
            "trade_rows_scanned": self.trade_rows_scanned,
            "error_count": errors, "warning_count": warnings,
            "orders_enabled": False, "orders_submitted": 0,
            "strategy_profitability_verified": False, "strategy_promotion_enabled": False,
            "reported_results": self.results, "findings": self.findings,
            "limitations": [
                "PASS only means implemented artifact checks found no issues; it does not prove profitability.",
                "Reported performance is not reproduced from original market bars.",
                "Return reconciliation is a simple long-only diagnostic and may differ from net accounting.",
                "Missing timestamps prevent chronology verification.",
                "This tool does not fetch market data, execute orders, or connect to a broker.",
            ],
        }


def self_test() -> int:
    import tempfile
    import unittest
    class Tests(unittest.TestCase):
        def test_iso_z(self):
            self.assertEqual(timestamp("2026-05-22T18:05:00Z").tzinfo, timezone.utc)
        def test_invalid_timestamp(self):
            self.assertIsNone(timestamp("not-a-date"))
        def test_nonfinite_number(self):
            self.assertIsNone(number("nan")); self.assertIsNone(number("inf"))
        def test_compare_mixed_timezone(self):
            self.assertIsNone(compare_times(datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc)))
        def test_missing_dir_no_data_error(self):
            with tempfile.TemporaryDirectory() as tmp:
                report = Audit(Path(tmp) / "missing").run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertEqual(report["findings"][0]["code"], "INPUT_DIR_MISSING")
        def test_empty_dir_no_data(self):
            with tempfile.TemporaryDirectory() as tmp:
                report = Audit(Path(tmp)).run()
                self.assertEqual(report["audit_status"], "NO_DATA")
                self.assertEqual(report["error_count"], 0)
        def test_entry_before_signal_fails(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_signal_timestamp,entry_timestamp,entry_price,exit_timestamp,exit_price,return_pct\n"
                    "1,2026-05-22T18:05:00Z,2026-05-22T18:00:00Z,100,2026-05-22T19:00:00Z,101,1\n", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "ENTRY_BEFORE_SIGNAL" for x in report["findings"]))
        def test_valid_ledger_passes(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_signal_timestamp,entry_timestamp,entry_price,exit_signal_timestamp,exit_timestamp,exit_price,return_pct,quantity\n"
                    "1,2026-05-22T18:00:00Z,2026-05-22T18:05:00Z,100,2026-05-22T18:55:00Z,2026-05-22T19:00:00Z,101,1,2\n", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "PASS")
        def test_output_file_excluded(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); output = p / "audit.json"
                output.write_text(json.dumps({"audit_status": "PASS"}), encoding="utf-8")
                report = Audit(p, exclude_paths={output}).run()
                self.assertEqual(report["audit_status"], "NO_DATA")
                self.assertEqual(report["files_scanned"], 0)
        def test_report_without_ledger_is_no_data(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "summary.json").write_text(json.dumps({"symbol": "TSLA", "total_return_pct": 17.72}), encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "NO_DATA")
                self.assertTrue(any(x["code"] == "NO_TRADE_LEDGER_ROWS" for x in report["findings"]))
        def test_duplicate_trade_id_detected(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_timestamp,entry_price,exit_timestamp,exit_price\n"
                    "T1,2026-05-22T18:05:00Z,100,2026-05-22T19:00:00Z,101\n"
                    "T1,2026-05-23T18:05:00Z,100,2026-05-23T19:00:00Z,101\n", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "DUPLICATE_TRADE_ID" for x in report["findings"]))
        def test_orders_enabled_report_fails(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "report.json").write_text(json.dumps({"orders_enabled": True, "orders_submitted": 1}), encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "ORDERS_ENABLED" for x in report["findings"]))
        def test_exit_before_entry_fails(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_timestamp,entry_price,exit_timestamp,exit_price\n"
                    "T1,2026-05-22T19:00:00Z,100,2026-05-22T18:00:00Z,101\n", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "EXIT_BEFORE_ENTRY" for x in report["findings"]))
        def test_exit_before_exit_signal_fails(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_timestamp,entry_price,exit_signal_timestamp,exit_timestamp,exit_price\n"
                    "T1,2026-05-22T18:00:00Z,100,2026-05-22T19:00:00Z,2026-05-22T18:55:00Z,101\n", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "EXIT_BEFORE_SIGNAL" for x in report["findings"]))
        def test_invalid_price_and_quantity_fail(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "ledger.csv").write_text(
                    "trade_id,entry_timestamp,entry_price,exit_timestamp,exit_price,quantity\n"
                    "T1,2026-05-22T18:00:00Z,0,2026-05-22T19:00:00Z,101,-2\n", encoding="utf-8")
                report = Audit(p).run()
                codes = {x["code"] for x in report["findings"]}
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertIn("INVALID_ENTRY_PRICE", codes)
                self.assertIn("INVALID_QUANTITY", codes)
        def test_malformed_json_fails(self):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / "report.json").write_text("{broken", encoding="utf-8")
                report = Audit(p).run()
                self.assertEqual(report["audit_status"], "FAIL")
                self.assertTrue(any(x["code"] == "JSON_UNREADABLE" for x in report["findings"]))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="research_artifacts")
    parser.add_argument("--output", default="research_artifacts/v0_9_audit_report.json")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--strict-no-data", action="store_true", help="Return exit code 2 when no audit inputs are found")
    args = parser.parse_args()
    if args.run_tests:
        return self_test()
    output = Path(args.output)
    report = Audit(Path(args.input_dir), exclude_paths={output}).run()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("version", "audit_status", "files_scanned", "reports_scanned", "csv_files_scanned", "trade_rows_scanned", "error_count", "warning_count", "orders_enabled", "orders_submitted", "strategy_profitability_verified")}, indent=2))
    if report["audit_status"] == "FAIL":
        return 1
    if args.strict_no_data and (report["audit_status"] == "NO_DATA" or report["trade_rows_scanned"] == 0):
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
