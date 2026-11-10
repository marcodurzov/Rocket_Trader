#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper-account fee resolution from Alpaca Account Activities.

The resolver never estimates fees from a published tier. It requires actual
execution-linked fee activities, except for equity BUYs where the broker's
commission-free schedule explicitly yields zero per-trade commission. Unlinked
daily regulatory fees are not guessed or spread across fills.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional


class AlpacaFeeResolutionError(RuntimeError):
    """Fee data is unavailable, ambiguous, or inconsistent."""


class AlpacaFeeNotAvailable(AlpacaFeeResolutionError):
    """The broker has not yet posted a fee activity for this execution."""


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    return value.value if hasattr(value, "value") else value


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaFeeResolutionError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise AlpacaFeeResolutionError(f"{field} must be finite")
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise AlpacaFeeResolutionError("Fill timestamp is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise AlpacaFeeResolutionError("Fill timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


class AlpacaPaperActivitiesClient:
    """Read-only REST client for Paper Account Activities fee records."""

    BASE_URL = "https://paper-api.alpaca.markets/v2/account/activities"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        *,
        timeout_seconds: int = 10,
        cache_seconds: int = 900,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        if not self.api_key or not self.secret_key:
            raise AlpacaFeeResolutionError("Alpaca Paper API credentials are required")
        if timeout_seconds <= 0 or cache_seconds < 0:
            raise AlpacaFeeResolutionError("Invalid fee activity client timing configuration")
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self.opener = opener
        self._cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_lock = threading.RLock()

    def list_fee_activities(self, fill_time: datetime) -> List[Dict[str, Any]]:
        fill_time = _timestamp(fill_time)
        cache_key = fill_time.date().isoformat()
        now_monotonic = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and now_monotonic - cached[0] <= self.cache_seconds:
                return list(cached[1])
        day_start = datetime.combine(fill_time.date(), datetime.min.time(), tzinfo=timezone.utc)
        after = (day_start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = (day_start + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        token = None
        output: List[Dict[str, Any]] = []
        seen_tokens = set()
        while True:
            params = {
                "activity_types": "CFEE,FEE",
                "after": after,
                "until": until,
                "direction": "asc",
                "page_size": "100",
            }
            if token:
                params["page_token"] = token
            url = self.BASE_URL + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(url, headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key,
                "Accept": "application/json",
            })
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    status = getattr(response, "status", 200)
                    if status != 200:
                        raise AlpacaFeeResolutionError(
                            f"Alpaca Paper activities returned HTTP {status}"
                        )
                    page = json.loads(response.read().decode("utf-8"))
            except AlpacaFeeResolutionError:
                raise
            except Exception as exc:
                raise AlpacaFeeResolutionError(
                    "Could not retrieve Alpaca Paper fee activities"
                ) from exc
            if not isinstance(page, list):
                raise AlpacaFeeResolutionError("Alpaca fee activities response is not a list")
            output.extend(row for row in page if isinstance(row, dict))
            if len(page) < 100:
                break
            next_token = str(page[-1].get("id") or "")
            if not next_token or next_token in seen_tokens:
                raise AlpacaFeeResolutionError("Fee activity pagination cursor did not advance")
            seen_tokens.add(next_token)
            token = next_token
        with self._cache_lock:
            self._cache[cache_key] = (time.monotonic(), list(output))
        return output


class AlpacaActivityFeeResolver:
    """Resolve actual fees for one fill using exact execution linkage."""

    def __init__(
        self,
        activities_fetcher: Callable[[datetime], Iterable[Dict[str, Any]]],
    ) -> None:
        if not callable(activities_fetcher):
            raise AlpacaFeeResolutionError("activities_fetcher must be callable")
        self.activities_fetcher = activities_fetcher

    @staticmethod
    def _matches(activity: Dict[str, Any], execution_id: str) -> bool:
        details = activity.get("details") or {}
        candidates = [
            activity.get("execution_id"),
            activity.get("parent_id"),
            details.get("execution_id"),
            details.get("parent_id"),
        ]
        activity_id = str(activity.get("id") or activity.get("ref_id") or "")
        if "::" in activity_id:
            candidates.append(activity_id.rsplit("::", 1)[-1])
        return any(str(candidate or "") == execution_id for candidate in candidates)

    def __call__(self, fill: Dict[str, Any]) -> Dict[str, Any]:
        execution_id = str(fill.get("execution_id") or "").strip()
        if not execution_id:
            raise AlpacaFeeResolutionError("Fill requires execution_id for fee matching")
        fill_time = _timestamp(fill.get("timestamp"))
        side = str(fill.get("side") or _value(fill.get("order") or {}, "side", "")).upper()
        symbol = str(fill.get("symbol") or _value(fill.get("order") or {}, "symbol", "")).upper()
        is_crypto = "/" in symbol
        if side not in {"BUY", "SELL"} or not symbol:
            raise AlpacaFeeResolutionError("Fill requires symbol and BUY/SELL side")

        activities = list(self.activities_fetcher(fill_time))
        matches = []
        seen = set()
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            activity_type = str(activity.get("activity_type") or "").upper()
            if activity_type not in {"CFEE", "FEE"} or not self._matches(activity, execution_id):
                continue
            activity_id = str(activity.get("id") or activity.get("ref_id") or "")
            if activity_id and activity_id in seen:
                continue
            if activity_id:
                seen.add(activity_id)
            if str(activity.get("status") or "executed").lower() != "executed":
                continue
            matches.append(activity)

        if not matches:
            if not is_crypto and side == "BUY":
                return {
                    "fee_usd": "0",
                    "fee_asset_qty": "0",
                    "fee_source": "Alpaca commission-free US equity BUY; no linked fee activity",
                }
            raise AlpacaFeeNotAvailable(
                f"No execution-linked Alpaca fee activity is posted yet for {execution_id}; "
                "fill remains pending. Unlinked daily regulatory fees require separate allocation."
            )

        fee_usd = Decimal("0")
        fee_asset_qty = Decimal("0")
        source_ids = []
        for activity in matches:
            activity_type = str(activity.get("activity_type") or "").upper()
            amount = _decimal(activity.get("net_amount", "0"), "fee net_amount")
            if amount > 0:
                raise AlpacaFeeResolutionError(
                    "Positive fee activity is a credit/reversal and requires correction handling"
                )
            if activity_type == "FEE":
                currency = str(activity.get("currency") or "USD").upper()
                if currency != "USD":
                    raise AlpacaFeeResolutionError("Only USD-denominated FEE activities are supported")
                fee_usd += abs(amount)
            else:
                qty = _decimal(activity.get("qty", "0"), "CFEE qty")
                price = _decimal(activity.get("price", "0"), "CFEE price")
                if side == "BUY" and qty < 0 and price > 0:
                    # Alpaca charges crypto BUY fees in the credited base asset.
                    fee_asset_qty += qty
                    fee_usd += abs(qty) * price
                elif side == "SELL" and amount < 0:
                    # For USD-quoted crypto SELLs, the credited asset is USD.
                    fee_usd += abs(amount)
                else:
                    raise AlpacaFeeResolutionError(
                        "CFEE denomination cannot be safely mapped to this fill"
                    )
            source_ids.append(activity_id or "activity-without-id")

        return {
            "fee_usd": str(fee_usd),
            "fee_asset_qty": str(fee_asset_qty),
            "fee_source": "Alpaca Paper Account Activities: " + ",".join(source_ids),
        }
