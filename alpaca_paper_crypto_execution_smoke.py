#!/usr/bin/env python3
"""Capped $10 Alpaca Paper crypto order lifecycle smoke test; never LIVE."""
from __future__ import annotations
import os
import tempfile
import time
from decimal import Decimal
from rocket_trader_core import Side
from rocket_trader_crypto_paper_execution import (
    AlpacaCryptoPaperExecutionAdapter, CryptoOrderIntent,
)

SYMBOL = "BTC/USD"
MAX_NOTIONAL_USD = Decimal("10.00")
TERMINAL = {"filled", "canceled", "cancelled", "expired", "rejected", "done_for_day"}


def held_qty(adapter):
    for position in adapter.reconcile_positions()["positions"]:
        if position["symbol"] == SYMBOL:
            return Decimal(str(position["qty"]))
    return Decimal("0")


def settle(adapter, client, client_id, initial):
    snapshot = initial
    for _ in range(8):
        status = str(snapshot.get("status", "unknown")).lower()
        if status in TERMINAL:
            return snapshot
        time.sleep(1)
        snapshot = adapter.reconcile(client_id)
        if not snapshot.get("found"):
            raise RuntimeError(f"Order {client_id} disappeared during reconciliation.")
    status = str(snapshot.get("status", "unknown")).lower()
    if status not in TERMINAL:
        order_id = snapshot.get("order_id")
        if not order_id:
            raise RuntimeError(f"Order {client_id} remains {status} without broker order ID.")
        try:
            client.cancel_order_by_id(order_id)
        except Exception:
            # Resolve fill/cancel races by querying the broker again.
            pass
        for _ in range(8):
            time.sleep(1)
            snapshot = adapter.reconcile(client_id)
            if not snapshot.get("found"):
                raise RuntimeError(f"Order {client_id} disappeared after cancel attempt.")
            status = str(snapshot.get("status", "unknown")).lower()
            if status in TERMINAL:
                return snapshot
        raise RuntimeError(f"Order {client_id} did not reach a terminal state after cancellation.")
    return snapshot


def main() -> int:
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: ALPACA_PAPER must be exactly true.")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError("Safety stop: LIVE mode is prohibited.")
    if os.getenv("ROCKET_TRADER_PAPER_SMOKE_ALLOW_ORDERS", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: Paper smoke orders are not explicitly enabled.")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Alpaca Paper credentials are missing.")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    buy_id, sell_id = f"rt-smoke-v2-{run_id}-buy", f"rt-smoke-v2-{run_id}-sell"

    from alpaca.trading.client import TradingClient
    client = TradingClient(key, secret, paper=True)
    with tempfile.TemporaryDirectory(prefix="rocket-paper-smoke-v2-") as tmp:
        adapter = AlpacaCryptoPaperExecutionAdapter(
            api_key=key, api_secret=secret,
            db_path=os.path.join(tmp, "crypto-smoke.sqlite3"), client=client,
        )
        account = adapter.verify_account()
        cash = min(Decimal(account["cash"]), Decimal(account["non_marginable_buying_power"]))
        if cash < MAX_NOTIONAL_USD * Decimal("1.02"):
            raise RuntimeError("Insufficient cash-only buying power for the capped Paper test.")
        existing_qty = held_qty(adapter)
        if existing_qty > 0:
            raise RuntimeError(
                f"Refusing new smoke entry: existing {SYMBOL} position qty={existing_qty} needs reconciliation."
            )

        buy = adapter.submit(CryptoOrderIntent(
            client_order_id=buy_id, symbol=SYMBOL, side=Side.BUY,
            notional_usd=str(MAX_NOTIONAL_USD),
        ))
        buy = settle(adapter, client, buy_id, buy)
        gross_filled = Decimal(str(buy.get("filled_qty") or "0"))
        net_held = held_qty(adapter)
        print("environment=PAPER")
        print(f"symbol={SYMBOL}")
        print(f"max_buy_notional_usd={MAX_NOTIONAL_USD}")
        print(f"buy_status={buy.get('status')}")
        print(f"buy_gross_filled_qty={gross_filled}")
        print(f"net_position_qty={net_held}")
        print("live_orders_submitted=0")
        print("paper_buy_orders_submitted=1")

        if gross_filled <= 0:
            if net_held != 0:
                raise RuntimeError("Position exists despite zero reported buy fill; manual review required.")
            print("paper_sell_orders_submitted=0")
            print("result=NO_FILL_NO_POSITION")
            return 0

        if net_held == 0:
            prior_sell = adapter.reconcile(sell_id)
            if prior_sell.get("found") and Decimal(str(prior_sell.get("filled_qty") or "0")) > 0:
                print("paper_sell_orders_submitted=1")
                print("result=ALREADY_CLOSED_ON_RETRY")
                return 0
            raise RuntimeError("Buy fill reported but no net position is visible; refusing an ungrounded sell.")
        if net_held > gross_filled:
            raise RuntimeError("Net position exceeds this smoke buy fill; refusing to sell unrelated inventory.")

        # Fees can be charged in the base asset. Close the broker-confirmed net
        # position, not gross filled_qty, and never exceed owned quantity.
        sell = adapter.reconcile(sell_id)
        if not sell.get("found"):
            sell = adapter.submit(CryptoOrderIntent(
                client_order_id=sell_id, symbol=SYMBOL, side=Side.SELL,
                quantity=net_held,
            ))
        sell = settle(adapter, client, sell_id, sell)
        residual = Decimal("0")
        for _ in range(5):
            time.sleep(1)
            residual = held_qty(adapter)
            if residual == 0:
                break
        print(f"sell_status={sell.get('status')}")
        print(f"sell_filled_qty={sell.get('filled_qty')}")
        print(f"residual_btc_qty={residual}")
        print("paper_sell_orders_submitted=1")
        if residual != 0:
            print("result=MANUAL_REVIEW_REQUIRED")
            return 2
        print("result=BUY_AND_NET_POSITION_EXIT_RECONCILED")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("environment=PAPER")
        print("live_orders_submitted=0")
        print(f"smoke_error={type(exc).__name__}: {exc}")
        raise
