#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for explicit Paper cash coverage-schema migration."""

import os
import sqlite3
import tempfile
import unittest

from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger
from rocket_trader_paper_cash_coverage_migration import (
    CashCoverageMigrationError,
    migrate_coverage_schema,
)

ACCOUNT = "paper-account-migration"


class CashCoverageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cash.sqlite3")
        self.backup = os.path.join(self.tmp.name, "cash.pre-coverage.sqlite3")
        ledger = AlpacaPaperUSDCashLedger(self.db, account_id=ACCOUNT)
        ledger.record_anchor(
            anchor_id="migration-anchor",
            cash_usd="1000",
            observed_at="2026-11-13T18:00:00Z",
            source_reference="test-snapshot",
        )
        with sqlite3.connect(self.db) as conn:
            for trigger in (
                "paper_activity_coverage_audits_no_update",
                "paper_activity_coverage_audits_no_delete",
                "paper_activity_coverage_audit_events_no_update",
                "paper_activity_coverage_audit_events_no_delete",
            ):
                conn.execute(f"DROP TRIGGER {trigger}")
            conn.execute("DROP TABLE paper_activity_coverage_audit_events")
            conn.execute("DROP TABLE paper_activity_coverage_audits")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_creates_verified_backup_and_append_only_schema(self):
        result = migrate_coverage_schema(
            db_path=self.db, backup_path=self.backup, account_id=ACCOUNT,
            confirm=True, no_writers_confirmed=True,
        )
        self.assertEqual(result["status"], "MIGRATED")
        self.assertTrue(os.path.isfile(self.backup))
        with sqlite3.connect(self.backup) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertNotIn("paper_activity_coverage_audits", tables)
        with sqlite3.connect(self.db) as conn:
            triggers = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )}
            self.assertIn("paper_activity_coverage_audits_no_update", triggers)
            self.assertIn("paper_activity_coverage_audit_events_no_delete", triggers)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM paper_cash_anchors"
            ).fetchone()[0], 1)

    def test_migration_requires_stopped_writer_confirmation(self):
        with self.assertRaisesRegex(CashCoverageMigrationError, "no-writers-confirmed"):
            migrate_coverage_schema(
                db_path=self.db, backup_path=self.backup, account_id=ACCOUNT,
                confirm=True, no_writers_confirmed=False,
            )
        self.assertFalse(os.path.exists(self.backup))

    def test_migration_refuses_existing_backup_path(self):
        with open(self.backup, "w", encoding="utf-8") as stream:
            stream.write("do not overwrite")
        with self.assertRaisesRegex(CashCoverageMigrationError, "must not already exist"):
            migrate_coverage_schema(
                db_path=self.db, backup_path=self.backup, account_id=ACCOUNT,
                confirm=True, no_writers_confirmed=True,
            )
        with open(self.backup, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "do not overwrite")

    def test_migration_refuses_account_mismatch(self):
        with self.assertRaisesRegex(CashCoverageMigrationError, "differs from the persisted"):
            migrate_coverage_schema(
                db_path=self.db, backup_path=self.backup, account_id="other-account",
                confirm=True, no_writers_confirmed=True,
            )

    def test_migration_is_idempotent_after_success(self):
        migrate_coverage_schema(
            db_path=self.db, backup_path=self.backup, account_id=ACCOUNT,
            confirm=True, no_writers_confirmed=True,
        )
        again = migrate_coverage_schema(
            db_path=self.db,
            backup_path=os.path.join(self.tmp.name, "second-backup.sqlite3"),
            account_id=ACCOUNT, confirm=True, no_writers_confirmed=True,
        )
        self.assertEqual(again["status"], "ALREADY_CURRENT")

