#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent, fail-closed portfolio drawdown guard.

Stores a high-water mark and sticky lock in durable JSON state. It never
unlocks automatically: an operator must review the incident and perform an
explicit, audited reset using a separate procedure (not implemented here).
"""
from __future__ import annotations
import json, math, os, tempfile, threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

class DrawdownGuardError(RuntimeError):
    """Invalid or unavailable drawdown protection state."""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class DrawdownAssessment:
    allowed: bool
    locked: bool
    reason: Optional[str]
    equity: float
    high_water_mark: float
    drawdown_pct: float
    max_drawdown_pct: float
    updated_at: str

class PersistentDrawdownGuard:
    """Track equity peaks and persist a sticky max-drawdown lock.

    max_drawdown_pct is a fraction (0.15 means 15%). Evaluate before every
    new entry. This guard does not liquidate positions; it blocks new risk
    while exits and reconciliation remain available.
    """
    SCHEMA_VERSION = 1

    def __init__(self, state_path: str, max_drawdown_pct: float = 0.15) -> None:
        if not state_path:
            raise DrawdownGuardError("A durable drawdown state_path is required.")
        if not math.isfinite(max_drawdown_pct) or not 0 < max_drawdown_pct < 1:
            raise DrawdownGuardError("max_drawdown_pct must be finite and between 0 and 1.")
        self.path = Path(state_path)
        self.max_drawdown_pct = float(max_drawdown_pct)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("unsupported schema_version")
            if not math.isclose(float(state["max_drawdown_pct"]), self.max_drawdown_pct, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("configured max_drawdown_pct differs from persisted state")
            high = float(state["high_water_mark"])
            if not math.isfinite(high) or high <= 0:
                raise ValueError("invalid high_water_mark")
            if not isinstance(state.get("locked"), bool):
                raise ValueError("invalid locked flag")
            if state["locked"] and not state.get("lock_reason"):
                raise ValueError("locked state has no lock_reason")
            return state
        except Exception as exc:
            raise DrawdownGuardError("Persistent drawdown state is unreadable or inconsistent; entries must remain blocked.") from exc

    def _write(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            json.loads(Path(temp_name).read_text(encoding="utf-8"))
            os.replace(temp_name, self.path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass

    def evaluate(self, equity: float) -> DrawdownAssessment:
        try:
            current = float(equity)
        except (TypeError, ValueError) as exc:
            raise DrawdownGuardError("equity must be a finite positive number.") from exc
        if not math.isfinite(current) or current <= 0:
            raise DrawdownGuardError("equity must be a finite positive number.")
        with self._lock:
            state = self._read()
            timestamp = _now()
            if state is None:
                state = {
                    "schema_version": self.SCHEMA_VERSION,
                    "max_drawdown_pct": self.max_drawdown_pct,
                    "high_water_mark": current,
                    "current_equity": current,
                    "drawdown_pct": 0.0,
                    "locked": False,
                    "lock_reason": None,
                    "locked_at": None,
                    "updated_at": timestamp,
                }
            else:
                high = float(state["high_water_mark"])
                locked = bool(state["locked"])
                high = max(high, current)
                drawdown = max(0.0, (high - current) / high)
                if not locked and drawdown >= self.max_drawdown_pct:
                    locked = True
                    state["lock_reason"] = "MAX_DRAWDOWN_LIMIT_REACHED"
                    state["locked_at"] = timestamp
                state.update({
                    "high_water_mark": high,
                    "current_equity": current,
                    "drawdown_pct": drawdown,
                    "locked": locked,
                    "updated_at": timestamp,
                })
            self._write(state)
            high = float(state["high_water_mark"])
            drawdown = max(0.0, (high - current) / high)
            locked = bool(state["locked"])
            return DrawdownAssessment(
                allowed=not locked, locked=locked, reason=state.get("lock_reason"),
                equity=current, high_water_mark=high, drawdown_pct=drawdown,
                max_drawdown_pct=self.max_drawdown_pct, updated_at=str(state["updated_at"]),
            )

    def status(self) -> Dict[str, Any]:
        """Read-only status; missing state is an error to prevent false green."""
        with self._lock:
            state = self._read()
            if state is None:
                raise DrawdownGuardError("Drawdown guard has not been initialized.")
            return dict(state)
