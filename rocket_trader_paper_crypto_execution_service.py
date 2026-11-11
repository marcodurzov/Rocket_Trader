#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed startup gate for the future Paper crypto execution host.

The market-data observer remains observe-only. This wrapper is the required
orchestration boundary for any future process that wants to submit crypto
Paper intents: verify the account, recover the durable journal, then open the
process-local submission gate. It does not create a broker client or place
orders during startup.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict


class PaperExecutionStartupError(RuntimeError):
    """Startup recovery or execution-gate failure."""


class PaperCryptoExecutionService:
    """Require successful read-only recovery before accepting any new intent.

    Instantiate this wrapper around the adapter configured with the same
    persistent journal and immutable event-ledger paths used by the host.
    Readiness is process-local and starts closed after every process restart.
    """

    @classmethod
    def from_existing_storage(
        cls,
        *,
        db_path: str,
        event_ledger_path: str,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> "PaperCryptoExecutionService":
        """Build the service only from pre-existing durable journal files.

        This prevents a path typo or lost volume from silently creating a new
        empty journal and making startup recovery appear successful.
        """
        if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
            raise PaperExecutionStartupError("ALPACA_PAPER must be exactly true.")
        if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
            raise PaperExecutionStartupError("LIVE mode is prohibited.")
        journal = Path(db_path).expanduser()
        events = Path(event_ledger_path).expanduser()
        if not journal.is_file() or not events.is_file():
            raise PaperExecutionStartupError(
                "Existing durable journal and event-ledger files are required; empty state will not be initialized."
            )
        if journal.resolve() == events.resolve():
            raise PaperExecutionStartupError(
                "Mutable order journal and immutable event ledger must be separate files."
            )
        required_journal_columns = {
            "client_order_id", "fingerprint", "payload_json", "state",
            "broker_order_id", "broker_status", "filled_qty",
            "filled_avg_price", "last_error", "created_at", "updated_at",
        }
        required_event_columns = {
            "sequence", "event_id", "aggregate_id", "event_type",
            "occurred_at", "payload_json", "previous_hash", "event_hash",
        }
        try:
            with sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                journal_columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info(crypto_paper_order_journal)"
                    ).fetchall()
                }
                journal_orders = {
                    row[0] for row in conn.execute(
                        "SELECT client_order_id FROM crypto_paper_order_journal"
                    ).fetchall()
                } if journal_columns else set()
            if not required_journal_columns.issubset(journal_columns):
                raise PaperExecutionStartupError(
                    "Existing execution journal is missing required order-state columns."
                )
            with sqlite3.connect(events.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                event_columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info(execution_events)"
                    ).fetchall()
                }
                triggers = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger'"
                    ).fetchall()
                }
                order_evidence = {
                    (row[0], row[1]) for row in conn.execute(
                        "SELECT DISTINCT aggregate_id, event_type FROM execution_events"
                    ).fetchall()
                } if event_columns else set()
        except sqlite3.Error as exc:
            raise PaperExecutionStartupError(
                "Existing execution journal or immutable event ledger cannot be opened read-only."
            ) from exc
        if not required_event_columns.issubset(event_columns):
            raise PaperExecutionStartupError(
                "Existing immutable event ledger is missing its event table or required columns."
            )
        if not {"execution_events_no_update", "execution_events_no_delete"}.issubset(triggers):
            raise PaperExecutionStartupError(
                "Existing event ledger is missing append-only integrity triggers."
            )
        initial_evidence = {
            aggregate_id for aggregate_id, event_type in order_evidence
            if event_type in {"ORDER_PREPARED", "BROKER_ORDER_DISCOVERED"}
        }
        if not journal_orders.issubset(initial_evidence):
            raise PaperExecutionStartupError(
                "One or more journaled orders lack matching immutable preparation evidence."
            )

        from rocket_trader_crypto_paper_execution import AlpacaCryptoPaperExecutionAdapter

        adapter = AlpacaCryptoPaperExecutionAdapter(
            api_key=api_key,
            api_secret=api_secret,
            db_path=str(journal),
            event_ledger_path=str(events),
        )
        return cls(adapter)

    def __init__(self, adapter: Any) -> None:
        required = ("verify_account", "recover_journaled_orders", "submit")
        if adapter is None or any(not callable(getattr(adapter, name, None)) for name in required):
            raise PaperExecutionStartupError(
                "A crypto Paper adapter with account verification, recovery and submit methods is required."
            )
        self.adapter = adapter
        self._lock = threading.RLock()
        self._ready = False
        self._closed = False
        self._startup_report: Dict[str, Any] | None = None

    @staticmethod
    def _account_is_cash_only_paper(snapshot: Any) -> bool:
        if not isinstance(snapshot, dict):
            return False
        return (
            snapshot.get("mode") == "PAPER"
            and snapshot.get("status") == "ACTIVE"
            and snapshot.get("currency") == "USD"
            and snapshot.get("crypto_status") == "ACTIVE"
            and snapshot.get("trading_blocked") is False
            and str(snapshot.get("multiplier")) == "1"
            and str(snapshot.get("max_margin_multiplier")) == "1"
            and snapshot.get("no_shorting") is True
            and snapshot.get("max_options_trading_level") == 0
        )

    @staticmethod
    def _recovery_is_complete(report: Any) -> bool:
        if not isinstance(report, dict):
            return False
        if report.get("mode") != "PAPER" or report.get("read_only") is not True:
            return False
        if report.get("status") != "SUCCESS":
            return False
        counts = (
            report.get("orders_scanned"),
            report.get("orders_reconciled"),
            report.get("orders_unresolved"),
            report.get("orders_failed"),
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            return False
        scanned, reconciled, unresolved, failed = counts
        return scanned == reconciled and unresolved == 0 and failed == 0

    def start(self) -> Dict[str, Any]:
        """Verify account and reconcile every journaled order before opening the gate."""
        with self._lock:
            if self._closed:
                raise PaperExecutionStartupError("Execution service is stopped and cannot be restarted.")
            if self._ready and self._startup_report is not None:
                return dict(self._startup_report)

            self._ready = False
            self._startup_report = None
            try:
                account_snapshot = self.adapter.verify_account()
                if not self._account_is_cash_only_paper(account_snapshot):
                    raise PaperExecutionStartupError(
                        "Account preflight did not prove ACTIVE USD cash-only Paper configuration."
                    )
                recovery = self.adapter.recover_journaled_orders()
            except PaperExecutionStartupError:
                raise
            except Exception as exc:
                raise PaperExecutionStartupError(
                    "Paper startup verification/recovery failed; new order intents remain blocked."
                ) from exc

            if not self._recovery_is_complete(recovery):
                self._startup_report = {
                    "mode": "PAPER",
                    "ready": False,
                    "recovery": recovery if isinstance(recovery, dict) else None,
                }
                raise PaperExecutionStartupError(
                    "Journal recovery is incomplete or malformed; new order intents remain blocked."
                )

            self._startup_report = {
                "mode": "PAPER",
                "ready": True,
                "account_verified": True,
                "recovery": recovery,
            }
            self._ready = True
            return dict(self._startup_report)

    def submit(self, intent: Any) -> Dict[str, Any]:
        """Submit only after successful startup recovery.

        Any adapter exception closes this process's gate. The operator must
        restart and run recovery before another intent can be accepted.
        """
        with self._lock:
            if self._closed or not self._ready:
                raise PaperExecutionStartupError(
                    "Paper execution startup gate is closed; recover the durable journal before submitting."
                )
            try:
                result = self.adapter.submit(intent)
                if not isinstance(result, dict) or result.get("mode") != "PAPER" or result.get("accepted") is not True:
                    self._ready = False
                    raise PaperExecutionStartupError(
                        "Adapter returned an invalid or non-Paper submission result; execution gate closed."
                    )
                return result
            except Exception as exc:
                self._ready = False
                if isinstance(exc, PaperExecutionStartupError):
                    raise
                raise PaperExecutionStartupError(
                    "Adapter submission raised an error; execution gate closed until restart recovery."
                ) from exc

    def stop(self) -> None:
        """Close the process-local gate; no broker action is performed."""
        with self._lock:
            self._ready = False
            self._closed = True

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": "PAPER",
                "ready": self._ready and not self._closed,
                "closed": self._closed,
                "recovery_status": (
                    (self._startup_report or {}).get("recovery", {}).get("status")
                    if isinstance((self._startup_report or {}).get("recovery"), dict)
                    else None
                ),
            }
