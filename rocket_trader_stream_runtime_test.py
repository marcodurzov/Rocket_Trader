#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for Paper observer runtime; no broker or network calls."""
import asyncio, os, tempfile, unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from rocket_trader_stream_runtime import (
    AlpacaPaperObserverRuntime, MarketRuntimeRecorder, RuntimeConfigurationError, RuntimeStorageError, RuntimeConfig,
    build_fill_ledger_bridge, build_activity_stager, sync_cash_activity_review,\n    account_activity_reconciliation_clear,
)

class StreamRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "runtime.sqlite3")
        self.recorder = MarketRuntimeRecorder(self.db)
    def tearDown(self):
        self.tmp.cleanup()
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
