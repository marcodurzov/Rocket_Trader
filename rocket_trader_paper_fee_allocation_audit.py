#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify Paper fill-to-fee allocation across cash, bridge and MXN ledgers.

The auditor reads only local append-only databases. It never calls Alpaca and
never places or changes orders. Every fee activity must map to exactly one
processed fill, and the mapped amounts must equal the fee values persisted in
the MXN realized-P&L ledger. Unlinked regulatory/venue fees remain unresolved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from rocket_trader_alpaca_cash_ledger import (
    AlpacaPaperUSDCashLedger,
    PaperCashLedgerError,
    _canonical,
    _iso,
    _timestamp,
)


class PaperFeeAllocationAuditError(RuntimeError):
    """Paper fee evidence is missing, ambiguous or inconsistent."""


def _read_only(path: str) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise PaperFeeAllocationAuditError(f"Required existing database is missing: {resolved.name}")
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    from decimal import Decimal, InvalidOperation
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperFeeAllocationAuditError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise PaperFeeAllocationAuditError(f"{field} must be finite")
    return result


def _utc(value: Any, field: str) -> datetime:
    try:
        return _timestamp(value, field)
    except PaperCashLedgerError as exc:
        raise PaperFeeAllocationAuditError(str(exc)) from exc


class AlpacaPaperFeeAllocationAuditor:
    def __init__(
        self,
        *,
        cash_ledger: AlpacaPaperUSDCashLedger,
        realized_pnl_db_path: str,
        fill_bridge_db_path: str,
    ) -> None:
        if cash_ledger is None:
            raise PaperFeeAllocationAuditError("Paper cash ledger is required")
        self.cash_ledger = cash_ledger
        self.realized_pnl_db_path = str(Path(realized_pnl_db_path).expanduser())
        self.fill_bridge_db_path = str(Path(fill_bridge_db_path).expanduser())

    @staticmethod
    def _verify_event_hash(row: sqlite3.Row, label: str) -> Dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise PaperFeeAllocationAuditError(f"{label} payload JSON is invalid") from exc
        if not isinstance(payload, dict) or _hash_json(payload) != str(row["payload_hash"]):
            raise PaperFeeAllocationAuditError(f"{label} payload hash mismatch")
        return payload

    def audit(
        self,
        *,
        coverage_audit_id: str,
        since: Any,
        until: Any,
        checked_at: Optional[Any] = None,
    ) -> Dict[str, Any]:
        start = _utc(since, "fee audit since")
        end = _utc(until, "fee audit until")
        checked = _utc(checked_at or datetime.now(timezone.utc), "fee audit checked_at")
        if start >= end or checked < end:
            raise PaperFeeAllocationAuditError("Fee audit requires since < until and checked_at after the window")
        try:
            coverage = self.cash_ledger.verify_activity_coverage_audit(
                audit_id=coverage_audit_id,
                observed_at=end,
            )
        except PaperCashLedgerError as exc:
            raise PaperFeeAllocationAuditError("A valid bounded Activity SSE coverage audit is required first") from exc
        if coverage["since_at"] != _iso(start):
            raise PaperFeeAllocationAuditError("Fee audit window must begin at the active cash anchor")
        if _utc(coverage["until_at"], "coverage until_at") < end:
            raise PaperFeeAllocationAuditError("Activity coverage audit does not cover the fee audit window")

        try:
            with _read_only(self.cash_ledger.db_path) as cash_db:
                cash_rows = cash_db.execute(
                    """SELECT * FROM paper_cash_activities
                       WHERE account_id=? AND occurred_at>? AND occurred_at<=?
                       ORDER BY occurred_at,event_id""",
                    (self.cash_ledger.account_id, _iso(start), _iso(end)),
                ).fetchall()
            with _read_only(self.fill_bridge_db_path) as bridge_db:
                bridge_rows = bridge_db.execute(
                    "SELECT execution_id,payload_hash,payload_json,status FROM paper_fill_ledger_inbox"
                ).fetchall()
            with _read_only(self.realized_pnl_db_path) as pnl_db:
                meta = dict(pnl_db.execute("SELECT key,value FROM ledger_meta").fetchall())
                pnl_triggers = {
                    row[0] for row in pnl_db.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger'"
                    ).fetchall()
                }
                required_pnl_triggers = {
                    "ledger_events_no_update", "ledger_events_no_delete",
                    "monthly_closes_no_update", "monthly_closes_no_delete",
                }
                if meta.get("realized_pnl_accounting_method") != "FIFO_MXN_ENTRY_AND_EXIT_FX_V2":
                    raise PaperFeeAllocationAuditError("MXN ledger must use the entry/exit FX FIFO accounting method")
                if not required_pnl_triggers.issubset(pnl_triggers):
                    raise PaperFeeAllocationAuditError("MXN ledger append-only triggers are missing")
                pnl_rows = pnl_db.execute(
                    "SELECT event_id,event_type,occurred_at,payload_json,payload_hash FROM ledger_events WHERE event_type='FILL'"
                ).fetchall()
        except sqlite3.Error as exc:
            raise PaperFeeAllocationAuditError("Could not read the cash, fill bridge and MXN ledger databases") from exc

        bridge_by_id: Dict[str, sqlite3.Row] = {}
        for row in bridge_rows:
            execution_id = str(row["execution_id"])
            if execution_id in bridge_by_id:
                raise PaperFeeAllocationAuditError("Fill bridge contains duplicate execution IDs")
            bridge_by_id[execution_id] = row
        pnl_by_event: Dict[str, tuple[sqlite3.Row, Dict[str, Any]]] = {}
        for row in pnl_rows:
            payload = self._verify_event_hash(row, "MXN fill event")
            if row["event_id"] in pnl_by_event:
                raise PaperFeeAllocationAuditError("MXN ledger contains duplicate fill event IDs")
            pnl_by_event[str(row["event_id"])] = (row, payload)

        fills: Dict[str, Dict[str, Any]] = {}
        fees: Dict[str, Dict[str, Any]] = {}
        fee_totals: Dict[str, Dict[str, Any]] = {}
        for row in cash_rows:
            activity_type = str(row["activity_type"]).upper()
            payload = json.loads(row["payload_json"])
            if activity_type == "TRD":
                execution_id = str(row["ref_id"])
                details = payload.get("details") or {}
                if (
                    str(payload.get("status") or "").lower() != "executed"
                    or str(details.get("execution_type") or "").lower() != "fill"
                    or payload.get("previous_id") is not None
                ):
                    raise PaperFeeAllocationAuditError(
                        f"Trade activity {execution_id} is not a final ordinary fill; correction/bust review is required"
                    )
                bridge_row = bridge_by_id.get(execution_id)
                if bridge_row is None or bridge_row["status"] != "PROCESSED":
                    raise PaperFeeAllocationAuditError(f"Fill {execution_id} is not PROCESSED by the fee-aware bridge")
                bridge_payload = self._verify_event_hash(bridge_row, "Fill bridge")
                pnl_event_id = f"ALPACA-FILL-{execution_id}"
                pnl_pair = pnl_by_event.get(pnl_event_id)
                if pnl_pair is None:
                    raise PaperFeeAllocationAuditError(f"Fill {execution_id} is missing from the MXN realized-P&L ledger")
                pnl_row, pnl_payload = pnl_pair
                symbol = str(details.get("symbol") or "").upper()
                side = str(details.get("side") or "").upper()
                qty = _decimal(payload.get("qty"), "Activity fill qty")
                price = _decimal(payload.get("price"), "Activity fill price")
                if (
                    bridge_payload.get("execution_id") != execution_id
                    or str(bridge_payload.get("symbol") or "").upper() != symbol
                    or str(bridge_payload.get("side") or "").upper() != side
                    or _decimal(bridge_payload.get("qty"), "Bridge fill qty") != qty
                    or _decimal(bridge_payload.get("price"), "Bridge fill price") != price
                    or str(bridge_payload.get("activity_event_id") or "") != str(payload.get("event_id") or "")
                    or str(pnl_payload.get("symbol") or "").upper() != symbol
                    or str(pnl_payload.get("side") or "").upper() != side
                    or _decimal(pnl_payload.get("quantity"), "MXN fill quantity") != qty
                    or _decimal(pnl_payload.get("price_usd"), "MXN fill price") != price
                    or _utc(pnl_row["occurred_at"], "MXN fill timestamp")
                       != _utc(payload.get("executed_at"), "Activity executed_at")
                ):
                    raise PaperFeeAllocationAuditError(f"Cash, bridge and MXN fill evidence disagree for {execution_id}")
                fee_refs = pnl_payload.get("fee_activity_refs", [])
                fee_ids = pnl_payload.get("fee_activity_ids", [])
                if (
                    not isinstance(fee_refs, list) or not isinstance(fee_ids, list)
                    or any(not isinstance(ref, str) or not ref.strip() for ref in fee_refs)
                    or len(set(fee_refs)) != len(fee_refs)
                ):
                    raise PaperFeeAllocationAuditError(f"Fill {execution_id} has invalid persisted fee references")
                fills[execution_id] = {
                    "execution_id": execution_id,
                    "fill_event_id": pnl_event_id,
                    "fill_event_hash": str(pnl_row["payload_hash"]),
                    "bridge_payload_hash": str(bridge_row["payload_hash"]),
                    "fee_usd": str(pnl_payload.get("fee_usd", "0")),
                    "fee_asset_qty": str(pnl_payload.get("fee_asset_qty", "0")),
                    "fee_source": str(pnl_payload.get("fee_source") or ""),
                    "fee_activity_refs": sorted(fee_refs),
                    "fee_activity_ids": sorted(fee_ids),
                    "asset_class": str(pnl_payload.get("asset_class") or ""),
                    "side": side,
                }
                fee_totals[execution_id] = {"fee_usd": Decimal("0"), "fee_asset_qty": Decimal("0"), "refs": []}

        for row in cash_rows:
            activity_type = str(row["activity_type"]).upper()
            if activity_type not in {"FEE", "CFEE"}:
                continue
            payload = json.loads(row["payload_json"])
            ref_id = str(row["ref_id"])
            if payload.get("previous_id") is not None or str(payload.get("status") or "").lower() != "executed":
                raise PaperFeeAllocationAuditError(f"Fee activity {ref_id} is a correction or non-final record")
            matches = [
                execution_id for execution_id, fill in fills.items()
                if ref_id in fill["fee_activity_refs"]
            ]
            if len(matches) != 1:
                raise PaperFeeAllocationAuditError(
                    f"Fee activity {ref_id} maps to {len(matches)} fills; exact one-to-one allocation is required"
                )
            execution_id = matches[0]
            fill = fills[execution_id]
            amount = _decimal(payload.get("net_amount", "0"), "Fee net_amount")
            fee_usd = Decimal("0")
            fee_asset_qty = Decimal("0")
            if amount > 0:
                raise PaperFeeAllocationAuditError(f"Fee activity {ref_id} is a credit/reversal")
            if activity_type == "FEE":
                if str(payload.get("currency") or "").upper() != "USD":
                    raise PaperFeeAllocationAuditError(f"Non-USD FEE activity {ref_id} needs separate conversion")
                fee_usd = abs(amount)
            else:
                qty = _decimal(payload.get("qty", "0"), "CFEE qty")
                price = _decimal(payload.get("price", "0"), "CFEE price")
                if fill["side"] == "BUY" and qty < 0 and price > 0:
                    fee_asset_qty = qty
                    fee_usd = abs(qty) * price
                elif fill["side"] == "SELL" and amount < 0:
                    fee_usd = abs(amount)
                else:
                    raise PaperFeeAllocationAuditError(f"CFEE activity {ref_id} denomination cannot be mapped to its fill")
            fee_totals[execution_id]["fee_usd"] += fee_usd
            fee_totals[execution_id]["fee_asset_qty"] += fee_asset_qty
            fee_totals[execution_id]["refs"].append(ref_id)
            fees[ref_id] = {
                "ref_id": ref_id,
                "execution_id": execution_id,
                "cash_payload_hash": str(row["payload_hash"]),
                "fee_usd": str(fee_usd),
                "fee_asset_qty": str(fee_asset_qty),
            }

        fill_manifest = []
        for execution_id, fill in sorted(fills.items()):
            totals = fee_totals[execution_id]
            if set(totals["refs"]) != set(fill["fee_activity_refs"]):
                raise PaperFeeAllocationAuditError(f"Fill {execution_id} has fee references not present in the cash activity window")
            if (
                totals["fee_usd"] != _decimal(fill["fee_usd"], "MXN fill fee_usd")
                or totals["fee_asset_qty"] != _decimal(fill["fee_asset_qty"], "MXN fill fee_asset_qty")
            ):
                if not (
                    fill["asset_class"] == "US_EQUITY" and fill["side"] == "BUY"
                    and not fill["fee_activity_refs"]
                    and _decimal(fill["fee_usd"], "MXN fill fee_usd") == 0
                    and _decimal(fill["fee_asset_qty"], "MXN fill fee_asset_qty") == 0
                    and "commission-free" in fill["fee_source"].lower()
                ):
                    raise PaperFeeAllocationAuditError(f"Resolved fee totals do not match the MXN fill {execution_id}")
            fill_manifest.append({
                key: fill[key] for key in (
                    "execution_id", "fill_event_id", "fill_event_hash", "bridge_payload_hash",
                    "fee_usd", "fee_asset_qty", "fee_source", "fee_activity_refs",
                )
            })

        report = self.cash_ledger.record_fee_allocation_audit(
            coverage_audit_id=coverage_audit_id,
            since_at=start,
            until_at=end,
            checked_at=checked,
            fill_manifest=fill_manifest,
            fee_manifest=[fees[key] for key in sorted(fees)],
        )
        return {
            **report,
            "account_id": self.cash_ledger.account_id,
            "fill_count": len(fills),
            "fee_count": len(fees),
            "all_fills_processed": True,
            "all_fee_activities_allocated": True,
            "fee_amounts_match_mxn_ledger": True,
            "orders_enabled": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cash-db", default=os.getenv("ROCKET_TRADER_CASH_LEDGER_DB", "/app/data/rocket_trader_paper_cash.sqlite3"))
    parser.add_argument("--realized-pnl-db", default=os.getenv("ROCKET_TRADER_LEDGER_DB", "/app/data/rocket_trader_ledger.sqlite3"))
    parser.add_argument("--fill-bridge-db", default=os.getenv("ROCKET_TRADER_FILL_LEDGER_INBOX_DB", "/app/data/rocket_trader_fill_ledger_inbox.sqlite3"))
    parser.add_argument("--coverage-audit-id", required=True)
    parser.add_argument("--until", help="Inclusive audit window end (RFC3339); defaults to current UTC time.")
    args = parser.parse_args()

    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise PaperFeeAllocationAuditError("ALPACA_LIVE_ENABLED must remain false")
    if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
        raise PaperFeeAllocationAuditError("ROCKET_TRADER_EXECUTION_MODE must be PAPER")
    cash_path = Path(args.cash_db).expanduser().resolve()
    with _read_only(str(cash_path)) as conn:
        anchor = conn.execute(
            "SELECT account_id,observed_at FROM paper_cash_anchors ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
    if anchor is None:
        raise PaperFeeAllocationAuditError("A Paper cash anchor is required")
    ledger = AlpacaPaperUSDCashLedger(str(cash_path), account_id=str(anchor["account_id"]), initialize=False)
    until = _utc(args.until, "fee audit until") if args.until else datetime.now(timezone.utc)
    auditor = AlpacaPaperFeeAllocationAuditor(
        cash_ledger=ledger,
        realized_pnl_db_path=args.realized_pnl_db,
        fill_bridge_db_path=args.fill_bridge_db,
    )
    report = auditor.audit(
        coverage_audit_id=args.coverage_audit_id,
        since=anchor["observed_at"],
        until=until,
        checked_at=datetime.now(timezone.utc),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
