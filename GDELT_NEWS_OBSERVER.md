# GDELT global and geopolitical news observer

## Scope

The GDELT DOC 2.0 observer searches global online news coverage for five predeclared themes:
- Geopolitical conflict, sanctions, tariffs and blockades
- Energy security and oil/gas supply
- Strategic shipping routes and ports
- Central-bank and macro-policy coverage
- Natural disasters

GDELT documents its DOC API as a full-text news search that supports JSON article lists and multilingual coverage. The API can search translated coverage across 65 languages. This makes it a useful discovery layer for international events, not a primary-source verification system.

## Ingestion design

- Fixed HTTPS endpoint: `https://api.gdeltproject.org/api/v2/doc/doc`.
- Five fixed topic queries; no arbitrary user-supplied URLs or hosts.
- Article-list JSON, one-hour search window, at most 75 records per topic/poll.
- Six-second gap between topic requests to keep the query cadence conservative.
- Poll interval defaults to 15 minutes; minimum 5 minutes.
- Store article title, publisher domain, source timestamp and original URL in the existing point-in-time SQLite news ledger.
- Preserve topic associations plus GDELT language and source-country metadata in separate tables.
- Reject missing/invalid titles, non-HTTP(S) URLs and timestamps without explicit UTC information.
- Deduplicate by stable URL-derived article ID and preserve revisions/first live observation.

## Attribution and limitations

GDELT Project datasets are available for commercial use without fee under its published terms, but use/redistribution must cite the GDELT Project and link to `https://www.gdeltproject.org/`. Publisher article text remains subject to the publisher's own copyright and terms. Rocket Trader stores article metadata and links only; it does not copy full article text.

GDELT coverage is not complete global coverage. Its translation, entity/topic matching and source-country metadata can contain errors or representation bias. Repeated coverage of the same event is not independent confirmation. Article counts and tone are not severity, credibility or market impact scores.

This observer generates no sentiment, affected-symbol mapping, severity, direction or trade decision. It is not connected to the regime selector. Every event must be clustered, checked against primary/independent sources, assessed with provenance and confidence, and tested through point-in-time event studies before any risk overlay can use it.

## Social media

No social platform is scraped by this service. Reddit's current policy requires explicit API approval and separate permission/contract for commercial use. X's current developer pricing charges for returned post reads. Social data should be added only after the use case, access approval, retention, cost and redistribution rights are confirmed. Do not bypass platform controls through unofficial scraping.

## Operations

Compose service: `rocket-trader-gdelt-news`.
Database: `/app/data/rocket_trader_gdelt_news.sqlite3`.
No broker credentials are passed to the service. It has no order capability.
Health is tracked per topic and requires a successful poll within the 30-minute health window.
