#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Online SQLite backup and restore verification for the Paper Observer volume.

backup:        copy every *.sqlite3 under --source using SQLite's online backup
               API (consistent while writers run), run integrity_check on each
               copy and write a SHA-256 manifest. Non-SQLite files (e.g. the
               genesis attestation) are copied as-is. Source files are only read.
restore-test:  copy a backup into an EMPTY target directory, re-verify hashes
               and integrity, and run the runtime's own read-only preflight
               validators on the restored accounting databases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "manifest.json"
ACCOUNTING = {
    "ledger": "rocket_trader_ledger.sqlite3",
    "fill_inbox": "rocket_trader_fill_inbox.sqlite3",
    "activity_stager": "rocket_trader_activity_stager.sqlite3",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity(path: Path) -> str:
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as conn:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def backup(source: Path, dest: Path) -> dict:
    if not source.is_dir():
        raise SystemExit(f"Source {source} is not a directory.")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise SystemExit(f"Destination {dest} is not empty; refusing to overwrite a backup.")
    files = {}
    for src in sorted(source.iterdir()):
        if not src.is_file() or src.name.endswith(("-wal", "-shm", "-journal")):
            continue
        out = dest / src.name
        if src.suffix == ".sqlite3":
            with sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True, timeout=30) as s, \
                    sqlite3.connect(str(out)) as d:
                s.backup(d)
            # Self-contained single-file copy: no -wal sidecar can hide changes.
            with sqlite3.connect(str(out)) as d:
                mode = d.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(mode).lower() != "delete":
                raise SystemExit(f"Could not convert backup of {src.name} to rollback-journal mode.")
            status = _integrity(out)
            if status != "ok":
                raise SystemExit(f"Integrity check failed for backup copy of {src.name}: {status}")
        else:
            shutil.copy2(src, out)
            status = "copied"
        files[src.name] = {"sha256": _sha256(out), "bytes": out.stat().st_size, "integrity": status}
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "files": files}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "file_count": len(files),
            "sqlite_files": sorted(k for k in files if k.endswith(".sqlite3"))}


def restore_test(backup_dir: Path, target: Path) -> dict:
    manifest = json.loads((backup_dir / MANIFEST).read_text(encoding="utf-8"))
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Restore target must be empty.")
    target.mkdir(parents=True, exist_ok=True)
    for name, meta in manifest["files"].items():
        src = backup_dir / name
        if _sha256(src) != meta["sha256"]:
            raise SystemExit(f"Hash mismatch in backup for {name}.")
        shutil.copy2(src, target / name)
        if name.endswith(".sqlite3") and _integrity(target / name) != "ok":
            raise SystemExit(f"Restored {name} failed integrity_check.")
    checks = {}
    if all((target / f).exists() for f in ACCOUNTING.values()):
        for candidate in ("/app", str(Path(__file__).resolve().parent.parent)):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
        from rocket_trader_cash_activity_admin import _require_existing_state
        from rocket_trader_stream_runtime import _require_existing_activity_stager, _require_existing_fill_bridge
        _require_existing_state(str(target / ACCOUNTING["ledger"]), str(target / ACCOUNTING["activity_stager"]))
        _require_existing_fill_bridge(str(target / ACCOUNTING["fill_inbox"]))
        _require_existing_activity_stager(str(target / ACCOUNTING["activity_stager"]))
        checks["runtime_preflight"] = "passed"
    else:
        checks["runtime_preflight"] = "skipped_no_accounting_databases"
    return {"ok": True, "restored_files": len(manifest["files"]), **checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--source", required=True)
    b.add_argument("--dest", required=True)
    r = sub.add_parser("restore-test")
    r.add_argument("--backup", required=True)
    r.add_argument("--target", required=True)
    args = parser.parse_args()
    if args.cmd == "backup":
        result = backup(Path(args.source), Path(args.dest))
    else:
        result = restore_test(Path(args.backup), Path(args.target))
    print("ROCKET_TRADER_BACKUP " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
