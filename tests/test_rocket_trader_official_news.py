import tempfile, unittest
from pathlib import Path
from rocket_trader_official_news import FeedConfig, OfficialNewsStore, parse_feed

class OfficialNewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "official.sqlite3")
        self.feed = FeedConfig("test", "https://news.example.test/feed.xml", "Test Publisher", "MACRO", "news.example.test")
    def tearDown(self):
        self.temp.cleanup()
    def test_parse_rss_preserves_provider_timestamp_and_link(self):
        xml = b"""<?xml version="1.0"?><rss><channel><item><title>Central bank decision</title><guid>abc-1</guid><pubDate>Tue, 10 Nov 2026 15:00:00 GMT</pubDate><description>Policy announcement</description><link>https://news.example.test/story/1</link></item></channel></rss>"""
        rows = parse_feed(xml, self.feed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].created_at, "2026-11-10T15:00:00+00:00")
        self.assertEqual(rows[0].url, "https://news.example.test/story/1")
    def test_atom_supported(self):
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Inflation data</title><id>urn:bls:1</id><updated>2026-11-10T15:00:00Z</updated><link href="https://news.example.test/item/1"/><summary>Summary</summary></entry></feed>"""
        self.assertEqual(len(parse_feed(xml, self.feed)), 1)
    def test_missing_provider_date_is_rejected(self):
        self.assertEqual(parse_feed(b"<rss><channel><item><title>No date</title><guid>x</guid></item></channel></rss>", self.feed), [])
    def test_untrusted_link_is_removed(self):
        xml = b"""<rss><channel><item><title>News</title><guid>x</guid><pubDate>Tue, 10 Nov 2026 15:00:00 GMT</pubDate><link>https://evil.example/steal</link></item></channel></rss>"""
        self.assertIsNone(parse_feed(xml, self.feed)[0].url)
    def test_deduplicates_and_preserves_first_live_observation(self):
        xml = b"""<rss><channel><item><title>News</title><guid>x</guid><pubDate>Tue, 10 Nov 2026 15:00:00 GMT</pubDate><link>https://news.example.test/story</link></item></channel></rss>"""
        store = OfficialNewsStore(self.db)
        records = parse_feed(xml, self.feed)
        self.assertEqual(store.ingest(records)["new_articles"], 1)
        self.assertEqual(store.ingest(records)["new_articles"], 0)
        saved = store.news.get_article("test", records[0].article_id)
        self.assertEqual(saved["point_in_time_eligible"], 1)
        self.assertIsNotNone(saved["live_first_seen_at"])
    def test_feed_health_requires_success(self):
        store = OfficialNewsStore(self.db)
        store.record_health(self.feed, False, error="timeout")
        self.assertFalse(store.health()["healthy"])
        store.record_health(self.feed, True, 3)
        self.assertTrue(store.health()["healthy"])

if __name__ == "__main__":
    unittest.main()

class OfficialNewsAgentTests(unittest.TestCase):
    def _capture(self, key, contact):
        import urllib.request
        from unittest.mock import patch
        import rocket_trader_official_news as m
        seen = {}
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return b"<rss/>"
        def fake_open(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            return Resp()
        feed = m.FeedConfig(key, "https://www.bls.gov/feed/x.rss", "BLS", "LABOR", "www.bls.gov")
        tmp = tempfile.TemporaryDirectory()
        collector_cls = next(getattr(m, n) for n in dir(m) if hasattr(getattr(m, n), "fetch") and hasattr(getattr(m, n), "poll_once"))
        collector = collector_cls(m.OfficialNewsStore(str(Path(tmp.name) / "o.sqlite3")), feeds=(feed,), contact_email=contact)
        with patch.object(urllib.request, "urlopen", fake_open):
            collector.fetch(feed)
        tmp.cleanup()
        return seen["ua"]

    def test_bls_identifies_contact_when_configured(self):
        self.assertIn("contact=ops@example.com", self._capture("bls", "ops@example.com"))

    def test_bls_works_without_contact(self):
        self.assertNotIn("contact=", self._capture("bls", ""))

