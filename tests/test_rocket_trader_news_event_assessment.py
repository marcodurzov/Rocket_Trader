import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from rocket_trader_news_event_assessment import NewsEventAssessmentStore
from rocket_trader_regime_selector import NewsRiskOverlay, NewsSeverity


class NewsEventAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "events.sqlite3")
        self.now = datetime.now(timezone.utc)
        self.store = NewsEventAssessmentStore(self.db)
        self.source_db = os.path.join(self.tmp.name, "rocket_trader_alpaca_news.sqlite3")
        with sqlite3.connect(self.source_db) as db:
            db.execute("""CREATE TABLE news_articles (
                source TEXT, article_id INTEGER, provider_created_at TEXT,
                live_first_seen_at TEXT, url TEXT, point_in_time_eligible INTEGER
            )""")

    def tearDown(self):
        self.tmp.cleanup()

    def event_payload(self, independent_groups=("reuters", "ap")):
        published = (self.now - timedelta(minutes=6)).isoformat()
        seen = (self.now - timedelta(minutes=5)).isoformat()
        domains = ("reuters.com", "apnews.com")
        sources = []
        for index, group in enumerate(independent_groups):
            article_id = str(1000 + index)
            url = f"https://{domains[index % 2]}/story-{index}"
            sources.append({
                "source": "fixture-news",
                "article_id": article_id,
                "url": url,
                "published_at": published,
                "first_seen_at": seen,
                "source_domain": domains[index % 2],
                "independent_source_group": group,
            })
            with sqlite3.connect(self.source_db) as db:
                db.execute("""INSERT OR REPLACE INTO news_articles
                    (source,article_id,provider_created_at,live_first_seen_at,url,point_in_time_eligible)
                    VALUES(?,?,?,?,?,1)""",
                    ("fixture-news", int(article_id), published, seen, url))
        return {
            "event_id": "event-geopolitical-1",
            "title": "Verified geopolitical event",
            "event_type": "geopolitical",
            "summary": "Evidence-backed event summary.",
            "affected_symbols": ["SPY", "QQQ"],
            "sources": sources,
        }

    def assessment_payload(self, **overrides):
        data = {
            "event_id": "event-geopolitical-1",
            "severity": "CRITICAL",
            "relevance": 0.9,
            "credibility": 0.9,
            "novelty": 0.9,
            "point_in_time_eligible": True,
            "evaluator_version": "human-reviewed-v1",
            "rationale": "Two independent sources confirm the event.",
            "assessed_at": self.now.isoformat(),
            "expires_at": (self.now + timedelta(hours=4)).isoformat(),
        }
        data.update(overrides)
        return data

    def create_pending_critical(self, groups=("reuters", "ap")):
        self.store.import_event(self.event_payload(groups))
        return self.store.import_assessment(self.assessment_payload())

    def test_assessments_are_pending_until_human_review(self):
        assessment_id = self.create_pending_critical()
        self.assertEqual(len(self.store.pending()), 1)
        self.assertEqual(self.store.load_approved(now=self.now), [])
        self.store.review(assessment_id, "human-reviewer", "approve", self.now)
        approved = self.store.load_approved(now=self.now, symbols=("SPY",))
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].severity, NewsSeverity.CRITICAL)
        risk = NewsRiskOverlay().evaluate(approved, symbols=("SPY",), now=self.now)
        self.assertTrue(risk.block_new_entries)

    def test_critical_event_requires_two_independent_source_groups(self):
        assessment_id = self.create_pending_critical(groups=("same-wire",))
        with self.assertRaisesRegex(ValueError, "two independent source groups"):
            self.store.review(assessment_id, "reviewer", "approve", self.now)
        self.assertEqual(len(self.store.load_approved(now=self.now)), 0)

    def test_critical_event_requires_high_confidence_and_point_in_time_evidence(self):
        self.store.import_event(self.event_payload())
        assessment_id = self.store.import_assessment(
            self.assessment_payload(credibility=0.6)
        )
        with self.assertRaisesRegex(ValueError, "credibility/relevance"):
            self.store.review(assessment_id, "reviewer", "approve", self.now)

    def test_expired_approved_assessment_is_not_loaded(self):
        self.store.import_event(self.event_payload())
        assessment_id = self.store.import_assessment(self.assessment_payload(
            severity="HIGH",
            assessed_at=(self.now - timedelta(minutes=4)).isoformat(),
            expires_at=(self.now - timedelta(minutes=1)).isoformat(),
        ))
        self.store.review(assessment_id, "reviewer", "approve", self.now)
        self.assertEqual(self.store.load_approved(now=self.now), [])

    def test_future_source_evidence_cannot_be_approved_as_point_in_time(self):
        self.store.import_event(self.event_payload())
        future = (self.now + timedelta(minutes=5)).isoformat()
        assessment_id = self.store.import_assessment(self.assessment_payload(
            severity="HIGH", assessed_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(hours=1)).isoformat(),
        ))
        # Import an event with future first-seen evidence is rejected before assessment.
        with self.assertRaisesRegex(ValueError, "first-seen before"):
            self.store.import_event({
                **self.event_payload(),
                "event_id": "future-event",
                "sources": [{
                    "source": "fixture", "article_id": "future",
                    "url": "https://example.com/future",
                    "published_at": future, "first_seen_at": self.now.isoformat(),
                    "source_domain": "example.com",
                    "independent_source_group": "example",
                }],
            })
        self.store.review(assessment_id, "reviewer", "approve", self.now)
        self.assertEqual(len(self.store.load_approved(now=self.now)), 1)

    def test_assessment_cannot_predate_first_live_observation(self):
        self.store.import_event(self.event_payload())
        assessment_id = self.store.import_assessment(self.assessment_payload(
            severity="HIGH",
            assessed_at=(self.now - timedelta(minutes=10)).isoformat(),
            expires_at=(self.now + timedelta(hours=1)).isoformat(),
        ))
        with self.assertRaisesRegex(ValueError, "predate the event"):
            self.store.review(assessment_id, "reviewer", "approve", self.now)

    def test_symbol_filter_does_not_apply_btc_news_to_equity_universe(self):
        assessment_id = self.create_pending_critical()
        self.store.review(assessment_id, "reviewer", "approve", self.now)
        approved = self.store.load_approved(now=self.now, symbols=("BTCUSD",))
        self.assertEqual(approved, [])
        equity = self.store.load_approved(now=self.now, symbols=("SPY",))
        self.assertEqual(len(equity), 1)

    def test_reject_review_never_loads_into_selector(self):
        assessment_id = self.create_pending_critical()
        self.store.review(assessment_id, "reviewer", "reject", self.now)
        self.assertEqual(self.store.load_approved(now=self.now), [])

    def test_point_in_time_flag_must_be_json_boolean(self):
        self.store.import_event(self.event_payload())
        with self.assertRaisesRegex(ValueError, "JSON boolean"):
            self.store.import_assessment(self.assessment_payload(
                point_in_time_eligible="false"
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
