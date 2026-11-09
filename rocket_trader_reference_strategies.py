#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sourced strategy references for Rocket Trader research.

This registry is not a signal generator and does not create successful-trader
trade records. It separates quantitative, reproducible baselines from qualitative
practitioner material so that anecdotes cannot be mistaken for statistical edge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


REGISTRY_PATH = Path(__file__).resolve().parent / "research" / "reference_strategy_registry_v0_1.json"


class ReferenceRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrategyReference:
    reference_id: str
    name: str
    reference_type: str
    source_url: str
    markets_to_test: Sequence[str]
    quantitative_reference: bool
    status: str
    rule_hypothesis: str
    limitations: Sequence[str]


class ReferenceStrategyRegistry:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path) if path else REGISTRY_PATH
        self._raw = self._load()
        self._references = self._parse(self._raw)

    def _load(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ReferenceRegistryError(
                f"No se pudo leer el registro de estrategias: {exc}"
            ) from exc
        if payload.get("schema_version") != 1:
            raise ReferenceRegistryError("schema_version no soportado.")
        return payload

    @staticmethod
    def _parse(payload: Dict[str, Any]) -> List[StrategyReference]:
        items = payload.get("references")
        if not isinstance(items, list) or not items:
            raise ReferenceRegistryError("El registro no contiene referencias.")
        parsed: List[StrategyReference] = []
        seen = set()
        for item in items:
            required = (
                "id", "name", "reference_type", "source_url",
                "markets_to_test", "quantitative_reference", "status",
                "rule_hypothesis", "limitations",
            )
            missing = [key for key in required if key not in item]
            if missing:
                raise ReferenceRegistryError(
                    f"Referencia incompleta {item.get('id')}: {missing}"
                )
            reference_id = str(item["id"]).strip()
            if not reference_id or reference_id in seen:
                raise ReferenceRegistryError(f"ID vacío o duplicado: {reference_id!r}")
            seen.add(reference_id)
            url = str(item["source_url"])
            if not url.startswith(("https://", "http://")):
                raise ReferenceRegistryError(f"URL no válida en {reference_id}")
            if item["status"] not in {
                "RESEARCH_ONLY", "QUALITATIVE_REFERENCE_ONLY",
                "MANDATORY_BASELINE",
            }:
                raise ReferenceRegistryError(
                    f"Estado no permitido en {reference_id}: {item['status']}"
                )
            parsed.append(
                StrategyReference(
                    reference_id=reference_id,
                    name=str(item["name"]),
                    reference_type=str(item["reference_type"]),
                    source_url=url,
                    markets_to_test=tuple(item["markets_to_test"]),
                    quantitative_reference=bool(item["quantitative_reference"]),
                    status=str(item["status"]),
                    rule_hypothesis=str(item["rule_hypothesis"]),
                    limitations=tuple(str(x) for x in item["limitations"]),
                )
            )
        return parsed

    @property
    def policy(self) -> Dict[str, Any]:
        return dict(self._raw.get("policy", {}))

    def all(self) -> List[StrategyReference]:
        return list(self._references)

    def for_market(
        self,
        market: str,
        quantitative_only: bool = False,
    ) -> List[StrategyReference]:
        market = str(market).strip().lower()
        return [
            item for item in self._references
            if market in item.markets_to_test
            and (not quantitative_only or item.quantitative_reference)
        ]

    def get(self, reference_id: str) -> StrategyReference:
        for item in self._references:
            if item.reference_id == reference_id:
                return item
        raise KeyError(reference_id)

    def can_create_precedent_evidence(
        self,
        reference_id: str,
        comparable_out_of_sample_events: int,
        independent_implementations: int,
        independent_validation_passed: bool,
        risk_adjusted_benchmark_passed: bool,
    ) -> bool:
        """A citation alone never creates PRECEDENTED; independent tests are required."""
        reference = self.get(reference_id)
        return bool(
            reference.quantitative_reference
            and comparable_out_of_sample_events >= 20
            and independent_implementations >= 3
            and independent_validation_passed
            and risk_adjusted_benchmark_passed
        )


def self_test() -> Dict[str, Any]:
    registry = ReferenceStrategyRegistry()
    all_refs = registry.all()
    equity_quant = registry.for_market("us_equities_etfs", quantitative_only=True)
    crypto_quant = registry.for_market("crypto_spot", quantitative_only=True)
    qualitative = [
        item for item in all_refs if not item.quantitative_reference
    ]
    assert len(all_refs) >= 5
    assert len(equity_quant) >= 3
    assert len(crypto_quant) >= 2
    assert qualitative
    assert registry.can_create_precedent_evidence(
        "time_series_momentum_12m",
        comparable_out_of_sample_events=100,
        independent_implementations=3,
        independent_validation_passed=True,
        risk_adjusted_benchmark_passed=True,
    ) is True
    assert registry.can_create_precedent_evidence(
        "jesse_livermore_trend_principle",
        comparable_out_of_sample_events=1000,
        independent_implementations=10,
        independent_validation_passed=True,
        risk_adjusted_benchmark_passed=True,
    ) is False
    assert registry.can_create_precedent_evidence(
        "time_series_momentum_12m",
        comparable_out_of_sample_events=19,
        independent_implementations=3,
        independent_validation_passed=True,
        risk_adjusted_benchmark_passed=True,
    ) is False
    return {
        "ok": True,
        "version": "0.1",
        "pipeline": "rocket_trader_reference_strategy_registry",
        "references": len(all_refs),
        "equity_quantitative_references": len(equity_quant),
        "crypto_quantitative_hypotheses": len(crypto_quant),
        "qualitative_references": len(qualitative),
        "source_only_precedent_approval": False,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2))
