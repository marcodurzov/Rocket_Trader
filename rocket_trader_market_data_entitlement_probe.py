#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Alpaca stock-feed entitlement probe (IEX baseline vs SIP)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class FeedProbeError(RuntimeError):
    pass


def _status_code(exc: Exception) -> Optional[int]:
    value = getattr(exc, "status_code", None)
    if value is None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None) if response is not None else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def probe_feed(
    client: Any,
    feed: DataFeed,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise FeedProbeError("now must be timezone-aware")
    request = StockBarsRequest(
        symbol_or_symbols=["SPY"],
        timeframe=TimeFrame.Day,
        start=current - timedelta(days=14),
        end=current,
        limit=5,
        feed=feed,
    )
    try:
        response = client.get_stock_bars(request)
        frame = response.df
        count = 0 if frame is None else len(frame)
        if count < 1:
            return {"feed": feed.value, "status": "NO_DATA", "bars_returned": count}
        return {"feed": feed.value, "status": "AVAILABLE", "bars_returned": count}
    except Exception as exc:
        code = _status_code(exc)
        status = {
            401: "AUTH_ERROR",
            403: "NOT_ENTITLED",
            429: "RATE_LIMITED",
        }.get(code, "ERROR")
        return {
            "feed": feed.value,
            "status": status,
            "http_status": code,
            "error_type": type(exc).__name__,
        }


def run_probe(client: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    iex = probe_feed(client, DataFeed.IEX, now=now)
    sip = probe_feed(client, DataFeed.SIP, now=now)
    return {
        "ok": iex["status"] == "AVAILABLE",
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(),
        "symbol": "SPY",
        "timeframe": "1Day",
        "iex": iex,
        "sip": sip,
        "research_feed_recommendation": "SIP" if sip["status"] == "AVAILABLE" else "IEX_ONLY_WITH_LIMITATION",
        "orders_enabled": False,
        "orders_submitted": 0,
    }


class _Response:
    def __init__(self, df):
        self.df = df


def self_test() -> Dict[str, Any]:
    import pandas as pd

    class FakeClient:
        def get_stock_bars(self, request):
            if request.feed == DataFeed.SIP:
                raise PermissionError("simulated entitlement restriction")
            return _Response(pd.DataFrame({"close": [100.0]}))

    result = run_probe(FakeClient(), now=datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert result["ok"] is True
    assert result["iex"]["status"] == "AVAILABLE"
    assert result["sip"]["status"] == "ERROR"
    assert result["orders_enabled"] is False
    assert result["orders_submitted"] == 0
    return {
        "ok": True,
        "pipeline": "rocket_trader_market_data_entitlement_probe",
        "mode": "READ_ONLY",
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default="research_artifacts/market_data_entitlements.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise FeedProbeError("Alpaca API credentials are missing.")
    client = StockHistoricalDataClient(key, secret)
    result = run_probe(client)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
