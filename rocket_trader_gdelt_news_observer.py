#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observe-only global/geopolitical news collector using GDELT DOC 2.0."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from rocket_trader_news import NewsArticleRecord, SQLiteNewsStore, utc_now

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "RocketTraderGDELTObserver/1.0 (+https://github.com/marcodurzov/Rocket_Trader)"
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_RECORDS = 75
POLL_SECONDS = 900
REQUEST_GAP_SECONDS = 6
HEALTH_MAX_AGE_SECONDS = 1800


@dataclass(frozen=True)
class GDELTTopic:
    key: str
    query: str


DEFAULT_TOPICS = (
    GDELTTopic("geopolitical_conflict",
               '("military conflict" OR sanctions OR tariff OR blockade OR coup OR invasion)'),
    GDELTTopic("energy_security",
               '("oil supply" OR OPEC OR "natural gas" OR pipeline OR tanker)'),
    GDELTTopic("strategic_shipping",
               '("strait of hormuz" OR "taiwan strait" OR "red sea" OR shipping OR port)'),
    GDELTTopic("macro_policy",
               '("central bank" OR "interest rates" OR inflation OR recession OR "federal reserve")'),
    GDELTTopic("natural_disasters",
               '(earthquake OR flood OR wildfire OR hurricane OR drought)'),
)


class GDELTObserver:
    def __init__(self, database_path: str, topics: Sequence[GDELTTopic] = DEFAULT_TOPICS,
                 fetcher: Optional[Callable[[GDELTTopic], Dict[str, object]]] = None,
                 sleep_func: Callable[[float], None] = time.sleep) -> None:
        if not database_path:
            raise ValueError("A durable GDELT database path is required.")
        if not topics:
            raise ValueError("At least one GDELT topic is required.")
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.topics = tuple(topics)
        self.store = SQLiteNewsStore(self.database_path)
        self.fetcher = fetcher or self.fetch_topic
        self.sleep_func = sleep_func
        with sqlite3.connect(self.database_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS gdelt_topic_health (
                topic TEXT PRIMARY KEY, last_attempt_at TEXT NOT NULL,
                last_success_at TEXT, last_article_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS gdelt_article_topics (
                article_id INTEGER NOT NULL, topic TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                PRIMARY KEY(article_id, topic)
            )""")

    @staticmethod
    def parse_seen_date(value: str) -> Optional[str]:
        raw = str(value or "").strip()
        if not raw:
            return None
        for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
            try:
                parsed = datetime.strptime(raw, pattern).replace(tzinfo=timezone.utc)
                return parsed.isoformat()
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None

    @classmethod
    def parse_articles(cls, payload: Dict[str, object], topic: GDELTTopic
                       ) -> List[NewsArticleRecord]:
        articles = payload.get("articles")
        if not isinstance(articles, list):
            raise ValueError("GDELT response does not contain an articles array.")
        records = []
        for item in articles[:MAX_RECORDS]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            published = cls.parse_seen_date(str(item.get("seendate") or ""))
            parsed_url = urlparse(url)
            if (not title or not published or parsed_url.scheme not in {"http", "https"}
                    or not parsed_url.hostname):
                continue
            stable = hashlib.sha256(url.encode("utf-8")).hexdigest()
            article = {
                "id": int(stable[:15], 16),
                "source": "gdelt_doc",
                "author": str(item.get("domain") or parsed_url.hostname).strip().lower(),
                "created_at": published,
                "updated_at": published,
                "headline": title,
                "summary": "",
                "content": "",
                "url": url,
                "symbols": [],
            }
            records.append(NewsArticleRecord.from_article(article))
        return records

    def fetch_topic(self, topic: GDELTTopic) -> Dict[str, object]:
        params = {
            "query": topic.query,
            "mode": "artlist",
            "maxrecords": str(MAX_RECORDS),
            "timespan": "1h",
            "sort": "datedesc",
            "format": "json",
        }
        url = API_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("GDELT response exceeds maximum allowed size.")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("GDELT response must be a JSON object.")
        return decoded

    def _record_health(self, topic: str, success: bool, count: int = 0,
                       error: Optional[str] = None) -> None:
        now = utc_now()
        with sqlite3.connect(self.database_path) as db:
            db.execute("""INSERT INTO gdelt_topic_health
                (topic,last_attempt_at,last_success_at,last_article_count,last_error)
                VALUES(?,?,?,?,?)
                ON CONFLICT(topic) DO UPDATE SET
                  last_attempt_at=excluded.last_attempt_at,
                  last_success_at=CASE WHEN ? THEN excluded.last_success_at
                    ELSE gdelt_topic_health.last_success_at END,
                  last_article_count=excluded.last_article_count,
                  last_error=excluded.last_error""",
                (topic, now, now if success else None, int(count), error, int(success)))

    def _store_topic_associations(self, records: Sequence[NewsArticleRecord],
                                  topic: str) -> None:
        now = utc_now()
        with sqlite3.connect(self.database_path) as db:
            db.executemany("""INSERT OR IGNORE INTO gdelt_article_topics
                (article_id,topic,first_seen_at) VALUES(?,?,?)""",
                [(record.article_id, topic, now) for record in records])

    def poll_once(self) -> Dict[str, object]:
        report: Dict[str, object] = {
            "started_at": utc_now(), "topics": {}, "articles_received": 0,
            "new_articles": 0, "new_versions": 0, "orders_enabled": False,
        }
        for index, topic in enumerate(self.topics):
            try:
                payload = self.fetcher(topic)
                records = self.parse_articles(payload, topic)
                counts = self.store.ingest(records, observation_mode="LIVE")
                self._store_topic_associations(records, topic.key)
                self._record_health(topic.key, True, len(records))
                report["topics"][topic.key] = {"ok": True, "parsed": len(records), **counts}
                report["articles_received"] += len(records)
                report["new_articles"] += int(counts.get("new_articles", 0))
                report["new_versions"] += int(counts.get("new_versions", 0))
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:500]
                self._record_health(topic.key, False, error=message)
                report["topics"][topic.key] = {"ok": False, "error": message}
            if index < len(self.topics) - 1:
                self.sleep_func(REQUEST_GAP_SECONDS)
        report["healthy"] = all(item.get("ok") for item in report["topics"].values())
        return report

    def health(self, max_age_seconds: int = HEALTH_MAX_AGE_SECONDS) -> Dict[str, object]:
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM gdelt_topic_health ORDER BY topic").fetchall()
        by_topic = {row["topic"]: row for row in rows}
        now = datetime.now(timezone.utc)
        topics = {}
        for topic in self.topics:
            row = by_topic.get(topic.key)
            age = None
            healthy = False
            if row and row["last_success_at"]:
                success = datetime.fromisoformat(row["last_success_at"])
                age = (now - success).total_seconds()
                healthy = 0 <= age <= max_age_seconds
            topics[topic.key] = {
                "healthy": healthy, "age_seconds": age,
                "last_success_at": row["last_success_at"] if row else None,
                "last_article_count": row["last_article_count"] if row else 0,
                "last_error": row["last_error"] if row else "not polled yet",
            }
        return {
            "healthy": bool(topics) and all(item["healthy"] for item in topics.values()),
            "topics": topics, "provider": "GDELT DOC 2.0",
            "attribution_required": "GDELT Project — https://www.gdeltproject.org/",
            "orders_enabled": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe-only GDELT geopolitical news collector.")
    parser.add_argument("--db-path", default=os.getenv(
        "ROCKET_TRADER_GDELT_NEWS_DB", "/app/data/rocket_trader_gdelt_news.sqlite3"))
    parser.add_argument("--poll-forever", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=POLL_SECONDS)
    args = parser.parse_args()
    try:
        observer = GDELTObserver(args.db_path)
        if args.healthcheck:
            result = observer.health()
            print(json.dumps(result, sort_keys=True), flush=True)
            return 0 if result["healthy"] else 1
        if args.interval_seconds < 300:
            parser.error("--interval-seconds must be at least 300")
        while True:
            report = observer.poll_once()
            print(json.dumps(report, sort_keys=True), flush=True)
            if not args.poll_forever:
                return 0 if report["healthy"] else 1
            time.sleep(args.interval_seconds)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "error": str(exc), "orders_enabled": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
