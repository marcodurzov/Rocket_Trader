#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot, read-only recovery pass for the durable Alpaca Paper crypto journal.

Run this at execution-service startup before allowing any new order intent.
It never submits, replaces, or cancels orders. Ambiguous records remain blocked.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from alpaca.trading.client import TradingClient
from rocket_trader_crypto_paper_execution import AlpacaCryptoPaperExecutionAdapter


JOURNAL_TABLE = "crypto_paper_order_journal"


def _require_durable_state(db_path: str, event_path: str) -> None:
    journal = Path(db_path).expanduser()
    events = Path(event_path).expanduser()
    if not journal.is_file():
        raise ValueError("The configured execution journal does not exist; recovery cannot safely initialize an empty journal.")
    if not events.is_file():
        raise ValueError("The configured immutable event ledger does not exist; recovery cannot initialize replacement evidence.")
    uri = journal.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (JOURNAL_TABLE,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("The configured execution journal cannot be opened read-only.") from exc
    if exists is None:
        raise ValueError("The configured execution journal is missing its order table.")


def _write_report(report: Dict[str, Any]) -> None:
    path = os.getenv("ROCKET_TRADER_RECOVERY_REPORT")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER",
        "read_only": True,
        "status": "FAILED",
    }
    try:
        if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
            raise ValueError("ALPACA_PAPER must be exactly true.")
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise ValueError("LIVE mode is prohibited.")
        if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
            raise ValueError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")

        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        api_secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not api_secret:
            raise ValueError("Alpaca Paper credentials are unavailable.")

        db_path = os.getenv("ROCKET_TRADER_CRYPTO_EXECUTION_DB", "").strip()
        if not db_path:
            raise ValueError("ROCKET_TRADER_CRYPTO_EXECUTION_DB must identify the durable execution journal.")
        event_path = os.getenv(
            "ROCKET_TRADER_EXECUTION_EVENT_LEDGER_DB",
            db_path + ".events.sqlite3",
        ).strip()
        _require_durable_state(db_path, event_path)

        client = TradingClient(api_key, api_secret, paper=True)
        adapter = AlpacaCryptoPaperExecutionAdapter(
            db_path=db_path,
            client=client,
            event_ledger_path=event_path,
        )
        adapter.verify_account()
        recovery = adapter.recover_journaled_orders()
        report.update(recovery)
        report["account_preflight"] = "PAPER_CASH_ONLY_VERIFIED"
        report["status"] = recovery["status"]
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "SUCCESS" else 2

    except Exception as exc:
        # Do not print raw broker/SDK exception strings or credential-bearing request metadata.
        report["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError):
            report["error_message"] = str(exc)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        detail = report.get("error_message", report["error_type"])
        print(f"Paper execution recovery failed: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
