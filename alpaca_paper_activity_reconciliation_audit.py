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
            f"- Fill reconciliation: **{report.get('fill_reconciliation_status', 'UNKNOWN')}**",
            f"- Fee reconciliation: **{report.get('fee_reconciliation_status', 'UNKNOWN')}**",
            f"- Symbol: {report.get('symbol', 'UNKNOWN')}",
            f"- Orders found: {report.get('order_count', 0)}",
            f"- Fill reconciliations matched: {report.get('matched_order_count', 0)}",
            f"- Fill reconciliations requiring review: {report.get('unmatched_order_count', 0)}",
            f"- Crypto fee activities found: {report.get('fee_activity_count', 0)}",
            f"- Fee evidence: **{report.get('fee_evidence_status', 'UNKNOWN')}**",
            f"- Unclassified fee activities: {report.get('unclassified_fee_activity_count', 0)}",
            f"- Other-symbol fee activities: {report.get('other_symbol_fee_activity_count', 0)}",
            f"- Incomplete fee activities: {report.get('incomplete_fee_activity_count', 0)}",
            f"- Out-of-window fee activities: {report.get('out_of_window_fee_activity_count', 0)}",
            f"- Fee activities with unverified creation time: {report.get('window_unverified_fee_activity_count', 0)}",
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
                expected_filled_avg_price=getattr(order, "filled_avg_price", None),
                require_average_price=True,
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
                "expected_filled_avg_price": reconciliation["expected_filled_avg_price"],
                "activity_avg_price": reconciliation["activity_avg_price"],
                "average_price_difference": reconciliation["average_price_difference"],
                "average_price_match": reconciliation["average_price_match"],
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
        report["other_symbol_fee_activity_count"] = fee_result["other_symbol_activity_count"]
        report["unclassified_fee_activity_count"] = fee_result["unclassified_activity_count"]
        report["incomplete_fee_activity_count"] = fee_result["incomplete_activity_count"]
        report["out_of_window_fee_activity_count"] = fee_result["out_of_window_activity_count"]
        report["window_unverified_fee_activity_count"] = fee_result["window_unverified_activity_count"]
        report["fee_window_after"] = fee_result["after"]
        report["fee_window_until"] = fee_result["until"]
        report["unclassified_fee_activities"] = fee_result["unclassified_fee_activities"]
        if fee_result["fee_activity_count"]:
            report["fee_evidence_status"] = "UNALLOCATED_CANDIDATES"
        elif fee_result["unclassified_activity_count"] or fee_result["incomplete_activity_count"]:
            report["fee_evidence_status"] = "UNCLASSIFIED_OR_INCOMPLETE_RECORDS"
        elif fee_result["other_symbol_activity_count"]:
            report["fee_evidence_status"] = "OTHER_SYMBOL_RECORDS_ONLY_FEES_UNKNOWN"
        else:
            report["fee_evidence_status"] = "NO_RECORDS_FEES_UNKNOWN"
        report["symbol"] = symbol
        report["order_count"] = len(orders)
        report["matched_order_count"] = matched
        report["unmatched_order_count"] = len(orders) - matched
        fills_matched = matched == len(orders)
        report["fill_reconciliation_status"] = (
            "ALL_ORDERS_MATCHED" if fills_matched else "REQUIRES_REVIEW"
        )
        # This audit gathers account-level fee candidates only. It does not
        # prove allocation to individual executions or post fees to the P&L
        # ledger. An empty fee query is unknown, not zero-cost evidence.
        report["fee_reconciliation_status"] = "UNRESOLVED"
        report["status"] = (
            "FILLS_MATCHED_FEES_UNRESOLVED"
            if fills_matched else "RECONCILIATION_REQUIRES_REVIEW"
        )
        report["review_reason"] = (
            "Fee activities are not linked and allocated to individual fills; "
            "no returned fee records does not establish zero fees."
        )
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        # Exit 2 means the query completed but accounting evidence remains unresolved.
        return 2

    except Exception as exc:
        # Our own validation/reconciliation messages are deliberately safe to
        # display. Never print raw SDK/HTTP exception text, which may contain
        # request details. Preserve only the cause class and HTTP status.
        report["error_type"] = type(exc).__name__
        if isinstance(exc, (ValueError, RuntimeError)):
            report["error_message"] = str(exc)
        cause = exc.__cause__
        cause_chain = []
        while cause is not None and len(cause_chain) < 4:
            item = {"type": type(cause).__name__}
            status = getattr(cause, "status_code", None)
            response = getattr(cause, "response", None)
            if status is None and response is not None:
                status = getattr(response, "status_code", None)
            if isinstance(status, int):
                item["http_status"] = status
            cause_chain.append(item)
            cause = cause.__cause__
        if cause_chain:
            report["cause_chain"] = cause_chain
        report["status"] = "FAILED"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        detail = report.get("error_message", type(exc).__name__)
        cause_detail = ""
        if cause_chain:
            cause_detail = " | cause: " + " -> ".join(
                item["type"] + (
                    f" (HTTP {item['http_status']})"
                    if "http_status" in item else ""
                )
                for item in cause_chain
            )
        print(f"Paper activity audit failed: {detail}{cause_detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
