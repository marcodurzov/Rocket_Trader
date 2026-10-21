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

VERSION = "0.9.1"
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
