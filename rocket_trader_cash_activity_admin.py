#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operator CLI for explicit Alpaca Paper cash-activity reconciliation.

This command reads only the durable activity-stager database. It never calls
Alpaca, submits orders, or silently classifies deposits, withdrawals, or JNLC.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
from decimal import Decimal, InvalidOperation

from rocket_trader_alpaca_activity_stager import AlpacaPaperActivityStager
from rocket_trader_alpaca_cash_activity_bridge import AlpacaCashActivityBridge
from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger


def _fx_from_args(args):
    if not args.fx_rate or not args.fx_observed_at or not args.fx_source:
        raise ValueError(
            "USD cash movements require --fx-rate, --fx-observed-at and --fx-source "
            "from a traceable historical USD/MXN reference."
        )
    raw = args.fx_observed_at
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return LedgerFX(Decimal(args.fx_rate), datetime.fromisoformat(raw), args.fx_source)


def _require_existing_state(ledger_path: str, stager_path: str) -> None:
    """Refuse to initialize a missing, empty, or wrong persistent database."""
    ledger_file = Path(ledger_path).expanduser()
    stager_file = Path(stager_path).expanduser()
    if not ledger_file.is_file():
        raise ValueError("Existing realized-P&L ledger database is missing; refusing to create a replacement.")
    if not stager_file.is_file():
        raise ValueError("Existing activity-stager database is missing; refusing to create a replacement.")
    if ledger_file.resolve() == stager_file.resolve():
        raise ValueError("Ledger and activity-stager databases must be separate files.")

    def read_tables(path: Path):
        uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            triggers = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()}
            return names, triggers, conn
        except Exception:
            conn.close()
            raise

    ledger_tables, ledger_triggers, ledger_conn = read_tables(ledger_file)
    try:
        required = {"ledger_meta", "ledger_events", "monthly_closes"}
        if not required.issubset(ledger_tables):
            raise ValueError("Existing realized-P&L ledger is missing required tables; refusing initialization.")
        required_triggers = {
            "ledger_events_no_update", "ledger_events_no_delete",
            "monthly_closes_no_update", "monthly_closes_no_delete",
        }
        if not required_triggers.issubset(ledger_triggers):
            raise ValueError("Existing realized-P&L ledger is missing append-only triggers; refusing initialization.")
        meta = dict(ledger_conn.execute("SELECT key,value FROM ledger_meta").fetchall())
        if meta.get("schema_version") != "1":
            raise ValueError("Existing realized-P&L ledger schema version is missing or unsupported.")
        configured_policy = {
            "initial_capital_mxn": os.getenv("ROCKET_TRADER_INITIAL_CAPITAL_MXN", "1000.00"),
            "milestone_mxn": os.getenv("ROCKET_TRADER_MILESTONE_MXN", "100000.00"),
        }
        for key, configured_value in configured_policy.items():
            try:
                stored_value = Decimal(meta[key])
                expected_value = Decimal(configured_value)
            except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("Existing realized-P&L ledger capital policy metadata is missing or invalid.") from exc
            if stored_value != expected_value:
                raise ValueError("Configured capital policy differs from the existing realized-P&L ledger.")
        initial = ledger_conn.execute(
            "SELECT 1 FROM ledger_events WHERE event_id='SYSTEM-INITIAL-CAPITAL' AND event_type='INITIAL_CAPITAL'"
        ).fetchone()
        if not initial:
            raise ValueError("Existing realized-P&L ledger has no initial-capital event; refusing initialization.")
    finally:
        ledger_conn.close()

    stager_tables, stager_triggers, stager_conn = read_tables(stager_file)
    try:
        required = {"staged_activities", "activity_stager_meta"}
        if not required.issubset(stager_tables):
            raise ValueError("Existing activity-stager database is missing required tables; refusing initialization.")
        required_triggers = {"staged_activities_no_update", "staged_activities_no_delete"}
        if not required_triggers.issubset(stager_triggers):
            raise ValueError("Existing activity-stager database is missing append-only triggers; refusing initialization.")
    finally:
        stager_conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="List unresolved staged cash movements.")
    action.add_argument("--confirm-deposit", metavar="ACTIVITY_ID")
    action.add_argument("--confirm-withdrawal", metavar="ACTIVITY_ID")
    action.add_argument("--resolve-journal", metavar="ACTIVITY_ID",
                         help="Resolve a JNLC only when evidence proves it is not user capital.")
    parser.add_argument("--reference", help="Traceable bank/broker/operator evidence reference.")
    parser.add_argument("--rationale", help="Required explanation for a JNLC non-capital resolution.")
    parser.add_argument("--fx-rate", help="Validated historical MXN per USD rate.")
    parser.add_argument("--fx-observed-at", help="Timezone-aware quote time, ISO-8601.")
    parser.add_argument("--fx-source", help="Traceable FX source and reference.")
    args = parser.parse_args()

    parent = os.getenv("ROCKET_TRADER_DATA_DIR", "/app/data")
    ledger_path = os.getenv("ROCKET_TRADER_LEDGER_DB", os.path.join(parent, "rocket_trader_ledger.sqlite3"))
    stager_path = os.getenv(
        "ROCKET_TRADER_ACTIVITY_STAGER_DB",
        os.path.join(parent, "rocket_trader_activity_stager.sqlite3"),
    )
    try:
        _require_existing_state(ledger_path, stager_path)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Cash activity admin refused unsafe persistent state: {exc}", file=sys.stderr)
        return 1

    ledger = RealizedPnLLedger(
        ledger_path,
        initial_capital_mxn=os.getenv("ROCKET_TRADER_INITIAL_CAPITAL_MXN", "1000.00"),
        milestone_mxn=os.getenv("ROCKET_TRADER_MILESTONE_MXN", "100000.00"),
    )
    # A fetch override prevents this administrative command from making any
    # network request; it only reads already-staged immutable activity rows.
    stager = AlpacaPaperActivityStager(
        db_path=stager_path,
        fetch_page=lambda _cursor, _size: [],
    )
    fx = _fx_from_args(args) if args.fx_rate else None

    def resolve_fx(_when):
        if fx is None:
            raise ValueError("A validated historical USD/MXN quote is required for USD cash movements.")
        return fx

    bridge = AlpacaCashActivityBridge(
        db_path=stager_path,
        ledger=ledger,
        fx_resolver=resolve_fx,
    )
    # Idempotently mirror all staged movements into the review table before
    # listing or resolving. The ledger remains untouched until explicit action.
    for activity in stager.cash_movements():
        bridge.process_activity(activity)

    if args.list:
        result = {
            "cash_activity_review": bridge.status(),
            "ledger_snapshot": {
                "initial_capital_mxn": str(ledger.snapshot().initial_capital_mxn),
                "deposits_mxn": str(ledger.snapshot().deposits_mxn),
                "withdrawals_mxn": str(ledger.snapshot().withdrawals_mxn),
                "realized_net_pnl_mxn": str(ledger.snapshot().realized_net_pnl_mxn),
                "operating_capital_mxn": str(ledger.snapshot().operating_capital_mxn),
            },
        }
    elif args.confirm_deposit:
        if not args.reference:
            parser.error("--confirm-deposit requires --reference")
        result = bridge.confirm_external_deposit(
            args.confirm_deposit, confirmation_reference=args.reference
        )
    elif args.confirm_withdrawal:
        if not args.reference:
            parser.error("--confirm-withdrawal requires --reference")
        result = bridge.confirm_external_withdrawal(
            args.confirm_withdrawal, confirmation_reference=args.reference
        )
    else:
        if not args.reference or not args.rationale:
            parser.error("--resolve-journal requires --reference and --rationale")
        result = bridge.resolve_journal_as_non_user_capital(
            args.resolve_journal,
            resolution_reference=args.reference,
            rationale=args.rationale,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
