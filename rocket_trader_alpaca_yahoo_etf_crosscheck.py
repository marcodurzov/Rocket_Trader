#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent daily ETF price-history cross-check: Alpaca market data vs Yahoo.

RESEARCH/AUDIT ONLY. This module has no TradingClient and cannot submit orders.
Alpaca IEX is compared with Yahoo auto-adjusted history on common sessions.
This is a data-consistency audit, not proof of executable fills or profitability.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

DEFAULT_SYMBOLS = ("DIA", "EEM", "EFA", "GLD", "IWM", "QQQ", "SPY", "TLT")


class CrosscheckError(RuntimeError):
    """A source returned missing, invalid, or incomparable price history."""


def _close_series(values: Any, source: str) -> pd.Series:
    """Normalize a Series/DataFrame/dict of closes into unique UTC session dates."""
    if isinstance(values, pd.DataFrame):
        if "close" in values.columns:
            values = values["close"]
        elif "Close" in values.columns:
            values = values["Close"]
        else:
            raise CrosscheckError(f"{source}: close column is missing")
        if isinstance(values, pd.DataFrame):
            if values.shape[1] != 1:
                raise CrosscheckError(f"{source}: close data is ambiguous")
            values = values.iloc[:, 0]
    if not isinstance(values, pd.Series):
        values = pd.Series(values)
    if values.empty:
        raise CrosscheckError(f"{source}: zero daily closes returned")
    index = pd.to_datetime(values.index, utc=True, errors="coerce")
    if index.isna().any():
        raise CrosscheckError(f"{source}: invalid timestamps")
    out = pd.Series(pd.to_numeric(values.to_numpy(), errors="coerce"), index=index.date)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    if out.empty or (out <= 0).any():
        raise CrosscheckError(f"{source}: close prices must be finite and positive")
    out.index.name = "session"
    return out.astype(float)


def compare_close_series(
    symbol: str,
    yahoo_close: Any,
    alpaca_close: Any,
    *,
    min_common_sessions: int = 1000,
    min_source_coverage: float = 0.95,
    min_return_correlation: float = 0.995,
    max_p95_abs_return_diff_bps: float = 20.0,
) -> Dict[str, Any]:
    """Compare adjusted closes and daily returns without fitting any strategy."""
    yahoo = _close_series(yahoo_close, "Yahoo")
    alpaca = _close_series(alpaca_close, "Alpaca")
    common = pd.concat(
        [yahoo.rename("yahoo"), alpaca.rename("alpaca")], axis=1, join="inner"
    ).dropna()
    if len(common) < 3:
        raise CrosscheckError(f"{symbol}: fewer than three common daily sessions")

    yahoo_ret = common["yahoo"].pct_change().dropna()
    alpaca_ret = common["alpaca"].pct_change().dropna()
    paired = pd.concat(
        [yahoo_ret.rename("yahoo"), alpaca_ret.rename("alpaca")], axis=1
    ).dropna()
    if len(paired) < 2:
        raise CrosscheckError(f"{symbol}: insufficient paired daily returns")

    abs_diff_bps = (paired["alpaca"] - paired["yahoo"]).abs() * 10000.0
    corr = float(paired["yahoo"].corr(paired["alpaca"]))
    if not np.isfinite(corr):
        corr = 0.0
    yahoo_coverage = len(common) / len(yahoo)
    alpaca_coverage = len(common) / len(alpaca)
    overlap_start = common.index.min()
    overlap_end = common.index.max()
    yahoo_overlap = yahoo.loc[(yahoo.index >= overlap_start) & (yahoo.index <= overlap_end)]
    alpaca_overlap = alpaca.loc[(alpaca.index >= overlap_start) & (alpaca.index <= overlap_end)]
    yahoo_overlap_completeness = len(common) / len(yahoo_overlap)
    alpaca_overlap_completeness = len(common) / len(alpaca_overlap)
    if (
        alpaca.index.min() > yahoo.index.min()
        and min(yahoo_overlap_completeness, alpaca_overlap_completeness) >= min_source_coverage
    ):
        history_window_assessment = "ALPACA_HISTORY_STARTS_LATER_THAN_YAHOO"
    elif min(yahoo_overlap_completeness, alpaca_overlap_completeness) < min_source_coverage:
        history_window_assessment = "SESSION_GAPS_WITHIN_OVERLAP"
    else:
        history_window_assessment = "COMPARABLE_HISTORY_WINDOWS"
    yahoo_total = float((1.0 + paired["yahoo"]).prod() - 1.0)
    alpaca_total = float((1.0 + paired["alpaca"]).prod() - 1.0)
    yahoo_norm = common["yahoo"] / common["yahoo"].iloc[0]
    alpaca_norm = common["alpaca"] / common["alpaca"].iloc[0]
    normalized_close_diff_pct = (
        (alpaca_norm / yahoo_norm - 1.0).abs() * 100.0
    )

    return_diff = (paired["alpaca"] - paired["yahoo"]) * 10000.0
    largest_return_divergences = []
    for session, value in return_diff.abs().sort_values(ascending=False).head(10).items():
        largest_return_divergences.append({
            "session": str(session),
            "yahoo_daily_return_pct": round(float(paired.loc[session, "yahoo"] * 100.0), 6),
            "alpaca_daily_return_pct": round(float(paired.loc[session, "alpaca"] * 100.0), 6),
            "alpaca_minus_yahoo_return_difference_bps": round(float(return_diff.loc[session]), 4),
        })
    largest_close_divergences = []
    for session, value in normalized_close_diff_pct.sort_values(ascending=False).head(10).items():
        largest_close_divergences.append({
            "session": str(session),
            "yahoo_normalized_close": round(float(yahoo_norm.loc[session]), 8),
            "alpaca_normalized_close": round(float(alpaca_norm.loc[session]), 8),
            "alpaca_vs_yahoo_normalized_close_difference_pct": round(float(value), 6),
        })

    history_overlap_gate = min(yahoo_coverage, alpaca_coverage) >= min_source_coverage
    gates = {
        "minimum_common_sessions": len(common) >= min_common_sessions,
        "minimum_requested_history_overlap": history_overlap_gate,
        # Backward-compatible alias; this is full-history overlap, not missing-bar rate.
        "minimum_source_coverage": history_overlap_gate,
        "minimum_overlap_session_completeness": min(
            yahoo_overlap_completeness, alpaca_overlap_completeness
        ) >= min_source_coverage,
        "minimum_daily_return_correlation": corr >= min_return_correlation,
        "maximum_p95_abs_return_difference": float(abs_diff_bps.quantile(0.95))
        <= max_p95_abs_return_diff_bps,
    }
    return {
        "symbol": symbol,
        "yahoo_sessions": int(len(yahoo)),
        "alpaca_sessions": int(len(alpaca)),
        "common_sessions": int(len(common)),
        "yahoo_first_session": str(yahoo.index.min()),
        "alpaca_first_session": str(alpaca.index.min()),
        "yahoo_last_session": str(yahoo.index.max()),
        "alpaca_last_session": str(alpaca.index.max()),
        "first_common_session": str(common.index[0]),
        "last_common_session": str(common.index[-1]),
        "history_window_assessment": history_window_assessment,
        "alpaca_history_start_lag_days": int((alpaca.index.min() - yahoo.index.min()).days),
        "yahoo_sessions_in_overlap_window": int(len(yahoo_overlap)),
        "alpaca_sessions_in_overlap_window": int(len(alpaca_overlap)),
        "yahoo_overlap_session_completeness": round(float(yahoo_overlap_completeness), 6),
        "alpaca_overlap_session_completeness": round(float(alpaca_overlap_completeness), 6),
        "yahoo_coverage_on_common": round(float(yahoo_coverage), 6),
        "alpaca_coverage_on_common": round(float(alpaca_coverage), 6),
        "coverage_gate_semantics": (
            "Full-history overlap ratio; a low value may reflect different first available "
            "dates, not missing sessions within the shared date window."
        ),
        "daily_return_correlation": round(corr, 8),
        "mean_abs_daily_return_difference_bps": round(float(abs_diff_bps.mean()), 4),
        "p95_abs_daily_return_difference_bps": round(float(abs_diff_bps.quantile(0.95)), 4),
        "max_abs_daily_return_difference_bps": round(float(abs_diff_bps.max()), 4),
        "yahoo_cumulative_return_common_period": round(yahoo_total, 8),
        "alpaca_cumulative_return_common_period": round(alpaca_total, 8),
        "cumulative_return_difference_bps": round((alpaca_total - yahoo_total) * 10000.0, 4),
        "max_normalized_close_difference_pct": round(float(normalized_close_diff_pct.max()), 4),
        "largest_daily_return_divergences": largest_return_divergences,
        "largest_normalized_close_divergences": largest_close_divergences,
        "diagnostic_gates": gates,
        "diagnostic_pass": all(gates.values()),
    }


def fetch_yahoo_history(symbol: str, start: datetime, end: datetime) -> pd.Series:
    import yfinance as yf
    frame = yf.Ticker(symbol).history(
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        interval="1d",
        auto_adjust=True,
        actions=True,
        repair=False,
        timeout=30,
    )
    if frame is None or frame.empty or "Close" not in frame.columns:
        raise CrosscheckError(f"Yahoo returned no adjusted daily history for {symbol}")
    return _close_series(frame["Close"], "Yahoo")


def fetch_alpaca_history(
    client: Any,
    symbol: str,
    start: datetime,
    end: datetime,
    feed: Any,
) -> pd.Series:
    from alpaca.data.enums import Adjustment
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=10000,
        adjustment=Adjustment.ALL,
        feed=feed,
    )
    response = client.get_stock_bars(request)
    bars = response.data.get(symbol, [])
    if not bars:
        raise CrosscheckError(f"Alpaca {feed} returned no adjusted daily history for {symbol}")
    frame = pd.DataFrame({
        "timestamp": [bar.timestamp for bar in bars],
        "close": [bar.close for bar in bars],
    }).set_index("timestamp")
    return _close_series(frame["close"], "Alpaca")



def fetch_tiingo_history(
    symbol: str,
    start: datetime,
    end: datetime,
    api_token: Optional[str] = None,
    *,
    opener=urlopen,
) -> pd.Series:
    """Fetch Tiingo adjusted EOD closes; optional provider audit, never execution data."""
    token = str(api_token or os.getenv("TIINGO_API_TOKEN", "")).strip()
    if not token:
        raise CrosscheckError("TIINGO_API_TOKEN is required for the Tiingo comparison")
    if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
        raise CrosscheckError("Tiingo audit range must be timezone-aware")
    url = (
        "https://api.tiingo.com/tiingo/daily/" + quote(str(symbol).upper(), safe="")
        + "?" + urlencode({
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
            "format": "json",
        })
    )
    request = Request(url, headers={
        "Authorization": f"Token {token}",
        "Accept": "application/json",
    })
    try:
        with opener(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise CrosscheckError(f"Tiingo returned HTTP {status}")
            payload = json.loads(response.read().decode("utf-8"))
    except CrosscheckError:
        raise
    except Exception as exc:
        raise CrosscheckError(
            f"Tiingo request failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise CrosscheckError(f"Tiingo returned no adjusted daily history for {symbol}")
    rows = []
    for item in payload:
        if not isinstance(item, dict) or item.get("date") is None or item.get("adjClose") is None:
            raise CrosscheckError(f"Tiingo returned malformed adjusted close data for {symbol}")
        rows.append((item["date"], item["adjClose"]))
    frame = pd.DataFrame(rows, columns=["date", "close"])
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    if frame["date"].isna().any():
        raise CrosscheckError(f"Tiingo returned invalid dates for {symbol}")
    return _close_series(frame.set_index("date")["close"], "Tiingo")


def _rename_pair_result(
    result: Dict[str, Any], left_name: str, right_name: str
) -> Dict[str, Any]:
    """Give generic two-source comparison fields their actual provider names."""
    output = dict(result)
    output["comparison"] = f"{right_name.upper()}_VS_{left_name.upper()}"
    for old, new in (
        ("yahoo_sessions", f"{left_name.lower()}_sessions"),
        ("alpaca_sessions", f"{right_name.lower()}_sessions"),
        ("yahoo_coverage_on_common", f"{left_name.lower()}_coverage_on_common"),
        ("alpaca_coverage_on_common", f"{right_name.lower()}_coverage_on_common"),
        ("yahoo_cumulative_return_common_period", f"{left_name.lower()}_cumulative_return_common_period"),
        ("alpaca_cumulative_return_common_period", f"{right_name.lower()}_cumulative_return_common_period"),
    ):
        output[new] = output.pop(old)
    output["right_minus_left_cumulative_return_difference_bps"] = output.pop(
        "cumulative_return_difference_bps"
    )
    return output




def fetch_yahoo_adjustment_fields(
    symbol: str, start: datetime, end: datetime
) -> Dict[str, pd.Series]:
    """Fetch raw Close and dividend/split adjusted Adj Close from Yahoo."""
    import yfinance as yf
    frame = yf.Ticker(symbol).history(
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=True,
        repair=False,
        timeout=30,
    )
    if frame is None or frame.empty or "Close" not in frame.columns or "Adj Close" not in frame.columns:
        raise CrosscheckError(f"Yahoo raw/adjusted close fields missing for {symbol}")
    action_index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    if action_index.isna().any():
        raise CrosscheckError(f"Yahoo returned invalid action dates for {symbol}")
    action_dates = action_index.date
    dividends = pd.Series(
        pd.to_numeric(frame.get("Dividends", 0.0), errors="coerce").fillna(0.0).to_numpy()
        if isinstance(frame.get("Dividends", 0.0), pd.Series)
        else np.zeros(len(frame)),
        index=action_dates,
        dtype=float,
    )
    splits = pd.Series(
        pd.to_numeric(frame.get("Stock Splits", 0.0), errors="coerce").fillna(0.0).to_numpy()
        if isinstance(frame.get("Stock Splits", 0.0), pd.Series)
        else np.zeros(len(frame)),
        index=action_dates,
        dtype=float,
    )
    dividends = dividends[~dividends.index.duplicated(keep="last")]
    splits = splits[~splits.index.duplicated(keep="last")]
    return {
        "raw_close": _close_series(frame["Close"], "Yahoo raw"),
        "adjusted_close": _close_series(frame["Adj Close"], "Yahoo adjusted"),
        "dividends": dividends,
        "splits": splits,
    }


def fetch_alpaca_raw_history(
    client: Any,
    symbol: str,
    start: datetime,
    end: datetime,
    feed: Any,
) -> pd.Series:
    """Fetch unadjusted Alpaca daily closes for corporate-action factor analysis."""
    from alpaca.data.enums import Adjustment
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=10000,
        adjustment=Adjustment.RAW,
        feed=feed,
    )
    response = client.get_stock_bars(request)
    bars = response.data.get(symbol, [])
    if not bars:
        raise CrosscheckError(f"Alpaca {feed} returned no raw daily history for {symbol}")
    frame = pd.DataFrame({
        "timestamp": [bar.timestamp for bar in bars],
        "close": [bar.close for bar in bars],
    }).set_index("timestamp")
    return _close_series(frame["close"], "Alpaca raw")


def fetch_alpaca_corporate_actions(
    symbols: Iterable[str],
    start: datetime,
    end: datetime,
    api_key: str,
    secret_key: str,
    *,
    opener=urlopen,
) -> List[Dict[str, Any]]:
    """Fetch issuer-action records from Alpaca's corporate-actions market-data API."""
    if not api_key or not secret_key:
        raise CrosscheckError("Alpaca API credentials are required for corporate actions")
    symbol_list = sorted({str(item).strip().upper() for item in symbols if str(item).strip()})
    if not symbol_list:
        return []
    if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
        raise CrosscheckError("Corporate-action date range must be timezone-aware")
    # API filters by process_date, not ex_date; pad both ends to include delayed processing.
    query_start = (start.date() - timedelta(days=60)).isoformat()
    query_end = (end.date() + timedelta(days=60)).isoformat()
    params = {
        "symbols": ",".join(symbol_list),
        "start": query_start,
        "end": query_end,
        "limit": "1000",
        "data_quality": "complete",
        "region": "us",
        "sort": "asc",
    }
    url = "https://data.alpaca.markets/v1/corporate-actions?" + urlencode(params)
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }
    key_types = {
        "cash_dividends": "cash_dividend",
        "stock_dividends": "stock_dividend",
        "forward_splits": "forward_split",
        "reverse_splits": "reverse_split",
        "unit_splits": "unit_split",
        "spin_offs": "spin_off",
        "capital_gains_distributions": "capital_gains_distribution",
        "rights_distributions": "rights_distribution",
        "cash_mergers": "cash_merger",
        "stock_mergers": "stock_merger",
        "stock_and_cash_mergers": "stock_and_cash_merger",
        "redemptions": "redemption",
        "name_changes": "name_change",
        "worthless_removals": "worthless_removal",
        "reorganizations": "reorganization",
        "partial_calls": "partial_call",
    }
    events: List[Dict[str, Any]] = []
    page_token = None
    for page in range(10):
        page_url = url
        if page_token:
            page_url += "&" + urlencode({"page_token": page_token})
        request = Request(page_url, headers=headers)
        try:
            with opener(request, timeout=30) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise CrosscheckError(f"Alpaca corporate actions returned HTTP {status}")
                payload = json.loads(response.read().decode("utf-8"))
        except CrosscheckError:
            raise
        except Exception as exc:
            raise CrosscheckError(
                f"Alpaca corporate actions failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CrosscheckError("Alpaca corporate actions response was not an object")
        action_payload = payload.get("corporate_actions")
        if not isinstance(action_payload, dict):
            raise CrosscheckError(
                "Alpaca corporate actions response is missing the corporate_actions object"
            )
        for key, kind in key_types.items():
            rows = action_payload.get(key, [])
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise CrosscheckError(f"Alpaca corporate actions field {key} was not a list")
            for row in rows:
                if not isinstance(row, dict):
                    raise CrosscheckError(f"Alpaca corporate action in {key} was malformed")
                event = dict(row)
                event["action_type"] = kind
                events.append(event)
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    else:
        raise CrosscheckError("Alpaca corporate actions pagination exceeded 10 pages")
    return events


def compare_adjustment_factors(
    symbol: str,
    yahoo_raw_close: Any,
    yahoo_adjusted_close: Any,
    alpaca_raw_close: Any,
    alpaca_adjusted_close: Any,
    *,
    min_common_sessions: int = 1000,
    yahoo_dividends: Any = None,
    yahoo_splits: Any = None,
    alpaca_corporate_actions: Any = None,
) -> Dict[str, Any]:
    """Separate raw-price divergence from provider adjustment-factor divergence."""
    frames = [
        _close_series(yahoo_raw_close, "Yahoo raw").rename("yahoo_raw"),
        _close_series(yahoo_adjusted_close, "Yahoo adjusted").rename("yahoo_adjusted"),
        _close_series(alpaca_raw_close, "Alpaca raw").rename("alpaca_raw"),
        _close_series(alpaca_adjusted_close, "Alpaca adjusted").rename("alpaca_adjusted"),
    ]
    common = pd.concat(frames, axis=1, join="inner").dropna()
    if len(common) < min_common_sessions:
        raise CrosscheckError(
            f"{symbol}: only {len(common)} common raw/adjusted sessions; "
            f"minimum is {min_common_sessions}"
        )
    yahoo_factor = common["yahoo_adjusted"] / common["yahoo_raw"]
    alpaca_factor = common["alpaca_adjusted"] / common["alpaca_raw"]
    factor_ratio = alpaca_factor / yahoo_factor
    relative_factor_divergence_pct = (
        factor_ratio / factor_ratio.iloc[0] - 1.0
    ) * 100.0
    factor_step_change_bps = relative_factor_divergence_pct.diff() * 100.0

    def action_series(values: Any) -> pd.Series:
        if values is None:
            return pd.Series(0.0, index=common.index, dtype=float)
        if isinstance(values, pd.DataFrame):
            if values.shape[1] != 1:
                raise CrosscheckError(f"{symbol}: ambiguous Yahoo action series")
            values = values.iloc[:, 0]
        if not isinstance(values, pd.Series):
            values = pd.Series(values)
        action_index = pd.to_datetime(values.index, utc=True, errors="coerce")
        if action_index.isna().any():
            raise CrosscheckError(f"{symbol}: invalid Yahoo action timestamps")
        normalized = pd.Series(
            pd.to_numeric(values.to_numpy(), errors="coerce"),
            index=action_index.date,
        ).replace([np.inf, -np.inf], np.nan)
        normalized = normalized[~normalized.index.duplicated(keep="last")]
        return normalized.reindex(common.index).fillna(0.0).astype(float)

    dividend_events = action_series(yahoo_dividends)
    split_events = action_series(yahoo_splits)

    raw_returns = pd.concat([
        common["yahoo_raw"].pct_change().rename("yahoo"),
        common["alpaca_raw"].pct_change().rename("alpaca"),
    ], axis=1).dropna()
    raw_return_diff_bps = (raw_returns["alpaca"] - raw_returns["yahoo"]) * 10000.0
    raw_normalized_ratio = (
        (common["alpaca_raw"] / common["alpaca_raw"].iloc[0])
        / (common["yahoo_raw"] / common["yahoo_raw"].iloc[0]) - 1.0
    ) * 100.0

    top_steps = []
    for session, _ in factor_step_change_bps.abs().sort_values(ascending=False).head(10).items():
        if pd.isna(factor_step_change_bps.loc[session]):
            continue
        position = int(common.index.get_loc(session))
        previous_session = common.index[position - 1] if position > 0 else None
        previous_yahoo_factor = (
            float(yahoo_factor.iloc[position - 1]) if position > 0 else None
        )
        previous_alpaca_factor = (
            float(alpaca_factor.iloc[position - 1]) if position > 0 else None
        )
        previous_factor_ratio = (
            float(factor_ratio.iloc[position - 1]) if position > 0 else None
        )
        previous_yahoo_raw = (
            float(common["yahoo_raw"].iloc[position - 1]) if position > 0 else None
        )
        previous_alpaca_raw = (
            float(common["alpaca_raw"].iloc[position - 1]) if position > 0 else None
        )
        dividend_cash = float(dividend_events.loc[session])
        split_ratio = float(split_events.loc[session])
        event_date = str(session)
        previous_date = str(previous_session) if previous_session is not None else None
        alpaca_events_current = [
            event for event in (alpaca_corporate_actions or [])
            if str(event.get("ex_date") or "") == event_date
        ]
        alpaca_events_previous = [
            event for event in (alpaca_corporate_actions or [])
            if previous_date is not None and str(event.get("ex_date") or "") == previous_date
        ]
        alpaca_cash_dividend_events = [
            event for event in alpaca_events_current
            if event.get("action_type") == "cash_dividend"
        ]
        alpaca_cash_dividend_event_count = len(alpaca_cash_dividend_events)
        if alpaca_cash_dividend_event_count == 0:
            alpaca_cash_dividend = 0.0
            alpaca_cash_dividend_total_status = "NO_EVENT"
        elif alpaca_cash_dividend_event_count == 1:
            alpaca_cash_dividend = float(
                alpaca_cash_dividend_events[0].get("rate") or 0.0
            )
            alpaca_cash_dividend_total_status = "SINGLE_EVENT"
        else:
            # Multiple same-symbol/ex-date records may be duplicate versions or
            # distinct issuer actions. Never sum them without resolving identity.
            alpaca_cash_dividend = None
            alpaca_cash_dividend_total_status = "MULTIPLE_RECORDS_REQUIRES_REVIEW"
        top_steps.append({
            "session": str(session),
            "previous_session": str(previous_session) if previous_session is not None else None,
            "previous_yahoo_adjustment_factor": (
                round(previous_yahoo_factor, 10) if previous_yahoo_factor is not None else None
            ),
            "previous_alpaca_adjustment_factor": (
                round(previous_alpaca_factor, 10) if previous_alpaca_factor is not None else None
            ),
            "previous_alpaca_to_yahoo_factor_ratio": (
                round(previous_factor_ratio, 10) if previous_factor_ratio is not None else None
            ),
            "previous_yahoo_raw_close": (
                round(previous_yahoo_raw, 8) if previous_yahoo_raw is not None else None
            ),
            "previous_alpaca_raw_close": (
                round(previous_alpaca_raw, 8) if previous_alpaca_raw is not None else None
            ),
            "yahoo_dividend_cash_on_session": round(dividend_cash, 8),
            "yahoo_split_ratio_on_session": round(split_ratio, 8),
            "alpaca_corporate_actions_on_session": [
                {
                    "id": event.get("id"),
                    "cusip": event.get("cusip"),
                    "isin": event.get("isin"),
                    "record_date": event.get("record_date"),
                    "action_type": event.get("action_type"),
                    "symbol": event.get("symbol"),
                    "ex_date": event.get("ex_date"),
                    "rate": event.get("rate"),
                    "long_term_rate": event.get("long_term_rate"),
                    "short_term_rate": event.get("short_term_rate"),
                    "special": event.get("special"),
                    "sub_type": event.get("sub_type"),
                    "process_date": event.get("process_date"),
                    "payable_date": event.get("payable_date"),
                    "currency": event.get("currency"),
                }
                for event in alpaca_events_current
            ],
            "alpaca_corporate_actions_on_previous_session": [
                {
                    "id": event.get("id"),
                    "cusip": event.get("cusip"),
                    "isin": event.get("isin"),
                    "record_date": event.get("record_date"),
                    "action_type": event.get("action_type"),
                    "symbol": event.get("symbol"),
                    "ex_date": event.get("ex_date"),
                    "rate": event.get("rate"),
                    "process_date": event.get("process_date"),
                }
                for event in alpaca_events_previous
            ],
            "alpaca_cash_dividend_event_count": alpaca_cash_dividend_event_count,
            "alpaca_cash_dividend_event_ids": [
                event.get("id") for event in alpaca_cash_dividend_events
            ],
            "alpaca_cash_dividend_total_status": (
                alpaca_cash_dividend_total_status
                if alpaca_corporate_actions is not None else "NOT_AVAILABLE"
            ),
            "alpaca_cash_dividend_total_on_session": (
                round(alpaca_cash_dividend, 8)
                if alpaca_corporate_actions is not None and alpaca_cash_dividend is not None
                else None
            ),
            "yahoo_minus_alpaca_cash_dividend_on_session": (
                round(dividend_cash - alpaca_cash_dividend, 8)
                if alpaca_corporate_actions is not None and alpaca_cash_dividend is not None
                else None
            ),
            "expected_cash_dividend_adjustment_bps_vs_previous_yahoo_raw_close": (
                round(dividend_cash / previous_yahoo_raw * 10000.0, 4)
                if dividend_cash > 0 and previous_yahoo_raw and previous_yahoo_raw > 0
                else None
            ),
            "yahoo_adjustment_factor": round(float(yahoo_factor.loc[session]), 10),
            "alpaca_adjustment_factor": round(float(alpaca_factor.loc[session]), 10),
            "alpaca_to_yahoo_factor_ratio": round(float(factor_ratio.loc[session]), 10),
            "relative_adjustment_factor_divergence_pct": round(
                float(relative_factor_divergence_pct.loc[session]), 6
            ),
            "daily_relative_factor_change_bps": round(
                float(factor_step_change_bps.loc[session]), 4
            ),
        })
    top_raw = []
    for session, _ in raw_return_diff_bps.abs().sort_values(ascending=False).head(10).items():
        top_raw.append({
            "session": str(session),
            "yahoo_raw_daily_return_pct": round(float(raw_returns.loc[session, "yahoo"] * 100.0), 6),
            "alpaca_raw_daily_return_pct": round(float(raw_returns.loc[session, "alpaca"] * 100.0), 6),
            "alpaca_minus_yahoo_raw_return_difference_bps": round(
                float(raw_return_diff_bps.loc[session]), 4
            ),
        })
    return {
        "symbol": symbol,
        "common_raw_adjusted_sessions": int(len(common)),
        "first_common_session": str(common.index[0]),
        "last_common_session": str(common.index[-1]),
        "max_abs_relative_adjustment_factor_divergence_pct": round(
            float(relative_factor_divergence_pct.abs().max()), 6
        ),
        "max_abs_raw_normalized_close_difference_pct": round(
            float(raw_normalized_ratio.abs().max()), 6
        ),
        "mean_abs_raw_daily_return_difference_bps": round(
            float(raw_return_diff_bps.abs().mean()), 4
        ),
        "p95_abs_raw_daily_return_difference_bps": round(
            float(raw_return_diff_bps.abs().quantile(0.95)), 4
        ),
        "largest_adjustment_factor_step_changes": top_steps,
        "largest_raw_return_divergences": top_raw,
    }




def require_zero_budget_feed(feed_name: str) -> str:
    """Only permit the free IEX feed until a paid SIP plan is explicitly approved."""
    normalized = str(feed_name or "").strip().upper()
    if normalized != "IEX":
        raise CrosscheckError(
            "SIP is disabled by Rocket Trader's zero-budget policy; only free IEX is enabled."
        )
    return normalized


def resolve_tiingo_token(
    include_tiingo: bool, token: Optional[str] = None
) -> str:
    """Never consume Tiingo API quota unless explicitly opted in."""
    if not include_tiingo:
        return ""
    resolved = str(token or os.getenv("TIINGO_API_TOKEN", "")).strip()
    if not resolved:
        raise CrosscheckError(
            "Tiingo comparison was explicitly requested but TIINGO_API_TOKEN is missing."
        )
    return resolved


def tiingo_audit_status(
    token: Optional[str],
    results: Iterable[Dict[str, Any]],
    errors: Iterable[Dict[str, Any]],
    expected_symbols: int,
) -> Dict[str, Any]:
    """Represent an optional Tiingo check as NOT_REQUESTED, PASSED or FAILED.

    An unconfigured optional provider is unknown/not requested, never a pass.
    """
    if not str(token or "").strip():
        return {
            "requested": False,
            "status": "NOT_REQUESTED",
            "all_diagnostic_gates_pass": None,
        }
    result_list = list(results)
    error_list = list(errors)
    passed = (
        len(result_list) == expected_symbols
        and not error_list
        and all(
            item.get("tiingo_vs_yahoo", {}).get("diagnostic_pass") is True
            and item.get("tiingo_vs_alpaca", {}).get("diagnostic_pass") is True
            for item in result_list
        )
    )
    return {
        "requested": True,
        "status": "PASSED" if passed else "FAILED",
        "all_diagnostic_gates_pass": bool(passed),
    }



def run_audit(
    *,
    api_key: str,
    secret_key: str,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    years: int = 10,
    feed_name: str = "IEX",
    now: Optional[datetime] = None,
    yahoo_loader=fetch_yahoo_history,
    alpaca_loader=fetch_alpaca_history,
    tiingo_loader=fetch_tiingo_history,
    tiingo_token: Optional[str] = None,
    yahoo_adjustment_loader=fetch_yahoo_adjustment_fields,
    alpaca_raw_loader=fetch_alpaca_raw_history,
    alpaca_corporate_actions_loader=fetch_alpaca_corporate_actions,
    include_tiingo: bool = False,
) -> Dict[str, Any]:
    if years < 1 or years > 20:
        raise CrosscheckError("years must be between 1 and 20")
    if not api_key or not secret_key:
        raise CrosscheckError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
    feed_name = require_zero_budget_feed(feed_name)
    token = resolve_tiingo_token(include_tiingo, tiingo_token)
    if token and years > 5:
        raise CrosscheckError(
            "The zero-cost Tiingo Starter tier provides 5 years of history; use --years 5 or less."
        )
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise CrosscheckError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    start = current - timedelta(days=365.25 * years)

    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    feed_map = {"IEX": DataFeed.IEX}
    feed = feed_map[feed_name]
    client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    symbol_list = sorted({str(x).strip().upper() for x in symbols if str(x).strip()})
    corporate_actions_error = None
    corporate_action_events = None
    try:
        corporate_action_events = alpaca_corporate_actions_loader(
            symbol_list, start, current, api_key, secret_key
        )
    except Exception as exc:
        corporate_actions_error = {
            "error_type": type(exc).__name__, "error": str(exc)
        }
    results = []
    errors = []
    tiingo_results = []
    tiingo_errors = []
    for symbol in symbol_list:
        try:
            yahoo = yahoo_loader(symbol, start, current)
            alpaca = alpaca_loader(client, symbol, start, current, feed)
            result = compare_close_series(symbol, yahoo, alpaca)
            yahoo_fields = yahoo_adjustment_loader(symbol, start, current)
            alpaca_raw = alpaca_raw_loader(client, symbol, start, current, feed)
            result["adjustment_factor_diagnostics"] = compare_adjustment_factors(
                symbol,
                yahoo_fields["raw_close"],
                yahoo_fields["adjusted_close"],
                alpaca_raw,
                alpaca,
                yahoo_dividends=yahoo_fields.get("dividends"),
                yahoo_splits=yahoo_fields.get("splits"),
                alpaca_corporate_actions=[
                    event for event in (corporate_action_events or [])
                    if str(event.get("symbol") or "").upper() == symbol
                ] if corporate_action_events is not None else None,
            )
            results.append(result)
            if token:
                try:
                    tiingo = tiingo_loader(symbol, start, current, token)
                    tiingo_results.append({
                        "symbol": symbol,
                        "tiingo_vs_yahoo": _rename_pair_result(
                            compare_close_series(symbol, yahoo, tiingo), "YAHOO", "TIINGO"
                        ),
                        "tiingo_vs_alpaca": _rename_pair_result(
                            compare_close_series(symbol, alpaca, tiingo), "ALPACA", "TIINGO"
                        ),
                    })
                except Exception as exc:
                    tiingo_errors.append({
                        "symbol": symbol, "error_type": type(exc).__name__, "error": str(exc)
                    })
        except Exception as exc:
            errors.append({"symbol": symbol, "error_type": type(exc).__name__, "error": str(exc)})

    tiingo_status = tiingo_audit_status(
        token, tiingo_results, tiingo_errors, len(symbol_list)
    )
    base_diagnostics_pass = (
        bool(results) and not errors and corporate_actions_error is None
        and all(x["diagnostic_pass"] for x in results)
    )
    return {
        "ok": bool(results) and not errors and corporate_actions_error is None and (
            not token or (
                len(tiingo_results) == len(symbol_list) and not tiingo_errors
            )
        ),
        "pipeline": "rocket_trader_alpaca_yahoo_etf_crosscheck_v0_1",
        "mode": "DATA_AUDIT_ONLY",
        "period_start": start.isoformat(),
        "period_end": current.isoformat(),
        "years_requested": years,
        "symbols_requested": symbol_list,
        "feed": feed_name.upper(),
        "alpaca_adjustment": "ALL",
        "yahoo_adjustment": "auto_adjust=True; actions=True; repair=False",
        "price_series": "daily adjusted close",
        "results": results,
        "errors": errors,
        "corporate_actions_requested": True,
        "corporate_actions_complete": corporate_actions_error is None,
        "corporate_actions_error": corporate_actions_error,
        "corporate_actions_count": len(corporate_action_events or []),
        "tiingo_comparison_requested": tiingo_status["requested"],
        "tiingo_comparison_status": tiingo_status["status"],
        "tiingo_results": tiingo_results,
        "tiingo_errors": tiingo_errors,
        "tiingo_symbols_compared": len(tiingo_results),
        "tiingo_all_diagnostic_gates_pass": tiingo_status["all_diagnostic_gates_pass"],
        "symbols_diagnostic_pass": sum(bool(x["diagnostic_pass"]) for x in results),
        "symbols_compared": len(results),
        "all_diagnostic_gates_pass": bool(base_diagnostics_pass) and corporate_actions_error is None and (
            not tiingo_status["requested"]
            or tiingo_status["all_diagnostic_gates_pass"] is True
        ),
        "research_cost_assumptions_validated": False,
        "research_cost_note": (
            "This price-history comparison does not validate historical bid/ask spread, "
            "commissions, market impact, or realized Paper slippage. Existing 5 bps/side "
            "ETF assumptions remain unverified."
        ),
        "execution_fill_validation": False,
        "candidate_promotion_allowed": False,
        "paper_approval": False,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--feed", choices=("IEX",), default="IEX")
    parser.add_argument(
        "--include-tiingo", action="store_true",
        help="Explicitly opt in to Tiingo; requires a free Starter token and a maximum 5-year window."
    )
    parser.add_argument("--output", default="artifacts/alpaca_yahoo_etf_crosscheck.json")
    args = parser.parse_args()
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        parser.error("ALPACA_PAPER must be exactly 'true' (audit is read-only).")

    try:
        report = run_audit(
            api_key=os.getenv("ALPACA_API_KEY", "").strip(),
            secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
            symbols=args.symbols,
            years=args.years,
            feed_name=args.feed,
            include_tiingo=args.include_tiingo,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except Exception as exc:
        print(json.dumps({
            "ok": False, "mode": "DATA_AUDIT_ONLY",
            "error_type": type(exc).__name__, "error": str(exc),
            "orders_submitted": 0,
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
