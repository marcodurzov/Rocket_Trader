#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicitly add immutable Activity SSE coverage-audit tables to a Paper cash DB.

This migration is local SQLite schema work only. It does not call Alpaca,
modify account state, or submit orders. Stop every process writing to the cash
ledger and create a verified backup before allowing the schema change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


class CashCoverageMigrationError(RuntimeError):
    """Unsafe or incomplete Paper cash-ledger schema migration."""


COVERAGE_TABLES = {
    "paper_activity_coverage_audits",
    "paper_activity_coverage_audit_events",
}
COVERAGE_TRIGGERS = {
    "paper_activity_coverage_audits_no_update",
    "paper_activity_coverage_audits_no_delete",
    "paper_activity_coverage_audit_events_no_update",
    "paper_activity_coverage_audit_events_no_delete",
}
BASE_TABLES = {"paper_cash_anchors", "paper_cash_activities"}
BASE_TRIGGERS = {
    "paper_cash_anchors_no_update", "paper_cash_anchors_no_delete",
    "paper_cash_activities_no_update", "paper_cash_activities_no_delete",
}


def _state(conn: sqlite3.Connection) -> Dict[str, Any]:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    triggers = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    counts = {}
    for table in sorted(BASE_TABLES):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return {
        "tables": tables,
        "triggers": triggers,
        "counts": counts,
        "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
    }


def migrate_coverage_schema(
    *,
    db_path: str,
    backup_path: str,
    account_id: str,
    confirm: bool = False,
    no_writers_confirmed: bool = False,
) -> Dict[str, Any]:
    if confirm is not True or no_writers_confirmed is not True:
        raise CashCoverageMigrationError(
            "Migration requires --confirm and --no-writers-confirmed"
        )
    source_path = Path(db_path).expanduser()
    backup_file = Path(backup_path).expanduser()
    if not source_path.is_file():
        raise CashCoverageMigrationError("Existing Paper cash ledger database is missing")
    if not account_id.strip():
        raise CashCoverageMigrationError("Paper account ID is required")
    if source_path.resolve() == backup_file.resolve() or backup_file.exists():
        raise CashCoverageMigrationError("Backup path must be different and must not already exist")
    if not backup_file.parent.is_dir():
        raise CashCoverageMigrationError("Backup directory must already exist")

    source = sqlite3.connect(str(source_path), timeout=30, isolation_level=None)
    try:
        source.execute("PRAGMA foreign_keys=ON")
        before = _state(source)
        if before["integrity"] != "ok":
            raise CashCoverageMigrationError("Source cash ledger integrity check failed")
        if not BASE_TABLES.issubset(before["tables"]) or not BASE_TRIGGERS.issubset(before["triggers"]):
            raise CashCoverageMigrationError("Source cash ledger schema or append-only triggers are incomplete")
        anchor = source.execute(
            "SELECT account_id FROM paper_cash_anchors ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        if anchor and str(anchor[0]) != account_id.strip():
            raise CashCoverageMigrationError("Provided account ID differs from the persisted cash anchor")
        existing_coverage_tables = COVERAGE_TABLES & before["tables"]
        existing_coverage_triggers = COVERAGE_TRIGGERS & before["triggers"]
        if existing_coverage_tables or existing_coverage_triggers:
            if COVERAGE_TABLES.issubset(before["tables"]) and COVERAGE_TRIGGERS.issubset(before["triggers"]):
                return {"status": "ALREADY_CURRENT", "db_path": str(source_path)}
            raise CashCoverageMigrationError("Partial coverage schema detected; manual review is required")

        backup = sqlite3.connect(str(backup_file), timeout=30)
        try:
            source.backup(backup)
            backup_state = _state(backup)
            if (
                backup_state["integrity"] != "ok"
                or backup_state["counts"] != before["counts"]
                or not BASE_TABLES.issubset(backup_state["tables"])
            ):
                raise CashCoverageMigrationError("Backup integrity or row-count verification failed")
        finally:
            backup.close()
    finally:
        source.close()

    backup_digest = hashlib.sha256(backup_file.read_bytes()).hexdigest()
    conn = sqlite3.connect(str(source_path), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        current = _state(conn)
        if current["counts"] != before["counts"] or current["integrity"] != "ok":
            raise CashCoverageMigrationError("Cash ledger changed after backup; migration refused")
        if COVERAGE_TABLES & current["tables"] or COVERAGE_TRIGGERS & current["triggers"]:
            raise CashCoverageMigrationError("Coverage schema changed after backup; migration refused")
        anchor = conn.execute(
            "SELECT account_id FROM paper_cash_anchors ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        if anchor and str(anchor[0]) != account_id.strip():
            raise CashCoverageMigrationError("Provided account ID differs from the persisted cash anchor")
        conn.execute("""
            CREATE TABLE paper_activity_coverage_audits (
                audit_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                anchor_id TEXT NOT NULL,
                since_at TEXT NOT NULL,
                until_at TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                events_digest TEXT NOT NULL,
                inbox_cursor TEXT,
                payload_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE paper_activity_coverage_audit_events (
                audit_id TEXT NOT NULL,
                ref_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                PRIMARY KEY(audit_id, ref_id),
                FOREIGN KEY(audit_id) REFERENCES paper_activity_coverage_audits(audit_id)
            )
        """)
        for table in ("paper_activity_coverage_audits", "paper_activity_coverage_audit_events"):
            conn.execute(
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Paper coverage evidence is append-only'); END"
            )
            conn.execute(
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Paper coverage evidence is append-only'); END"
            )
        after = _state(conn)
        if not COVERAGE_TABLES.issubset(after["tables"]) or not COVERAGE_TRIGGERS.issubset(after["triggers"]):
            raise CashCoverageMigrationError("Coverage schema creation did not complete")
        if after["counts"] != before["counts"] or after["integrity"] != "ok":
            raise CashCoverageMigrationError("Existing cash ledger rows changed during schema migration")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {
        "status": "MIGRATED",
        "db_path": str(source_path),
        "backup_path": str(backup_file),
        "backup_sha256": backup_digest,
        "existing_cash_anchor_count": before["counts"]["paper_cash_anchors"],
        "existing_cash_activity_count": before["counts"]["paper_cash_activities"],
        "coverage_schema_tables": sorted(COVERAGE_TABLES),
        "append_only_triggers_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--backup-path", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument(
        "--no-writers-confirmed",
        action="store_true",
        help="Confirm all processes writing to this cash ledger have been stopped.",
    )
    args = parser.parse_args()
    result = migrate_coverage_schema(
        db_path=args.db_path,
        backup_path=args.backup_path,
        account_id=args.account_id,
        confirm=args.confirm,
        no_writers_confirmed=args.no_writers_confirmed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
