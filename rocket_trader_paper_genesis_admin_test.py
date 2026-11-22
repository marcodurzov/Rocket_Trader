#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the one-time Paper accounting genesis command."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import rocket_trader_paper_genesis_admin as genesis
from rocket_trader_cash_activity_admin import _require_existing_state
from rocket_trader_stream_runtime import _require_existing_fill_bridge, _require_existing_activity_stager

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, *, status="ACTIVE", positions=(), open_orders=(), closed=()):
        self.status, self.positions = status, list(positions)
        self.open_orders, self.closed = list(open_orders), list(closed)
        self.mutations = 0

    def get_account(self):
        return SimpleNamespace(status=self.status)

    def get_all_positions(self):
        return self.positions

    def get_orders(self, filter=None):
        status = getattr(getattr(filter, "status", None), "value", str(getattr(filter, "status", "")))
        return self.open_orders if "open" in status.lower() else self.closed

    def submit_order(self, *a, **k):  # pragma: no cover - must never be called
        self.mutations += 1
        raise AssertionError("genesis must not submit orders")

    cancel_orders = cancel_order_by_id = replace_order_by_id = submit_order


SAFE_ENV = {"ALPACA_PAPER": "true", "ALPACA_LIVE_ENABLED": "false", "ROCKET_TRADER_EXECUTION_MODE": "PAPER"}


class GenesisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = patch.dict(os.environ, SAFE_ENV, clear=False)
        self.env.start()
        for key in ("ROCKET_TRADER_LEDGER_DB", "ROCKET_TRADER_LEDGER_INBOX_DB", "ROCKET_TRADER_ACTIVITY_STAGER_DB"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_genesis(self, client, **kw):
        return genesis.run_genesis(data_dir=self.dir, confirmed=kw.pop("confirmed", True),
                                   client_factory=lambda: client, now=NOW, **kw)

    def test_genesis_creates_state_that_passes_runtime_preflight(self):
        client = FakeClient()
        result = self.run_genesis(client)
        paths = genesis._default_paths(self.dir)
        _require_existing_state(str(paths["ledger"]), str(paths["activity_stager"]))
        _require_existing_fill_bridge(str(paths["fill_inbox"]))
        _require_existing_activity_stager(str(paths["activity_stager"]))
        self.assertEqual(result["initial_capital_mxn"], "1000.00")
        self.assertEqual(result["activity_sse_bootstrap_since"], "2026-11-22T18:00:00Z")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(client.mutations, 0)
        saved = json.loads((self.dir / genesis.ATTESTATION_NAME).read_text())
        self.assertEqual(saved["genesis_at_utc"], result["genesis_at_utc"])

    def test_refuses_without_confirmation_and_creates_nothing(self):
        with self.assertRaises(genesis.GenesisError):
            self.run_genesis(FakeClient(), confirmed=False)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_refuses_to_overwrite_any_existing_file(self):
        self.run_genesis(FakeClient())
        before = {p.name: p.read_bytes() for p in self.dir.iterdir() if p.is_file()}
        with self.assertRaises(genesis.GenesisError):
            self.run_genesis(FakeClient())
        after = {p.name: p.read_bytes() for p in self.dir.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_refuses_when_only_a_wal_sidecar_exists(self):
        Path(str(genesis._default_paths(self.dir)["ledger"]) + "-wal").write_bytes(b"x")
        with self.assertRaises(genesis.GenesisError):
            self.run_genesis(FakeClient())

    def test_refuses_open_positions_orders_recent_fills_or_inactive(self):
        cases = [
            FakeClient(positions=[object()]),
            FakeClient(open_orders=[object()]),
            FakeClient(closed=[SimpleNamespace(filled_at=NOW - timedelta(hours=3))]),
            FakeClient(status="ACCOUNT_CLOSED"),
        ]
        for client in cases:
            with self.subTest(client=client.__dict__):
                with self.assertRaises(genesis.GenesisError):
                    self.run_genesis(client)
                self.assertFalse(genesis._default_paths(self.dir)["ledger"].exists())

    def test_cancelled_unfilled_recent_orders_do_not_block(self):
        self.run_genesis(FakeClient(closed=[SimpleNamespace(filled_at=None)]))

    def test_refuses_live_or_non_paper_configuration(self):
        for env in ({"ALPACA_LIVE_ENABLED": "true"}, {"ALPACA_PAPER": "false"},
                    {"ALPACA_LIVE_ENABLED": "maybe"}, {"ROCKET_TRADER_EXECUTION_MODE": "LIVE"}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                with self.assertRaises(genesis.GenesisError):
                    self.run_genesis(FakeClient())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_quiet_window_minimum(self):
        with self.assertRaises(genesis.GenesisError):
            self.run_genesis(FakeClient(), quiet_hours=6)

    def test_cli_exit_code_on_refusal(self):
        self.assertEqual(genesis.main(["--data-dir", str(self.dir)]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
