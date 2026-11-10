#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Human-reviewed, point-in-time news event assessment store.

Raw headlines never become risk scores. Events and structured assessments are
imported as pending; a named reviewer must approve them before the regime
selector can load them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from rocket_trader_regime_selector import NewsAssessment, NewsSeverity


def parse_aware(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def unit(value: object, field: str) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1.")
    return result


class NewsEventAssessmentStore:
    def __init__(self, database_path: str) -> None:
        if not database_path:
            raise ValueError("A durable event assessment database path is required.")
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS news_events (
                event_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                event_type TEXT NOT NULL, summary TEXT NOT NULL,
                first_observed_at TEXT NOT NULL, affected_symbols_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN', created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS news_event_sources (
                event_id TEXT NOT NULL, source_name TEXT NOT NULL,
                article_id TEXT NOT NULL, url TEXT NOT NULL,
                published_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                source_domain TEXT NOT NULL, independent_source_group TEXT NOT NULL,
                PRIMARY KEY(event_id, source_name, article_id),
                FOREIGN KEY(event_id) REFERENCES news_events(event_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS news_event_assessments (
                assessment_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                assessed_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                severity TEXT NOT NULL, relevance REAL NOT NULL,
                credibility REAL NOT NULL, novelty REAL NOT NULL,
                point_in_time_eligible INTEGER NOT NULL,
                evaluator_version TEXT NOT NULL, rationale TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'PENDING',
                reviewer TEXT, reviewed_at TEXT,
                FOREIGN KEY(event_id) REFERENCES news_events(event_id)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_news_assessment_load
                ON news_event_assessments(review_status, expires_at, event_id)""")

    def import_event(self, data: Dict[str, object]) -> str:
        event_id = str(data.get("event_id") or "").strip()
        title = str(data.get("title") or "").strip()
        event_type = str(data.get("event_type") or "").strip().lower()
        summary = str(data.get("summary") or "").strip()
        sources = data.get("sources")
        raw_symbols = data.get("affected_symbols", [])
        if not isinstance(raw_symbols, list):
            raise ValueError("affected_symbols must be a JSON array.")
        symbols = sorted({str(x).strip().upper() for x in raw_symbols if str(x).strip()})
        if not event_id or not title or not event_type or not isinstance(sources, list) or not sources:
            raise ValueError("event_id, title, event_type and at least one source are required.")
        prepared = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Each source must be an object.")
            source_name = str(source.get("source") or "").strip()
            article_id = str(source.get("article_id") or "").strip()
            url = str(source.get("url") or "").strip()
            parsed_url = urlparse(url)
            published = parse_aware(source.get("published_at"), "source.published_at")
            first_seen = parse_aware(source.get("first_seen_at"), "source.first_seen_at")
            domain = str(source.get("source_domain") or parsed_url.hostname or "").strip().lower()
            independent_group = str(source.get("independent_source_group") or domain).strip().lower()
            if (not source_name or not article_id or parsed_url.scheme not in {"http", "https"}
                    or not parsed_url.hostname or not domain or not independent_group):
                raise ValueError("Each source needs a name, article ID, HTTP(S) URL and source group.")
            if published > first_seen:
                raise ValueError("A source cannot be first-seen before its published timestamp.")
            prepared.append((source_name, article_id, url, published.isoformat(),
                             first_seen.isoformat(), domain, independent_group))
        first_observed = min(row[4] for row in prepared)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.database_path) as db:
            db.execute("""INSERT INTO news_events
                (event_id,title,event_type,summary,first_observed_at,affected_symbols_json,status,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (event_id, title, event_type, summary, first_observed,
                 json.dumps(symbols), "OPEN", now))
            db.executemany("""INSERT INTO news_event_sources
                (event_id,source_name,article_id,url,published_at,first_seen_at,
                 source_domain,independent_source_group)
                VALUES(?,?,?,?,?,?,?,?)""",
                [(event_id, *row) for row in prepared])
        return event_id

    def import_assessment(self, data: Dict[str, object]) -> str:
        event_id = str(data.get("event_id") or "").strip()
        severity = NewsSeverity(str(data.get("severity") or "UNKNOWN").upper())
        relevance = unit(data.get("relevance", 0), "relevance")
        credibility = unit(data.get("credibility", 0), "credibility")
        novelty = unit(data.get("novelty", 0), "novelty")
        evaluator = str(data.get("evaluator_version") or "").strip()
        rationale = str(data.get("rationale") or "").strip()
        point_in_time_value = data.get("point_in_time_eligible", False)
        if not isinstance(point_in_time_value, bool):
            raise ValueError("point_in_time_eligible must be a JSON boolean.")
        point_in_time = point_in_time_value
        assessed = parse_aware(data.get("assessed_at") or datetime.now(timezone.utc).isoformat(),
                               "assessed_at")
        expires = parse_aware(data.get("expires_at") or
                              (assessed + timedelta(hours=6)).isoformat(), "expires_at")
        if not event_id or not rationale:
            raise ValueError("event_id and rationale are required.")
        if severity != NewsSeverity.UNKNOWN and not evaluator:
            raise ValueError("A versioned evaluator is required for scored assessments.")
        if expires <= assessed:
            raise ValueError("expires_at must be after assessed_at.")
        payload = "|".join((event_id, assessed.isoformat(), severity.value,
                            f"{relevance:.6f}", f"{credibility:.6f}", f"{novelty:.6f}",
                            evaluator, rationale))
        assessment_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database_path) as db:
            exists = db.execute("SELECT 1 FROM news_events WHERE event_id=?", (event_id,)).fetchone()
            if not exists:
                raise ValueError(f"Unknown event_id: {event_id}")
            db.execute("""INSERT INTO news_event_assessments
                (assessment_id,event_id,assessed_at,expires_at,severity,relevance,
                 credibility,novelty,point_in_time_eligible,evaluator_version,rationale)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (assessment_id, event_id, assessed.isoformat(), expires.isoformat(),
                 severity.value, relevance, credibility, novelty, int(point_in_time),
                 evaluator, rationale))
        return assessment_id

    def review(self, assessment_id: str, reviewer: str, decision: str,
               reviewed_at: Optional[datetime] = None) -> None:
        reviewer = str(reviewer or "").strip()
        decision = str(decision or "").strip().upper()
        if not reviewer or decision not in {"APPROVE", "REJECT"}:
            raise ValueError("reviewer and decision APPROVE/REJECT are required.")
        current = reviewed_at or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware.")
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("""SELECT a.*,e.first_observed_at FROM news_event_assessments a
                JOIN news_events e ON e.event_id=a.event_id WHERE a.assessment_id=?""",
                (assessment_id,)).fetchone()
            if not row:
                raise ValueError("Unknown assessment_id.")
            if row["review_status"] != "PENDING":
                raise ValueError("Only pending assessments can be reviewed.")
            if decision == "APPROVE":
                sources = db.execute("""SELECT * FROM news_event_sources
                    WHERE event_id=?""", (row["event_id"],)).fetchall()
                if not sources:
                    raise ValueError("Cannot approve an event without source evidence.")
                if row["point_in_time_eligible"]:
                    for source in sources:
                        seen = parse_aware(source["first_seen_at"], "source.first_seen_at")
                        published = parse_aware(source["published_at"], "source.published_at")
                        if seen > current or published > current:
                            raise ValueError("Point-in-time source evidence cannot be from the future.")
                if row["severity"] == NewsSeverity.CRITICAL.value:
                    independent = {source["independent_source_group"] for source in sources}
                    if len(independent) < 2:
                        raise ValueError("CRITICAL requires at least two independent source groups.")
                    if (row["credibility"] < 0.75 or row["relevance"] < 0.75
                            or row["novelty"] < 0.50 or not row["point_in_time_eligible"]):
                        raise ValueError("CRITICAL requires credibility/relevance >=0.75, novelty >=0.50 and point-in-time evidence.")
            db.execute("""UPDATE news_event_assessments
                SET review_status=?,reviewer=?,reviewed_at=?
                WHERE assessment_id=?""",
                ("APPROVED" if decision == "APPROVE" else "REJECT",
                 reviewer, current.astimezone(timezone.utc).isoformat(), assessment_id))

    def load_approved(self, now: Optional[datetime] = None,
                      symbols: Optional[Sequence[str]] = None) -> List[NewsAssessment]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("news assessment load time must be timezone-aware.")
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT a.*,e.first_observed_at,e.affected_symbols_json,
                e.title,e.summary FROM news_event_assessments a
                JOIN news_events e ON e.event_id=a.event_id
                WHERE a.review_status='APPROVED' AND a.point_in_time_eligible=1
                  AND e.status='OPEN' AND a.expires_at>?
                ORDER BY a.assessed_at""",
                (current.astimezone(timezone.utc).isoformat(),)).fetchall()
        wanted = {str(x).upper() for x in symbols} if symbols else None
        output = []
        for row in rows:
            affected = tuple(json.loads(row["affected_symbols_json"]))
            if wanted and affected and not (wanted & {x.upper() for x in affected}):
                continue
            output.append(NewsAssessment(
                event_id=row["event_id"],
                observed_at=row["first_observed_at"],
                severity=NewsSeverity(row["severity"]),
                relevance=float(row["relevance"]),
                credibility=float(row["credibility"]),
                novelty=float(row["novelty"]),
                affected_symbols=affected,
                point_in_time_eligible=True,
                evaluator_version=row["evaluator_version"],
                rationale=(row["title"] + ": " + row["rationale"])[:1000],
            ))
        return output

    def pending(self) -> List[Dict[str, object]]:
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT assessment_id,event_id,severity,assessed_at,
                relevance,credibility,novelty,rationale FROM news_event_assessments
                WHERE review_status='PENDING' ORDER BY assessed_at""").fetchall()
        return [dict(row) for row in rows]


def _read_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Input JSON must be an object.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Human-reviewed news event assessment workflow.")
    parser.add_argument("--db", default="data/rocket_trader_news_events.sqlite3")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--import-event")
    actions.add_argument("--import-assessment")
    actions.add_argument("--review-assessment")
    actions.add_argument("--list-pending", action="store_true")
    parser.add_argument("--reviewer")
    parser.add_argument("--decision", choices=("approve", "reject"))
    args = parser.parse_args()
    store = NewsEventAssessmentStore(args.db)
    try:
        if args.import_event:
            result = {"event_id": store.import_event(_read_json(args.import_event)),
                      "status": "EVENT_IMPORTED"}
        elif args.import_assessment:
            result = {"assessment_id": store.import_assessment(_read_json(args.import_assessment)),
                      "status": "ASSESSMENT_PENDING_REVIEW"}
        elif args.review_assessment:
            store.review(args.review_assessment, args.reviewer, args.decision)
            result = {"assessment_id": args.review_assessment,
                      "status": "REVIEW_RECORDED"}
        else:
            result = {"status": "PENDING", "assessments": store.pending()}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
