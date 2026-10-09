name: Rocket Trader - Signal Research
on:
  workflow_dispatch:
    inputs:
      days:
        description: "Calendar days of Alpaca data"
        required: false
        default: "30"
        type: string
jobs:
  signal-research:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-alpaca.txt
      - name: Structural self-test
        run: python rocket_trader_signal_research.py --self-test
      - name: Walk-forward signal research
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
        run: |
          python rocket_trader_signal_research.py \
            --symbols SPY QQQ \
            --days "${{ inputs.days || '30' }}" \
            --friction 0.00020 \
            --slippage 0.00010
