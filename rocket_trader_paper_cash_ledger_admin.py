#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create an explicit read-only Alpaca Paper USD cash anchor.

This command only calls TradingClient.get_account(). It never submits,
replaces, cancels or modifies an order. A new cash ledger database is created
only when --initialize-db is explicitly supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from rocket_trader_alpaca_cash_ledger import (
    AlpacaPaperUSDCashLedger,
    PaperCashLedgerError,
)
from rocket_trader_alpaca_activity_sse_consumer import (
    ActivitySSEConsumerError,
    DurableActivitySSEInbox,
)


def create_paper_cash_anchor(
    *,
    client: Any,
    inbox_db_path: str,
    cash_db_path: str,
    initialize_db: bool = False,
    anchor_id: Optional[str] = None,
    source_reference: Optional[str] = None,
    rebase_confirmed: bool = False,
    rebase_reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Read inbox cursor first, then take one Paper cash snapshot and anchor it."""
    if not Path(inbox_db_path).expanduser().is_file():
        raise PaperCashLedgerError("Existing durable Activity SSE inbox is missing")
    try:
        inbox = DurableActivitySSEInbox(
            str(Path(inbox_db_path).expanduser()), initialize=False
        )
        integrity = inbox.verify()
    except (ActivitySSEConsumerError, ValueError) as exc:
        raise PaperCashLedgerError("Activity SSE inbox integrity verification failed") from exc
    if not isinstance(integrity, dict) or integrity.get("valid") is not True:
        raise PaperCashLedgerError("Activity SSE inbox hash chain/cursor is invalid")
    # Capture the cursor BEFORE the broker snapshot. Events with business time
    # after the snapshot are replayed from this cursor; older delayed events are
    # already reflected in the cash anchor and excluded by event timestamp.
    cursor_before_snapshot = integrity.get("cursor")

    account = client.get_account()
    account_id = str(getattr(account, "id", "") or "").strip()
    currency = str(getattr(account, "currency", "USD") or "USD").strip().upper()
    if not account_id or currency != "USD":
        raise PaperCashLedgerError("Paper account ID and USD account currency are required")
    cash = getattr(account, "cash", None)
    equity = getattr(account, "equity", None)
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise PaperCashLedgerError("Anchor timestamp must be timezone-aware")
    observed = observed.astimezone(timezone.utc)
    observed_iso = observed.isoformat()
    ledger = AlpacaPaperUSDCashLedger(
        str(Path(cash_db_path).expanduser()),
        account_id=account_id,
        initialize=initialize_db,
    )
    final_anchor_id = anchor_id or (
        "paper-cash-anchor-" + observed.strftime("%Y%m%dT%H%M%S%fZ")
    )
    final_source = source_reference or (
        f"alpaca-paper-get-account:{account_id}:{observed_iso}"
    )
    result = ledger.record_anchor(
        anchor_id=final_anchor_id,
        cash_usd=cash,
        observed_at=observed,
        source_reference=final_source,
        activity_cursor_before_snapshot=cursor_before_snapshot,
        rebase_confirmed=rebase_confirmed,
        rebase_reason=rebase_reason,
    )
    return {
        **result,
        "environment": "PAPER",
        "account_id": account_id,
        "account_currency": currency,
        "broker_equity_usd_observed_only": str(equity),
        "activity_cursor_before_snapshot": cursor_before_snapshot,
        "activity_inbox_integrity_valid": True,
        "activity_coverage_complete": False,
        "observed_at": observed_iso,
        "orders_enabled": False,
    }


def _enabled(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cash-db",
        default=os.getenv("ROCKET_TRADER_CASH_LEDGER_DB", "/app/data/rocket_trader_paper_cash.sqlite3"),
    )
    parser.add_argument(
        "--activity-sse-db",
        default=os.getenv("ROCKET_TRADER_ACTIVITY_SSE_DB", "/app/data/rocket_trader_activity_sse.sqlite3"),
    )
    parser.add_argument("--initialize-db", action="store_true")
    parser.add_argument("--anchor-id")
    parser.add_argument("--source-reference")
    parser.add_argument("--rebase-confirmed", action="store_true")
    parser.add_argument("--rebase-reason")
    args = parser.parse_args(argv)

    if os.getenv("ALPACA_PAPER", "false").strip().lower() != "true":
        raise PaperCashLedgerError("ALPACA_PAPER=true is required")
    if _enabled(os.getenv("ALPACA_LIVE_ENABLED", "false")):
        raise PaperCashLedgerError("ALPACA_LIVE_ENABLED must remain false")
    if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
        raise PaperCashLedgerError("ROCKET_TRADER_EXECUTION_MODE must be PAPER")
    if os.getenv("ROCKET_TRADER_RUNTIME_MODE", "OBSERVE_ONLY").strip().upper() != "OBSERVE_ONLY":
        raise PaperCashLedgerError("Only OBSERVE_ONLY runtime mode is permitted")
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        raise PaperCashLedgerError("Paper API credentials are required in the private environment")

    from alpaca.trading.client import TradingClient

    client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
    result = create_paper_cash_anchor(
        client=client,
        inbox_db_path=args.activity_sse_db,
        cash_db_path=args.cash_db,
        initialize_db=args.initialize_db,
        anchor_id=args.anchor_id,
        source_reference=args.source_reference,
        rebase_confirmed=args.rebase_confirmed,
        rebase_reason=args.rebase_reason,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PaperCashLedgerError, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "orders_enabled": False,
        }, indent=2), file=sys.stderr)
        raise SystemExit(1)
