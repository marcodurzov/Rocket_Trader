import os
import tempfile
import unittest
from datetime import datetime, timezone

from rocket_trader_alpaca_news_observer import AlpacaNewsObserver


class FakeCollector:
    def __init__(self, articles=None, failing=()):
        self.articles = articles or {}
        self.failing = set(failing)
        self.calls = []

    def fetch(self, symbols, start=None, end=None, limit=50, include_content=True):
        symbol = symbols[0]
        self.calls.append((symbol, start, end, limit, include_content))
        if symbol in self.failing:
            raise RuntimeError("provider unavailable")
        return list(self.articles.get(symbol, []))


def article(article_id, symbol):
    return {
        "id": article_id,
        "source": "Benzinga",
        "author": "Fixture",
        "created_at": "2026-11-10T11:00:00+00:00",
        "updated_at": "2026-11-10T11:00:00+00:00",
        "headline": f"Test headline {article_id}",
        "summary": "Fixture summary",
        "content": "",
        "url": "https://example.com/story",
        "symbols": [symbol],
    }


class AlpacaNewsObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "alpaca-news.sqlite3")
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_poll_fetches_per_symbol_and_persists_live_articles(self):
        fake = FakeCollector({
            "SPY": [article(101, "SPY")],
            "BTCUSD": [article(202, "BTCUSD")],
        })
        observer = AlpacaNewsObserver(self.db, ("SPY", "BTCUSD"), collector=fake)
        report = observer.poll_once(now=self.now)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["articles_fetched"], 2)
        self.assertEqual(report["new_articles"], 2)
        self.assertEqual([call[0] for call in fake.calls], ["SPY", "BTCUSD"])
        self.assertTrue(all(call[3] == 50 and call[4] for call in fake.calls))
        self.assertTrue(observer.health()["healthy"])

    def test_repeated_poll_deduplicates_articles_and_preserves_revision_ledger(self):
        fake = FakeCollector({"SPY": [article(101, "SPY")]})
        observer = AlpacaNewsObserver(self.db, ("SPY",), collector=fake)
        first = observer.poll_once(now=self.now)
        second = observer.poll_once(now=self.now)
        self.assertEqual(first["new_articles"], 1)
        self.assertEqual(second["new_articles"], 0)
        self.assertEqual(second["new_versions"], 0)

    def test_one_symbol_failure_keeps_other_symbol_health_visible(self):
        fake = FakeCollector({"SPY": [article(101, "SPY")]}, failing=("BTCUSD",))
        observer = AlpacaNewsObserver(self.db, ("SPY", "BTCUSD"), collector=fake)
        report = observer.poll_once(now=self.now)
        self.assertFalse(report["healthy"])
        health = observer.health()
        self.assertTrue(health["symbols"]["SPY"]["healthy"])
        self.assertFalse(health["symbols"]["BTCUSD"]["healthy"])
        self.assertIn("provider unavailable", health["symbols"]["BTCUSD"]["last_error"])

    def test_naive_poll_clock_is_rejected(self):
        fake = FakeCollector()
        observer = AlpacaNewsObserver(self.db, ("SPY",), collector=fake)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            observer.poll_once(now=datetime(2026, 11, 10, 12, 0))

    def test_empty_symbol_list_is_rejected(self):
        fake = FakeCollector()
        with self.assertRaisesRegex(ValueError, "At least one"):
            AlpacaNewsObserver(self.db, (), collector=fake)


if __name__ == "__main__":
    unittest.main(verbosity=2)
