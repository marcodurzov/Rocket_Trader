#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only regime observer for the Paper market-data database.

The observer derives reproducible market features from persisted minute bars,
runs the portfolio selector with an intentionally empty candidate set, and
persists an auditable CASH/ABSTAIN decision. It cannot submit orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rocket_trader_regime_selector import (
    MarketState, RegimeAwarePortfolioSelector, StrategyCandidate,
)
from rocket_trader_news_event_assessment import NewsEventAssessmentStore

DEFAULT_UNIVERSES = {
    "EQUITY": ("SPY", "QQQ", "IWM"),
    "CRYPTO": ("BTC/USD", "ETH/USD", "SOL/USD"),
}


class RegimeObserverError(RuntimeError):
    pass


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Market bar timestamps must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        raise ValueError("Correlation requires at least three paired returns.")
    lm, rm = mean(left), mean(right)
    covariance = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    lvar = sum((a - lm) ** 2 for a in left)
    rvar = sum((b - rm) ** 2 for b in right)
    if lvar <= 0 or rvar <= 0:
        return 0.0
    return _clamp(covariance / math.sqrt(lvar * rvar), -1.0, 1.0)


class RegimeDecisionStore:
    def __init__(self, path: str) -> None:
        if not path:
            raise RegimeObserverError("A durable decision database path is required.")
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS regime_decisions (
                decision_id TEXT PRIMARY KEY,
                asset_class TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                market_timestamp TEXT,
                status TEXT NOT NULL,
                decision_json TEXT NOT NULL
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_regime_decisions_latest
                ON regime_decisions(asset_class, evaluated_at)""")

    def save(self, asset_class: str, evaluated_at: str, market_timestamp: Optional[str],
             decision: Dict[str, object]) -> bool:
        encoded = json.dumps(decision, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256((asset_class + "|" + evaluated_at + "|" + encoded).encode()).hexdigest()
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""INSERT OR IGNORE INTO regime_decisions
                (decision_id,asset_class,evaluated_at,market_timestamp,status,decision_json)
                VALUES(?,?,?,?,?,?)""",
                (digest, asset_class, evaluated_at, market_timestamp,
                 str(decision.get("status", "UNKNOWN")), encoded))
        return cursor.rowcount == 1

    def latest(self) -> List[Dict[str, object]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT asset_class,evaluated_at,market_timestamp,status,decision_json
                FROM regime_decisions d WHERE evaluated_at=(
                    SELECT MAX(evaluated_at) FROM regime_decisions x
                    WHERE x.asset_class=d.asset_class)
                ORDER BY asset_class""").fetchall()
        return [{
            "asset_class": row["asset_class"], "evaluated_at": row["evaluated_at"],
            "market_timestamp": row["market_timestamp"], "status": row["status"],
            "decision": json.loads(row["decision_json"]),
        } for row in rows]

    def health(self, max_age_seconds: int = 180) -> Dict[str, object]:
        rows = self.latest()
        now = datetime.now(timezone.utc)
        components = {}
        for row in rows:
            age = (now - _parse_time(row["evaluated_at"])).total_seconds()
            decision = row["decision"].get("decision", {})
            diagnostics = decision.get("diagnostics", {})
            if not diagnostics:
                diagnostics = decision.get("features", {})
            market_status = diagnostics.get("status", "UNKNOWN")
            market_data_ready = market_status == "FEATURES_READY"
            exposure = float(decision.get("total_exposure", 0.0) or 0.0)
            safe_cash = (
                not market_data_ready
                or bool(decision.get("abstain", False))
                or exposure <= 0.0
            )
            components[row["asset_class"]] = {
                "status": row["status"], "age_seconds": age,
                "decision_status": decision.get("status", "UNKNOWN"),
                "market_data_status": market_status,
                "market_data_ready": market_data_ready,
                "safe_cash": safe_cash,
                "total_exposure": exposure,
                "healthy": row["status"] == "EVALUATED" and 0 <= age <= max_age_seconds,
            }
        return {
            "healthy": bool(components) and all(x["healthy"] for x in components.values()),
            "market_data_ready": bool(components) and all(
                x["market_data_ready"] for x in components.values()
            ),
            "safe_cash": bool(components) and all(x["safe_cash"] for x in components.values()),
            "components": components, "orders_enabled": False,
        }


class MarketFeatureBuilder:
    """Builds cross-sectional features; insufficient or stale bars fail closed."""

    def __init__(self, market_db: str, min_bars: int = 60,
                 max_bar_age_seconds: int = 1800,
                 min_aligned_coverage: float = 0.95,
                 max_aligned_gap_seconds: int = 180) -> None:
        self.market_db = market_db
        self.min_bars = max(30, int(min_bars))
        self.max_bar_age_seconds = max(60, int(max_bar_age_seconds))
        if not 0.0 < float(min_aligned_coverage) <= 1.0:
            raise ValueError("min_aligned_coverage must be in (0, 1]")
        self.min_aligned_coverage = float(min_aligned_coverage)
        self.max_aligned_gap_seconds = max(60, int(max_aligned_gap_seconds))

    def _load(self, asset_class: str, symbols: Sequence[str]) -> Dict[str, List[Tuple[str, float]]]:
        result: Dict[str, List[Tuple[str, float]]] = {}
        with sqlite3.connect(f"file:{Path(self.market_db).resolve()}?mode=ro", uri=True) as db:
            for symbol in symbols:
                rows = db.execute("""SELECT timestamp,close FROM (
                    SELECT timestamp,close FROM market_bars
                    WHERE asset_class=? AND symbol=? ORDER BY timestamp DESC LIMIT 180
                ) ORDER BY timestamp ASC""", (asset_class, symbol)).fetchall()
                result[symbol] = [(str(ts), float(close)) for ts, close in rows]
        return result

    def build(self, asset_class: str, symbols: Sequence[str],
              now: Optional[datetime] = None) -> Tuple[Optional[MarketState], Dict[str, object]]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Feature builder clock must be timezone-aware.")
        bars = self._load(asset_class, symbols)
        counts = {symbol: len(rows) for symbol, rows in bars.items()}
        if not symbols or any(count < self.min_bars for count in counts.values()):
            return None, {"status": "INSUFFICIENT_DATA", "bar_counts": counts}

        # Normalize timestamps to UTC instants and align by timestamp, never by
        # array position. A single missing minute in one asset must not pair its
        # return with a different minute from another asset.
        timestamp_maps: Dict[str, Dict[datetime, float]] = {}
        for symbol, rows in bars.items():
            normalized: Dict[datetime, float] = {}
            for raw_timestamp, close in rows:
                timestamp = _parse_time(raw_timestamp)
                if timestamp in normalized:
                    return None, {
                        "status": "DUPLICATE_NORMALIZED_TIMESTAMPS",
                        "symbol": symbol,
                        "timestamp": timestamp.isoformat(),
                    }
                normalized[timestamp] = close
            timestamp_maps[symbol] = normalized

        latest_times = [max(values) for values in timestamp_maps.values()]
        skew = (max(latest_times) - min(latest_times)).total_seconds()
        common_timestamps = sorted(set.intersection(*(
            set(values) for values in timestamp_maps.values()
        )))
        coverage_by_symbol = {
            symbol: len(common_timestamps) / len(values)
            for symbol, values in timestamp_maps.items()
        }
        min_coverage = min(coverage_by_symbol.values(), default=0.0)
        if len(common_timestamps) < self.min_bars or min_coverage < self.min_aligned_coverage:
            return None, {
                "status": "INSUFFICIENT_ALIGNED_DATA",
                "bar_counts": counts,
                "common_aligned_bars": len(common_timestamps),
                "aligned_coverage_by_symbol": coverage_by_symbol,
                "minimum_aligned_coverage": self.min_aligned_coverage,
                "cross_symbol_skew_seconds": skew,
            }

        latest = common_timestamps[-1]
        age = (current - latest).total_seconds()
        gaps = [
            (right - left).total_seconds()
            for left, right in zip(common_timestamps, common_timestamps[1:])
        ]
        max_gap = max(gaps, default=0.0)
        if age < 0 or age > self.max_bar_age_seconds or skew > 180:
            return None, {"status": "STALE_OR_UNALIGNED_DATA", "bar_counts": counts,
                          "latest_bar_at": latest.isoformat(), "bar_age_seconds": age,
                          "cross_symbol_skew_seconds": skew,
                          "common_aligned_bars": len(common_timestamps),
                          "aligned_coverage_by_symbol": coverage_by_symbol}
        if max_gap > self.max_aligned_gap_seconds:
            return None, {
                "status": "ALIGNED_SERIES_GAP",
                "bar_counts": counts,
                "common_aligned_bars": len(common_timestamps),
                "aligned_coverage_by_symbol": coverage_by_symbol,
                "maximum_aligned_gap_seconds": max_gap,
                "allowed_aligned_gap_seconds": self.max_aligned_gap_seconds,
            }

        returns: Dict[str, List[float]] = {}
        momentum: Dict[str, float] = {}
        vol_percentiles: List[float] = []
        for symbol, values in timestamp_maps.items():
            closes = [values[timestamp] for timestamp in common_timestamps]
            if any(not math.isfinite(x) or x <= 0 for x in closes):
                return None, {"status": "INVALID_PRICE_DATA", "symbol": symbol}
            series = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            returns[symbol] = series
            momentum[symbol] = math.log(closes[-1] / closes[-21])
            rolling_vol = []
            for end in range(20, len(series) + 1):
                window = series[end - 20:end]
                rolling_vol.append(pstdev(window) * math.sqrt(20))
            current_vol = rolling_vol[-1]
            percentile = sum(x <= current_vol for x in rolling_vol) / len(rolling_vol)
            vol_percentiles.append(percentile)

        aligned = list(returns.values())
        correlations = []
        for i in range(len(aligned)):
            for j in range(i + 1, len(aligned)):
                correlations.append(_pearson(aligned[i], aligned[j]))
        correlation = mean(correlations) if correlations else 0.0
        directions = [1.0 if value > 0 else (-1.0 if value < 0 else 0.0)
                      for value in momentum.values()]
        trend_direction = mean(directions)
        trend_strength = _clamp(mean(
            abs(momentum[symbol]) / max(pstdev(returns[symbol][-20:]) * math.sqrt(20), 1e-9)
            for symbol in symbols
        ) / 2.0)
        breadth = sum(value > 0 for value in momentum.values()) / len(symbols)
        volatility = mean(vol_percentiles)
        drawdowns = []
        for symbol, values in timestamp_maps.items():
            closes = [values[timestamp] for timestamp in common_timestamps[-60:]]
            peak = max(closes)
            drawdowns.append((peak - closes[-1]) / peak if peak else 0.0)
        stress = _clamp(0.45 * volatility + 0.30 * max(0.0, correlation)
                        + 0.25 * _clamp(mean(drawdowns) / 0.08))
        freshness_quality = _clamp(1.0 - age / self.max_bar_age_seconds)
        skew_quality = _clamp(1.0 - skew / 180.0)
        quality = freshness_quality * skew_quality * min_coverage
        state = MarketState(
            trend_strength=trend_strength,
            trend_direction=trend_direction,
            volatility_percentile=volatility,
            breadth=breadth,
            correlation=_clamp((correlation + 1.0) / 2.0),
            stress=stress,
            data_quality=quality,
            timestamp=current.astimezone(timezone.utc).isoformat(),
        )
        return state, {
            "status": "FEATURES_READY", "bar_counts": counts,
            "latest_bar_at": latest.isoformat(), "bar_age_seconds": age,
            "cross_symbol_skew_seconds": skew,
            "features": {
                "trend_strength": trend_strength, "trend_direction": trend_direction,
                "volatility_percentile": volatility, "breadth": breadth,
                "correlation": correlation, "stress": stress, "data_quality": quality,
            },
            "feature_window": "minute bars; up to 180 observations; 20-bar momentum and realized volatility",
            "common_aligned_bars": len(common_timestamps),
            "aligned_coverage_by_symbol": coverage_by_symbol,
            "minimum_aligned_coverage": self.min_aligned_coverage,
            "maximum_aligned_gap_seconds": max_gap,
            "allowed_aligned_gap_seconds": self.max_aligned_gap_seconds,
        }


class PaperRegimeObserver:
    def __init__(self, market_db: str, decision_db: str,
                 universes: Optional[Dict[str, Sequence[str]]] = None,
                 event_db: Optional[str] = None) -> None:
        self.builder = MarketFeatureBuilder(market_db)
        self.store = RegimeDecisionStore(decision_db)
        self.universes = universes or DEFAULT_UNIVERSES
        event_path = event_db or str(Path(decision_db).resolve().parent / "rocket_trader_news_events.sqlite3")
        self.event_store = NewsEventAssessmentStore(event_path)
        self.selector = RegimeAwarePortfolioSelector()

    def evaluate_once(self, now: Optional[datetime] = None) -> Dict[str, object]:
        current = now or datetime.now(timezone.utc)
        evaluated_at = current.astimezone(timezone.utc).isoformat()
        report: Dict[str, object] = {"evaluated_at": evaluated_at, "universes": {},
                                     "orders_enabled": False, "candidate_count": 0}
        for asset_class, symbols in self.universes.items():
            state, diagnostics = self.builder.build(asset_class, tuple(symbols), current)
            if state is None:
                decision = {
                    "status": "CASH_ABSTAIN", "reason": diagnostics["status"],
                    "allocations": [], "cash_weight": 1.0, "total_exposure": 0.0,
                    "abstain": True, "regime": "UNKNOWN", "diagnostics": diagnostics,
                }
                market_timestamp = diagnostics.get("latest_bar_at")
            else:
                # No candidate can be allocated until a strategy has independently
                # passed OOS, empirical-cost, data-quality and conservative-edge gates.
                assessments = self.event_store.load_approved(now=current, symbols=symbols)
                selected = self.selector.select(
                    state, candidates=(), news=assessments, now=current, symbols=symbols
                )
                reason = (
                    "Critical reviewed point-in-time news blocks new entries."
                    if selected.news_risk.block_new_entries
                    else "No independently approved strategy candidates are registered."
                )
                decision = {
                    "status": "CASH_ABSTAIN" if selected.abstain else "CASH_NO_EDGE",
                    "reason": reason,
                    "regime": selected.regime.label.value,
                    "regime_rationale": list(selected.regime.rationale),
                    "features": diagnostics,
                    "allocations": [],
                    "cash_weight": selected.cash_weight,
                    "total_exposure": selected.total_exposure,
                    "abstain": selected.abstain,
                    "news_assessments_loaded": len(assessments),
                    "news_overlay": {
                        "exposure_multiplier": selected.news_risk.exposure_multiplier,
                        "block_new_entries": selected.news_risk.block_new_entries,
                        "confidence": selected.news_risk.confidence,
                        "rationale": list(selected.news_risk.rationale),
                    },
                }
                market_timestamp = diagnostics.get("latest_bar_at")
            report["universes"][asset_class] = decision
            self.store.save(asset_class, evaluated_at, market_timestamp,
                             {"status": "EVALUATED", "decision": decision})
        return report

    def health(self) -> Dict[str, object]:
        return self.store.health()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rocket Trader Paper regime observer (read-only).")
    parser.add_argument("--market-db", default=os.getenv("ROCKET_TRADER_RUNTIME_DB", "/app/data/runtime.sqlite3"))
    parser.add_argument("--decision-db", default=os.getenv("ROCKET_TRADER_REGIME_DB", "/app/data/regime_decisions.sqlite3"))
    parser.add_argument("--event-db", default=os.getenv("ROCKET_TRADER_EVENT_DB"))
    parser.add_argument("--poll-forever", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()
    observer = PaperRegimeObserver(args.market_db, args.decision_db, event_db=args.event_db)
    if args.healthcheck:
        result = observer.health()
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result["healthy"] else 1
    if args.interval_seconds < 15:
        parser.error("--interval-seconds must be at least 15")
    while True:
        try:
            result = observer.evaluate_once()
            print(json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__,
                              "error": str(exc), "orders_enabled": False}), flush=True)
            if not args.poll_forever:
                return 1
        if not args.poll_forever:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
