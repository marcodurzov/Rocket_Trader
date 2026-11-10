# Alpaca/Benzinga news observer

## Scope

The `rocket-trader-alpaca-news` service polls the Alpaca News API for the configured equity ETF and crypto symbols. The provider documentation describes its historical news data as Benzinga-sourced. Articles are stored through the existing point-in-time SQLite revision ledger, with provider timestamps, first live observation, content revisions and related symbols retained.

Default symbols: `SPY,QQQ,IWM,BTCUSD,ETHUSD,SOLUSD`.

Each symbol is queried independently with a 60-minute overlap and a maximum of 50 articles per symbol per poll. The overlap supports recovery after short outages and deduplication prevents repeated rows from creating duplicate article versions.

## Safety

- The service receives Alpaca API credentials only to read market news.
- It imports no TradingClient, order adapter or order-submission method.
- It produces no sentiment, event severity, direction, affected-asset inference beyond provider tags, or trade signal.
- The news observer is not connected to the portfolio selector. Its output is evidence for a later event-assessment pipeline only.
- Historical lookback results first observed during a live poll receive a live first-seen timestamp; this is not the same as claiming the article was first published at that time.

## Coverage limits

- A maximum of 50 results per symbol per poll is requested. This version does not implement pagination, so it is not a complete news archive for unusually active symbols.
- Alpaca's available real-time news timing depends on the user's market-data/news entitlement. Provider documentation describes delayed defaults for users without real-time access. Record the actual received/first-seen timestamps and never assume zero latency.
- This source covers symbol-linked financial news, not the full geopolitical or social-media universe.
- Social sources are deliberately not scraped without permission and compliant access. Reddit's current policy requires explicit API approval, and commercial use requires Reddit's permission/contract. Do not use unofficial scraping to bypass these requirements.

## Configuration

The Compose service reads `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` from the host `.env` file and stores data in `/app/data/rocket_trader_alpaca_news.sqlite3`.

Override the watchlist with `ROCKET_TRADER_ALPACA_NEWS_SYMBOLS`. Polling defaults to five minutes; the 60-minute query overlap is intentionally wider than the polling interval.

Health is tracked per symbol. The service reports healthy only when every configured symbol has had a successful poll within the 20-minute health window. Health means ingestion is working, not that every article has been captured.

## Next stage

Build a versioned event assessment pipeline with source provenance, event identity/clustering, credibility, novelty, relevance, severity, affected assets, causal channel, expected horizon, conflicting evidence and reviewer traceability. Validate every feature with point-in-time event studies before the news layer can reduce Paper exposure. News must never increase exposure or independently trigger an order.
