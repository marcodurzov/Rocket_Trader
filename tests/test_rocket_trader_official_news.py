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
