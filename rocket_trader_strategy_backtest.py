#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rocket Trader — OOS walk-forward strategy backtest. PAPER/RESEARCH ONLY."""
from __future__ import annotations
import argparse,json,math
from dataclasses import dataclass,asdict
from typing import List,Tuple
import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed
from rocket_trader_market_data import AlpacaMarketDataClient
from rocket_trader_engine import EngineConfig,EnsembleModel,FeatureEngine,FEATURE_COLUMNS,MarketDataValidator
VERSION="0.1"; DEFAULT_DAYS=30; MIN_TRAIN_ROWS=3000; TEST_BLOCK_ROWS=1000; MAX_FOLDS=5
DEFAULT_THRESHOLDS=[.05,.07,.10,.12,.15,.20,.25]
@dataclass
class Trade:
    symbol:str; entry_timestamp:str; exit_timestamp:str; entry_price:float; exit_price:float; probability_up:float; gross_return:float; net_return:float
@dataclass
class Metrics:
    threshold:float; trades:int; win_rate:float; avg_return:float; median_return:float; total_return:float; profit_factor:float; max_drawdown:float; sharpe:float; best_trade:float; worst_trade:float

def fetch(symbol:str,days:int)->pd.DataFrame:
    c=AlpacaMarketDataClient(feed=DataFeed.IEX); bars=c.get_recent_bars(symbol=symbol,minutes=max(days*1440,10080))
    if not bars: raise RuntimeError(f"Alpaca no devolvió barras para {symbol}")
    return MarketDataValidator.normalize(pd.DataFrame([{"timestamp":b.timestamp,"open":b.open,"high":b.high,"low":b.low,"close":b.close,"volume":b.volume} for b in bars]))

def train_xy(f:pd.DataFrame,cfg:EngineConfig,end:int)->Tuple[pd.DataFrame,pd.Series]:
    end=max(0,end-cfg.horizon_bars); p=f.iloc[:end].copy(); fut=p.close.shift(-cfg.horizon_bars)/p.close-1; y=(fut>=cfg.target_return).astype(int); ok=p[FEATURE_COLUMNS].notna().all(axis=1)&fut.notna(); X,y=p.loc[ok,FEATURE_COLUMNS],y.loc[ok]
    if len(X)<cfg.min_training_rows or y.nunique()<2: raise RuntimeError(f"Training insuficiente o una sola clase: rows={len(X)}")
    if len(X)>cfg.max_training_rows: X,y=X.iloc[-cfg.max_training_rows:],y.iloc[-cfg.max_training_rows:]
    return X.reset_index(drop=True),y.reset_index(drop=True)

def walk_forward(raw:pd.DataFrame,cfg:EngineConfig)->pd.DataFrame:
    f=FeatureEngine.build(raw); n=len(f); train_end=min(max(MIN_TRAIN_ROWS,cfg.min_training_rows),n); out=[]; fold=0
    while train_end<n and fold<MAX_FOLDS:
        test_end=min(train_end+TEST_BLOCK_ROWS,n); X,y=train_xy(f,cfg,train_end); m=EnsembleModel(cfg); m.fit(X,y); b=f.iloc[train_end:test_end].copy(); ok=b[FEATURE_COLUMNS].notna().all(axis=1); b=b.loc[ok].copy()
        if not b.empty:
            p,_=m.predict_proba(b[FEATURE_COLUMNS]); b["probability_up"]=np.asarray(p,dtype=float); b["fold"]=fold+1; out.append(b)
        train_end=test_end; fold+=1
    if not out: raise RuntimeError("No se generaron predicciones OOS.")
    return pd.concat(out).sort_index()

def simulate(pred:pd.DataFrame,symbol:str,threshold:float,horizon:int,cost:float,slippage:float)->Tuple[Metrics,List[Trade]]:
    r=pred.sort_index().reset_index(); idx=r.columns[0]; trades=[]; i=0
    while i<len(r):
        p=float(r.iloc[i].probability_up)
        if p<threshold: i+=1; continue
        ei=int(r.iloc[i][idx]); xi=ei+horizon; future=r[r[idx]==xi]
        if future.empty: break
        ex=future.iloc[0]; entry=float(r.iloc[i].close); exit_=float(ex.close); gross=exit_/entry-1; net=gross-cost-slippage
        trades.append(Trade(symbol,str(r.iloc[i].timestamp),str(ex.timestamp),entry,exit_,p,gross,net))
        pos=r.index[r[idx]==xi]; i=int(pos[0])+1 if len(pos) else i+1
    a=np.asarray([t.net_return for t in trades],dtype=float)
    if not len(a): return Metrics(threshold,0,0,0,0,0,0,0,0,0,0),trades
    eq=np.cumprod(1+a); dd=eq/np.maximum.accumulate(eq)-1; gains=a[a>0].sum(); losses=-a[a<0].sum(); pf=float(gains/losses) if losses>0 else float("inf"); sd=float(np.std(a,ddof=1)) if len(a)>1 else 0; sh=float(np.mean(a)/sd*math.sqrt(len(a))) if sd>0 else 0
    return Metrics(threshold,len(a),float(np.mean(a>0)),float(np.mean(a)),float(np.median(a)),float(eq[-1]-1),pf,float(dd.min()),sh,float(a.max()),float(a.min())),trades

def evaluate(symbol,days,thresholds,cost,slippage):
    raw=fetch(symbol,days); cfg=EngineConfig(target_return=.001,horizon_bars=5,min_training_rows=300,max_training_rows=5000,probability_threshold=.50); pred=walk_forward(raw,cfg); results=[]; samples={}
    for t in thresholds:
        m,tr=simulate(pred,symbol,t,cfg.horizon_bars,cost,slippage); results.append(asdict(m)); samples[str(t)]=[asdict(x) for x in tr[:25]]
    qualified=[x for x in results if x["trades"]>=20 and x["total_return"]>0 and x["profit_factor"]>1]; best=max(qualified or results,key=lambda x:(x["profit_factor"],x["total_return"],x["sharpe"])); bh=float(pred.iloc[-1].close/pred.iloc[0].close-1)
    return {"symbol":symbol,"days_requested":days,"raw_bars":len(raw),"oos_predictions":len(pred),"folds":int(pred.fold.nunique()),"target_return":cfg.target_return,"horizon_bars":cfg.horizon_bars,"round_trip_cost":cost,"slippage":slippage,"buy_hold_return":bh,"thresholds":results,"best_threshold":best["threshold"],"research_pass":bool(qualified),"reason":"OOS threshold con trades>=20, retorno>0 y profit_factor>1." if qualified else "No threshold cumple todavía los criterios mínimos de expectativa.","sample_trades":samples[str(best["threshold"])],"orders_enabled":False,"orders_submitted":0}

def self_test():
    rng=np.random.default_rng(42); n=5000; ts=pd.date_range("2025-01-01",periods=n,freq="min",tz="UTC"); close=100*np.exp(np.cumsum(rng.normal(0,.001,n))); op=close*(1+rng.normal(0,.0002,n)); sp=np.abs(rng.normal(.0008,.0002,n)); raw=pd.DataFrame({"timestamp":ts,"open":op,"high":np.maximum(op,close)*(1+sp),"low":np.minimum(op,close)*(1-sp),"close":close,"volume":rng.lognormal(10,.3,n)}); f=FeatureEngine.build(MarketDataValidator.normalize(raw)); assert len(f)==n and all(c in f.columns for c in FEATURE_COLUMNS); return {"ok":True,"version":VERSION,"pipeline":"rocket_trader_strategy_backtest","mode":"PAPER_ONLY","orders_enabled":False,"orders_submitted":0,"features_rows":len(f)}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); p.add_argument("--symbols",nargs="+",default=["SPY","QQQ"]); p.add_argument("--days",type=int,default=DEFAULT_DAYS); p.add_argument("--thresholds",nargs="+",type=float,default=DEFAULT_THRESHOLDS); p.add_argument("--friction",type=float,default=.00020); p.add_argument("--slippage",type=float,default=.00010); a=p.parse_args()
    print("="*72); print(f"ROCKET TRADER — STRATEGY WALK-FORWARD BACKTEST v{VERSION}"); print("="*72); print("MODE: PAPER / RESEARCH ONLY"); print("LIVE ORDERS: DISABLED"); print("ORDER SUBMISSION: DISABLED"); print("="*72)
    if a.self_test: print(json.dumps(self_test(),indent=2)); print("ROCKET TRADER STRATEGY BACKTEST SELF-TEST: OK"); return 0
    if a.days<15 or any(t<=0 or t>=1 for t in a.thresholds): print("ERROR: days >= 15 y thresholds entre 0 y 1 son requeridos"); return 1
    results=[]; failures=[]
    for s in [x.upper() for x in a.symbols]:
        try: r=evaluate(s,a.days,a.thresholds,a.friction,a.slippage); results.append(r); print(json.dumps(r,indent=2,ensure_ascii=False))
        except Exception as e: failures.append({"symbol":s,"error":f"{type(e).__name__}: {e}"}); print(json.dumps(failures[-1],indent=2))
    summary={"ok":bool(results) and not failures,"version":VERSION,"pipeline":"rocket_trader_strategy_backtest","mode":"PAPER_ONLY","orders_enabled":False,"orders_submitted":0,"symbols_processed":[r["symbol"] for r in results],"symbols_failed":[x["symbol"] for x in failures],"research_pass":bool(results) and all(r["research_pass"] for r in results),"failures":failures}; print(json.dumps(summary,indent=2,ensure_ascii=False)); print("ROCKET TRADER STRATEGY BACKTEST: OK" if summary["ok"] else "ROCKET TRADER STRATEGY BACKTEST: FAIL"); return 0 if summary["ok"] else 1
if __name__=="__main__": raise SystemExit(main())
