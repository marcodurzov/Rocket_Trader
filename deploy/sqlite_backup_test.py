#!/usr/bin/env python3
"""Offline tests for deploy/sqlite_backup.py using genesis-created databases."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

import sqlite_backup  # noqa: E402
import rocket_trader_paper_genesis_admin as genesis  # noqa: E402
from rocket_trader_paper_genesis_admin_test import FakeClient  # noqa: E402

ENV = {"ALPACA_PAPER": "true", "ALPACA_LIVE_ENABLED": "false", "ROCKET_TRADER_EXECUTION_MODE": "PAPER"}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.data, self.backup, self.restore = base / "data", base / "backup", base / "restore"
        self.data.mkdir()
        with patch.dict(os.environ, ENV):
            for k in ("ROCKET_TRADER_LEDGER_DB", "ROCKET_TRADER_LEDGER_INBOX_DB", "ROCKET_TRADER_ACTIVITY_STAGER_DB"):
                os.environ.pop(k, None)
            genesis.run_genesis(data_dir=self.data, confirmed=True, client_factory=FakeClient,
                                now=datetime(2026, 11, 22, tzinfo=timezone.utc),
                                filters_factory=lambda since: ("OPEN", ("CLOSED", since)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_then_restore_passes_runtime_preflight(self):
        b = sqlite_backup.backup(self.data, self.backup)
        self.assertEqual(len(b["sqlite_files"]), 3)
        manifest = json.loads((self.backup / sqlite_backup.MANIFEST).read_text())
        self.assertIn(genesis.ATTESTATION_NAME, manifest["files"])
        r = sqlite_backup.restore_test(self.backup, self.restore)
        self.assertEqual(r["runtime_preflight"], "passed")

    def test_backup_refuses_non_empty_destination(self):
        self.backup.mkdir()
        (self.backup / "x").write_text("x")
        with self.assertRaises(SystemExit):
            sqlite_backup.backup(self.data, self.backup)

    def test_tampered_backup_is_rejected(self):
        sqlite_backup.backup(self.data, self.backup)
        with sqlite3.connect(self.backup / "rocket_trader_activity_stager.sqlite3") as c:
            c.execute("CREATE TABLE tamper(x)")
        with self.assertRaises(SystemExit):
            sqlite_backup.restore_test(self.backup, self.restore)

    def test_source_is_not_modified(self):
        def dump(path):
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as c:
                return list(c.iterdump())
        names = [p for p in self.data.iterdir() if p.suffix == ".sqlite3"]
        before = {p.name: dump(p) for p in names}
        sqlite_backup.backup(self.data, self.backup)
        self.assertEqual(before, {p.name: dump(p) for p in names})

    def test_backup_copies_are_single_file_rollback_journal(self):
        sqlite_backup.backup(self.data, self.backup)
        for p in self.backup.glob("*.sqlite3"):
            with sqlite3.connect(p) as c:
                self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")

if __name__ == "__main__":
    unittest.main(verbosity=2)
