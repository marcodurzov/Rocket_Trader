#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rocket_trader_news import (
    AlpacaNewsCollector,
    SQLiteNewsStore,
    self_test,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alpaca-api",
        action="store_true",
        help="Perform a read-only News API smoke test using GitHub Actions secrets.",
    )
    args = parser.parse_args()

    result = self_test()
    assert result["ok"] is True
    assert result["historical_backfill_point_in_time_eligible_by_default"] is False
    assert result["sentiment_scoring_enabled"] is False
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0

    if args.alpaca_api:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        collector = AlpacaNewsCollector()
        articles = collector.fetch(
            symbols=["SPY", "QQQ", "AAPL", "BTCUSD"],
            start=start,
            end=end,
            limit=20,
            include_content=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteNewsStore(str(Path(directory) / "news.sqlite3"))
            stored = store.ingest(articles, observation_mode="LIVE")
        result["alpaca_news_api"] = {
            "connection": "SUCCESS",
            "articles_fetched": len(articles),
            "new_articles_stored": stored["new_articles"],
            "new_revisions_stored": stored["new_versions"],
            "orders_enabled": False,
            "orders_submitted": 0,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
