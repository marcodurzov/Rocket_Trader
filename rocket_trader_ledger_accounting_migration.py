#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicitly migrate a legacy realized-P&L ledger to FX-aware MXN FIFO."""

import argparse
import json

from rocket_trader_realized_pnl_ledger import RealizedPnLLedger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--backup-path", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument(
        "--no-writers-confirmed",
        action="store_true",
        help="Confirm all runtime processes using this ledger have been stopped.",
    )
    args = parser.parse_args()
    result = RealizedPnLLedger.migrate_legacy_accounting_method(
        args.db_path,
        backup_path=args.backup_path,
        confirm=args.confirm,
        no_writers_confirmed=args.no_writers_confirmed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
