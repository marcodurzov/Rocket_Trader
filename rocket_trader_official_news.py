#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official macro/regulatory RSS ingestion for Rocket Trader; observe-only."""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, sys, time, urllib.request, xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from rocket_trader_news import NewsArticleRecord, SQLiteNewsStore, utc_now

POLL_INTERVAL_SECONDS = 300
MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_ITEMS_PER_FEED = 100
USER_AGENT = "RocketTraderNewsMonitor/1.0 (+https://github.com/marcodurzov/Rocket_Trader)"

@dataclass(frozen=True)
class FeedConfig:
    key: str
    url: str
    publisher: str
    category: str
    allowed_host: str

BASE_FEEDS: Tuple[FeedConfig, ...] = (
    FeedConfig("federal_reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", "CENTRAL_BANK", "www.federalreserve.gov"),
    FeedConfig("bls", "https://www.bls.gov/feed/bls_latest.rss", "U.S. Bureau of Labor Statistics", "LABOR_AND_INFLATION", "www.bls.gov"),
    FeedConfig("bea", "https://apps.bea.gov/rss/rss.xml", "U.S. Bureau of Economic Analysis", "MACROECONOMY", "apps.bea.gov"),
)

def configured_feeds(environ: Optional[Dict[str, str]] = None) -> Tuple[FeedConfig, ...]:
    env = environ if environ is not None else os.environ
    feeds = list(BASE_FEEDS)
    contact = env.get("SEC_CONTACT_EMAIL", "").strip()
    if contact:
        feeds.append(FeedConfig("sec_press_releases", "https://www.sec.gov/news/pressreleases.rss", "U.S. Securities and Exchange Commission", "FINANCIAL_REGULATION", "www.sec.gov"))
    return tuple(feeds)

def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()

def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child.tag) in wanted:
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return ""

def _parse_published(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()

def parse_feed(xml_payload: bytes, feed: FeedConfig) -> List[NewsArticleRecord]:
    if len(xml_payload) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds maximum allowed size.")
    root = ET.fromstring(xml_payload)
    records: List[NewsArticleRecord] = []
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "entry"}:
            continue
        headline = _child_text(item, "title")
        link = ""
        for child in item.iter():
            if _local_name(child.tag) == "link":
                link = child.attrib.get("href") or "".join(child.itertext()).strip()
                if link:
                    break
        guid = _child_text(item, "guid", "id") or link
        published = _parse_published(_child_text(item, "pubDate", "published", "updated", "date"))
        if not headline or not guid or not published:
            continue
        if link:
            parsed_link = urlparse(link)
            allowed = {feed.allowed_host, feed.allowed_host.removeprefix("www.")}
            if parsed_link.scheme != "https" or parsed_link.hostname not in allowed:
                link = ""
        summary = _child_text(item, "description", "summary", "content")
        stable = hashlib.sha256(f"{feed.key}|{guid}".encode("utf-8")).hexdigest()
        article = {
            "id": int(stable[:15], 16), "source": feed.key, "author": feed.publisher,
            "created_at": published, "updated_at": published, "headline": headline,
            "summary": summary, "content": "", "url": link or None, "symbols": [],
        }
        records.append(NewsArticleRecord.from_article(article))
        if len(records) >= MAX_ITEMS_PER_FEED:
            break
    return records

class OfficialNewsStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.news = SQLiteNewsStore(database_path)
        with sqlite3.connect(database_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS official_feed_health (
                feed_key TEXT PRIMARY KEY, publisher TEXT NOT NULL, category TEXT NOT NULL,
                last_attempt_at TEXT NOT NULL, last_success_at TEXT,
                last_item_count INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")

    def record_health(self, feed: FeedConfig, success: bool, item_count: int = 0,
                      error: Optional[str] = None) -> None:
        now = utc_now()
        with sqlite3.connect(self.database_path) as db:
            db.execute("""INSERT INTO official_feed_health
                (feed_key,publisher,category,last_attempt_at,last_success_at,last_item_count,last_error)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(feed_key) DO UPDATE SET
                publisher=excluded.publisher, category=excluded.category,
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=CASE WHEN ? THEN excluded.last_success_at ELSE official_feed_health.last_success_at END,
                last_item_count=excluded.last_item_count,last_error=excluded.last_error""",
                (feed.key, feed.publisher, feed.category, now, now if success else None,
                 int(item_count), error, int(success)))

    def health(self, max_age_seconds: int = 1200) -> Dict[str, object]:
        with sqlite3.connect(self.database_path) as db:
            rows = db.execute("SELECT feed_key,last_success_at,last_error,last_item_count FROM official_feed_health").fetchall()
        now = datetime.now(timezone.utc)
        feeds = {}
        for key, success_at, error, count in rows:
            age = None
            healthy = False
            if success_at:
                age = (now - datetime.fromisoformat(success_at)).total_seconds()
                healthy = 0 <= age <= max_age_seconds
            feeds[key] = {"healthy": healthy, "last_success_at": success_at,
                          "age_seconds": age, "last_item_count": count, "last_error": error}
        return {"healthy": bool(feeds) and any(x["healthy"] for x in feeds.values()),
                "feeds": feeds, "orders_enabled": False}

    def ingest(self, records: List[NewsArticleRecord]) -> Dict[str, int]:
        return self.news.ingest(records, observation_mode="LIVE")

class OfficialRSSCollector:
    def __init__(self, store: OfficialNewsStore, feeds: Optional[Tuple[FeedConfig, ...]] = None,
                 timeout_seconds: int = 20, contact_email: Optional[str] = None) -> None:
        self.store = store
        self.feeds = feeds if feeds is not None else configured_feeds()
        self.timeout_seconds = timeout_seconds
        self.contact_email = (contact_email or os.getenv("SEC_CONTACT_EMAIL", "")).strip()

    def fetch(self, feed: FeedConfig) -> bytes:
        parsed = urlparse(feed.url)
        if parsed.scheme != "https" or parsed.hostname != feed.allowed_host:
            raise ValueError("Feed URL is outside the configured HTTPS allowlist.")
        agent = USER_AGENT
        if feed.key == "sec_press_releases":
            if not self.contact_email:
                raise RuntimeError("SEC feed disabled: SEC_CONTACT_EMAIL is required.")
            agent += f" contact={self.contact_email}"
        request = urllib.request.Request(feed.url, headers={
            "User-Agent": agent, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read(MAX_FEED_BYTES + 1)
        if len(payload) > MAX_FEED_BYTES:
            raise ValueError("Feed exceeds maximum allowed size.")
        return payload

    def poll_once(self) -> Dict[str, object]:
        report: Dict[str, object] = {"feeds": {}, "articles_received": 0,
            "new_articles": 0, "new_versions": 0, "orders_enabled": False}
        for feed in self.feeds:
            try:
                records = parse_feed(self.fetch(feed), feed)
                counts = self.store.ingest(records)
                self.store.record_health(feed, True, len(records))
                report["feeds"][feed.key] = {"ok": True, "parsed": len(records), **counts}
                for key in ("articles_received", "new_articles", "new_versions"):
                    report[key] += int(counts.get(key, 0))
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:500]
                self.store.record_health(feed, False, error=message)
                report["feeds"][feed.key] = {"ok": False, "error": message}
        report["healthy"] = any(x.get("ok") for x in report["feeds"].values())
        return report

def main() -> int:
    parser = argparse.ArgumentParser(description="Observe-only official macro news RSS collector.")
    parser.add_argument("--db-path", default=os.getenv("ROCKET_TRADER_OFFICIAL_NEWS_DB", "data/rocket_trader_official_news.sqlite3"))
    parser.add_argument("--poll-forever", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=POLL_INTERVAL_SECONDS)
    args = parser.parse_args()
    store = OfficialNewsStore(args.db_path)
    if args.healthcheck:
        health = store.health()
        print(json.dumps(health, indent=2, sort_keys=True))
        return 0 if health["healthy"] else 1
    if args.interval_seconds < 60:
        parser.error("--interval-seconds must be at least 60")
    collector = OfficialRSSCollector(store)
    while True:
        report = collector.poll_once()
        print(json.dumps(report, sort_keys=True), flush=True)
        if not args.poll_forever:
            return 0 if report["healthy"] else 1
        time.sleep(args.interval_seconds)

if __name__ == "__main__":
    sys.exit(main())
