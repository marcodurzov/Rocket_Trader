import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from rocket_trader_gdelt_news_observer import (
    GDELTObserver, GDELTTopic,
)


class GDELTObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "gdelt.sqlite3")
        self.topics = (
            GDELTTopic("geopolitics", '(war OR sanctions)'),
            GDELTTopic("energy", '(oil OR pipeline)'),
        )
        self.seen = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.article = {
            "url": "https://news.example.com/story-1",
            "title": "Energy and geopolitical event",
            "seendate": self.seen,
            "domain": "news.example.com",
            "language": "English",
            "sourcecountry": "United States",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def fake_payload(self, _topic):
        return {"articles": [dict(self.article)]}

    def test_poll_deduplicates_articles_and_preserves_topic_and_source_metadata(self):
        sleeps = []
        observer = GDELTObserver(
            self.db, self.topics, fetcher=self.fake_payload,
            sleep_func=lambda seconds: sleeps.append(seconds),
        )
        report = observer.poll_once()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["articles_received"], 2)
        self.assertEqual(report["new_articles"], 1)
        self.assertEqual(sleeps, [6.0])
        self.assertTrue(observer.health()["healthy"])
        with sqlite3.connect(self.db) as db:
            topics = db.execute(
                "SELECT topic FROM gdelt_article_topics ORDER BY topic"
            ).fetchall()
            metadata = db.execute(
                "SELECT domain,language,source_country FROM gdelt_article_metadata"
            ).fetchone()
            article = db.execute(
                "SELECT headline,author,point_in_time_eligible FROM news_articles"
            ).fetchone()
        self.assertEqual(topics, [("energy",), ("geopolitics",)])
        self.assertEqual(metadata, ("news.example.com", "English", "United States"))
        self.assertEqual(article[0], self.article["title"])
        self.assertEqual(article[1], "news.example.com")
        self.assertEqual(article[2], 1)

    def test_invalid_or_missing_article_fields_are_rejected(self):
        payload = {"articles": [
            {"title": "No URL", "seendate": self.seen},
            {"url": "javascript:alert(1)", "title": "Unsafe URL", "seendate": self.seen},
            {"url": "https://example.com/no-date", "title": "No date"},
        ]}
        records = GDELTObserver.parse_articles(payload, self.topics[0])
        self.assertEqual(records, [])

    def test_naive_seen_date_is_rejected(self):
        self.assertIsNone(GDELTObserver.parse_seen_date("20261110T120000"))

    def test_topic_failure_is_visible_without_discarding_successful_topic(self):
        def fetch(topic):
            if topic.key == "energy":
                raise RuntimeError("temporary API failure")
            return {"articles": [dict(self.article)]}
        observer = GDELTObserver(self.db, self.topics, fetcher=fetch,
                                 sleep_func=lambda _seconds: None)
        report = observer.poll_once()
        self.assertFalse(report["healthy"])
        health = observer.health()
        self.assertTrue(health["topics"]["geopolitics"]["healthy"])
        self.assertFalse(health["topics"]["energy"]["healthy"])
        self.assertIn("temporary API failure", health["topics"]["energy"]["last_error"])

    def test_empty_topics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            GDELTObserver(self.db, (), fetcher=self.fake_payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
