#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trade-condition audit of 2020 Alpaca/Yahoo ETF daily-close discrepancies.

Historical market-data audit only. Uses Alpaca SIP daily bars and trades plus
Yahoo's unadjusted-for-dividends Close field. It never imports TradingClient and
cannot submit, cancel, replace, or modify orders.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import requests
import yfinance as yf
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

NY = ZoneInfo("America/New_York")
DEFAULT_SYMBOLS = ("DIA", "EEM", "EFA", "GLD", "IWM", "QQQ", "SPY", "TLT")
DEFAULT_SESSIONS = (
    "2020-03-12",
    "2020-03-13",
    "2020-03-16",
    "2020-03-17",
    "2020-03-18",
    "2020-03-19",
)
TRADE_QUERY_START = time(15, 59, 50)
TRADE_QUERY_END = time(16, 0, 5)
MAX_TRADE_PAGES = 5
PAGE_LIMIT = 10000
PRICE_TOLERANCE_USD = 0.005
# These SIP conditions do not update the daily close according to Alpaca's
# published aggregation table. G/P/Z/4 are excluded here because their daily
# close update is conditional on being the first trade of the day.
DAILY_CLOSE_EXCLUDED_CONDITIONS = frozenset({
    "B", "C", "G", "H", "I", "M", "N", "P", "Q", "R",
    "T", "U", "V", "W", "Z", "4", "7",
})
OFFICIAL_CLOSE_CONDITIONS = frozenset({"M", "6", "9"})


class CloseAuditError(RuntimeError):
    """Raised when a required historical source cannot be verified."""


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CloseAuditError("Trade timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def daily_close_eligible(conditions: Iterable[str]) -> bool:
    """Whether a trade may update the Alpaca daily close under the published table."""
    return not (set(str(code).strip() for code in (conditions or ())) & DAILY_CLOSE_EXCLUDED_CONDITIONS)


def classify_close_discrepancy(
    *,
    symbol: str,
    session: str,
    alpaca_daily_close: Optional[float],
    yahoo_close: Optional[float],
    trades: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare daily close with pre/post-close SIP trades and auction candidates."""
    raw_count = 0
    deduplicated: Dict[Any, Dict[str, Any]] = {}
    for raw in trades:
        raw_count += 1
        item = {
            "timestamp": _timestamp(raw["timestamp"]),
            "price": float(raw["price"]),
            "size": float(raw.get("size") or 0),
            "exchange": raw.get("exchange"),
            "conditions": [str(x).strip() for x in (raw.get("conditions") or [])],
            "trade_id": raw.get("trade_id"),
            "tape": raw.get("tape"),
        }
        # SIP may expose the same trade ID more than once with identical
        # economic fields and slightly different timestamps. Collapse only
        # exact duplicate representations; preserve corrected/changed records.
        key = (
            item["trade_id"],
            item["price"],
            item["size"],
            item["exchange"],
            tuple(item["conditions"]),
            item["tape"],
        ) if item["trade_id"] is not None else (
            item["timestamp"], item["price"], item["size"], item["exchange"],
            tuple(item["conditions"]), item["tape"],
        )
        existing = deduplicated.get(key)
        if existing is None or item["timestamp"] > existing["timestamp"]:
            deduplicated[key] = item

    normalized = sorted(deduplicated.values(), key=lambda item: item["timestamp"])
    eligible = [item for item in normalized if daily_close_eligible(item["conditions"])]
    pre_close = [
        item for item in eligible
        if item["timestamp"].astimezone(NY).time() < time(16, 0, 0)
    ]
    post_close = [
        item for item in eligible
        if item["timestamp"].astimezone(NY).time() >= time(16, 0, 0)
    ]
    official = [
        item for item in normalized
        if (
            set(item["conditions"]) & OFFICIAL_CLOSE_CONDITIONS
            and item["timestamp"].astimezone(NY).time() >= time(16, 0, 0)
        )
    ]
    last_pre_close = pre_close[-1] if pre_close else None
    last_post_close = post_close[-1] if post_close else None
    yahoo_matches = [
        item for item in official
        if yahoo_close is not None and abs(item["price"] - float(yahoo_close)) <= PRICE_TOLERANCE_USD
    ]
    daily_matches_pre = (
        last_pre_close is not None
        and alpaca_daily_close is not None
        and abs(last_pre_close["price"] - float(alpaca_daily_close)) <= PRICE_TOLERANCE_USD
    )
    daily_matches_post = (
        last_post_close is not None
        and alpaca_daily_close is not None
        and abs(last_post_close["price"] - float(alpaca_daily_close)) <= PRICE_TOLERANCE_USD
    )
    closes_agree = (
        alpaca_daily_close is not None
        and yahoo_close is not None
        and abs(float(alpaca_daily_close) - float(yahoo_close)) <= PRICE_TOLERANCE_USD
    )

    if closes_agree:
        status = "CLOSES_AGREE"
    elif not normalized:
        status = "NO_TRADES_RETURNED"
    elif daily_matches_pre and yahoo_matches:
        status = "PRE_CLOSE_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED"
    elif daily_matches_pre:
        status = "ALPACA_DAILY_CLOSE_MATCHES_PRE_CLOSE_TRADE_ONLY"
    elif daily_matches_post:
        status = "ALPACA_DAILY_CLOSE_MATCHES_POST_CLOSE_TRADE"
    else:
        status = "ALPACA_DAILY_CLOSE_NOT_REPRODUCED_FROM_WINDOW_TRADES"

    def public_trade(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if item is None:
            return None
        return {
            "timestamp_utc": item["timestamp"].isoformat(),
            "timestamp_new_york": item["timestamp"].astimezone(NY).isoformat(),
            "price": item["price"],
            "size": item["size"],
            "exchange": item["exchange"],
            "conditions": item["conditions"],
            "trade_id": item["trade_id"],
            "tape": item["tape"],
            "daily_close_eligible": daily_close_eligible(item["conditions"]),
        }

    return {
        "symbol": symbol,
        "session": session,
        "alpaca_daily_raw_close": alpaca_daily_close,
        "yahoo_raw_close": yahoo_close,
        "alpaca_yahoo_close_difference_usd": (
            round(float(alpaca_daily_close) - float(yahoo_close), 8)
            if alpaca_daily_close is not None and yahoo_close is not None else None
        ),
        "last_eligible_trade_before_1600": public_trade(last_pre_close),
        "last_eligible_trade_after_1600": public_trade(last_post_close),
        "alpaca_daily_close_matches_pre_close_trade": bool(daily_matches_pre),
        "alpaca_daily_close_matches_post_close_trade": bool(daily_matches_post),
        "official_close_condition_trades": [public_trade(item) for item in official[-20:]],
        "official_close_trades_matching_yahoo": [public_trade(item) for item in yahoo_matches],
        "trade_record_count_in_window": raw_count,
        "unique_trade_count_in_window": len(normalized),
        "duplicate_trade_records_collapsed": raw_count - len(normalized),
        "status": status,
        "status_is_diagnostic_only_not_a_data_quality_or_profitability_pass": True,
    }


def _fetch_trades(
    session: requests.Session,
    *,
    symbol: str,
    session_date: str,
) -> Dict[str, Any]:
    start_dt = datetime.combine(date.fromisoformat(session_date), TRADE_QUERY_START, tzinfo=NY)
    end_dt = datetime.combine(date.fromisoformat(session_date), TRADE_QUERY_END, tzinfo=NY)
    params: Dict[str, Any] = {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "feed": "sip",
        "sort": "desc",
        "limit": PAGE_LIMIT,
    }
    all_trades: List[Dict[str, Any]] = []
    pages = 0
    next_page_token = None
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/trades"
    while True:
        if next_page_token:
            params["page_token"] = next_page_token
        response = session.get(url, params=params, timeout=30)
        if response.status_code != 200:
            raise CloseAuditError(
                f"Alpaca historical trades failed for {symbol} {session_date}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
        payload = response.json()
        all_trades.extend(payload.get("trades") or [])
        pages += 1
        next_page_token = payload.get("next_page_token")
        if not next_page_token:
            break
        if pages >= MAX_TRADE_PAGES:
            break

    return {
        "trades": [
            {
                "timestamp": item["t"],
                "price": item["p"],
                "size": item.get("s", 0),
                "exchange": item.get("x"),
                "conditions": item.get("c") or [],
                "trade_id": item.get("i"),
                "tape": item.get("z"),
            }
            for item in all_trades
        ],
        "pages": pages,
        "complete": next_page_token is None,
        "remaining_page_token": next_page_token,
    }


def _fetch_alpaca_daily_closes(
    client: StockHistoricalDataClient,
    symbols: Iterable[str],
) -> Dict[str, Dict[str, float]]:
    request = StockBarsRequest(
        symbol_or_symbols=list(symbols),
        timeframe=TimeFrame.Day,
        start=datetime(2020, 3, 11, tzinfo=timezone.utc),
        end=datetime(2020, 3, 20, tzinfo=timezone.utc),
        adjustment=Adjustment.RAW,
        feed=DataFeed.SIP,
        limit=10000,
    )
    bars = client.get_stock_bars(request)
    output: Dict[str, Dict[str, float]] = {}
    for symbol in symbols:
        output[symbol] = {}
        for bar in bars[symbol]:
            local_session = bar.timestamp.astimezone(NY).date().isoformat()
            output[symbol][local_session] = float(bar.close)
    return output


def _fetch_yahoo_raw_closes(symbols: Iterable[str]) -> Dict[str, Dict[str, float]]:
    output: Dict[str, Dict[str, float]] = {}
    for symbol in symbols:
        history = yf.Ticker(symbol).history(
            start="2020-03-11",
            end="2020-03-20",
            auto_adjust=False,
            actions=False,
            repair=False,
        )
        if history.empty or "Close" not in history.columns:
            raise CloseAuditError(f"Yahoo returned no raw Close history for {symbol}")
        frame = history.copy()
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize(NY)
        else:
            frame.index = frame.index.tz_convert(NY)
        output[symbol] = {
            index.date().isoformat(): float(row["Close"])
            for index, row in frame.iterrows()
            if row.get("Close") is not None
        }
    return output


def run_audit(
    *,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    sessions: Iterable[str] = DEFAULT_SESSIONS,
) -> Dict[str, Any]:
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        raise CloseAuditError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")

    symbols = tuple(str(item).upper() for item in symbols)
    sessions = tuple(str(item) for item in sessions)
    client = StockHistoricalDataClient(api_key, secret_key)
    alpaca_daily = _fetch_alpaca_daily_closes(client, symbols)
    yahoo_daily = _fetch_yahoo_raw_closes(symbols)

    http = requests.Session()
    http.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    })

    results = []
    errors = []
    for symbol in symbols:
        for session_date in sessions:
            try:
                trade_payload = _fetch_trades(
                    http,
                    symbol=symbol,
                    session_date=session_date,
                )
                row = classify_close_discrepancy(
                    symbol=symbol,
                    session=session_date,
                    alpaca_daily_close=alpaca_daily.get(symbol, {}).get(session_date),
                    yahoo_close=yahoo_daily.get(symbol, {}).get(session_date),
                    trades=trade_payload["trades"],
                )
                row["trade_pages"] = trade_payload["pages"]
                row["trade_query_complete"] = trade_payload["complete"]
                if not trade_payload["complete"]:
                    row["status"] = "TRADE_QUERY_INCOMPLETE"
                results.append(row)
            except Exception as exc:
                errors.append({
                    "symbol": symbol,
                    "session": session_date,
                    "error": str(exc),
                })

    statuses: Dict[str, int] = {}
    for row in results:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    return {
        "ok": (
            not errors
            and len(results) == len(symbols) * len(sessions)
            and all(row.get("trade_query_complete") is True for row in results)
        ),
        "pipeline": "rocket_trader_sip_daily_close_trade_condition_audit_v0_1",
        "mode": "HISTORICAL_TRADE_CONDITION_DIAGNOSTIC_ONLY",
        "symbols": list(symbols),
        "sessions": list(sessions),
        "trade_window_new_york": {
            "start": TRADE_QUERY_START.isoformat(),
            "end": TRADE_QUERY_END.isoformat(),
        },
        "data_sources": {
            "alpaca_daily": "SIP historical daily bars, Adjustment.RAW",
            "alpaca_trades": "SIP historical trades with condition codes",
            "yahoo": "Yahoo Close, auto_adjust=False, actions=False, repair=False",
        },
        "close_condition_reference": "https://docs.alpaca.markets/us/docs/market-data-faq",
        "no_source_designated_truth": True,
        "orders_enabled": False,
        "orders_submitted": 0,
        "results": results,
        "errors": errors,
        "status_counts": statuses,
        "all_close_gaps_have_observed_preclose_or_official_close_pattern": (
            bool(results) and not errors and all(
                row["status"] in {
                    "CLOSES_AGREE",
                    "PRE_CLOSE_VS_OFFICIAL_CLOSE_PATTERN_OBSERVED",
                }
                for row in results
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--sessions", nargs="+", default=list(DEFAULT_SESSIONS))
    parser.add_argument("--output", default="artifacts/sip_close_condition_audit.json")
    args = parser.parse_args()
    try:
        result = run_audit(symbols=args.symbols, sessions=args.sessions)
    except Exception as exc:
        result = {
            "ok": False,
            "pipeline": "rocket_trader_sip_daily_close_trade_condition_audit_v0_1",
            "mode": "HISTORICAL_TRADE_CONDITION_DIAGNOSTIC_ONLY",
            "orders_enabled": False,
            "orders_submitted": 0,
            "errors": [{"error": str(exc)}],
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok"),
        "mode": result.get("mode"),
        "result_count": len(result.get("results") or []),
        "status_counts": result.get("status_counts"),
        "all_close_gaps_have_observed_preclose_or_official_close_pattern": result.get("all_close_gaps_have_observed_preclose_or_official_close_pattern"),
        "errors": result.get("errors"),
        "output": str(output),
        "orders_enabled": False,
        "orders_submitted": 0,
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
