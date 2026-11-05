
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ROCKET TRADER - RESEARCH ARTIFACT AUDITOR v1.0

Audita reportes JSON/CSV de investigación.
No conecta con brokers.
No ejecuta órdenes.
No verifica rentabilidad real ni promueve estrategias.

PASS = reporte reconocido, datos estructuralmente válidos y controles de
       seguridad aprobados. NO significa rentabilidad demostrada.
FAIL = errores estructurales, valores inválidos o controles incumplidos.
NO_DATA = no se encontraron reportes de investigación utilizables.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = "1.0.0"

EXCLUDED_NAMES = {
    "v0_9_audit_report.json",
    "v1_0_audit_report.json",
}

LEDGER_KEYS = {
    "trade_ledger",
    "trades",
    "sample_holdout_trades",
    "ledger",
}


def is_finite_tree(value: Any, path: str = "$") -> list[dict]:
    """Detecta NaN e infinitos en cualquier nivel del JSON."""
    issues = []

    if isinstance(value, float) and not math.isfinite(value):
        issues.append({
            "code": "NON_FINITE_NUMBER",
            "path": path,
            "message": f"Valor numérico no finito en {path}",
        })

    elif isinstance(value, dict):
        for key, child in value.items():
            issues.extend(is_finite_tree(child, f"{path}.{key}"))

    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(is_finite_tree(child, f"{path}[{index}]"))

    return issues


def walk_dicts(value: Any):
    """Recorre recursivamente todos los diccionarios."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def parse_timestamp(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        normalized = value.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def find_ledgers(data: Any):
    """Busca listas que aparenten ser historiales de operaciones."""
    found = []

    for item in walk_dicts(data):
        for key, value in item.items():
            if key.lower() in LEDGER_KEYS and isinstance(value, list):
                if value and all(isinstance(row, dict) for row in value):
                    found.append((key, value))

    return found


def audit_ledger(rows: list[dict], source: str):
    findings = []
    valid_rows = 0

    for index, row in enumerate(rows):
        prefix = f"{source}[{index}]"

        signal = (
            row.get("signal_timestamp")
            or row.get("signal_time")
        )
        entry = (
            row.get("entry_timestamp")
            or row.get("entry_time")
        )
        exit_time = (
            row.get("exit_timestamp")
            or row.get("exit_time")
        )

        signal_dt = parse_timestamp(signal)
        entry_dt = parse_timestamp(entry)
        exit_dt = parse_timestamp(exit_time)

        if signal and not signal_dt:
            findings.append({
                "severity": "ERROR",
                "code": "INVALID_SIGNAL_TIMESTAMP",
                "message": f"Timestamp de señal inválido: {prefix}",
            })

        if entry and not entry_dt:
            findings.append({
                "severity": "ERROR",
                "code": "INVALID_ENTRY_TIMESTAMP",
                "message": f"Timestamp de entrada inválido: {prefix}",
            })

        if exit_time and not exit_dt:
            findings.append({
                "severity": "ERROR",
                "code": "INVALID_EXIT_TIMESTAMP",
                "message": f"Timestamp de salida inválido: {prefix}",
            })

        # Comparación cronológica solo si las fechas tienen zonas compatibles.
        try:
            if signal_dt and entry_dt and entry_dt < signal_dt:
                findings.append({
                    "severity": "ERROR",
                    "code": "ENTRY_BEFORE_SIGNAL",
                    "message": f"Entrada anterior a la señal: {prefix}",
                })

            if entry_dt and exit_dt and exit_dt < entry_dt:
                findings.append({
                    "severity": "ERROR",
                    "code": "EXIT_BEFORE_ENTRY",
                    "message": f"Salida anterior a la entrada: {prefix}",
                })

            if signal_dt and exit_dt and exit_dt < signal_dt:
                findings.append({
                    "severity": "ERROR",
                    "code": "EXIT_BEFORE_SIGNAL",
                    "message": f"Salida anterior a la señal: {prefix}",
                })

        except TypeError:
            findings.append({
                "severity": "ERROR",
                "code": "INCOMPARABLE_TIMESTAMPS",
                "message": f"Zonas horarias incompatibles: {prefix}",
            })

        for field in ("entry_price", "exit_price", "quantity"):
            if field in row:
                try:
                    number = float(row[field])
                    if not math.isfinite(number) or number <= 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    findings.append({
                        "severity": "ERROR",
                        "code": "INVALID_TRADE_VALUE",
                        "message": f"{field} inválido en {prefix}",
                    })

        valid_rows += 1

    return valid_rows, findings


def recognize_research_report(data: Any):
    """
    Reconoce el formato de Traditional Research v0.2:
    {
        "summary": {...},
        "results": [...]
    }

    También acepta reportes que declaren pipeline y results.
    """
    if not isinstance(data, dict):
        return False, None, None

    summary = data.get("summary")
    results = data.get("results")

    if isinstance(summary, dict) and isinstance(results, list):
        return True, summary, results

    if isinstance(data.get("pipeline"), str) and isinstance(results, list):
        return True, data, results

    return False, None, None


def audit_json(path: Path):
    findings = []

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception as exc:
        return None, [{
            "severity": "ERROR",
            "code": "INVALID_JSON",
            "message": f"{path.name}: {type(exc).__name__}: {exc}",
        }]

    for issue in is_finite_tree(data):
        findings.append({
            "severity": "ERROR",
            "code": issue["code"],
            "message": f"{path.name}: {issue['message']}",
        })

    recognized, summary, results = recognize_research_report(data)

    if not recognized:
        return None, findings + [{
            "severity": "WARNING",
            "code": "UNRECOGNIZED_JSON",
            "message": (
                f"{path.name}: JSON válido, pero no tiene la estructura "
                "summary/results ni pipeline/results."
            ),
        }]

    if not results:
        findings.append({
            "severity": "ERROR",
            "code": "EMPTY_RESULTS",
            "message": f"{path.name}: el reporte no contiene resultados.",
        })

    if not isinstance(summary, dict):
        findings.append({
            "severity": "ERROR",
            "code": "INVALID_SUMMARY",
            "message": f"{path.name}: summary no es un objeto.",
        })
        summary = {}

    # Revisar controles de seguridad en todo el reporte.
    for item in walk_dicts(data):
        if item.get("orders_enabled") is True:
            findings.append({
                "severity": "ERROR",
                "code": "ORDERS_ENABLED",
                "message": f"{path.name}: se encontró orders_enabled=true.",
            })

        if "orders_submitted" in item:
            try:
                submitted = int(item["orders_submitted"])
                if submitted > 0:
                    findings.append({
                        "severity": "ERROR",
                        "code": "ORDERS_SUBMITTED",
                        "message": (
                            f"{path.name}: orders_submitted={submitted}."
                        ),
                    })
                elif submitted < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                findings.append({
                    "severity": "ERROR",
                    "code": "INVALID_ORDER_COUNT",
                    "message": f"{path.name}: orders_submitted inválido.",
                })

    if summary.get("ok") is False:
        findings.append({
            "severity": "ERROR",
            "code": "RESEARCH_PIPELINE_FAILED",
            "message": f"{path.name}: el pipeline reportó ok=false.",
        })

    if summary.get("symbols_failed"):
        findings.append({
            "severity": "ERROR",
            "code": "SYMBOL_FAILURES",
            "message": (
                f"{path.name}: uno o más símbolos fallaron en investigación."
            ),
        })

    ledgers = find_ledgers(data)
    ledger_rows = 0

    if not ledgers:
        findings.append({
            "severity": "WARNING",
            "code": "LEDGER_NOT_PRESENT",
            "message": (
                f"{path.name}: reporte válido, pero no incluye un ledger "
                "individual de operaciones. No se puede verificar cronología "
                "ni reconciliar cada operación."
            ),
        })
    else:
        for ledger_name, rows in ledgers:
            count, ledger_findings = audit_ledger(
                rows, f"{path.name}.{ledger_name}"
            )
            ledger_rows += count
            findings.extend(ledger_findings)

    report_info = {
        "file": str(path),
        "pipeline": summary.get("pipeline", data.get("pipeline")),
        "version": summary.get("version", data.get("version")),
        "symbols_processed": summary.get("symbols_processed", []),
        "symbols_failed": summary.get("symbols_failed", []),
        "result_count": len(results),
        "ledger_rows": ledger_rows,
        "ledger_present": bool(ledgers),
        "research_pass": summary.get("research_pass"),
    }

    return report_info, findings


def audit_csv(path: Path):
    findings = []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            rows = list(reader)

        if not headers:
            findings.append({
                "severity": "ERROR",
                "code": "CSV_WITHOUT_HEADERS",
                "message": f"{path.name}: CSV sin encabezados.",
            })

        return {
            "file": str(path),
            "headers": headers,
            "rows": len(rows),
        }, findings

    except Exception as exc:
        return None, [{
            "severity": "ERROR",
            "code": "INVALID_CSV",
            "message": f"{path.name}: {type(exc).__name__}: {exc}",
        }]


def run_audit(input_dir: Path, output: Path):
    findings = []
    reports = []
    csv_reports = []
    files_scanned = 0
    trade_rows = 0

    if not input_dir.exists() or not input_dir.is_dir():
        findings.append({
            "severity": "NO_DATA",
            "code": "INPUT_DIRECTORY_MISSING",
            "message": f"No existe el directorio de entrada: {input_dir}",
        })
    else:
        candidates = sorted(
            p for p in input_dir.rglob("*")
            if p.is_file()
            and p.name not in EXCLUDED_NAMES
            and p.resolve() != output.resolve()
            and p.suffix.lower() in {".json", ".csv"}
        )

        files_scanned = len(candidates)

        for path in candidates:
            if path.suffix.lower() == ".json":
                report, issues = audit_json(path)
                findings.extend(issues)
                if report:
                    reports.append(report)
                    trade_rows += report["ledger_rows"]

            elif path.suffix.lower() == ".csv":
                report, issues = audit_csv(path)
                findings.extend(issues)
                if report:
                    csv_reports.append(report)

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    warnings = sum(1 for f in findings if f["severity"] == "WARNING")

    if errors:
        status = "FAIL"
    elif not reports:
        status = "NO_DATA"
        if not any(f["severity"] == "NO_DATA" for f in findings):
            findings.append({
                "severity": "NO_DATA",
                "code": "NO_RESEARCH_REPORTS",
                "message": (
                    "No se encontró ningún reporte JSON reconocido. "
                    "Un CSV aislado no sustituye al reporte de investigación."
                ),
            })
    else:
        status = "PASS"

    result = {
        "version": VERSION,
        "audit_status": status,
        "input_directory": str(input_dir),
        "files_scanned": files_scanned,
        "reports_scanned": len(reports),
        "csv_files_scanned": len(csv_reports),
        "trade_rows_scanned": trade_rows,
        "error_count": errors,
        "warning_count": warnings,
        "orders_enabled": False,
        "orders_submitted": 0,
        "strategy_profitability_verified": False,
        "strategy_promotion_enabled": False,
        "reported_results": reports,
        "csv_reports": csv_reports,
        "findings": findings,
        "limitations": [
            "PASS valida estructura y controles del artefacto, no rentabilidad.",
            "Sin ledger no se verifica la cronología individual de operaciones.",
            "No se reconstruyen resultados desde barras originales de mercado.",
            "No se conecta con brokers ni se envían órdenes.",
            "No se habilita promoción automática de estrategias.",
        ],
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)

    return result


def self_test():
    tests = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        tests.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "input"
        source.mkdir()
        output = root / "out" / "audit.json"

        # Reporte válido v0.2 sin ledger: debe ser PASS con advertencia.
        valid = {
            "summary": {
                "ok": True,
                "version": "0.2",
                "pipeline": "rocket_trader_traditional_research_v0_2",
                "symbols_processed": ["SPY", "QQQ"],
                "symbols_failed": [],
                "orders_enabled": False,
                "orders_submitted": 0,
            },
            "results": [
                {"symbol": "SPY"},
                {"symbol": "QQQ"},
            ],
        }
        (source / "valid.json").write_text(json.dumps(valid), encoding="utf-8")
        result = run_audit(source, output)
        check("v02_report_without_ledger_passes_with_warning",
              result["audit_status"] == "PASS"
              and any(f["code"] == "LEDGER_NOT_PRESENT"
                      for f in result["findings"]))

        # Órdenes activadas: FAIL.
        valid["summary"]["orders_enabled"] = True
        (source / "valid.json").write_text(json.dumps(valid), encoding="utf-8")
        result = run_audit(source, output)
        check("orders_enabled_fails", result["audit_status"] == "FAIL")

        # JSON no reconocido: NO_DATA.
        for p in source.iterdir():
            p.unlink()
        (source / "other.json").write_text('{"hello":"world"}', encoding="utf-8")
        result = run_audit(source, output)
        check("unrecognized_json_is_no_data",
              result["audit_status"] == "NO_DATA")

        # NaN: FAIL.
        bad = {
            "summary": {"ok": True, "orders_enabled": False,
                        "orders_submitted": 0},
            "results": [{"metric": float("nan")}],
        }
        (source / "other.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        result = run_audit(source, output)
        check("non_finite_number_fails", result["audit_status"] == "FAIL")

        # Cronología incorrecta: FAIL.
        ledger = {
            "summary": {"ok": True, "orders_enabled": False,
                        "orders_submitted": 0},
            "results": [{
                "trade_ledger": [{
                    "signal_timestamp": "2026-01-01T10:00:00Z",
                    "entry_timestamp": "2026-01-01T09:00:00Z",
                    "exit_timestamp": "2026-01-01T11:00:00Z",
                    "entry_price": 100,
                    "exit_price": 101,
                    "quantity": 1,
                }]
            }],
        }
        (source / "other.json").write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        result = run_audit(source, output)
        check("entry_before_signal_fails", result["audit_status"] == "FAIL")

        # Sin archivos: NO_DATA.
        for p in source.iterdir():
            p.unlink()
        result = run_audit(source, output)
        check("empty_directory_is_no_data",
              result["audit_status"] == "NO_DATA")

    return {
        "ok": True,
        "version": VERSION,
        "tests_passed": len(tests),
        "tests": tests,
        "orders_enabled": False,
        "orders_submitted": 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rocket Trader Research Artifact Auditor v1.0"
    )
    parser.add_argument("--input-dir", default="audit_input")
    parser.add_argument("--output", default="audit_output/v1_0_audit_report.json")
    parser.add_argument("--run-tests", "--self-test",
                        dest="run_tests", action="store_true")
    parser.add_argument("--strict-no-data", action="store_true")
    args = parser.parse_args()

    if args.run_tests:
        result = self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    result = run_audit(Path(args.input_dir), Path(args.output))
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["audit_status"] == "FAIL":
        return 1

    if result["audit_status"] == "NO_DATA" and args.strict_no_data:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
