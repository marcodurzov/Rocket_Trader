#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, bounded probe of Alpaca Paper Activity SSE support.

This is a capability/evidence probe only. It does not maintain a cursor,
mutate the event ledger, submit orders, or apply corrections to positions.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

ENDPOINT = "https://paper-api.alpaca.markets/v2beta1/events/activities"


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp.")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def parse_sse_lines(lines: Iterable[Any]) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """Parse SSE data frames; return event objects, comments and invalid frames."""
    events: List[Dict[str, Any]] = []
    comments: List[str] = []
    invalid_frames = 0
    data_lines: List[str] = []

    def flush() -> None:
        nonlocal invalid_frames
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            invalid_frames += 1
            return
        if isinstance(decoded, dict):
            events.append(decoded)
        elif isinstance(decoded, list) and all(isinstance(item, dict) for item in decoded):
            events.extend(decoded)
        else:
            invalid_frames += 1

    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = str(raw_line)
        line = line.rstrip("\r\n")
        if not line:
            flush()
        elif line.startswith(":"):
            comments.append(line[1:].strip())
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return events, comments, invalid_frames


def _is_crypto_symbol(symbol: Any) -> bool:
    if not isinstance(symbol, str):
        return False
    normalized = symbol.strip().upper()
    return "/" in normalized or (normalized.endswith("USD") and len(normalized) > 3)


def summarize_events(
    events: List[Dict[str, Any]],
    comments: List[str],
    invalid_frames: int,
    *,
    since: str,
    until: str,
    http_status: int = 200,
) -> Dict[str, Any]:
    activity_types: Counter[str] = Counter()
    execution_types: Counter[str] = Counter()
    crypto_events: List[Dict[str, Any]] = []
    fee_counts: Counter[str] = Counter()
    previous_id_count = 0
    correction_count = 0
    bust_count = 0
    duplicate_ref_count = 0
    ordering_anomalies = 0
    seen_refs = set()
    previous_event_id = None
    invalid_events = 0
    event_ids: List[str] = []

    for event in events:
        event_id = event.get("event_id")
        ref_id = event.get("ref_id")
        activity_type = event.get("activity_type")
        details = event.get("details")
        required_ok = (
            isinstance(event_id, str) and bool(event_id)
            and isinstance(ref_id, str) and bool(ref_id)
            and isinstance(activity_type, str) and bool(activity_type)
            and isinstance(details, dict)
        )
        if not required_ok:
            invalid_events += 1
            continue

        activity_type = activity_type.upper()
        activity_types[activity_type] += 1
        if ref_id in seen_refs:
            duplicate_ref_count += 1
        seen_refs.add(ref_id)
        if previous_event_id is not None and event_id < previous_event_id:
            ordering_anomalies += 1
        previous_event_id = event_id
        event_ids.append(event_id)

        if activity_type in {"CFEE", "FEE"}:
            fee_counts[activity_type] += 1

        execution_type = details.get("execution_type")
        if isinstance(execution_type, str):
            execution_type = execution_type.lower()
            execution_types[execution_type] += 1
            if execution_type == "trade_correct":
                correction_count += 1
            elif execution_type == "trade_bust":
                bust_count += 1
        if event.get("previous_id"):
            previous_id_count += 1

        symbol = details.get("symbol")
        if symbol is None and isinstance(event.get("asset"), dict):
            symbol = event["asset"].get("symbol")
        if activity_type == "TRD" and _is_crypto_symbol(symbol):
            crypto_events.append({
                "event_id": event_id,
                "ref_id": ref_id,
                "previous_id": event.get("previous_id"),
                "execution_type": execution_type,
                "order_id": details.get("order_id"),
                "client_order_id": details.get("client_order_id"),
                "symbol": symbol,
                "side": details.get("side"),
                "qty": event.get("qty"),
                "price": event.get("price"),
                "net_amount": event.get("net_amount"),
                "currency": event.get("currency"),
                "at": event.get("at"),
                "executed_at": event.get("executed_at"),
            })

    dropped_comments = [
        comment for comment in comments
        if "dropped" in comment.lower() or "reading too slowly" in comment.lower()
    ]
    server_error_comments = [
        comment for comment in comments if "internal server error" in comment.lower()
    ]

    if http_status != 200:
        status = "UNAVAILABLE" if http_status in {401, 403, 404, 405} else "HTTP_ERROR"
    elif dropped_comments or server_error_comments or invalid_frames or invalid_events:
        status = "INCOMPLETE"
    elif not events:
        status = "NO_EVENTS"
    elif crypto_events:
        status = "CRYPTO_EVENTS_FOUND"
    else:
        status = "NO_CRYPTO_TRADES"

    return {
        "mode": "PAPER",
        "endpoint": ENDPOINT,
        "status": status,
        "since": since,
        "until": until,
        "http_status": http_status,
        "event_count": len(events),
        "valid_event_count": len(event_ids),
        "invalid_event_count": invalid_events,
        "invalid_frame_count": invalid_frames,
        "duplicate_ref_id_count": duplicate_ref_count,
        "event_ordering_anomaly_count": ordering_anomalies,
        "dropped_message_comment_count": len(dropped_comments),
        "server_error_comment_count": len(server_error_comments),
        "activity_type_counts": dict(sorted(activity_types.items())),
        "trade_execution_type_counts": dict(sorted(execution_types.items())),
        "fee_activity_counts": dict(sorted(fee_counts.items())),
        "previous_id_event_count": previous_id_count,
        "trade_correction_event_count": correction_count,
        "trade_bust_event_count": bust_count,
        "crypto_trade_event_count": len(crypto_events),
        "crypto_symbols": sorted({str(item["symbol"]) for item in crypto_events}),
        "first_event_id": event_ids[0] if event_ids else None,
        "last_event_id": event_ids[-1] if event_ids else None,
        "crypto_trade_events": crypto_events[:100],
        "comments": comments[:50],
    }


def run_probe(
    *,
    api_key: str,
    api_secret: str,
    since: str,
    until: str | None = None,
    request_get: Callable[..., Any] | None = None,
) -> Dict[str, Any]:
    since_dt = _parse_utc(since, "since")
    until_text = until or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    until_dt = _parse_utc(until_text, "until")
    if until_dt <= since_dt:
        raise ValueError("until must be later than since.")
    if not api_key or not api_secret:
        return {
            "mode": "PAPER", "endpoint": ENDPOINT, "status": "MISSING_CREDENTIALS",
            "since": since, "until": until_text, "http_status": None,
            "event_count": 0, "crypto_trade_event_count": 0,
        }

    if request_get is None:
        import requests
        request_get = requests.get

    response = None
    try:
        response = request_get(
            ENDPOINT,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "Accept": "text/event-stream",
            },
            params={"since": since_dt.isoformat().replace("+00:00", "Z"),
                    "until": until_dt.isoformat().replace("+00:00", "Z")},
            stream=True,
            timeout=(10, 45),
        )
        status_code = int(getattr(response, "status_code", 0))
        if status_code != 200:
            return {
                "mode": "PAPER", "endpoint": ENDPOINT,
                "status": "UNAVAILABLE" if status_code in {401, 403, 404, 405} else "HTTP_ERROR",
                "since": since_dt.isoformat().replace("+00:00", "Z"),
                "until": until_dt.isoformat().replace("+00:00", "Z"),
                "http_status": status_code, "event_count": 0,
                "crypto_trade_event_count": 0,
            }
        events, comments, invalid_frames = parse_sse_lines(response.iter_lines(decode_unicode=True))
        return summarize_events(
            events, comments, invalid_frames,
            since=since_dt.isoformat().replace("+00:00", "Z"),
            until=until_dt.isoformat().replace("+00:00", "Z"),
            http_status=status_code,
        )
    except Exception as exc:
        return {
            "mode": "PAPER", "endpoint": ENDPOINT, "status": "ERROR",
            "since": since_dt.isoformat().replace("+00:00", "Z"),
            "until": until_dt.isoformat().replace("+00:00", "Z"),
            "http_status": None, "error_type": type(exc).__name__,
            "event_count": 0, "crypto_trade_event_count": 0,
        }
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=os.getenv("ACTIVITY_SSE_SINCE"))
    parser.add_argument("--until", default=os.getenv("ACTIVITY_SSE_UNTIL"))
    parser.add_argument("--output", default=os.getenv(
        "ACTIVITY_SSE_REPORT", "paper-activity-sse-probe.json"
    ))
    args = parser.parse_args()
    if not args.since:
        parser.error("--since or ACTIVITY_SSE_SINCE is required")

    report = run_probe(
        api_key=os.getenv("ALPACA_API_KEY", ""),
        api_secret=os.getenv("ALPACA_SECRET_KEY", ""),
        since=args.since,
        until=args.until,
    )
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        key: report.get(key) for key in (
            "mode", "status", "http_status", "since", "until", "event_count",
            "crypto_trade_event_count", "trade_correction_event_count",
            "trade_bust_event_count", "previous_id_event_count",
            "activity_type_counts", "trade_execution_type_counts",
            "fee_activity_counts", "dropped_message_comment_count",
        ) if key in report
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
