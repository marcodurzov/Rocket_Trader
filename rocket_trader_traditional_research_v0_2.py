```yaml
name: Rocket Trader - Traditional Research v0.2

on:
  workflow_dispatch:
    inputs:
      days:
        description: "Calendar lookback window"
        required: false
        default: "365"
        type: string
      symbols:
        description: "Space-separated US stocks/ETFs"
        required: false
        default: "SPY QQQ"
        type: string

  schedule:
    - cron: "0 15 * * 0"

permissions:
  contents: read

concurrency:
  group: rocket-trader-traditional-research-v02
  cancel-in-progress: false

jobs:
  research:
    name: research-v0-2
    runs-on: ubuntu-latest
    timeout-minutes: 35

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Verify exact research implementation
        shell: bash
        run: |
          set -euo pipefail

          FILE="rocket_trader_traditional_research_v0_2.py"

          if [[ ! -f "$FILE" ]]; then
            echo "FATAL: $FILE is missing."
            exit 1
          fi

          python -m py_compile "$FILE"

          python - <<'PY'
          import ast
          from pathlib import Path

          path = Path("rocket_trader_traditional_research_v0_2.py")
          tree = ast.parse(path.read_text(encoding="utf-8"))

          version = None

          for node in tree.body:
              if isinstance(node, ast.Assign):
                  for target in node.targets:
                      if isinstance(target, ast.Name) and target.id == "VERSION":
                          version = ast.literal_eval(node.value)

          if version != "0.2":
              raise SystemExit(
                  f"FATAL: Expected version 0.2, found {version!r}"
              )

          print("Exact research implementation verified: v0.2")
          PY

      - name: Validate research inputs
        shell: bash
        env:
          SYMBOLS_INPUT: ${{ inputs.symbols || 'SPY QQQ' }}
          DAYS_INPUT: ${{ inputs.days || '365' }}
        run: |
          set -euo pipefail

          if ! [[ "$DAYS_INPUT" =~ ^[1-9][0-9]*$ ]]; then
            echo "FATAL: days must be a positive integer."
            exit 1
          fi

          if [[ -z "${SYMBOLS_INPUT//[[:space:]]/}" ]]; then
            echo "FATAL: At least one symbol is required."
            exit 1
          fi

          echo "Days: $DAYS_INPUT"
          echo "Symbols: $SYMBOLS_INPUT"

      - name: Install dependencies
        shell: bash
        run: |
          set -euo pipefail
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-alpaca.txt

      - name: Run offline tests
        shell: bash
        run: |
          set -euo pipefail
          python rocket_trader_traditional_research_v0_2.py --self-test

      - name: Run research
        shell: bash
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
          SYMBOLS_INPUT: ${{ inputs.symbols || 'SPY QQQ' }}
          DAYS_INPUT: ${{ inputs.days || '365' }}
        run: |
          set -euo pipefail

          if [[ -z "${ALPACA_API_KEY:-}" || -z "${ALPACA_SECRET_KEY:-}" ]]; then
            echo "FATAL: Alpaca API credentials are not configured."
            exit 1
          fi

          mkdir -p research_artifacts

          read -r -a symbols <<< "$SYMBOLS_INPUT"

          echo "Starting v0.2 research."
          echo "Symbols: ${symbols[*]}"
          echo "Calendar days: $DAYS_INPUT"

          python rocket_trader_traditional_research_v0_2.py \
            --symbols "${symbols[@]}" \
            --days "$DAYS_INPUT" \
            --output research_artifacts/rocket_trader_traditional_research_v0_2_results.json

      - name: Verify generated report
        shell: bash
        run: |
          set -euo pipefail

          REPORT="research_artifacts/rocket_trader_traditional_research_v0_2_results.json"

          if [[ ! -s "$REPORT" ]]; then
            echo "FATAL: Research report missing or empty."
            exit 1
          fi

          python - <<'PY'
          import json
          from pathlib import Path

          path = Path(
              "research_artifacts/"
              "rocket_trader_traditional_research_v0_2_results.json"
          )

          data = json.loads(path.read_text(encoding="utf-8"))
          summary = data.get("summary", {})

          checks = {
              "version": summary.get("version") == "0.2",
              "pipeline": (
                  summary.get("pipeline")
                  == "rocket_trader_traditional_research_v0_2"
              ),
              "orders_disabled": summary.get("orders_enabled") is False,
              "zero_orders": summary.get("orders_submitted") == 0,
              "pipeline_ok": summary.get("ok") is True,
              "results_present": bool(data.get("results")),
              "no_symbol_failures": not summary.get("symbols_failed"),
          }

          for name, passed in checks.items():
              print(f"{'PASS' if passed else 'FAIL'}: {name}")

          failed = [name for name, passed in checks.items() if not passed]

          if failed:
              raise SystemExit(
                  "FATAL: Report validation failed: " + ", ".join(failed)
              )

          print("Research report identity and safety verified.")
          print("Version:", summary["version"])
          print("Pipeline:", summary["pipeline"])
          print("Symbols:", summary.get("symbols_processed"))
          print("Orders enabled:", summary["orders_enabled"])
          print("Orders submitted:", summary["orders_submitted"])
          PY

      - name: Upload research report
        uses: actions/upload-artifact@v4
        with:
          name: rocket-trader-traditional-research-v0-2-report
          path: research_artifacts/rocket_trader_traditional_research_v0_2_results.json
          if-no-files-found: error
          retention-days: 30
```
