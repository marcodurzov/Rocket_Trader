import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from rocket_trader_regime_observer import (
    MarketFeatureBuilder, PaperRegimeObserver, RegimeDecisionStore,
)
from rocket_trader_news_event_assessment import NewsEventAssessmentStore


class RegimeObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = os.path.join(self.tmp.name, "market.sqlite3")
        self.decision_db = os.path.join(self.tmp.name, "decisions.sqlite3")
        with sqlite3.connect(self.market_db) as db:
            db.execute("""CREATE TABLE market_bars (
                asset_class TEXT, symbol TEXT, timestamp TEXT, close REAL
            )""")
        self.now = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def add_bars(self, asset_class="EQUITY", symbols=("SPY", "QQQ", "IWM"),
                 count=90, stale_minutes=1):
        rows = []
        for index in range(count):
            timestamp = (self.now - timedelta(minutes=stale_minutes + count - index - 1)).isoformat()
            for symbol_index, symbol in enumerate(symbols):
                close = 100.0 + symbol_index * 10 + index * (0.08 + symbol_index * 0.01)
                rows.append((asset_class, symbol, timestamp, close))
        with sqlite3.connect(self.market_db) as db:
            db.executemany("INSERT INTO market_bars VALUES(?,?,?,?)", rows)

    def test_features_build_from_aligned_fresh_bars(self):
        self.add_bars()
        state, diagnostics = MarketFeatureBuilder(self.market_db).build(
            "EQUITY", ("SPY", "QQQ", "IWM"), now=self.now
        )
        self.assertIsNotNone(state)
        self.assertEqual(diagnostics["status"], "FEATURES_READY")
        self.assertGreaterEqual(state.data_quality, 0.8)
        self.assertGreater(state.trend_strength, 0)
        self.assertEqual(state.breadth, 1.0)

    def test_insufficient_bars_fail_closed(self):
        self.add_bars(count=20)
        state, diagnostics = MarketFeatureBuilder(self.market_db).build(
            "EQUITY", ("SPY", "QQQ", "IWM"), now=self.now
        )
        self.assertIsNone(state)
        self.assertEqual(diagnostics["status"], "INSUFFICIENT_DATA")

    def test_stale_bars_fail_closed(self):
        self.add_bars(stale_minutes=90)
        state, diagnostics = MarketFeatureBuilder(self.market_db).build(
            "EQUITY", ("SPY", "QQQ", "IWM"), now=self.now
        )
        self.assertIsNone(state)
        self.assertEqual(diagnostics["status"], "STALE_OR_UNALIGNED_DATA")

    def test_observer_persists_cash_only_until_candidates_are_approved(self):
        self.add_bars("EQUITY", ("SPY", "QQQ", "IWM"))
        self.add_bars("CRYPTO", ("BTC/USD", "ETH/USD", "SOL/USD"))
        observer = PaperRegimeObserver(self.market_db, self.decision_db)
        report = observer.evaluate_once(now=self.now)
        self.assertFalse(report["orders_enabled"])
        self.assertEqual(report["candidate_count"], 0)
        for asset_class in ("EQUITY", "CRYPTO"):
            decision = report["universes"][asset_class]
            self.assertEqual(decision["cash_weight"], 1.0)
            self.assertEqual(decision["total_exposure"], 0.0)
            self.assertEqual(decision["allocations"], [])
            self.assertTrue(decision["abstain"])
        latest = observer.store.latest()
        self.assertEqual(len(latest), 2)
        self.assertTrue(all(item["status"] == "EVALUATED" for item in latest))

    def test_approved_critical_news_is_applied_only_to_affected_universe(self):
        self.add_bars("EQUITY", ("SPY", "QQQ", "IWM"))
        self.add_bars("CRYPTO", ("BTC/USD", "ETH/USD", "SOL/USD"))
        event_db = os.path.join(self.tmp.name, "news_events.sqlite3")
        events = NewsEventAssessmentStore(event_db)
        published = (self.now - timedelta(minutes=6)).isoformat()
        seen = (self.now - timedelta(minutes=5)).isoformat()
        source_db = os.path.join(self.tmp.name, "rocket_trader_alpaca_news.sqlite3")
        with sqlite3.connect(source_db) as db:
            db.execute("""CREATE TABLE news_articles (
                source TEXT, article_id INTEGER, provider_created_at TEXT,
                live_first_seen_at TEXT, url TEXT, point_in_time_eligible INTEGER
            )""")
            db.executemany("""INSERT INTO news_articles
                (source,article_id,provider_created_at,live_first_seen_at,url,point_in_time_eligible)
                VALUES(?,?,?,?,?,1)""", [
                    ("wire-a", 101, published, seen, "https://wire-a.example/story"),
                    ("wire-b", 102, published, seen, "https://wire-b.example/story"),
                ])
        events.import_event({
            "event_id": "event-spy-systemic",
            "title": "Verified systemic market event",
            "event_type": "macro",
            "summary": "Two independent sources confirm a systemic event.",
            "affected_symbols": ["SPY", "QQQ", "IWM"],
            "sources": [
                {"source": "wire-a", "article_id": "101",
                 "url": "https://wire-a.example/story",
                 "published_at": published, "first_seen_at": seen,
                 "source_domain": "wire-a.example",
                 "independent_source_group": "wire-a"},
                {"source": "wire-b", "article_id": "102",
                 "url": "https://wire-b.example/story",
                 "published_at": published, "first_seen_at": seen,
                 "source_domain": "wire-b.example",
                 "independent_source_group": "wire-b"},
            ],
        })
        assessment_id = events.import_assessment({
            "event_id": "event-spy-systemic", "severity": "CRITICAL",
            "relevance": .9, "credibility": .9, "novelty": .9,
            "point_in_time_eligible": True,
            "evaluator_version": "human-reviewed-v1",
            "rationale": "Reviewed, independent, time-valid evidence.",
            "assessed_at": self.now.isoformat(),
            "expires_at": (self.now + timedelta(hours=2)).isoformat(),
        })
        events.review(assessment_id, "human-reviewer", "approve", self.now)
        observer = PaperRegimeObserver(self.market_db, self.decision_db, event_db=event_db)
        report = observer.evaluate_once(now=self.now)
        equity = report["universes"]["EQUITY"]
        crypto = report["universes"]["CRYPTO"]
        self.assertTrue(equity["news_overlay"]["block_new_entries"])
        self.assertEqual(equity["news_overlay"]["exposure_multiplier"], 0.0)
        self.assertEqual(equity["news_assessments_loaded"], 1)
        self.assertFalse(crypto["news_overlay"]["block_new_entries"])
        self.assertEqual(crypto["news_assessments_loaded"], 0)
        self.assertEqual(equity["cash_weight"], 1.0)
        self.assertEqual(crypto["cash_weight"], 1.0)

    def test_missing_universe_data_is_recorded_as_cash_abstention(self):
        self.add_bars("EQUITY", ("SPY", "QQQ", "IWM"))
        observer = PaperRegimeObserver(self.market_db, self.decision_db)
        report = observer.evaluate_once(now=self.now)
        self.assertEqual(
            report["universes"]["CRYPTO"]["reason"], "INSUFFICIENT_DATA"
        )
        self.assertEqual(report["universes"]["CRYPTO"]["cash_weight"], 1.0)

    def test_health_measures_observer_liveness_not_market_freshness(self):
        store = RegimeDecisionStore(self.decision_db)
        evaluated = datetime.now(timezone.utc).isoformat()
        store.save("EQUITY", evaluated, None, {
            "status": "EVALUATED",
            "decision": {"status": "CASH_ABSTAIN", "reason": "STALE_OR_UNALIGNED_DATA"},
        })
        health = store.health()
        self.assertTrue(health["healthy"])
        latest = store.latest()
        self.assertEqual(latest[0]["status"], "EVALUATED")
        self.assertIn("decision", latest[0]["decision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
