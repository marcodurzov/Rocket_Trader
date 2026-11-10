# Official macro and regulatory news ingestion

Rocket Trader has an observe-only path for official macro/regulatory publications. It polls a fixed HTTPS allowlist and stores articles in SQLite using the immutable news revision ledger. It does not generate sentiment, direction, severity, asset mapping or trade decisions.

Initial publishers:
- Federal Reserve Board all press releases: https://www.federalreserve.gov/feeds/press_all.xml
- U.S. Bureau of Labor Statistics latest numbers: https://www.bls.gov/feed/bls_latest.rss
- U.S. Bureau of Economic Analysis news releases: https://apps.bea.gov/rss/rss.xml
- SEC press releases are enabled only when SEC_CONTACT_EMAIL is set, to provide an identifying contact in the User-Agent.

Publisher category is source metadata, not a model assessment. Items without a provider publication timestamp are rejected. Non-allowlisted article links are stripped. Feed failures are recorded independently.

The Paper observer Compose stack adds a separate rocket-trader-official-news service. It shares the persistent Docker volume but uses a separate SQLite database. It has no Alpaca credentials and no order capability. Default polling is five minutes; minimum is one minute. Set SEC_CONTACT_EMAIL to enable SEC.

Health is true when at least one configured publisher has responded successfully within 20 minutes. This is ingestion health, not proof that all sources are current.

Next stages: add more official publishers and licensed news wires; build event extraction with provenance, confidence, novelty, affected assets, causal channel, horizon and conflicting-source tracking; validate impact with point-in-time event studies; only then allow validated event risk overlays to influence Paper allocation.

No sentiment model, selector or order path is connected by this collector.
