#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit, one-time genesis of Paper accounting state on a fresh volume.

Why this exists
---------------
The Paper Observer refuses to start without existing accounting databases and
must never create empty replacements silently. A brand-new host therefore needs
one explicit, audited way to create them. This command is that way.

Safety contract
---------------
* Paper only: requires ``ALPACA_PAPER=true`` and ``ALPACA_LIVE_ENABLED=false``.
* Read-only broker calls: ``get_account``, ``get_all_positions`` and
  ``get_orders``. It never submits, replaces or cancels an order.
* Refuses unless ``--genesis-confirmed`` is given.
* Refuses if any target database (or its ``-wal``/``-shm`` sidecar) exists.
  It cannot overwrite, repair or "reset" existing state.
* Refuses unless the Paper account is flat: no open positions, no open orders
  and no fill in the last ``--quiet-hours`` (default 48 h, so delayed crypto
  fees for earlier fills have posted). Earlier simulator activity (smoke tests)
  is not strategy activity and stays outside the MXN strategy ledger.
* The realized-P&L ledger starts with the configured seed capital (MXN 1,000 by
  default) and the configured MXN 100,000 milestone, the user's policy.
* Writes an attestation JSON with the genesis timestamp. Set
  ``ACTIVITY_SSE_BOOTSTRAP_SINCE`` to that timestamp so the Activity SSE inbox
  starts exactly at genesis.

The cash ledger anchor is created separately with
``rocket_trader_paper_cash_ledger_admin.py --initialize-db`` after genesis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rocket_trader_env import env_bool

DEFAULT_QUIET_HOURS = 48
ATTESTATION_NAME = "rocket_trader_genesis_attestation.json"


class GenesisError(RuntimeError):
    """Genesis refused; nothing was created."""


def _status(value: Any) -> str:
    value = getattr(value, "value", value)
    return str(value or "").strip().upper()


def _default_paths(data_dir: Path) -> Dict[str, Path]:
    return {
        "ledger": Path(os.getenv("ROCKET_TRADER_LEDGER_DB", str(data_dir / "rocket_trader_ledger.sqlite3"))),
        "fill_inbox": Path(os.getenv("ROCKET_TRADER_LEDGER_INBOX_DB", str(data_dir / "rocket_trader_fill_inbox.sqlite3"))),
        "activity_stager": Path(os.getenv("ROCKET_TRADER_ACTIVITY_STAGER_DB", str(data_dir / "rocket_trader_activity_stager.sqlite3"))),
    }


def require_paper_only() -> None:
    try:
        paper = env_bool("ALPACA_PAPER", default=False)
        live = env_bool("ALPACA_LIVE_ENABLED", default=False)
    except ValueError as exc:
        raise GenesisError("Invalid ALPACA_PAPER/ALPACA_LIVE_ENABLED boolean.") from exc
    if not paper or live:
        raise GenesisError("Genesis requires ALPACA_PAPER=true and ALPACA_LIVE_ENABLED=false.")
    if os.getenv("ROCKET_TRADER_EXECUTION_MODE", "PAPER").strip().upper() != "PAPER":
        raise GenesisError("ROCKET_TRADER_EXECUTION_MODE must be PAPER.")


def require_absent(paths: Dict[str, Path], attestation: Path) -> None:
    resolved = [p.expanduser().resolve() for p in paths.values()]
    if len(set(resolved)) != len(resolved):
        raise GenesisError("Ledger, fill inbox and activity stager must be separate files.")
    existing = []
    for p in resolved + [attestation.expanduser().resolve()]:
        for candidate in (p, Path(str(p) + "-wal"), Path(str(p) + "-shm")):
            if candidate.exists():
                existing.append(str(candidate))
    if existing:
        raise GenesisError(
            "Refusing genesis: accounting state already exists (" + ", ".join(existing)
            + "). Restore/inspect it instead; genesis never overwrites."
        )


def alpaca_order_filters(since: datetime):
    """Return (open_orders_filter, recently_closed_filter) for alpaca-py."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    return (GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500),
            GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since, limit=500))


def check_broker_flat(client: Any, *, now: datetime, quiet_hours: int,
                      filters_factory: Callable[[datetime], Any] = alpaca_order_filters) -> Dict[str, Any]:
    """Read-only broker checks. Raises GenesisError if the account is not flat."""
    since = now - timedelta(hours=quiet_hours)
    open_filter, closed_filter = filters_factory(since)
    account = client.get_account()
    if _status(getattr(account, "status", "")) != "ACTIVE":
        raise GenesisError("Paper account is not ACTIVE.")
    positions = list(client.get_all_positions() or [])
    if positions:
        raise GenesisError(f"Paper account has {len(positions)} open position(s); genesis requires a flat account.")
    open_orders = list(client.get_orders(filter=open_filter) or [])
    if open_orders:
        raise GenesisError(f"Paper account has {len(open_orders)} open order(s); genesis requires none.")
    recent = list(client.get_orders(filter=closed_filter) or [])
    recent_fills = [o for o in recent if getattr(o, "filled_at", None) is not None]
    if recent_fills:
        raise GenesisError(
            f"{len(recent_fills)} order(s) filled in the last {quiet_hours} h; wait until delayed fees post."
        )
    return {
        "account_status": "ACTIVE",
        "open_positions": 0,
        "open_orders": 0,
        "fills_in_quiet_window": 0,
        "quiet_window_hours": quiet_hours,
    }


def _refuse_fx(_when: datetime):
    raise GenesisError("Genesis processes no fills; FX must never be requested.")


def _refuse_fee(_fill: Dict[str, Any]):
    raise GenesisError("Genesis processes no fills; fees must never be requested.")


def create_state(paths: Dict[str, Path], *, initial_capital_mxn: str, milestone_mxn: str) -> None:
    from rocket_trader_alpaca_activity_stager import AlpacaPaperActivityStager
    from rocket_trader_paper_fill_ledger_bridge import PaperFillLedgerBridge
    from rocket_trader_realized_pnl_ledger import RealizedPnLLedger

    ledger = RealizedPnLLedger(str(paths["ledger"]), initial_capital_mxn=initial_capital_mxn,
                               milestone_mxn=milestone_mxn)
    PaperFillLedgerBridge(db_path=str(paths["fill_inbox"]), ledger=ledger,
                          fx_resolver=_refuse_fx, fee_resolver=_refuse_fee)
    # The override guarantees genesis makes no activity network request.
    AlpacaPaperActivityStager(db_path=str(paths["activity_stager"]), fetch_page=lambda _c, _s: [])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_genesis(
    *,
    data_dir: Path,
    confirmed: bool,
    client_factory: Callable[[], Any],
    now: Optional[datetime] = None,
    quiet_hours: int = DEFAULT_QUIET_HOURS,
    filters_factory: Callable[[datetime], Any] = alpaca_order_filters,
) -> Dict[str, Any]:
    if not confirmed:
        raise GenesisError("Refusing genesis without --genesis-confirmed.")
    if quiet_hours < 24:
        raise GenesisError("--quiet-hours must be at least 24.")
    require_paper_only()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paths = _default_paths(data_dir)
    attestation_path = data_dir / ATTESTATION_NAME
    require_absent(paths, attestation_path)
    broker = check_broker_flat(client_factory(), now=now, quiet_hours=quiet_hours,
                               filters_factory=filters_factory)
    # Re-check right before creation to narrow the race window.
    require_absent(paths, attestation_path)
    initial = os.getenv("ROCKET_TRADER_INITIAL_CAPITAL_MXN", "1000.00")
    milestone = os.getenv("ROCKET_TRADER_MILESTONE_MXN", "100000.00")
    create_state(paths, initial_capital_mxn=initial, milestone_mxn=milestone)
    attestation = {
        "genesis_at_utc": now.isoformat().replace("+00:00", "Z"),
        "activity_sse_bootstrap_since": now.isoformat().replace("+00:00", "Z"),
        "initial_capital_mxn": initial,
        "milestone_mxn": milestone,
        "broker_checks": broker,
        "databases": {k: {"path": str(p), "sha256_at_genesis": _sha256(p)} for k, p in paths.items()},
        "pre_genesis_activity": "Excluded from the MXN strategy ledger (simulator smoke tests, not strategy trades).",
        "orders_submitted": 0,
        "mode": "PAPER_GENESIS",
    }
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return attestation


def _client_factory() -> Any:
    from alpaca.trading.client import TradingClient
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise GenesisError("ALPACA_API_KEY/ALPACA_SECRET_KEY are not set.")
    return TradingClient(key, secret, paper=True)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--genesis-confirmed", action="store_true")
    parser.add_argument("--quiet-hours", type=int, default=DEFAULT_QUIET_HOURS)
    args = parser.parse_args(argv)
    try:
        result = run_genesis(data_dir=Path(args.data_dir), confirmed=args.genesis_confirmed,
                             client_factory=_client_factory, quiet_hours=args.quiet_hours)
    except GenesisError as exc:
        print(f"GENESIS REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nNext: set ACTIVITY_SSE_BOOTSTRAP_SINCE={result['activity_sse_bootstrap_since']} in .env, "
          "then create the cash anchor with rocket_trader_paper_cash_ledger_admin.py --initialize-db.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
