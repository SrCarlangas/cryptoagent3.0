"""Frozen 1h BAR_PROXY screening for EVIDENCE-V3.

This deliberately cannot PASS the production gate because 1m, aggTrade and BBO
history aren't available. It can reject the strategy early and quantifies the
sample/return/drawdown benchmark without pretending runtime parity.
"""
# ruff: noqa: E701, E702, F401, I001
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from research.engine import Candle, load_candles
from btc_decision_agent.policies.evidence_v3 import COST_MODEL_VERSION, PARAMETER_VERSION, STRATEGY_VERSION

D=Decimal
COST_BPS=D("74.242622")
ALLOC=min(D("0.80"),D("0.02")/D("0.03"))

@dataclass(frozen=True)
class ProxyTrade:
    entry_time:str; exit_time:str; entry:str; exit:str; gross_return:str; net_portfolio_return:str; reason:str


def conf(score:Decimal)->Decimal:
    return D(str(1/(1+math.exp(-1.8*max(-4,min(4,float(score)))))))

def clipped(ret:Decimal,scale:Decimal)->Decimal:
    return max(D("-2"),min(D("2"),ret/scale))

def ret(p:list[Decimal],i:int,k:int)->Decimal:
    return (p[i]/p[i-k]-1)*10000

def run(c:list[Candle],start:int)->tuple[list[ProxyTrade],list[Decimal],list[Decimal]]:
    p=[x.close for x in c]; trades=[]; curve=[]; bh=[]
    equity=D(1); inpos=False; entry=D(0); entry_i=0; high=D(0); pending_buy=False; pending_sell=False; cooldown=-1
    for i in range(max(720,start),len(c)-1):
        r1,r4,r24,r168,r720=(ret(p,i,k) for k in (1,4,24,168,720))
        structural=conf(D('.25')*clipped(r4,D(150))+D('.30')*clipped(r24,D(300))+D('.30')*clipped(r168,D(700))+D('.15')*clipped(r720,D(1500)))
        tactical_raw=D('.70')*r1+D('.30')*r4
        tactical=conf(D('.70')*clipped(r1,D(75))+D('.30')*clipped(r4,D(150)))
        edge=tactical_raw-D(30)
        if inpos:
            high=max(high,c[i].high); stop=entry*(1-D('.03'))
            if high>=entry*(1+D('.015')): stop=max(stop,high*(1-D('.025')))
            reason=None; exit_price=None
            if c[i].low<=stop: reason="STOP_PROXY"; exit_price=stop
            else:
                signal=tactical<=D('.42') or edge<=D('-10')
                if signal and pending_sell: reason="TACTICAL_PROXY"; exit_price=c[i+1].open
                pending_sell=signal
            if reason:
                gross=exit_price/entry-1; net=ALLOC*(gross-COST_BPS/10000); equity*=1+net
                trades.append(ProxyTrade(c[entry_i].open_time.isoformat(),c[i+1].open_time.isoformat(),str(entry),str(exit_price),str(gross),str(net),reason))
                inpos=False; cooldown=i+1; pending_sell=False
        else:
            signal=structural>=D('.72') and tactical>=D('.60') and edge>=D(10) and i>cooldown
            if signal and pending_buy:
                entry=c[i+1].open; entry_i=i+1; high=entry; inpos=True; pending_buy=False
            else: pending_buy=signal
        curve.append(equity*(1+ALLOC*(p[i]/entry-1)) if inpos else equity)
        bh.append(p[i]/p[max(720,start)])
    return trades,curve,bh

def maxdd(curve:list[Decimal])->Decimal:
    peak=D(1); dd=D(0)
    for x in curve: peak=max(peak,x); dd=max(dd,(peak-x)/peak)
    return dd

def main()->None:
    candles=list(load_candles("1h")); cut=int(len(candles)*.60)
    trades,curve,bh=run(candles,cut); nets=[D(t.net_portfolio_return) for t in trades]
    fold=[]
    for f in range(5):
        a=cut+(len(candles)-cut)*f//5; b=cut+(len(candles)-cut)*(f+1)//5
        values=[D(t.net_portfolio_return) for t in trades if a<=next(i for i,x in enumerate(candles) if x.open_time.isoformat()==t.entry_time)<b]
        fold.append(sum(values,D(0)))
    positive=D(sum(x>0 for x in fold))/D(5)
    strategy=curve[-1]-1 if curve else D(0); buyhold=bh[-1]-1 if bh else D(0)
    reasons=["DATA_PARITY_FAIL_BAR_PROXY"]
    if len(trades)<100: reasons.append("INSUFFICIENT_EFFECTIVE_SAMPLE")
    if strategy<=0: reasons.append("DELTA_UTILITY_BELOW_MARGIN")
    if positive<D('.70'): reasons.append("FOLD_STABILITY_FAIL")
    if strategy<=buyhold: reasons.append("BEHIND_BUY_AND_HOLD")
    report={"strategy_version":STRATEGY_VERSION,"parameter_version":PARAMETER_VERSION,"cost_model_version":COST_MODEL_VERSION,"evidence_class":"BAR_PROXY_NON_PROMOTABLE","dataset_id":"sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73","oos_start":candles[cut].open_time.isoformat(),"oos_end":candles[-1].close_time.isoformat(),"completed_trades":len(trades),"strategy_return":str(strategy),"buy_hold_return":str(buyhold),"excess_return":str(strategy-buyhold),"max_drawdown":str(maxdd(curve)),"positive_fold_ratio":str(positive),"fold_returns":[str(x) for x in fold],"win_rate":str(D(sum(x>0 for x in nets))/D(len(nets)) if nets else 0),"passed":False,"reasons":reasons,"trades":[asdict(t) for t in trades]}
    out=Path("data/validation"); out.mkdir(parents=True,exist_ok=True); (out/"evidence-v3-bar-proxy-report.json").write_text(json.dumps(report,indent=2)+"\n")
    md=f"# EVIDENCE-V3 BAR_PROXY report\n\n- Verdict: **NO_GO / NON_PROMOTABLE**\n- Trades: {len(trades)}\n- Strategy: {strategy*100:.2f}%\n- Buy & hold: {buyhold*100:.2f}%\n- Excess: {(strategy-buyhold)*100:.2f}%\n- Max drawdown: {maxdd(curve)*100:.2f}%\n- Positive folds: {positive:.2f}\n- Reasons: {', '.join(reasons)}\n\nThis is a coarse 1h rejection screen, not runtime-parity OOS evidence.\n"
    (out/"evidence-v3-bar-proxy-report.md").write_text(md)
    print(md)
if __name__=="__main__": main()
