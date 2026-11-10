#!/usr/bin/env python3
"""One-cycle, USD 10 maximum Alpaca Paper crypto execution smoke test.

This is a mechanical adapter test, not a strategy or profitability test.
It buys a small BTC/USD notional, then immediately sells only the filled quantity.
If an exit leaves residual inventory, it stops and reports manual review; it
never increases the order size or retries an uncertain order.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from decimal import Decimal

from rocket_trader_core import Side
from rocket_trader_crypto_paper_execution import (
    AlpacaCryptoPaperExecutionAdapter,
    CryptoOrderIntent,
)

SYMBOL = "BTC/USD"
MAX_NOTIONAL_USD = Decimal("10.00")


def field(obj, name, default=None):
    value = getattr(obj, name, default)
    return value.value if hasattr(value, "value") else value


def main() -> int:
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: ALPACA_PAPER must be exactly true.")
    if os.getenv("ALPACA_LIVE_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError("Safety stop: LIVE mode is prohibited.")
    if os.getenv("ROCKET_TRADER_PAPER_SMOKE_ALLOW_ORDERS", "").strip().lower() != "true":
        raise RuntimeError("Safety stop: Paper smoke orders are not explicitly enabled.")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    client_id = f"rt-smoke-{run_id}"
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("Alpaca Paper credentials are missing.")

    from alpaca.trading.client import TradingClient
    client = TradingClient(key, secret, paper=True)

    # Never add another test entry if a previous run left BTC inventory behind.
    for position in client.get_all_positions():
        if str(field(position, "symbol", "")).upper() == SYMBOL:
            qty = Decimal(str(field(position, "qty", "0")))
            if qty > 0:
                raise RuntimeError(
                    f"Refusing new smoke entry: existing {SYMBOL} position qty={qty} requires reconciliation."
                )

    with tempfile.TemporaryDirectory(prefix="rocket-paper-smoke-") as tmp:
        adapter = AlpacaCryptoPaperExecutionAdapter(
            api_key=key,
            api_secret=secret,
            db_path=os.path.join(tmp, "crypto-smoke.sqlite3"),
            client=client,
        )
        account = adapter.verify_account()
        available_cash = min(
            Decimal(account["cash"]),
            Decimal(account["non_marginable_buying_power"]),
        )
        if available_cash < MAX_NOTIONAL_USD * Decimal("1.02"):
            raise RuntimeError("Paper cash is insufficient for the capped smoke order.")

        buy = adapter.submit(CryptoOrderIntent(
            client_order_id=f"{client_id}-buy",
            symbol=SYMBOL,
            side=Side.BUY,
            notional_usd=str(MAX_NOTIONAL_USD),
        ))
        bought_qty = Decimal(str(buy.get("filled_qty") or "0"))
        print("environment=PAPER")
        print(f"symbol={SYMBOL}")
        print(f"max_buy_notional_usd={MAX_NOTIONAL_USD}")
        print(f"buy_status={buy.get('status')}")
        print(f"buy_filled_qty={bought_qty}")
        print(f"buy_filled_avg_price={buy.get('filled_avg_price')}")
        print("orders_submitted=1")

        if bought_qty <= 0:
            print("exit_order_submitted=0")
            print("result=NO_FILL_NO_POSITION_CREATED")
            return 0

        sell = adapter.submit(CryptoOrderIntent(
            client_order_id=f"{client_id}-sell",
            symbol=SYMBOL,
            side=Side.SELL,
            quantity=bought_qty,
        ))
        print(f"sell_status={sell.get('status')}")
        print(f"sell_filled_qty={sell.get('filled_qty')}")
        print("exit_order_submitted=1")

        residual = Decimal("0")
        for _ in range(3):
            time.sleep(1)
            for position in client.get_all_positions():
                if str(field(position, "symbol", "")).upper() == SYMBOL:
                    residual = Decimal(str(field(position, "qty", "0")))
                    break
            if residual == 0:
                break

        print(f"residual_btc_qty={residual}")
        print("orders_submitted=2")
        if residual != 0:
            print("result=MANUAL_REVIEW_REQUIRED")
            return 2
        print("result=BUY_AND_EXIT_RECONCILED")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("environment=PAPER")
        print("live_orders_submitted=0")
        print(f"smoke_error={type(exc).__name__}: {exc}")
        raise
