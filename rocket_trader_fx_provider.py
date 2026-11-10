#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict USD/MXN reference quote provider using exchangerate.dev.

The provider consumes the response's per-currency effective_at timestamp,
not the request time. The service documents free quotes as 15-minute delayed
and indicative (not settlement rates); stale, future, or unavailable quotes
are rejected. No fallback rate is ever substituted.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional

from rocket_trader_realized_pnl_ledger import LedgerFX


class FXProviderError(RuntimeError):
    """Missing, stale, invalid, or unsupported USD/MXN quote."""


def _aware(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise FXProviderError(f"{field} timestamp is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise FXProviderError(f"{field} timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FXProviderError("USD/MXN rate is not a valid decimal") from exc
    if not result.is_finite() or result <= 0:
        raise FXProviderError("USD/MXN rate must be finite and positive")
    return result


class ExchangerateDevFXProvider:
    """Fetch and validate the last available USD/MXN indicative quote."""

    URL = "https://api.exchangerate.dev/v1/latest/USD?symbols=MXN"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        max_age: timedelta = timedelta(minutes=45),
        cache_seconds: int = 900,
        timeout_seconds: int = 8,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if max_age.total_seconds() <= 0 or cache_seconds < 0 or timeout_seconds <= 0:
            raise FXProviderError("Invalid FX provider timing configuration")
        self.api_key = api_key or os.getenv("EXCHANGERATE_DEV_API_KEY")
        self.max_age = max_age
        self.cache_seconds = cache_seconds
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self._lock = threading.RLock()
        self._cached_payload: Optional[Dict[str, Any]] = None
        self._cached_at: Optional[datetime] = None

    def _fetch(self, now: datetime) -> Dict[str, Any]:
        if (
            self._cached_payload is not None
            and self._cached_at is not None
            and (now - self._cached_at).total_seconds() <= self.cache_seconds
        ):
            return self._cached_payload

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.URL, headers=headers)
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise FXProviderError(f"FX provider returned HTTP {status}")
                payload = json.loads(response.read().decode("utf-8"), parse_float=Decimal)
        except FXProviderError:
            raise
        except Exception as exc:
            raise FXProviderError("Could not retrieve USD/MXN reference quote") from exc
        if not isinstance(payload, dict) or payload.get("result") != "success":
            raise FXProviderError("FX provider response is unsuccessful or malformed")
        self._cached_payload = payload
        self._cached_at = now
        return payload

    def quote_for_fill(
        self,
        fill_time: datetime,
        *,
        now: Optional[datetime] = None,
    ) -> LedgerFX:
        fill = _aware(fill_time, "fill_time")
        current = _aware(now or datetime.now(timezone.utc), "now")
        if current < fill:
            raise FXProviderError("Reference clock cannot precede the fill timestamp")
        with self._lock:
            payload = self._fetch(current)

        if str(payload.get("base", "")).upper() != "USD":
            raise FXProviderError("FX provider returned a non-USD base currency")
        rates = payload.get("rates") or {}
        rate = rates.get("MXN")
        effective_map = payload.get("effective_at") or {}
        effective_at = effective_map.get("MXN")
        stale_map = payload.get("stale") or {}
        if stale_map.get("MXN") is True:
            raise FXProviderError("USD/MXN provider quote is marked stale")
        if effective_at is None:
            raise FXProviderError("USD/MXN quote lacks an effective_at timestamp")

        observed_at = _aware(effective_at, "effective_at")
        if observed_at > fill:
            raise FXProviderError("USD/MXN quote is newer than the fill; look-ahead is blocked")
        age = fill - observed_at
        if age > self.max_age:
            raise FXProviderError(
                f"USD/MXN quote is stale for this fill ({age.total_seconds():.0f}s)"
            )
        source_kind = str((payload.get("sources") or {}).get("MXN") or payload.get("source") or "unknown")
        market_session = str(payload.get("market_session") or "unknown")
        source = (
            f"exchangerate.dev:{source_kind}:indicative_not_settlement:"
            f"market_session={market_session}"
        )
        return LedgerFX(_decimal(rate), observed_at, source)
