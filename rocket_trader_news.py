#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — point-in-time news ingestion and immutable revision ledger.

The collector stores provider timestamps separately from the time Rocket Trader
first observed an article. Historical backfills are explicitly NOT point-in-time
eligible because their original first-seen time cannot be reconstructed.
No sentiment score or trading decision is produced by this module.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value(article: Any, key: str, default: Any = None) -> Any:
    if isinstance(article, dict):
        return article.get(key, default)
    return getattr(article, key, default)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True)
class NewsArticleRecord:
    article_id: int
    source: str
    author: str
    created_at: str
    updated_at: str
    headline: str
    summary: str
    content: str
    url: Optional[str]
    symbols: List[str]
    content_hash: str

    @classmethod
    def from_article(cls, article: Any) -> "NewsArticleRecord":
        article_id = _value(article, "id")
        headline = str(_value(article, "headline", "") or "").strip()
        if article_id is None or not headline:
            raise ValueError("Noticia sin id o headline; se rechaza.")
        source = str(_value(article, "source", "unknown") or "unknown").strip().lower()
        author = str(_value(article, "author", "") or "")
        created_at = _iso(_value(article, "created_at"))
        updated_at = _iso(_value(article, "updated_at"))
        if not created_at or not updated_at:
            raise ValueError("Noticia sin created_at/updated_at del proveedor.")
        summary = str(_value(article, "summary", "") or "")
        content = str(_value(article, "content", "") or "")
        url_value = _value(article, "url")
        url = str(url_value) if url_value else None
        symbols = sorted(
            {
                str(symbol).strip().upper()
                for symbol in (_value(article, "symbols", []) or [])
                if str(symbol).strip()
            }
        )
        payload = {
            "source": source,
            "article_id": int(article_id),
            "created_at": created_at,
            "updated_at": updated_at,
            "headline": headline,
            "summary": summary,
            "content": content,
            "url": url,
            "symbols": symbols,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return cls(
            article_id=int(article_id),
            source=source,
            author=author,
            created_at=created_at,
            updated_at=updated_at,
            headline=headline,
            summary=summary,
            content=content,
            url=url,
            symbols=symbols,
            content_hash=digest,
        )


class SQLiteNewsStore:
    """Durable article store preserving first-observed time and content revisions."""

    def __init__(self, database_path: str = "data/rocket_trader_news.sqlite3") -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS news_articles (
                    source TEXT NOT NULL,
                    article_id INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    provider_created_at TEXT NOT NULL,
                    provider_updated_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    live_first_seen_at TEXT,
                    last_seen_at TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT,
                    symbols_json TEXT NOT NULL,
                    latest_content_hash TEXT NOT NULL,
                    point_in_time_eligible INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (source, article_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS news_article_versions (
                    source TEXT NOT NULL,
                    article_id INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observation_mode TEXT NOT NULL,
                    provider_updated_at TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (source, article_id, content_hash)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_created_at ON news_articles(provider_created_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_live_first_seen ON news_articles(live_first_seen_at)"
            )

    def ingest(
        self,
        articles: Iterable[Any],
        observation_mode: str,
        observed_at: Optional[str] = None,
    ) -> Dict[str, int]:
        mode = str(observation_mode).strip().upper()
        if mode not in {"LIVE", "HISTORICAL_BACKFILL"}:
            raise ValueError("observation_mode debe ser LIVE o HISTORICAL_BACKFILL.")
        observed = observed_at or utc_now()
        received = 0
        inserted = 0
        versions_added = 0
        eligible = 0

        with self._connection() as db:
            for raw in articles:
                received += 1
                article = (
                    raw if isinstance(raw, NewsArticleRecord)
                    else NewsArticleRecord.from_article(raw)
                )
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO news_articles (
                        source, article_id, author, provider_created_at,
                        provider_updated_at, first_seen_at, live_first_seen_at,
                        last_seen_at, headline, summary, content, url,
                        symbols_json, latest_content_hash, point_in_time_eligible
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.source,
                        article.article_id,
                        article.author,
                        article.created_at,
                        article.updated_at,
                        observed,
                        observed if mode == "LIVE" else None,
                        observed,
                        article.headline,
                        article.summary,
                        article.content,
                        article.url,
                        json.dumps(article.symbols, ensure_ascii=False),
                        article.content_hash,
                        1 if mode == "LIVE" else 0,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1

                db.execute(
                    """
                    UPDATE news_articles
                    SET author = ?,
                        provider_updated_at = ?,
                        live_first_seen_at = CASE
                            WHEN ? = 'LIVE' THEN COALESCE(live_first_seen_at, ?)
                            ELSE live_first_seen_at
                        END,
                        last_seen_at = ?,
                        headline = ?,
                        summary = ?,
                        content = ?,
                        url = ?,
                        symbols_json = ?,
                        latest_content_hash = ?,
                        point_in_time_eligible = CASE
                            WHEN ? = 'LIVE' THEN 1
                            ELSE point_in_time_eligible
                        END
                    WHERE source = ? AND article_id = ?
                    """,
                    (
                        article.author,
                        article.updated_at,
                        mode,
                        observed,
                        observed,
                        article.headline,
                        article.summary,
                        article.content,
                        article.url,
                        json.dumps(article.symbols, ensure_ascii=False),
                        article.content_hash,
                        mode,
                        article.source,
                        article.article_id,
                    ),
                )

                version_cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO news_article_versions (
                        source, article_id, content_hash, observed_at,
                        observation_mode, provider_updated_at, headline,
                        summary, content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.source,
                        article.article_id,
                        article.content_hash,
                        observed,
                        mode,
                        article.updated_at,
                        article.headline,
                        article.summary,
                        article.content,
                    ),
                )
                if version_cursor.rowcount == 1:
                    versions_added += 1

                if mode == "LIVE":
                    eligible += 1

        return {
            "articles_received": received,
            "new_articles": inserted,
            "new_versions": versions_added,
            "live_observations": eligible,
        }

    def get_article(self, source: str, article_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM news_articles WHERE source = ? AND article_id = ?",
                (source.strip().lower(), int(article_id)),
            ).fetchone()
        return dict(row) if row else None

    def count_versions(self, source: str, article_id: int) -> int:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT COUNT(*) AS n FROM news_article_versions
                WHERE source = ? AND article_id = ?
                """,
                (source.strip().lower(), int(article_id)),
            ).fetchone()
        return int(row["n"])


class AlpacaNewsCollector:
    """Historical news collector; API credentials are read only from environment."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        client: Optional[NewsClient] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if client is None and (not self.api_key or not self.secret_key):
            raise RuntimeError("Faltan ALPACA_API_KEY y/o ALPACA_SECRET_KEY.")
        self.client = client or NewsClient(self.api_key, self.secret_key)

    def fetch(
        self,
        symbols: Sequence[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 50,
        include_content: bool = True,
    ) -> List[Any]:
        if not 1 <= limit <= 50:
            raise ValueError("limit debe estar entre 1 y 50.")
        clean_symbols = sorted(
            {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        )
        if not clean_symbols:
            raise ValueError("Se requiere al menos un símbolo para consultar noticias.")
        request = NewsRequest(
            symbols=",".join(clean_symbols),
            start=start,
            end=end,
            limit=limit,
            include_content=include_content,
        )
        try:
            response = self.client.get_news(request)
            return list(response.data.get("news", []))
        except Exception as exc:
            raise RuntimeError(
                f"Error consultando Alpaca News API: {type(exc).__name__}: {exc}"
            ) from exc

    def collect_and_store(
        self,
        store: SQLiteNewsStore,
        symbols: Sequence[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 50,
        observation_mode: str,
    ) -> Dict[str, int]:
        articles = self.fetch(
            symbols=symbols,
            start=start,
            end=end,
            limit=limit,
            include_content=True,
        )
        result = store.ingest(
            articles,
            observation_mode=observation_mode,
        )
        result["articles_fetched"] = len(articles)
        return result


def self_test() -> Dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteNewsStore(str(Path(directory) / "news.sqlite3"))
        article = {
            "id": 123,
            "source": "Benzinga",
            "author": "Test Author",
            "created_at": "2026-11-09T10:00:00+00:00",
            "updated_at": "2026-11-09T10:00:00+00:00",
            "headline": "Example earnings headline",
            "summary": "Example summary",
            "content": "<p>Example content</p>",
            "url": "https://example.com/story",
            "symbols": ["AAPL"],
        }
        backfill = store.ingest(
            [article],
            observation_mode="HISTORICAL_BACKFILL",
            observed_at="2026-11-09T11:00:00+00:00",
        )
        saved = store.get_article("benzinga", 123)
        assert backfill["new_articles"] == 1
        assert saved is not None
        assert saved["point_in_time_eligible"] == 0
        assert saved["live_first_seen_at"] is None

        updated = dict(article)
        updated["updated_at"] = "2026-11-09T12:00:00+00:00"
        updated["summary"] = "Updated summary"
        live = store.ingest(
            [updated],
            observation_mode="LIVE",
            observed_at="2026-11-09T12:01:00+00:00",
        )
        saved_after = store.get_article("benzinga", 123)
        assert live["new_articles"] == 0
        assert live["new_versions"] == 1
        assert saved_after["first_seen_at"] == "2026-11-09T11:00:00+00:00"
        assert saved_after["live_first_seen_at"] == "2026-11-09T12:01:00+00:00"
        assert saved_after["point_in_time_eligible"] == 1
        assert store.count_versions("benzinga", 123) == 2

        duplicate = store.ingest(
            [updated],
            observation_mode="LIVE",
            observed_at="2026-11-09T12:02:00+00:00",
        )
        assert duplicate["new_versions"] == 0

    return {
        "ok": True,
        "version": "0.1",
        "pipeline": "rocket_trader_news_ingestion",
        "storage": "sqlite",
        "preserves_provider_timestamps": True,
        "preserves_live_first_seen_at": True,
        "historical_backfill_point_in_time_eligible_by_default": False,
        "deduplicates_article_revisions": True,
        "sentiment_scoring_enabled": False,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
