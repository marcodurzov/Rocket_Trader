#!/usr/bin/env python3
"""Read-only audit of Alpaca Paper fills, fees and cash activities."""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from rocket_trader_alpaca_activity_stager import AlpacaPaperActivityStager


def main() -> int:
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: ALPACA_PAPER must be exactly true.")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError("Safety stop: LIVE mode is prohibited.")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Alpaca Paper credentials are missing.")
    with tempfile.TemporaryDirectory(prefix="rocket-paper-activity-audit-") as tmp:
        db = str(Path(tmp) / "activities.sqlite3")
        stager = AlpacaPaperActivityStager(
            db_path=db, api_key=key, api_secret=secret, page_size=100,
        )
        report = stager.sync(max_pages=10)
        print("environment=PAPER")
        print(f"total_staged={report['total_staged']}")
        print(f"pages_fetched={report['pages_fetched']}")
        print(f"counts={json.dumps(report['counts'], sort_keys=True)}")
        print(f"blocked_activity_types={','.join(report['blocked_activity_types'])}")
        print(f"ledger_posting_enabled={report['ledger_posting_enabled']}")
        print("orders_submitted=0")
        print("orders_cancelled=0")
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT activity_type,payload_json,classification FROM staged_activities "
                "ORDER BY occurred_at DESC LIMIT 30"
            ).fetchall()
        print("recent_activity_details_begin")
        for activity_type, raw, classification in rows:
            item = json.loads(raw)
            safe = {
                "activity_type": activity_type,
                "classification": classification,
                "id": item.get("id"),
                "status": item.get("status"),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "execution_id": item.get("execution_id"),
                "parent_id": item.get("parent_id"),
                "order_id": item.get("order_id"),
                "qty": item.get("qty"),
                "price": item.get("price"),
                "net_amount": item.get("net_amount"),
                "currency": item.get("currency"),
                "transaction_time": item.get("transaction_time"),
                "date": item.get("date"),
            }
            print(json.dumps(safe, sort_keys=True, default=str))
        print("recent_activity_details_end")
        if report["blocked_activity_types"]:
            print("audit_result=REVIEW_REQUIRED_UNSUPPORTED_ACTIVITY_TYPES")
            return 2
        print("audit_result=PASS_READ_ONLY_STAGING")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("environment=PAPER")
        print("orders_submitted=0")
        print(f"audit_error={type(exc).__name__}: {exc}")
        raise
