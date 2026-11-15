#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coordinate a bounded, read-only Paper cash/fee/account reconciliation.

This module does not submit orders or mutate the broker account. It binds one
broker account snapshot to an Activity SSE coverage audit and an independent
fill-to-fee allocation audit. Any pending fill, missing database, stale
reference, changed ledger, or failed audit blocks full account reconciliation.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rocket_trader_paper_reconciliation import PaperReconciliationError


class PaperAccountEvidenceError(RuntimeError):
    """Full Paper account evidence is incomplete or internally inconsistent."""


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise PaperAccountEvidenceError(f"{field} must be an ISO-8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PaperAccountEvidenceError(f"{field} must be timezone-aware")
    return result.astimezone(timezone.utc)


class PaperAccountEvidenceCoordinator:
    """Bind the cash, coverage, fee and position checks to one Paper snapshot."""

    def __init__(
        self,
        *,
        reconciliation_gate: Any,
        fill_ledger_bridge: Any,
        cash_ledger: Any,
        activity_sse_inbox_path: str,
        coverage_auditor: Any,
        fee_allocation_auditor: Any,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        required = {
            "reconciliation_gate": reconciliation_gate,
            "fill_ledger_bridge": fill_ledger_bridge,
            "cash_ledger": cash_ledger,
            "coverage_auditor": coverage_auditor,
            "fee_allocation_auditor": fee_allocation_auditor,
        }
        missing = [key for key, value in required.items() if value is None]
        if missing:
            raise PaperAccountEvidenceError(
                "Full account evidence requires: " + ", ".join(missing)
            )
        if not isinstance(activity_sse_inbox_path, str) or not activity_sse_inbox_path.strip():
            raise PaperAccountEvidenceError("A durable Activity SSE inbox path is required")
        if getattr(reconciliation_gate, "cash_ledger", None) is not cash_ledger:
            raise PaperAccountEvidenceError("Reconciliation gate and coordinator must share the same cash ledger")
        if getattr(coverage_auditor, "cash_ledger", None) is not cash_ledger:
            raise PaperAccountEvidenceError("Coverage auditor must use the same cash ledger")
        if getattr(fee_allocation_auditor, "cash_ledger", None) is not cash_ledger:
            raise PaperAccountEvidenceError("Fee auditor must use the same cash ledger")
        self.activity_sse_inbox_path = str(Path(activity_sse_inbox_path).expanduser())
        if Path(getattr(coverage_auditor, "inbox_db_path", "")).expanduser().resolve() != Path(
            self.activity_sse_inbox_path
        ).resolve():
            raise PaperAccountEvidenceError("Coverage auditor and coordinator must share the same Activity SSE inbox")
        if Path(getattr(reconciliation_gate, "activity_sse_inbox_path", "") or "").expanduser().resolve() != Path(
            self.activity_sse_inbox_path
        ).resolve():
            raise PaperAccountEvidenceError("Reconciliation gate and coordinator must share the same Activity SSE inbox")
        if Path(getattr(fee_allocation_auditor, "realized_pnl_db_path", "")).expanduser().resolve() != Path(
            fill_ledger_bridge.ledger.db_path
        ).resolve():
            raise PaperAccountEvidenceError("Fee auditor and fill bridge must share the same realized-P&L ledger")
        if Path(getattr(fee_allocation_auditor, "fill_bridge_db_path", "")).expanduser().resolve() != Path(
            fill_ledger_bridge.db_path
        ).resolve():
            raise PaperAccountEvidenceError("Fee auditor and fill bridge must share the same fill inbox")
        self.reconciliation_gate = reconciliation_gate
        self.fill_ledger_bridge = fill_ledger_bridge
        self.cash_ledger = cash_ledger
        self.coverage_auditor = coverage_auditor
        self.fee_allocation_auditor = fee_allocation_auditor
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _active_anchor(self) -> tuple[str, datetime]:
        path = Path(self.cash_ledger.db_path).expanduser().resolve()
        if not path.is_file():
            raise PaperAccountEvidenceError("Existing Paper cash ledger database is missing")
        uri = path.as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=30) as conn:
                conn.execute("PRAGMA query_only=ON")
                row = conn.execute(
                    "SELECT account_id,observed_at FROM paper_cash_anchors "
                    "WHERE account_id=? ORDER BY observed_at DESC LIMIT 1",
                    (self.cash_ledger.account_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PaperAccountEvidenceError("Could not read the active Paper cash anchor") from exc
        if row is None:
            raise PaperAccountEvidenceError("An existing immutable Paper cash anchor is required")
        return str(row[0]), _utc(row[1], "cash anchor observed_at")

    def _assert_fill_bridge_clear(self) -> Dict[str, Any]:
        status = self.fill_ledger_bridge.status()
        pending = int(status.get("pending_or_failed", 0))
        if pending:
            raise PaperAccountEvidenceError(
                f"{pending} fill(s) remain pending, failed or under manual review"
            )
        return status

    def reconcile(self) -> Dict[str, Any]:
        """Run all evidence checks for one read-only Paper account snapshot."""
        cash_path = Path(self.cash_ledger.db_path).expanduser()
        inbox_path = Path(self.activity_sse_inbox_path).expanduser()
        ledger_path = Path(self.fill_ledger_bridge.ledger.db_path).expanduser()
        bridge_path = Path(self.fill_ledger_bridge.db_path).expanduser()
        for label, path in (
            ("cash ledger", cash_path),
            ("Activity SSE inbox", inbox_path),
            ("realized-P&L ledger", ledger_path),
            ("fill-bridge inbox", bridge_path),
        ):
            if not path.is_file():
                raise PaperAccountEvidenceError(f"Existing {label} database is missing")

        # Stage all already-received SSE activities before taking the snapshot.
        self.cash_ledger.ingest_from_activity_sse_inbox(
            inbox_db_path=str(inbox_path)
        )
        account_id, anchor_at = self._active_anchor()
        if account_id != str(self.cash_ledger.account_id):
            raise PaperAccountEvidenceError("Active cash anchor account ID changed")

        bridge_before = self._assert_fill_bridge_clear()
        ledger_before = self.fill_ledger_bridge.ledger.snapshot()
        ledger_event_count = int(ledger_before.event_count)

        # Read positions first and account cash/equity last. The timestamp is
        # captured immediately after get_account; cash reconciliation only
        # includes activities through this boundary.
        try:
            broker_positions = self.reconciliation_gate.client.get_all_positions()
            broker_account = self.reconciliation_gate.client.get_account()
        except Exception as exc:
            raise PaperAccountEvidenceError("Read-only Paper account/position snapshot failed") from exc
        snapshot_at = _utc(self.clock(), "broker snapshot observed_at")
        if snapshot_at <= anchor_at:
            raise PaperAccountEvidenceError("Broker snapshot must be later than the active cash anchor")
        broker_account_id = str(
            getattr(broker_account, "id", None)
            or (broker_account.get("id") if isinstance(broker_account, dict) else "")
            or ""
        ).strip()
        if broker_account_id != account_id:
            raise PaperAccountEvidenceError("Broker snapshot account ID differs from the cash anchor")

        # Coverage and fee audits are bounded to exactly the same snapshot time.
        try:
            coverage = self.coverage_auditor.audit(
                since=anchor_at,
                until=snapshot_at,
                checked_at=_utc(self.clock(), "coverage checked_at"),
            )
            fee_audit = self.fee_allocation_auditor.audit(
                coverage_audit_id=str(coverage["audit_id"]),
                since=anchor_at,
                until=snapshot_at,
                checked_at=_utc(self.clock(), "fee audit checked_at"),
            )
        except Exception as exc:
            raise PaperAccountEvidenceError(
                f"Activity coverage or fee allocation audit failed: {exc}"
            ) from exc

        # If any fill was added while the broker snapshot and audits were in
        # flight, the snapshot is not a stable accounting boundary. Retry later.
        bridge_after = self._assert_fill_bridge_clear()
        ledger_after = self.fill_ledger_bridge.ledger.snapshot()
        if (
            int(ledger_after.event_count) != ledger_event_count
            or bridge_after.get("counts") != bridge_before.get("counts")
        ):
            raise PaperAccountEvidenceError(
                "Fill ledger changed during account snapshot/audits; retry on the next cycle"
            )

        try:
            from rocket_trader_currency import FXQuote

            fx_value = self.fill_ledger_bridge.fx_resolver(snapshot_at)
            fx_quote = FXQuote(
                mxn_per_usd=fx_value.mxn_per_usd,
                observed_at=fx_value.observed_at,
                source=fx_value.source,
            )
            report = self.reconciliation_gate.reconcile(
                ledger_snapshot=ledger_before,
                fx_quote=fx_quote,
                now=snapshot_at,
                activity_coverage_complete=True,
                activity_coverage_reference=str(coverage["audit_id"]),
                activity_coverage_checked_at=_utc(coverage["checked_at"], "coverage audit checked_at"),
                fee_reconciliation_complete=True,
                fee_reconciliation_reference=str(fee_audit["audit_id"]),
                fee_reconciliation_checked_at=_utc(fee_audit["checked_at"], "fee audit checked_at"),
                broker_snapshot=(broker_account, broker_positions),
            )
        except Exception as exc:
            raise PaperAccountEvidenceError(
                f"Paper cash/equity reconciliation failed closed: {exc}"
            ) from exc

        # The reconciliation gate itself performs local ledger/cash checks.
        # Recheck after it returns so a fill arriving during that final work
        # cannot leave a stale success report in the runtime recorder.
        bridge_final = self._assert_fill_bridge_clear()
        ledger_final = self.fill_ledger_bridge.ledger.snapshot()
        if (
            int(ledger_final.event_count) != ledger_event_count
            or bridge_final.get("counts") != bridge_before.get("counts")
        ):
            raise PaperAccountEvidenceError(
                "Fill ledger changed during final account reconciliation; retry on the next cycle"
            )

        report.update({
            "account_evidence_status": (
                "RECONCILED"
                if report.get("account_reconciliation_complete") is True
                and report.get("fee_reconciliation_status") == "RECONCILED"
                else "INCOMPLETE"
            ),
            "account_snapshot_observed_at": snapshot_at.isoformat(),
            "activity_coverage_audit_id": coverage["audit_id"],
            "activity_coverage_checked_at": coverage["checked_at"],
            "fee_allocation_audit_id": fee_audit["audit_id"],
            "fee_allocation_checked_at": fee_audit["checked_at"],
            "fill_ledger_event_count": ledger_event_count,
            "orders_enabled": False,
        })
        if report["account_evidence_status"] != "RECONCILED":
            raise PaperAccountEvidenceError(
                "Broker positions/cash/equity did not fully reconcile with covered fee allocation"
            )
        return report
