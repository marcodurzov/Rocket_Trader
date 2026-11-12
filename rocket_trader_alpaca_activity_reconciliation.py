#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Alpaca Paper account-activity reconciliation.

This module reads the Trading API account-activities endpoint. It does not
submit, replace, or cancel orders. Individual FILL activities are linked to a
specific broker order; CFEE activities are preserved as unallocated candidates
because the documented non-trade fee record does not guarantee an order_id.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


AVERAGE_PRICE_ABS_TOLERANCE = Decimal("0.00000001")


class AlpacaActivityReconciliationError(RuntimeError):
    """Incomplete, malformed, or unavailable broker activity evidence."""


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaActivityReconciliationError(f"{field} is not a valid decimal.") from exc
    if not result.is_finite():
        raise AlpacaActivityReconciliationError(f"{field} must be finite.")
    if positive and result <= 0:
        raise AlpacaActivityReconciliationError(f"{field} must be positive.")
    return result


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AlpacaActivityReconciliationError(f"{field} is missing.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlpacaActivityReconciliationError(f"{field} is not ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AlpacaActivityReconciliationError(f"{field} must include a timezone offset.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("-", "/")
    if "/" not in clean and clean.endswith("USD") and len(clean) > 3:
        clean = clean[:-3] + "/USD"
    if "/" not in clean:
        raise AlpacaActivityReconciliationError("Activity has an invalid crypto symbol.")
    base, quote = clean.split("/", 1)
    if not base or quote != "USD" or "/" in base:
        raise AlpacaActivityReconciliationError("Only BASE/USD crypto activities are supported.")
    return f"{base}/USD"


def _event_id(prefix: str, activity_id: str) -> str:
    return prefix + hashlib.sha256(activity_id.encode("utf-8")).hexdigest()


class AlpacaAccountActivityReader:
    """Paginated read-only reader for fills and crypto fee activities.

    client is an Alpaca TradingClient. Alpaca-py exposes its generic REST GET
    method through TradingClient; the endpoint is GET /v2/account/activities.
    """

    ALLOWED_ACTIVITY_TYPES = {"FILL", "CFEE"}

    def __init__(self, client: Any, event_ledger: Any, max_pages: int = 20) -> None:
        if client is None or not callable(getattr(client, "get", None)):
            raise AlpacaActivityReconciliationError("A TradingClient with read-only GET support is required.")
        if event_ledger is None or not callable(getattr(event_ledger, "append_event", None)):
            raise AlpacaActivityReconciliationError("An append-only execution event ledger is required.")
        if not isinstance(max_pages, int) or max_pages < 1 or max_pages > 100:
            raise AlpacaActivityReconciliationError("max_pages must be from 1 to 100.")
        try:
            integrity = event_ledger.verify_chain()
        except Exception as exc:
            raise AlpacaActivityReconciliationError(
                "Execution event ledger cannot be verified; activity ingestion is blocked."
            ) from exc
        if not isinstance(integrity, dict) or not integrity.get("valid"):
            raise AlpacaActivityReconciliationError(
                "Execution event ledger integrity check failed; activity ingestion is blocked."
            )
        self.client = client
        self.event_ledger = event_ledger
        self.max_pages = max_pages

    def _fetch(
        self,
        *,
        activity_types: List[str],
        order_id: Optional[str] = None,
        after: Optional[str] = None,
        until: Optional[str] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        normalized_types = [str(item).strip().upper() for item in activity_types]
        if not normalized_types or any(item not in self.ALLOWED_ACTIVITY_TYPES for item in normalized_types):
            raise AlpacaActivityReconciliationError("Only FILL and CFEE activity queries are supported.")
        if not isinstance(page_size, int) or page_size < 1 or page_size > 100:
            raise AlpacaActivityReconciliationError("page_size must be from 1 to 100.")
        if order_id is not None and (not isinstance(order_id, str) or not order_id.strip()):
            raise AlpacaActivityReconciliationError("order_id must be a non-empty string.")
        after_utc = _timestamp(after, "after") if after is not None else None
        until_utc = _timestamp(until, "until") if until is not None else None
        if after_utc and until_utc and after_utc >= until_utc:
            raise AlpacaActivityReconciliationError("after must be earlier than until.")

        base_params: Dict[str, Any] = {
            "activity_types": ",".join(normalized_types),
            "direction": "asc",
            "page_size": page_size,
        }
        if order_id is not None:
            base_params["order_id"] = order_id
        if after_utc is not None:
            base_params["after"] = after_utc
        if until_utc is not None:
            base_params["until"] = until_utc

        activities: List[Dict[str, Any]] = []
        seen_ids = set()
        seen_page_tokens = set()
        page_token = None

        for _page_number in range(self.max_pages):
            params = dict(base_params)
            if page_token is not None:
                params["page_token"] = page_token
            try:
                page = self.client.get("/account/activities", params)
            except Exception as exc:
                raise AlpacaActivityReconciliationError(
                    "Alpaca account-activity request failed; evidence is incomplete."
                ) from exc
            if not isinstance(page, list):
                raise AlpacaActivityReconciliationError("Alpaca account-activity response must be a list.")
            if not page:
                return activities

            for item in page:
                if not isinstance(item, dict):
                    raise AlpacaActivityReconciliationError("Account activity entries must be objects.")
                activity_id = item.get("id")
                if not isinstance(activity_id, str) or not activity_id.strip():
                    raise AlpacaActivityReconciliationError("Account activity is missing its immutable id.")
                if activity_id not in seen_ids:
                    activities.append(item)
                    seen_ids.add(activity_id)

            if len(page) < page_size:
                return activities

            next_token = page[-1].get("id")
            if not isinstance(next_token, str) or not next_token:
                raise AlpacaActivityReconciliationError("Full activity page has no pagination cursor.")
            if next_token == page_token or next_token in seen_page_tokens:
                raise AlpacaActivityReconciliationError("Account-activity pagination cursor repeated.")
            seen_page_tokens.add(next_token)
            page_token = next_token

        raise AlpacaActivityReconciliationError(
            "Account-activity page limit reached; result set is incomplete."
        )

    def reconcile_order_fills(
        self,
        *,
        client_order_id: str,
        broker_order_id: str,
        expected_symbol: str,
        expected_side: str,
        expected_filled_qty: Any,
        expected_filled_avg_price: Any = None,
        require_average_price: bool = False,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """Ingest individual FILL activities and compare them to the order snapshot."""
        if not isinstance(client_order_id, str) or not client_order_id.strip():
            raise AlpacaActivityReconciliationError("client_order_id is required.")
        if not isinstance(broker_order_id, str) or not broker_order_id.strip():
            raise AlpacaActivityReconciliationError("broker_order_id is required.")
        symbol = _normalize_symbol(expected_symbol)
        side = str(expected_side).strip().lower()
        if side not in {"buy", "sell"}:
            raise AlpacaActivityReconciliationError("Only buy/sell order sides are supported.")
        expected = _decimal(expected_filled_qty, "expected_filled_qty")
        if expected < 0:
            raise AlpacaActivityReconciliationError("expected_filled_qty cannot be negative.")
        if not isinstance(require_average_price, bool):
            raise AlpacaActivityReconciliationError("require_average_price must be boolean.")
        expected_avg_price = (
            None if expected_filled_avg_price in (None, "")
            else _decimal(expected_filled_avg_price, "expected_filled_avg_price", positive=True)
        )

        activities = self._fetch(
            activity_types=["FILL"], order_id=broker_order_id, page_size=page_size
        )
        fill_qty = Decimal("0")
        fill_notional = Decimal("0")
        fill_records = []
        cumulative_checks = 0
        cumulative_consistent = True

        for activity in activities:
            activity_type = str(activity.get("activity_type", "FILL")).upper()
            if activity_type != "FILL":
                raise AlpacaActivityReconciliationError("Order-specific query returned a non-FILL activity.")
            if str(activity.get("order_id", "")) != broker_order_id:
                raise AlpacaActivityReconciliationError("Fill activity order_id does not match the requested order.")
            activity_symbol = _normalize_symbol(activity.get("symbol"))
            activity_side = str(activity.get("side", "")).lower()
            if activity_symbol != symbol or activity_side != side:
                raise AlpacaActivityReconciliationError("Fill activity symbol or side conflicts with the order.")
            qty = _decimal(activity.get("qty"), "fill_qty", positive=True)
            price = _decimal(activity.get("price"), "fill_price", positive=True)
            executed_at = _timestamp(activity.get("transaction_time"), "transaction_time")
            fill_qty += qty
            fill_notional += qty * price

            raw_cum_qty = activity.get("cum_qty")
            if raw_cum_qty not in (None, ""):
                cumulative_checks += 1
                if _decimal(raw_cum_qty, "cum_qty", positive=True) != fill_qty:
                    cumulative_consistent = False

            payload = {
                "activity_id": activity["id"],
                "broker_order_id": broker_order_id,
                "symbol": symbol,
                "side": side,
                "fill_qty": str(qty),
                "fill_price": str(price),
                "fill_notional": str(qty * price),
                "transaction_time": executed_at,
                "fill_type": str(activity.get("type", "unknown")).lower(),
                "order_status": str(activity.get("order_status", "unknown")).lower(),
                "cum_qty": None if raw_cum_qty in (None, "") else str(raw_cum_qty),
                "leaves_qty": None if activity.get("leaves_qty") is None else str(activity.get("leaves_qty")),
            }
            self.event_ledger.append_event(
                event_id=_event_id("fill-", activity["id"]),
                aggregate_id=client_order_id,
                event_type="BROKER_FILL_ACTIVITY",
                payload=payload,
                occurred_at=executed_at,
            )
            fill_records.append(payload)

        activity_avg_price = fill_notional / fill_qty if fill_qty > 0 else None
        average_price_difference = (
            abs(activity_avg_price - expected_avg_price)
            if activity_avg_price is not None and expected_avg_price is not None
            else None
        )
        average_price_match = (
            average_price_difference <= AVERAGE_PRICE_ABS_TOLERANCE
            if average_price_difference is not None else None
        )

        if fill_qty == expected and cumulative_consistent:
            if require_average_price and expected > 0 and expected_avg_price is None:
                reconciliation_status = "ORDER_AVERAGE_PRICE_MISSING"
            elif expected_avg_price is not None and average_price_match is not True:
                reconciliation_status = "AVERAGE_FILL_PRICE_MISMATCH"
            else:
                reconciliation_status = "MATCHED"
        elif fill_qty < expected:
            reconciliation_status = "INCOMPLETE_ACTIVITY_HISTORY"
        elif fill_qty > expected:
            reconciliation_status = "ACTIVITY_OVERSTATES_ORDER_SNAPSHOT"
        else:
            reconciliation_status = "CUMULATIVE_FILL_SEQUENCE_MISMATCH"

        return {
            "client_order_id": client_order_id,
            "broker_order_id": broker_order_id,
            "symbol": symbol,
            "side": side,
            "expected_filled_qty": str(expected),
            "activity_filled_qty": str(fill_qty),
            "fill_notional": str(fill_notional),
            "expected_filled_avg_price": str(expected_avg_price) if expected_avg_price is not None else None,
            "activity_avg_price": str(activity_avg_price) if activity_avg_price is not None else None,
            "average_price_difference": str(average_price_difference) if average_price_difference is not None else None,
            "average_price_match": average_price_match,
            "fill_count": len(fill_records),
            "cumulative_checks": cumulative_checks,
            "cumulative_consistent": cumulative_consistent,
            "quantity_match": fill_qty == expected,
            "reconciliation_status": reconciliation_status,
            "fills": fill_records,
        }

    def collect_crypto_fee_candidates(
        self,
        *,
        symbol: str,
        after: str,
        until: str,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """Preserve account-level CFEE evidence without letting unrelated or
        malformed symbols invalidate already-reconciled order fills.

        CFEE is queried account-wide. Only records with a valid matching
        BASE/USD symbol are returned as candidates for the requested pair.
        Other and unclassifiable records are still appended to the immutable
        ledger and counted explicitly; none is attributed to an order.
        """
        normalized_symbol = _normalize_symbol(symbol)
        after_utc = _timestamp(after, "after")
        until_utc = _timestamp(until, "until")
        if after_utc >= until_utc:
            raise AlpacaActivityReconciliationError("after must be earlier than until.")

        activities = self._fetch(
            activity_types=["CFEE"], after=after_utc, until=until_utc, page_size=page_size
        )
        fee_records = []
        unclassified_records = []
        other_symbol_count = 0
        incomplete_count = 0
        out_of_window_count = 0
        window_unverified_count = 0
        for activity in activities:
            activity_type = str(activity.get("activity_type", "")).upper()
            if activity_type != "CFEE":
                raise AlpacaActivityReconciliationError("Crypto fee query returned a non-CFEE activity.")

            raw_symbol_value = activity.get("symbol")
            raw_symbol = (
                str(raw_symbol_value).strip()[:128]
                if raw_symbol_value is not None else None
            )
            activity_symbol = None
            classification = "UNCLASSIFIED_SYMBOL"
            try:
                activity_symbol = _normalize_symbol(raw_symbol_value)
                classification = (
                    "TARGET_SYMBOL" if activity_symbol == normalized_symbol
                    else "OTHER_SYMBOL"
                )
            except AlpacaActivityReconciliationError:
                pass

            raw_amount = activity.get("net_amount")
            amount = None
            try:
                amount = _decimal(raw_amount, "crypto_fee_net_amount")
            except AlpacaActivityReconciliationError:
                amount = None

            raw_currency = activity.get("currency")
            currency = (
                str(raw_currency).strip().upper()
                if isinstance(raw_currency, str) and raw_currency.strip()
                else None
            )
            created_at = activity.get("created_at")
            activity_date = activity.get("date")
            created_at_utc = None
            try:
                created_at_utc = _timestamp(created_at, "crypto_fee_created_at")
            except AlpacaActivityReconciliationError:
                pass

            occurred_at = created_at_utc
            timestamp_status = "VALID" if created_at_utc else "MISSING_OR_INVALID_TIMESTAMP"
            if occurred_at is None:
                try:
                    occurred_at = _timestamp(activity_date, "crypto_fee_activity_date")
                    timestamp_status = "VALID"
                except AlpacaActivityReconciliationError:
                    pass

            # Alpaca documents after/until as created_at filters. Enforce the
            # requested interval locally as well: account-wide backfills or
            # provider inconsistencies must not contaminate cost evidence.
            if created_at_utc is None:
                window_status = "UNVERIFIED_CREATED_AT"
                window_unverified_count += 1
            elif after_utc < created_at_utc < until_utc:
                window_status = "IN_WINDOW"
            else:
                window_status = "OUT_OF_WINDOW"
                out_of_window_count += 1

            record_is_incomplete = (
                amount is None or currency is None or timestamp_status != "VALID"
            )
            if record_is_incomplete:
                incomplete_count += 1

            record_status = "INCOMPLETE_FIELDS" if record_is_incomplete else "COMPLETE"
            payload = {
                "activity_id": activity["id"],
                "activity_type": "CFEE",
                "symbol": activity_symbol,
                "raw_symbol": raw_symbol,
                "symbol_classification": classification,
                "net_amount": str(amount) if amount is not None else (
                    str(raw_amount)[:128] if raw_amount is not None else None
                ),
                "currency": currency,
                "qty": None if activity.get("qty") is None else str(activity.get("qty"))[:128],
                "group_id": activity.get("group_id"),
                "created_at": created_at,
                "activity_date": activity_date,
                "record_status": record_status,
                "timestamp_status": timestamp_status,
                "window_status": window_status,
                "allocation_status": "UNALLOCATED",
            }
            if window_status == "OUT_OF_WINDOW":
                event_type = "CRYPTO_FEE_ACTIVITY_OUT_OF_WINDOW"
            elif window_status == "UNVERIFIED_CREATED_AT":
                event_type = "CRYPTO_FEE_ACTIVITY_WINDOW_UNVERIFIED"
            else:
                event_type = (
                    "CRYPTO_FEE_ACTIVITY_UNCLASSIFIED"
                    if activity_symbol is None
                    else "CRYPTO_FEE_ACTIVITY_UNALLOCATED"
                )
            self.event_ledger.append_event(
                event_id=_event_id("fee-", activity["id"]),
                aggregate_id="account-crypto-fees",
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            )

            # Only records whose broker creation timestamp is proven to be
            # inside the requested interval can enter interval-specific counts.
            if window_status != "IN_WINDOW":
                continue
            if classification == "TARGET_SYMBOL":
                fee_records.append(payload)
            elif classification == "OTHER_SYMBOL":
                other_symbol_count += 1
            else:
                unclassified_records.append(payload)

        return {
            "symbol": normalized_symbol,
            "after": after_utc,
            "until": until_utc,
            "fee_activity_count": len(fee_records),
            "other_symbol_activity_count": other_symbol_count,
            "unclassified_activity_count": len(unclassified_records),
            "incomplete_activity_count": incomplete_count,
            "out_of_window_activity_count": out_of_window_count,
            "window_unverified_activity_count": window_unverified_count,
            "allocation_status": "UNALLOCATED",
            "fee_activities": fee_records,
            "unclassified_fee_activities": unclassified_records,
        }
