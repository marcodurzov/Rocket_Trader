#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Paper observer runtime; no broker or network calls."""
import asyncio, json, os, sqlite3, tempfile, unittest, sys, types
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from rocket_trader_realized_pnl_ledger import LedgerFX
from rocket_trader_alpaca_cash_ledger import AlpacaPaperUSDCashLedger
from rocket_trader_alpaca_activity_sse_consumer import DurableActivitySSEInbox

from rocket_trader_stream_runtime import (
    AlpacaPaperObserverRuntime, MarketRuntimeRecorder, RuntimeConfigurationError, RuntimeStorageError, RuntimeConfig,
    build_fill_ledger_bridge, build_activity_stager, build_position_reconciliation_gate, sync_cash_activity_review,
    account_activity_reconciliation_clear, reconcile_paper_positions,
)

class StreamRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "runtime.sqlite3")
        self.recorder = MarketRuntimeRecorder(self.db)
    def tearDown(self):
        self.tmp.cleanup()
    def _patch_trading_client(self, client_class):
        alpaca = types.ModuleType("alpaca")
        trading = types.ModuleType("alpaca.trading")
        client = types.ModuleType("alpaca.trading.client")
        client.TradingClient = client_class
        return patch.dict(sys.modules, {
            "alpaca": alpaca,
            "alpaca.trading": trading,
            "alpaca.trading.client": client,
        })

    def test_cash_ledger_runtime_option_defaults_off(self):
        class FakeTradingClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
        config = RuntimeConfig(
            api_key="paper-key", secret_key="paper-secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with self._patch_trading_client(FakeTradingClient), patch.dict(os.environ, {
            "ROCKET_TRADER_CASH_LEDGER_ENABLED": "false",
        }, clear=False):
            gate = build_position_reconciliation_gate(config, object())
        self.assertIsNone(gate.cash_ledger)
        self.assertIsNone(gate.activity_sse_inbox_path)

    def test_cash_ledger_runtime_requires_existing_databases(self):
        class FakeTradingClient:
            def __init__(self, **kwargs):
                self.account_calls = 0
            def get_account(self):
                self.account_calls += 1
                return SimpleNamespace(id="paper-account-1", status="ACTIVE", currency="USD")
        config = RuntimeConfig(
            api_key="paper-key", secret_key="paper-secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with self._patch_trading_client(FakeTradingClient), patch.dict(os.environ, {
            "ROCKET_TRADER_CASH_LEDGER_ENABLED": "true",
            "ALPACA_PAPER": "true",
            "ROCKET_TRADER_CASH_LEDGER_DB": os.path.join(self.tmp.name, "missing-cash.sqlite3"),
            "ROCKET_TRADER_ACTIVITY_SSE_DB": os.path.join(self.tmp.name, "missing-inbox.sqlite3"),
            "ROCKET_TRADER_EXECUTION_MODE": "PAPER",
            "ALPACA_LIVE_ENABLED": "false",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeConfigurationError, "cash ledger is missing"):
                build_position_reconciliation_gate(config, object())

    def test_cash_ledger_runtime_uses_existing_paper_state_read_only(self):
        class FakeTradingClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.account_calls = 0
            def get_account(self):
                self.account_calls += 1
                return SimpleNamespace(id="paper-account-1", currency="USD")
        cash_path = os.path.join(self.tmp.name, "paper-cash.sqlite3")
        inbox_path = os.path.join(self.tmp.name, "activity-sse.sqlite3")
        AlpacaPaperUSDCashLedger(cash_path, account_id="paper-account-1")
        DurableActivitySSEInbox(inbox_path)
        config = RuntimeConfig(
            api_key="paper-key", secret_key="paper-secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with self._patch_trading_client(FakeTradingClient), patch.dict(os.environ, {
            "ROCKET_TRADER_CASH_LEDGER_ENABLED": "true",
            "ALPACA_PAPER": "true",
            "ROCKET_TRADER_CASH_LEDGER_DB": cash_path,
            "ROCKET_TRADER_ACTIVITY_SSE_DB": inbox_path,
            "ROCKET_TRADER_EXECUTION_MODE": "PAPER",
            "ALPACA_LIVE_ENABLED": "false",
        }, clear=False):
            gate = build_position_reconciliation_gate(config, object())
        self.assertIsNotNone(gate.cash_ledger)
        self.assertEqual(gate.activity_sse_inbox_path, inbox_path)
        self.assertEqual(gate.cash_ledger.account_id, "paper-account-1")

    def test_bar_record_is_idempotent(self):
        bar = SimpleNamespace(symbol="BTC/USD", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                               open=100, high=105, low=99, close=104, volume=12,
                               trade_count=3, vwap=102)
        self.assertTrue(self.recorder.record_bar("CRYPTO", bar))
        self.assertFalse(self.recorder.record_bar("CRYPTO", bar))
    def test_invalid_bar_is_rejected(self):
        bar = SimpleNamespace(symbol="SPY", timestamp="2026-01-01T00:00:00+00:00",
                              open=100, high=98, low=99, close=101, volume=10)
        with self.assertRaises(RuntimeError):
            self.recorder.record_bar("EQUITY", bar)
    def test_trade_update_is_deduplicated(self):
        event = {"event":"fill","order":{"id":"abc","client_order_id":"client-1"}}
        self.assertTrue(self.recorder.record_trade_update(event))
        self.assertFalse(self.recorder.record_trade_update(event))
    def test_health_requires_recent_healthy_heartbeats(self):
        now = datetime.now(timezone.utc)
        self.recorder.heartbeat("crypto", "HEALTHY", now.isoformat())
        self.assertTrue(self.recorder.health(120)["healthy"])
        self.recorder.heartbeat("crypto", "ERROR", last_error="disconnected")
        self.assertFalse(self.recorder.health(120)["healthy"])
    def test_health_fails_when_never_started(self):
        with self.assertRaises(RuntimeError):
            self.recorder.health()
    def test_health_separates_heartbeat_from_data_freshness(self):
        event_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        self.recorder.heartbeat("crypto", "HEALTHY", event_at.isoformat())
        now = datetime.now(timezone.utc)
        result = self.recorder.health(
            max_age_seconds=120, now=now,
            data_freshness_thresholds={"crypto": 600},
        )
        self.assertTrue(result["healthy"])
        self.assertEqual(result["components"]["crypto"]["data_freshness"], "STALE")
        self.assertGreaterEqual(result["components"]["crypto"]["event_age_seconds"], 1200)
        self.assertTrue(result["data_freshness_is_diagnostic_only"])
    def test_market_closed_equity_can_be_unmonitored(self):
        self.recorder.heartbeat("equity", "HEALTHY", None)
        now = datetime.now(timezone.utc)
        result = self.recorder.health(max_age_seconds=120, now=now)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["components"]["equity"]["data_freshness"], "NOT_MONITORED")
    def test_future_market_event_is_flagged_without_masking_heartbeat(self):
        event_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.recorder.heartbeat("crypto", "HEALTHY", event_at.isoformat())
        now = datetime.now(timezone.utc)
        result = self.recorder.health(
            max_age_seconds=120, now=now,
            data_freshness_thresholds={"crypto": 600},
        )
        self.assertTrue(result["healthy"])
        self.assertEqual(
            result["components"]["crypto"]["data_freshness"],
            "INVALID_FUTURE_TIMESTAMP",
        )
    def test_unexpected_stream_exit_remains_visible_after_shutdown(self):
        class ExitingStream:
            def run(self):
                return
            def stop(self):
                return

        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
            heartbeat_seconds=0.01,
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder)
        with patch.object(runtime, "build_streams", return_value={"equity": ExitingStream()}):
            with self.assertRaisesRegex(RuntimeError, "equity stream exited"):
                runtime.run()

        result = self.recorder.health(max_age_seconds=120)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["components"]["equity"]["status"], "ERROR")
        self.assertEqual(
            result["components"]["equity"]["last_error"],
            "Stream thread exited unexpectedly.",
        )

    def test_quote_and_fill_streams_record_empirical_cost_observation(self):
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder)
        now = datetime.now(timezone.utc)
        quote = {
            "symbol": "SPY", "timestamp": (now - timedelta(seconds=1)).isoformat(),
            "bid_price": 100.0, "ask_price": 100.2,
            "bid_size": 10, "ask_size": 10,
        }
        asyncio.run(runtime._quote_handler("EQUITY", "IEX")(quote))
        fill = {
            "event": "fill", "timestamp": now.isoformat(),
            "symbol": "SPY", "side": "buy", "price": 100.2, "qty": 2,
            "order": {"id": "cost-order-1", "symbol": "SPY", "side": "buy"},
        }
        asyncio.run(runtime._trade_update_handler(fill))
        summary = runtime.cost_telemetry.summary()
        self.assertEqual(summary["measured_fill_events"], 1)
        self.assertEqual(summary["groups"][0]["symbol"], "SPY")
        self.assertFalse(summary["costs_empirically_validated"])
        health = self.recorder.health(max_age_seconds=120)
        self.assertTrue(health["healthy"])
        self.assertEqual(health["components"]["execution_cost_telemetry"]["status"], "HEALTHY")

    def test_quote_callback_does_not_refresh_bar_stream_heartbeat(self):
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder)
        old_bar_event = datetime.now(timezone.utc) - timedelta(minutes=10)
        runtime.last_events["equity"] = old_bar_event
        good_quote = {
            "symbol": "SPY", "timestamp": datetime.now(timezone.utc).isoformat(),
            "bid_price": 100.0, "ask_price": 100.2,
            "bid_size": 10, "ask_size": 10,
        }
        asyncio.run(runtime._quote_handler("EQUITY", "IEX")(good_quote))
        self.assertEqual(runtime.last_events["equity"], old_bar_event)
        bad_quote = {**good_quote, "bid_price": 100.3, "ask_price": 100.2}
        asyncio.run(runtime._quote_handler("EQUITY", "IEX")(bad_quote))
        summary = runtime.cost_telemetry.summary()
        self.assertEqual(summary["quote_ingestion_errors"], 1)
        self.assertEqual(runtime.last_events["equity"], old_bar_event)

    def test_trade_update_is_forwarded_to_fill_ledger_bridge(self):
        class FakeBridge:
            def __init__(self):
                self.calls = []
            def process_trade_update(self, update):
                self.calls.append(update)
                return {"processed": True}
            def status(self):
                return {"pending_or_failed": 0, "counts": {}}

        bridge = FakeBridge()
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, bridge)
        event = {
            "event": "fill",
            "execution_id": "exec-runtime-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "qty": "1",
            "price": "100",
            "order": {"id": "order-1", "symbol": "SPY", "side": "buy"},
        }
        asyncio.run(runtime._trade_update_handler(event))
        self.assertEqual(len(bridge.calls), 1)
        result = self.recorder.health(max_age_seconds=120)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["components"]["ledger"]["status"], "HEALTHY")

    def test_fill_ledger_bridge_error_is_visible_without_killing_trade_stream(self):
        class FailingBridge:
            def process_trade_update(self, _update):
                raise RuntimeError("fee not yet posted")
            def status(self):
                return {"pending_or_failed": 1, "counts": {"FAILED": 1}}

        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, FailingBridge())
        event = {"event": "fill", "order": {"id": "order-2"}}
        asyncio.run(runtime._trade_update_handler(event))
        result = self.recorder.health(max_age_seconds=120)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["components"]["trading"]["status"], "HEALTHY")
        self.assertEqual(result["components"]["ledger"]["status"], "ERROR")
        self.assertEqual(result["components"]["ledger"]["last_error"], "fee not yet posted")

    def test_ledger_bridge_is_disabled_by_default(self):
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with patch.dict(os.environ, {"ROCKET_TRADER_LEDGER_ENABLED": "false"}, clear=False):
            self.assertIsNone(build_fill_ledger_bridge(config))

    def test_enabled_ledger_bridge_builds_with_durable_paths(self):
        config = RuntimeConfig(
            api_key="paper-key", secret_key="paper-secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        ledger_path = os.path.join(self.tmp.name, "ledger.sqlite3")
        inbox_path = os.path.join(self.tmp.name, "fill-inbox.sqlite3")
        env = {
            "ROCKET_TRADER_LEDGER_ENABLED": "true",
            "ROCKET_TRADER_LEDGER_DB": ledger_path,
            "ROCKET_TRADER_LEDGER_INBOX_DB": inbox_path,
            "ROCKET_TRADER_INITIAL_CAPITAL_MXN": "1000.00",
            "ROCKET_TRADER_MILESTONE_MXN": "100000.00",
        }
        with patch.dict(os.environ, env, clear=False):
            bridge = build_fill_ledger_bridge(config)
        self.assertIsNotNone(bridge)
        self.assertEqual(bridge.status()["pending_or_failed"], 0)
        self.assertTrue(os.path.exists(ledger_path))
        self.assertTrue(os.path.exists(inbox_path))

    def test_account_activity_stager_sync_sets_healthy_heartbeat(self):
        class FakeStager:
            def __init__(self):
                self.calls = 0
            def sync(self):
                self.calls += 1
                return {"total_staged": 3, "inserted_this_sync": 3, "ledger_posting_enabled": False, "blocked_activity_types": []}
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        stager = FakeStager()
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, activity_stager=stager)
        report = runtime._sync_account_activities()
        self.assertEqual(report["total_staged"], 3)
        self.assertEqual(stager.calls, 1)
        health = self.recorder.health(max_age_seconds=120)
        self.assertTrue(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "HEALTHY")

    def test_unmatched_staged_fill_keeps_account_activity_unhealthy(self):
        activity_db = os.path.join(self.tmp.name, "activities.sqlite3")
        inbox_db = os.path.join(self.tmp.name, "inbox.sqlite3")
        execution_id = "8efc7b9a-8b2b-4000-9955-d36e7db0df74"
        activity = {
            "id": "20261110160000000::" + execution_id,
            "activity_type": "FILL", "transaction_time": "2026-11-10T16:00:00Z",
            "symbol": "SPY", "side": "buy", "qty": "1", "price": "500",
            "order_id": "order-1",
        }
        with sqlite3.connect(activity_db) as db:
            db.execute("""CREATE TABLE staged_activities (
                activity_id TEXT PRIMARY KEY, activity_type TEXT, occurred_at TEXT,
                payload_json TEXT, payload_hash TEXT, classification TEXT, staged_at TEXT
            )""")
            db.execute("INSERT INTO staged_activities VALUES(?,?,?,?,?,?,?)", (
                activity["id"], "FILL", activity["transaction_time"],
                json.dumps(activity), "hash", "STAGED_PENDING_RECONCILIATION", "now",
            ))
        with sqlite3.connect(inbox_db) as db:
            db.execute("""CREATE TABLE paper_fill_ledger_inbox (
                execution_id TEXT PRIMARY KEY, payload_hash TEXT, payload_json TEXT,
                status TEXT, last_error TEXT, fx_json TEXT, created_at TEXT, updated_at TEXT
            )""")
        class FakeStager:
            db_path = activity_db
            def sync(self):
                return {
                    "total_staged": 1, "ledger_posting_enabled": False,
                    "blocked_activity_types": [],
                    "counts": {"FILL:STAGED_PENDING_RECONCILIATION": 1},
                }
        class FakeBridge:
            db_path = inbox_db
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, fill_ledger_bridge=FakeBridge(),
            activity_stager=FakeStager(),
        )
        report = runtime._sync_account_activities()
        self.assertEqual(report["trade_fill_reconciliation"]["missing_inbox_fills"], 1)
        health = self.recorder.health(max_age_seconds=120)
        self.assertFalse(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "ERROR")

    def test_matched_processed_fill_allows_account_activity_reconciliation(self):
        activity_db = os.path.join(self.tmp.name, "activities.sqlite3")
        inbox_db = os.path.join(self.tmp.name, "inbox.sqlite3")
        execution_id = "8efc7b9a-8b2b-4000-9955-d36e7db0df74"
        activity = {
            "id": "20261110160000000::" + execution_id,
            "activity_type": "FILL", "transaction_time": "2026-11-10T16:00:00Z",
            "symbol": "SPY", "side": "buy", "qty": "1", "price": "500",
            "order_id": "order-1",
        }
        payload = {
            "event": "fill", "execution_id": execution_id,
            "timestamp": "2026-11-10T16:00:00Z", "symbol": "SPY",
            "side": "BUY", "qty": "1.0", "price": "500",
            "order": {"id": "order-1", "symbol": "SPY", "side": "BUY"},
        }
        with sqlite3.connect(activity_db) as db:
            db.execute("""CREATE TABLE staged_activities (
                activity_id TEXT PRIMARY KEY, activity_type TEXT, occurred_at TEXT,
                payload_json TEXT, payload_hash TEXT, classification TEXT, staged_at TEXT
            )""")
            db.execute("INSERT INTO staged_activities VALUES(?,?,?,?,?,?,?)", (
                activity["id"], "FILL", activity["transaction_time"],
                json.dumps(activity), "hash", "STAGED_PENDING_RECONCILIATION", "now",
            ))
        with sqlite3.connect(inbox_db) as db:
            db.execute("""CREATE TABLE paper_fill_ledger_inbox (
                execution_id TEXT PRIMARY KEY, payload_hash TEXT, payload_json TEXT,
                status TEXT, last_error TEXT, fx_json TEXT, created_at TEXT, updated_at TEXT
            )""")
            db.execute("INSERT INTO paper_fill_ledger_inbox VALUES(?,?,?,?,?,?,?,?)", (
                execution_id, "hash", json.dumps(payload), "PROCESSED",
                None, None, "now", "now",
            ))
        class FakeStager:
            db_path = activity_db
            def sync(self):
                return {
                    "total_staged": 1, "ledger_posting_enabled": False,
                    "blocked_activity_types": [],
                    "counts": {"FILL:STAGED_PENDING_RECONCILIATION": 1},
                }
        class FakeBridge:
            db_path = inbox_db
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, fill_ledger_bridge=FakeBridge(),
            activity_stager=FakeStager(),
        )
        report = runtime._sync_account_activities()
        self.assertEqual(report["trade_fill_reconciliation"]["status"], "RECONCILED")
        health = self.recorder.health(max_age_seconds=120)
        self.assertTrue(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "HEALTHY")

    def test_blocked_account_activity_types_keep_runtime_unhealthy(self):
        class BlockedStager:
            def sync(self):
                return {
                    "total_staged": 4,
                    "blocked_activity_types": ["DIV", "UNKNOWN"],
                    "ledger_posting_enabled": False,
                }
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, activity_stager=BlockedStager())
        report = runtime._sync_account_activities()
        self.assertEqual(report["blocked_activity_types"], ["DIV", "UNKNOWN"])
        health = self.recorder.health(max_age_seconds=120)
        self.assertFalse(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "ERROR")

    def test_activity_stager_cannot_enable_ledger_posting(self):
        class UnsafeStager:
            def sync(self):
                return {"total_staged": 0, "ledger_posting_enabled": True}
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, activity_stager=UnsafeStager())
        self.assertIsNone(runtime._sync_account_activities())
        health = self.recorder.health(max_age_seconds=120)
        self.assertFalse(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "ERROR")

    def test_healthcheck_blocks_pending_and_unsupported_cash_activity(self):
        pending = {
            "blocked_activity_types": [],
            "counts": {"CSD:STAGED_PENDING_CAPITAL_RECONCILIATION": 1},
        }
        blocked = {
            "blocked_activity_types": ["CSD"],
            "counts": {},
        }
        self.assertFalse(account_activity_reconciliation_clear(pending, None))
        self.assertFalse(account_activity_reconciliation_clear(
            pending, {"pending_or_failed": 1}
        ))
        self.assertTrue(account_activity_reconciliation_clear(
            pending, {"pending_or_failed": 0}
        ))
        self.assertFalse(account_activity_reconciliation_clear(
            blocked, {"pending_or_failed": 0}
        ))

    def test_position_reconciliation_is_blocked_until_all_fills_and_fees_resolve(self):
        class Bridge:
            def __init__(self):
                self.fx_called = False
                self.ledger = SimpleNamespace(snapshot=lambda: None)
            def status(self):
                return {"pending_or_failed": 1}
            def fx_resolver(self, _now):
                self.fx_called = True
                raise AssertionError("FX must not be requested while ledger events are pending")
        class Gate:
            def reconcile(self, **_kwargs):
                raise AssertionError("broker positions must not be compared with an incomplete ledger")
        bridge = Bridge()
        result = reconcile_paper_positions(Gate(), bridge, now=datetime.now(timezone.utc))
        self.assertEqual(result["status"], "BLOCKED_PENDING_LEDGER_EVENTS")
        self.assertFalse(bridge.fx_called)

    def test_position_reconciliation_persists_read_only_broker_result(self):
        now = datetime.now(timezone.utc)
        class Ledger:
            def snapshot(self):
                return SimpleNamespace(
                    operating_capital_mxn=Decimal("1000.00"),
                    open_positions={},
                )
        class Bridge:
            ledger = Ledger()
            def status(self):
                return {"pending_or_failed": 0}
            def fx_resolver(self, _when):
                return LedgerFX(Decimal("18.5"), now, "fixture:USD/MXN")
        class Gate:
            def reconcile(self, *, ledger_snapshot, fx_quote, now):
                self.assertion = (
                    ledger_snapshot.operating_capital_mxn == Decimal("1000.00")
                    and fx_quote.mxn_per_usd == Decimal("18.5")
                    and now.tzinfo is not None
                )
                return {
                    "environment": "PAPER",
                    "status": "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE",
                    "position_reconciliation_status": "MATCHED",
                    "positions_match": True,
                    "cash_reconciliation_status": "NOT_IMPLEMENTED_NO_USD_CASH_LEDGER",
                    "account_reconciliation_complete": False,
                }
        gate = Gate()
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, fill_ledger_bridge=Bridge(),
            position_reconciliation_gate=gate,
        )
        report = runtime._reconcile_paper_positions()
        self.assertTrue(gate.assertion)
        self.assertEqual(report["status"], "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE")
        self.assertEqual(
            self.recorder.latest_position_reconciliation()["status"],
            "POSITIONS_MATCHED_ACCOUNTING_INCOMPLETE",
        )
        health = self.recorder.health(max_age_seconds=120)
        self.assertTrue(health["components"]["position_reconciliation"]["healthy"])

    def test_healthcheck_mirrors_staged_cash_before_reading_review_status(self):
        class Stager:
            def __init__(self):
                self.rows = [{
                    "id": "cash-health-1", "activity_type": "CSD",
                    "net_amount": "25", "currency": "MXN",
                    "date": "2026-11-10", "status": "executed",
                }]
            def cash_movements(self):
                return list(self.rows)
        class Bridge:
            def __init__(self):
                self.processed = []
            def process_activity(self, activity):
                self.processed.append(activity)
            def status(self):
                return {"pending_or_failed": 1, "manual_review": [
                    {"activity_id": self.processed[0]["id"]}
                ]}
        stager, bridge = Stager(), Bridge()
        status = sync_cash_activity_review(stager, bridge)
        self.assertEqual(len(bridge.processed), 1)
        self.assertEqual(status["pending_or_failed"], 1)

    def test_cash_healthcheck_requires_a_durable_stager(self):
        class Bridge:
            def status(self):
                return {"pending_or_failed": 0}
        with self.assertRaisesRegex(RuntimeStorageError, "requires a stager"):
            sync_cash_activity_review(None, Bridge())

    def test_cash_activity_bridge_resolves_staged_cash_and_controls_health(self):
        class Stager:
            db_path = os.path.join(tempfile.gettempdir(), "unused-activity.sqlite3")
            def sync(self):
                return {
                    "total_staged": 1,
                    "blocked_activity_types": [],
                    "counts": {"CSD:STAGED_PENDING_CAPITAL_RECONCILIATION": 1},
                    "ledger_posting_enabled": False,
                }
            def cash_movements(self):
                return [{
                    "id": "cash-activity-1", "activity_type": "CSD",
                    "net_amount": "100", "currency": "MXN",
                    "date": "2026-11-10", "status": "executed",
                }]
        class CashBridge:
            def __init__(self, pending):
                self.pending = pending
                self.processed = []
            def process_activity(self, activity):
                self.processed.append(activity)
                return {"manual_review": True}
            def status(self):
                return {
                    "pending_or_failed": self.pending,
                    "manual_review": [{"activity_id": "cash-activity-1"}] if self.pending else [],
                }
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        stager = Stager()
        unresolved = CashBridge(1)
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, activity_stager=stager,
            cash_activity_bridge=unresolved,
        )
        report = runtime._sync_account_activities()
        self.assertEqual(len(unresolved.processed), 1)
        self.assertIn("cash_activity_reconciliation", report)
        self.assertFalse(self.recorder.health(max_age_seconds=120)["healthy"])

        resolved = CashBridge(0)
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, activity_stager=stager,
            cash_activity_bridge=resolved,
        )
        report = runtime._sync_account_activities()
        self.assertEqual(len(resolved.processed), 1)
        self.assertEqual(report["cash_activity_reconciliation"]["pending_or_failed"], 0)
        self.assertTrue(self.recorder.health(max_age_seconds=120)["healthy"])

    def test_pending_capital_movements_keep_runtime_unhealthy(self):
        class PendingCapitalStager:
            def sync(self):
                return {
                    "total_staged": 1,
                    "blocked_activity_types": [],
                    "counts": {"JNLC:STAGED_PENDING_CAPITAL_RECONCILIATION": 1},
                    "ledger_posting_enabled": False,
                }
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(
            config, self.recorder, activity_stager=PendingCapitalStager()
        )
        runtime._sync_account_activities()
        health = self.recorder.health(max_age_seconds=120)
        self.assertFalse(health["healthy"])
        self.assertEqual(health["components"]["account_activity"]["status"], "ERROR")
        self.assertIn(
            "unresolved cash/journal movements",
            health["components"]["account_activity"]["last_error"],
        )

    def test_account_activity_sync_failure_is_visible(self):
        class FailingStager:
            def sync(self):
                raise RuntimeError("broker API unavailable")
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        runtime = AlpacaPaperObserverRuntime(config, self.recorder, activity_stager=FailingStager())
        self.assertIsNone(runtime._sync_account_activities())
        health = self.recorder.health(max_age_seconds=120)
        self.assertFalse(health["healthy"])
        self.assertEqual(
            health["components"]["account_activity"]["status"], "ERROR"
        )
        self.assertIn(
            "broker API unavailable",
            health["components"]["account_activity"]["last_error"],
        )

    def test_activity_stager_is_disabled_by_default(self):
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with patch.dict(os.environ, {"ROCKET_TRADER_ACTIVITY_STAGER_ENABLED": "false"}, clear=False):
            self.assertIsNone(build_activity_stager(config))

    def test_invalid_ledger_enable_flag_is_rejected(self):
        config = RuntimeConfig(
            api_key="key", secret_key="secret", db_path=self.db,
            equity_symbols=("SPY",), crypto_symbols=(),
        )
        with patch.dict(os.environ, {"ROCKET_TRADER_LEDGER_ENABLED": "maybe"}, clear=False):
            with self.assertRaisesRegex(RuntimeConfigurationError, "must be boolean"):
                build_fill_ledger_bridge(config)

    def test_runtime_rejects_any_trading_mode(self):
        env = {"ROCKET_TRADER_RUNTIME_MODE":"LIVE", "ALPACA_API_KEY":"x",
               "ALPACA_SECRET_KEY":"y", "ROCKET_TRADER_RUNTIME_DB":self.db}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeConfigurationError):
                RuntimeConfig.from_env()
    def test_runtime_requires_credentials_and_durable_path(self):
        with patch.dict(os.environ, {"ROCKET_TRADER_RUNTIME_MODE":"OBSERVE_ONLY",
             "ALPACA_API_KEY":"", "ALPACA_SECRET_KEY":"", "ROCKET_TRADER_RUNTIME_DB":""}, clear=False):
            with self.assertRaises(RuntimeConfigurationError):
                RuntimeConfig.from_env()

if __name__ == "__main__":
    unittest.main(verbosity=2)
