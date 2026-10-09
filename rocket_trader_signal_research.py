#!/usr/bin/env python3
# Rocket Trader — walk-forward signal research v0.2
# Research-only: no trading/order API is imported or called.
from __future__ import annotations
import argparse, json, math
from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed
from rocket_trader_market_data import AlpacaMarketDataClient
from rocket_trader_engine import EngineConfig, EnsembleModel, FeatureEngine, FEATURE_COLUMNS, MarketDataValidator

VERSION = "0.2"
ABS_THRESHOLDS = [0.035, 0.04, 0.045, 0.05, 0.055, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]
PERCENTILES = [90, 85, 80, 75]
MIN_TRAIN = 3000
TEST_BLOCK = 1000
MAX_FOLDS = 5

@dataclass
class Trade:
    symbol: str
    fold: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    probability_up: float
    gross_return: float
    net_return: float

def fetch(symbol, days):
    client = AlpacaMarketDataClient(feed=DataFeed.IEX)
    bars = client.get_recent_bars(symbol=symbol, minutes=max(days * 1440, 10080))
    if not bars:
        raise RuntimeError(f"Alpaca no devolvió barras para {symbol}")
    return MarketDataValidator.normalize(pd.DataFrame([{
        "timestamp": b.timestamp, "open": b.open, "high": b.high,
        "low": b.low, "close": b.close, "volume": b.volume
    } for b in bars]))

def training_data(features, cfg, train_end):
    # Labels cannot extend beyond the training window.
    part = features.iloc[:max(0, train_end - cfg.horizon_bars)].copy()
    future = part["close"].shift(-cfg.horizon_bars) / part["close"] - 1.0
    target = (future >= cfg.target_return).astype(int)
    valid = part[FEATURE_COLUMNS].notna().all(axis=1) & future.notna()
    X, y = part.loc[valid, FEATURE_COLUMNS], target.loc[valid]
    if len(X) < cfg.min_training_rows or y.nunique() < 2:
        raise RuntimeError(f"Training insuficiente: rows={len(X)}, classes={y.nunique()}")
    if len(X) > cfg.max_training_rows:
        X, y = X.iloc[-cfg.max_training_rows:], y.iloc[-cfg.max_training_rows:]
    return X.reset_index(drop=True), y.reset_index(drop=True)

def walk_forward(raw, cfg):
    features = FeatureEngine.build(raw)
    n = len(features)
    train_end = min(max(MIN_TRAIN, cfg.min_training_rows), n)
    outputs, fold_info, fold = [], [], 0
    while train_end < n and fold < MAX_FOLDS:
        test_end = min(train_end + TEST_BLOCK, n)
        X, y = training_data(features, cfg, train_end)
        model = EnsembleModel(cfg)
        model.fit(X, y)

        # Reference probability distribution is strictly historical for this fold.
        ref = features.iloc[max(0, train_end-cfg.max_training_rows):train_end].copy()
        ref = ref.loc[ref[FEATURE_COLUMNS].notna().all(axis=1)]
        ref_probs = np.asarray(model.predict_proba(ref[FEATURE_COLUMNS])[0]) if len(ref) else np.array([])

        block = features.iloc[train_end:test_end].copy()
        block = block.loc[block[FEATURE_COLUMNS].notna().all(axis=1)].copy()
        if len(block):
            block["probability_up"] = np.asarray(model.predict_proba(block[FEATURE_COLUMNS])[0])
            block["fold"] = fold + 1
            for pct in PERCENTILES:
                cutoff = float(np.quantile(ref_probs, pct/100)) if len(ref_probs) else float("nan")
                block[f"cutoff_{pct}"] = cutoff
                block[f"rank_{pct}"] = block["probability_up"] >= cutoff if np.isfinite(cutoff) else False
            outputs.append(block)
        fold_info.append({
            "fold": fold+1, "train_end": train_end, "test_end": test_end,
            "reference_rows": len(ref_probs),
            "reference_p90": float(np.quantile(ref_probs,.90)) if len(ref_probs) else None,
            "reference_p85": float(np.quantile(ref_probs,.85)) if len(ref_probs) else None,
            "reference_p80": float(np.quantile(ref_probs,.80)) if len(ref_probs) else None,
            "reference_p75": float(np.quantile(ref_probs,.75)) if len(ref_probs) else None,
        })
        train_end, fold = test_end, fold + 1
    if not outputs:
        raise RuntimeError("No se generaron predicciones fuera de muestra.")
    return pd.concat(outputs).sort_index(), fold_info

def simulate(pred, symbol, trigger_name, trigger, horizon, cost, slippage):
    rows = pred.sort_index().reset_index()
    idx_col = rows.columns[0]
    trades, i = [], 0
    while i < len(rows):
        row = rows.iloc[i]
        if not bool(trigger(row)):
            i += 1
            continue
        entry_idx = int(row[idx_col])
        future = rows[rows[idx_col] == entry_idx + horizon]
        if future.empty:
            i += 1
            continue
        ex = future.iloc[0]
        entry, exit_ = float(row["close"]), float(ex["close"])
        if entry <= 0 or exit_ <= 0:
            i += 1
            continue
        gross = exit_/entry - 1
        trades.append(Trade(symbol, int(row["fold"]), str(row["timestamp"]), str(ex["timestamp"]),
            entry, exit_, float(row["probability_up"]), gross, gross-cost-slippage))
        positions = rows.index[rows[idx_col] == entry_idx+horizon]
        i = int(positions[0])+1 if len(positions) else i+1
    r = np.array([t.net_return for t in trades], dtype=float)
    if not len(r):
        return {"trigger":trigger_name,"trades":0,"folds_with_trades":0,"profitable_folds":0,
            "win_rate":0,"avg_return":0,"median_return":0,"total_return":0,"profit_factor":0,
            "max_drawdown":0,"sharpe":0,"best_trade":0,"worst_trade":0}, trades
    equity = np.cumprod(1+r)
    dd = equity/np.maximum.accumulate(equity)-1
    gains, losses = r[r>0].sum(), -r[r<0].sum()
    pf = float(gains/losses) if losses else (float("inf") if gains else 0)
    fold_returns = [float(np.prod(1+np.array([t.net_return for t in trades if t.fold==f]))-1)
                    for f in sorted(set(t.fold for t in trades))]
    std = float(np.std(r, ddof=1)) if len(r)>1 else 0
    metrics = {"trigger":trigger_name,"trades":len(r),"folds_with_trades":len(fold_returns),
        "profitable_folds":sum(x>0 for x in fold_returns),"win_rate":float(np.mean(r>0)),
        "avg_return":float(np.mean(r)),"median_return":float(np.median(r)),
        "total_return":float(equity[-1]-1),"profit_factor":pf,"max_drawdown":float(dd.min()),
        "sharpe":float(np.mean(r)/std*math.sqrt(len(r))) if std else 0,
        "best_trade":float(r.max()),"worst_trade":float(r.min())}
    return metrics, trades

def evaluate(symbol, days, cost, slippage):
    raw = fetch(symbol, days)
    cfg = EngineConfig(target_return=.001, horizon_bars=5, min_training_rows=300,
                       max_training_rows=5000, probability_threshold=.50)
    pred, fold_info = walk_forward(raw, cfg)
    specs = [(f"prob>={t:.3f}", lambda row,t=t: row["probability_up"]>=t) for t in ABS_THRESHOLDS]
    specs += [(f"train_p{p}", lambda row,p=p: bool(row[f"rank_{p}"])) for p in PERCENTILES]
    results, samples = [], {}
    for name, fn in specs:
        m, trades = simulate(pred, symbol, name, fn, cfg.horizon_bars, cost, slippage)
        results.append(m); samples[name] = [asdict(t) for t in trades[:15]]
    qualified = [m for m in results if m["trades"]>=30 and m["folds_with_trades"]>=3
                 and m["profitable_folds"]>=2 and m["total_return"]>0 and m["profit_factor"]>1]
    best = max(qualified or results, key=lambda m:(m["profit_factor"],m["total_return"],
                m["profitable_folds"],m["sharpe"]))
    return {"symbol":symbol,"days_requested":days,"raw_bars":len(raw),
        "oos_predictions":len(pred),"folds":int(pred["fold"].nunique()),
        "target_return":cfg.target_return,"horizon_bars":cfg.horizon_bars,
        "round_trip_cost":cost,"slippage":slippage,
        "buy_hold_return":float(pred.close.iloc[-1]/pred.close.iloc[0]-1),
        "fold_reference":fold_info,"results":results,"best_trigger":best["trigger"],
        "research_pass":bool(qualified),
        "reason":"Cumple criterios OOS mínimos; todavía requiere más datos y paper trading." if qualified
                 else "No existe todavía un trigger OOS suficientemente estable.",
        "sample_trades":samples[best["trigger"]],"orders_enabled":False,"orders_submitted":0}

def self_test():
    rng=np.random.default_rng(42); n=5000
    ts=pd.date_range("2025-01-01",periods=n,freq="min",tz="UTC")
    close=100*np.exp(np.cumsum(rng.normal(0,.001,n)))
    op=close*(1+rng.normal(0,.0002,n)); spread=np.abs(rng.normal(.0008,.0002,n))
    raw=pd.DataFrame({"timestamp":ts,"open":op,"high":np.maximum(op,close)*(1+spread),
        "low":np.minimum(op,close)*(1-spread),"close":close,"volume":rng.lognormal(10,.3,n)})
    f=FeatureEngine.build(MarketDataValidator.normalize(raw))
    assert len(f)==n and all(c in f.columns for c in FEATURE_COLUMNS)
    return {"ok":True,"version":VERSION,"pipeline":"rocket_trader_signal_research",
        "mode":"PAPER_ONLY","orders_enabled":False,"orders_submitted":0,"features_rows":len(f)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true"); p.add_argument("--symbols",nargs="+",default=["SPY","QQQ"])
    p.add_argument("--days",type=int,default=30); p.add_argument("--friction",type=float,default=.00020)
    p.add_argument("--slippage",type=float,default=.00010); a=p.parse_args()
    print("="*72); print(f"ROCKET TRADER — WALK-FORWARD SIGNAL RESEARCH v{VERSION}")
    print("MODE: PAPER / RESEARCH ONLY"); print("LIVE ORDERS: DISABLED"); print("ORDER SUBMISSION: DISABLED"); print("="*72)
    if a.self_test:
        print(json.dumps(self_test(),indent=2)); print("ROCKET TRADER SIGNAL RESEARCH SELF-TEST: OK"); return 0
    if a.days<15: print("ERROR: --days debe ser >= 15"); return 1
    results, failures=[],[]
    for sym in [s.upper() for s in a.symbols]:
        try:
            r=evaluate(sym,a.days,a.friction,a.slippage); results.append(r)
            print(json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False))
        except Exception as e:
            failures.append({"symbol":sym,"error":f"{type(e).__name__}: {e}"})
            print(json.dumps(failures[-1],indent=2,ensure_ascii=False))
    summary={"ok":bool(results) and not failures,"version":VERSION,"pipeline":"rocket_trader_signal_research",
        "mode":"PAPER_ONLY","orders_enabled":False,"orders_submitted":0,
        "symbols_processed":[r["symbol"] for r in results],"symbols_failed":[r["symbol"] for r in failures],
        "research_pass":bool(results) and all(r["research_pass"] for r in results),"failures":failures}
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print("ROCKET TRADER SIGNAL RESEARCH: OK" if summary["ok"] else "ROCKET TRADER SIGNAL RESEARCH: FAIL")
    return 0 if summary["ok"] else 1

if __name__=="__main__":
    raise SystemExit(main())
