# Human-reviewed news event assessment

## Principle

Raw RSS/API articles never become trading risk scores. The event workflow requires a curator to consolidate evidence, create a structured assessment, and have a named reviewer explicitly approve it. Only approved, point-in-time-eligible, unexpired assessments are passed into the Paper regime selector.

No LLM or keyword classifier is currently authorized to set severity, credibility, novelty or affected symbols automatically.

## Event import

Create an event JSON document:

```json
{
  "event_id": "evt-20261110-001",
  "title": "Verified market-moving event",
  "event_type": "geopolitical",
  "summary": "Short factual summary, separated from interpretation.",
  "affected_symbols": ["SPY", "QQQ", "IWM"],
  "sources": [
    {
      "source": "alpaca_benzinga",
      "article_id": "provider-article-id-1",
      "url": "https://publisher.example/story-1",
      "published_at": "2026-11-10T10:00:00Z",
      "first_seen_at": "2026-11-10T10:01:00Z",
      "source_domain": "publisher.example",
      "independent_source_group": "publisher-owner-a"
    }
  ]
}
```

Use the ingestion ledger's actual `first_seen_at`, not the time an article claims to have been published. The event's first observation is derived from the earliest source first-seen time. Do not label syndicated copies as independent sources; group by the actual publisher/ownership or original wire.

Import:

```bash
python rocket_trader_news_event_assessment.py --db /app/data/rocket_trader_news_events.sqlite3 --import-event event.json
```

## Assessment import

```json
{
  "event_id": "evt-20261110-001",
  "severity": "HIGH",
  "relevance": 0.90,
  "credibility": 0.85,
  "novelty": 0.80,
  "point_in_time_eligible": true,
  "evaluator_version": "human-reviewed-v1",
  "rationale": "Explain source quality, event impact channel, affected assets and uncertainty.",
  "assessed_at": "2026-11-10T10:05:00Z",
  "expires_at": "2026-11-10T16:05:00Z"
}
```

Importing an assessment always creates `PENDING` status. It does not affect the selector.

```bash
python rocket_trader_news_event_assessment.py --db /app/data/rocket_trader_news_events.sqlite3 --import-assessment assessment.json
python rocket_trader_news_event_assessment.py --db /app/data/rocket_trader_news_events.sqlite3 --list-pending
```

## Human approval

```bash
python rocket_trader_news_event_assessment.py \
  --db /app/data/rocket_trader_news_events.sqlite3 \
  --review-assessment ASSESSMENT_ID \
  --reviewer "reviewer-id" \
  --decision approve
```

The reviewer must be a real accountable operator; do not use a generic or fabricated identity.

Additional critical-event gate:
- At least two independent source groups.
- Credibility >= 0.75.
- Relevance >= 0.75.
- Novelty >= 0.50.
- Point-in-time eligibility must be true.

A critical event that does not pass these conditions cannot be approved as a critical blocker. It may be re-assessed at a lower severity with an explicit rationale. This gate does not prove the event is true; it reduces single-source false positives.

## Selector behavior

The Paper regime observer loads only assessments that are:
- Human-approved.
- Point-in-time eligible.
- Not expired.
- Attached to an open event.
- Relevant to the current universe, unless `affected_symbols` is empty.

An empty `affected_symbols` list means the event is global and applies to all universes. Use it only when the causal channel genuinely affects the broad portfolio. A symbol-specific event should list the symbols it can affect.

The existing news overlay can only reduce exposure or block new entries; it can never increase exposure. The selector still has an empty strategy candidate set, so portfolio exposure remains 0% and cash remains 100%.

## Audit and limits

Every event retains source URLs, provider article IDs, publication times, first-seen times, source groups, assessment values, evaluator version, reviewer and review time. Rejected and pending assessments do not affect the selector.

The store does not automatically cluster stories, verify truth, infer causal channels, or estimate market impact. Those are human research tasks until a separately validated event model exists. A score is an auditable judgement, not an objective probability.
