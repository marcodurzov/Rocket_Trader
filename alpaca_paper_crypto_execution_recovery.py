#!/usr/bin/env python3
"""Recover and close only the prior capped Paper smoke-test order; never open a new position."""
from __future__ import annotations
import os
import sys
import tempfile
import time
from decimal import Decimal
from rocket_trader_core import Side
from rocket_trader_crypto_paper_execution import (
    AlpacaCryptoPaperExecutionAdapter, CryptoOrderIntent, normalize_crypto_symbol,
)

BUY_ID = "rt-smoke-42887047943-buy"
SELL_ID = "rt-smoke-42887047943-sell"
SYMBOL = "BTC/USD"
TERMINAL = {"filled", "canceled", "cancelled", "expired", "rejected", "done_for_day"}


def val(obj, name, default=None):
    x = getattr(obj, name, default)
    return x.value if hasattr(x, "value") else x


def order_state(adapter, client_id):
    return adapter.reconcile(client_id)


def settle(adapter, client, client_id, snapshot):
    state = str(snapshot.get("status", "unknown")).lower()
    for _ in range(5):
        if state in TERMINAL:
            return snapshot
        time.sleep(1)
        snapshot = order_state(adapter, client_id)
        if not snapshot.get("found"):
            raise RuntimeError(f"Order {client_id} disappeared during reconciliation.")
        state = str(snapshot.get("status", "unknown")).lower()
    if state not in TERMINAL:
        order_id = snapshot.get("order_id")
        if not order_id:
            raise RuntimeError(f"Order {client_id} remains {state} without a broker order ID.")
        try:
            client.cancel_order_by_id(order_id)
        except Exception:
            # A fill/cancel race is resolved by re-reading the broker state below.
            pass
        for _ in range(5):
            time.sleep(1)
            snapshot = order_state(adapter, client_id)
            if not snapshot.get("found"):
                raise RuntimeError(f"Order {client_id} missing after cancel attempt.")
            state = str(snapshot.get("status", "unknown")).lower()
            if state in TERMINAL:
                return snapshot
        raise RuntimeError(f"Order {client_id} did not reach a terminal state after cancellation.")
    return snapshot


def held_btc(client):
    for p in client.get_all_positions():
        raw = str(val(p, "symbol", "")).upper()
        try:
            symbol = normalize_crypto_symbol(raw)
        except Exception:
            continue
        if symbol == SYMBOL:
            return Decimal(str(val(p, "qty", "0")))
    return Decimal("0")


def main() -> int:
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: ALPACA_PAPER must be exactly true.")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError("Safety stop: LIVE mode is prohibited.")
    if os.getenv("ROCKET_TRADER_PAPER_SMOKE_RECOVERY", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: recovery action is not enabled.")
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Alpaca Paper credentials are missing.")
    from alpaca.trading.client import TradingClient
    client = TradingClient(key, secret, paper=True)
    with tempfile.TemporaryDirectory(prefix="rocket-paper-recovery-") as tmp:
        adapter = AlpacaCryptoPaperExecutionAdapter(
            api_key=key, api_secret=secret,
            db_path=os.path.join(tmp, "recovery.sqlite3"), client=client,
        )
        adapter.verify_account()
        buy = order_state(adapter, BUY_ID)
        print(f"environment=PAPER")
        print(f"buy_order_found={buy.get('found')}")
        if not buy.get("found"):
            held = held_btc(client)
            print(f"held_btc_qty={held}")
            if held != 0:
                raise RuntimeError("BTC position exists but the prior smoke order cannot be reconciled; no sell submitted.")
            print("result=NO_ORDER_NO_POSITION")
            return 0

        buy = settle(adapter, client, BUY_ID, buy)
        filled = Decimal(str(buy.get("filled_qty") or "0"))
        held = held_btc(client)
        print(f"buy_status={buy.get('status')}")
        print(f"buy_filled_qty={filled}")
        print(f"held_btc_qty={held}")
        if filled == 0:
            if held != 0:
                raise RuntimeError("Broker shows BTC inventory without a matching buy fill; manual review required.")
            print("result=BUY_CANCELLED_OR_UNFILLED_NO_POSITION")
            return 0
        if held <= 0:
            raise RuntimeError("Buy fill exists but no net BTC inventory is available to close.")
        if held > filled:
            raise RuntimeError(
                f"Broker BTC position {held} exceeds the smoke buy fill {filled}; refusing to sell unrelated inventory."
            )
        # Sell the broker-confirmed net quantity, not the gross buy fill.
        # Alpaca crypto fees may be deducted in base asset, so these values differ.
        sell_quantity = held
        print(f"net_quantity_delta_for_fees_or_adjustments={filled - held}")
        sell = order_state(adapter, SELL_ID)
        if not sell.get("found"):
            sell = adapter.submit(CryptoOrderIntent(
                client_order_id=SELL_ID, symbol=SYMBOL, side=Side.SELL, quantity=sell_quantity,
            ))
        sell = settle(adapter, client, SELL_ID, sell)
        residual = held_btc(client)
        print(f"sell_status={sell.get('status')}")
        print(f"sell_filled_qty={sell.get('filled_qty')}")
        print(f"residual_btc_qty={residual}")
        if residual != 0:
            print("result=MANUAL_REVIEW_REQUIRED")
            return 2
        print("result=PRIOR_SMOKE_ORDER_RECONCILED_AND_CLOSED")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("environment=PAPER")
        print("new_buy_orders_submitted=0")
        print(f"recovery_error={type(exc).__name__}: {exc}")
        raise
