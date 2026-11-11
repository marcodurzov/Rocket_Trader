#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manual, read-only Alpaca Paper order/fill/crypto-fee activity audit.

No order submission, replacement, cancellation, or account mutation exists in
this script. It is intended to verify the real Paper account-activity endpoint
against an explicitly supplied order time window.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from rocket_trader_alpaca_activity_reconciliation import (
    AlpacaAccountActivityReader,
)
from rocket_trader_crypto_paper_execution import normalize_crypto_symbol
from rocket_trader_execution_event_ledger import ExecutionEventLedger


def _aware_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset.")
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    return str(value)


def _write_report(report: Dict[str, Any]) -> None:
    report_path = os.getenv("ROCKET_TRADER_ACTIVITY_REPORT")
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Alpaca Paper read-only activity audit",
            "",
            f"- Status: **{report.get('status', 'UNKNOWN')}**",
            f"- Symbol: {report.get('symbol', 'UNKNOWN')}",
            f"- Orders found: {report.get('order_count', 0)}",
            f"- Fill reconciliations matched: {report.get('matched_order_count', 0)}",
            f"- Fill reconciliations requiring review: {report.get('unmatched_order_count', 0)}",
            f"- Crypto fee activities found: {report.get('fee_activity_count', 0)}",
            f"- Fee evidence: **{report.get('fee_evidence_status', 'UNKNOWN')}**",
            "",
            "Fee records, when present, are account-level candidates and are not assigned to an order without documented linkage.",
            "",
        ]
        for item in report.get("orders", []):
            lines.append(
                f"- Order {item.get('broker_order_id')}: {item.get('side')} "
                f"{item.get('filled_qty')} — {item.get('reconciliation_status')}"
            )
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main() -> int:
    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER",
        "status": "FAILED",
        "orders": [],
        "fees": [],
        "fee_activity_count": 0,
        "fee_evidence_status": "UNKNOWN",
    }
    try:
        if os.getenv("ALPACA_PAPER", "false").strip().lower() != "true":
            raise ValueError("ALPACA_PAPER must be true.")
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise ValueError("LIVE is prohibited for this audit.")

        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not api_secret:
            raise ValueError("Required Alpaca Paper secrets are unavailable.")

        symbol = normalize_crypto_symbol(os.getenv("AUDIT_SYMBOL", "BTC/USD"))
        orders_after = _aware_datetime(os.environ["AUDIT_ORDERS_AFTER"], "orders_after")
        orders_until = _aware_datetime(os.environ["AUDIT_ORDERS_UNTIL"], "orders_until")
        fees_after = _aware_datetime(os.environ["AUDIT_FEES_AFTER"], "fees_after")
        fees_until = _aware_datetime(os.environ["AUDIT_FEES_UNTIL"], "fees_until")
        if orders_after >= orders_until or fees_after >= fees_until:
            raise ValueError("Each audit time window must have after earlier than until.")

        client = TradingClient(api_key, api_secret, paper=True)
        account = client.get_account()
        account_status = _text(getattr(account, "status", "UNKNOWN")).upper()
        account_currency = _text(getattr(account, "currency", "UNKNOWN")).upper()
        crypto_status = _text(getattr(account, "crypto_status", "UNKNOWN")).upper()
        if (
            account_status != "ACTIVE"
            or account_currency != "USD"
            or crypto_status != "ACTIVE"
            or bool(getattr(account, "trading_blocked", False))
            or _text(getattr(account, "multiplier", "UNKNOWN")) != "1"
            or bool(getattr(account, "shorting_enabled", True))
        ):
            raise RuntimeError("Paper account does not satisfy the verified cash-only trading policy.")
        account_config = client.get_account_configurations()
        if (
            _text(getattr(account_config, "max_margin_multiplier", "UNKNOWN")) != "1"
            or not bool(getattr(account_config, "no_shorting", False))
            or int(getattr(account_config, "max_options_trading_level", -1)) != 0
        ):
            raise RuntimeError("Paper account configuration does not satisfy cash-only guardrails.")
        report["account_preflight"] = "ACTIVE_USD_CASH_ONLY_NO_SHORT"

        order_filter = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            symbols=[symbol],
            after=orders_after,
            until=orders_until,
            limit=500,
        )
        orders = client.get_orders(filter=order_filter)
        if not isinstance(orders, list):
            raise RuntimeError("Broker order query returned an invalid response.")
        if len(orders) >= 500:
            raise RuntimeError("Order query reached its 500-order limit; narrow the time window.")
        if not orders:
            raise RuntimeError("No matching orders found; verify the symbol and requested time window.")

        ledger_path = os.getenv(
            "ROCKET_TRADER_ACTIVITY_AUDIT_DB",
            str(Path(os.getenv("RUNNER_TEMP", ".")) / "paper-activity-evidence.sqlite3"),
        )
        ledger = ExecutionEventLedger(ledger_path)
        reader = AlpacaAccountActivityReader(client, ledger, max_pages=20)

        matched = 0
        for order in orders:
            broker_order_id = str(getattr(order, "id", "") or "")
            client_order_id = str(getattr(order, "client_order_id", "") or broker_order_id)
            order_symbol = normalize_crypto_symbol(str(getattr(order, "symbol", "")))
            side = _text(getattr(order, "side", "")).lower()
            if not broker_order_id or not client_order_id or order_symbol != symbol:
                raise RuntimeError("Broker order identity or symbol validation failed.")
            if side not in {"buy", "sell"}:
                raise RuntimeError("Broker order side is outside supported spot BUY/SELL scope.")

            snapshot_filled_qty = str(getattr(order, "filled_qty", None) or "0")
            reconciliation = reader.reconcile_order_fills(
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                expected_symbol=symbol,
                expected_side=side,
                expected_filled_qty=snapshot_filled_qty,
            )
            order_record = {
                "broker_order_id": broker_order_id,
                "client_order_id": client_order_id,
                "symbol": order_symbol,
                "side": side,
                "status": _text(getattr(order, "status", "UNKNOWN")).lower(),
                "filled_qty": snapshot_filled_qty,
                "reconciliation_status": reconciliation["reconciliation_status"],
                "activity_filled_qty": reconciliation["activity_filled_qty"],
                "fill_count": reconciliation["fill_count"],
            }
            report["orders"].append(order_record)
            if reconciliation["reconciliation_status"] == "MATCHED":
                matched += 1

        fee_result = reader.collect_crypto_fee_candidates(
            symbol=symbol,
            after=fees_after.isoformat(),
            until=fees_until.isoformat(),
        )
        report["fees"] = fee_result["fee_activities"]
        report["fee_activity_count"] = fee_result["fee_activity_count"]
        report["fee_evidence_status"] = (
            "UNALLOCATED_CANDIDATES"
            if fee_result["fee_activity_count"]
            else "NO_RECORDS_FEES_UNKNOWN"
        )
        report["symbol"] = symbol
        report["order_count"] = len(orders)
        report["matched_order_count"] = matched
        report["unmatched_order_count"] = len(orders) - matched
        report["status"] = "SUCCESS" if matched == len(orders) else "RECONCILIATION_REQUIRES_REVIEW"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        return 0 if report["status"] == "SUCCESS" else 1

    except Exception as exc:
        # Do not echo SDK exception strings: they can contain request metadata.
        report["error_type"] = type(exc).__name__
        report["status"] = "FAILED"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        print(f"Paper activity audit failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
