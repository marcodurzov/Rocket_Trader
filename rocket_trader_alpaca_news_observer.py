#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observe-only Alpaca/Benzinga news collector for Rocket Trader."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from rocket_trader_news import AlpacaNewsCollector, SQLiteNewsStore, utc_now

DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "BTCUSD", "ETHUSD", "SOLUSD")
DEFAULT_POLL_SECONDS = 300
MAX_ARTICLES_PER_SYMBOL = 50
LOOKBACK_MINUTES = 60


class AlpacaNewsObserver:
    def __init__(self, database_path: str, symbols: Sequence[str],
                 collector: Optional[AlpacaNewsCollector] = None,
                 lookback_minutes: int = LOOKBACK_MINUTES) -> None:
        if not database_path:
            raise ValueError("A durable Alpaca news database path is required.")
        clean = tuple(sorted({str(s).strip().upper() for s in symbols if str(s).strip()}))
        if not clean:
            raise ValueError("At least one news symbol is required.")
        if lookback_minutes < 15:
            raise ValueError("lookback_minutes must be >= 15.")
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.symbols = clean
        self.lookback_minutes = int(lookback_minutes)
        self.store = SQLiteNewsStore(self.database_path)
        self.collector = collector or AlpacaNewsCollector()
        with sqlite3.connect(self.database_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS alpaca_news_symbol_health (
                symbol TEXT PRIMARY KEY,
                last_attempt_at TEXT NOT NULL,
                last_success_at TEXT,
                last_article_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )""")

    def _record_health(self, symbol: str, success: bool, count: int = 0,
                       error: Optional[str] = None) -> None:
        now = utc_now()
        with sqlite3.connect(self.database_path) as db:
            db.execute("""INSERT INTO alpaca_news_symbol_health
                (symbol,last_attempt_at,last_success_at,last_article_count,last_error)
                VALUES(?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                  last_attempt_at=excluded.last_attempt_at,
                  last_success_at=CASE WHEN ? THEN excluded.last_success_at
                    ELSE alpaca_news_symbol_health.last_success_at END,
                  last_article_count=excluded.last_article_count,
                  last_error=excluded.last_error""",
                (symbol, now, now if success else None, int(count), error, int(success)))

    def health(self, max_age_seconds: int = 1200) -> Dict[str, object]:
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM alpaca_news_symbol_health ORDER BY symbol").fetchall()
        by_symbol = {row["symbol"]: row for row in rows}
        now = datetime.now(timezone.utc)
        results = {}
        for symbol in self.symbols:
            row = by_symbol.get(symbol)
            age = None
            healthy = False
            if row and row["last_success_at"]:
                success_at = datetime.fromisoformat(row["last_success_at"])
                if success_at.tzinfo is not None and success_at.utcoffset() is not None:
                    age = (now - success_at).total_seconds()
                    healthy = 0 <= age <= max_age_seconds
            results[symbol] = {
                "healthy": healthy,
                "last_success_at": row["last_success_at"] if row else None,
                "age_seconds": age,
                "last_article_count": row["last_article_count"] if row else 0,
                "last_error": row["last_error"] if row else "not polled yet",
            }
        return {
            "healthy": bool(results) and all(item["healthy"] for item in results.values()),
            "symbols": results,
            "provider": "Alpaca News API (Benzinga-sourced per provider documentation)",
            "orders_enabled": False,
        }

    def poll_once(self, now: Optional[datetime] = None) -> Dict[str, object]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("poll clock must be timezone-aware.")
        end = current.astimezone(timezone.utc)
        start = end - timedelta(minutes=self.lookback_minutes)
        report: Dict[str, object] = {
            "started_at": end.isoformat(), "symbols": {}, "articles_fetched": 0,
            "new_articles": 0, "new_versions": 0, "orders_enabled": False,
        }
        for symbol in self.symbols:
            try:
                articles = self.collector.fetch(
                    [symbol], start=start, end=end,
                    limit=MAX_ARTICLES_PER_SYMBOL, include_content=True,
                )
                counts = self.store.ingest(articles, observation_mode="LIVE")
                self._record_health(symbol, True, len(articles))
                report["symbols"][symbol] = {"ok": True, "fetched": len(articles), **counts}
                report["articles_fetched"] += len(articles)
                report["new_articles"] += int(counts.get("new_articles", 0))
                report["new_versions"] += int(counts.get("new_versions", 0))
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:500]
                self._record_health(symbol, False, error=message)
                report["symbols"][symbol] = {"ok": False, "error": message}
        report["healthy"] = all(item.get("ok") for item in report["symbols"].values())
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe-only Alpaca/Benzinga news collector.")
    parser.add_argument("--db-path", default=os.getenv(
        "ROCKET_TRADER_ALPACA_NEWS_DB", "/app/data/rocket_trader_alpaca_news.sqlite3"))
    parser.add_argument("--symbols", default=os.getenv(
        "ROCKET_TRADER_ALPACA_NEWS_SYMBOLS", ",".join(DEFAULT_SYMBOLS)))
    parser.add_argument("--poll-forever", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args()
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    try:
        observer = AlpacaNewsObserver(args.db_path, symbols)
        if args.healthcheck:
            result = observer.health()
            print(json.dumps(result, sort_keys=True), flush=True)
            return 0 if result["healthy"] else 1
        if args.interval_seconds < 60:
            parser.error("--interval-seconds must be at least 60")
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
