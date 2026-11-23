import math
FX=18.6
seed=1000.0
print("seed USD", round(seed/FX,2))
# years to reach earned milestone: seed + realized P&L >= 100000 -> P&L >= 99000 MXN on constant-ish capital C (deposits don't count)
caps=[1000,10000,25000,50000,100000]; rates=[0.05,0.08,0.12,0.20]
print("years table (C rows, r cols):")
for C in caps:
    row=[]
    for r in rates:
        t=math.log(1+99000/C)/math.log(1+r); row.append(round(t,1))
    print(C, row)
# granularity: 8-ETF EW, min order $1 -> smallest correctable drift
for C in [1000,7500,10000,25000]:
    usd=C/FX; pos=usd/8; print("C",C,"usd",round(usd,1),"pos",round(pos,2),"min drift correctable %",round(100/pos,1))
# reg fee penny per sell-day at 12 rebalances/yr
for C in [1000,7500,25000]:
    usd=C/FX; print("C",C,"penny fees/yr % of capital", round(0.12/usd*100,3))
# crypto taker 25bps per side: monthly rebalance 20% turnover one-way per month
print("crypto fee drag %/yr at 20%/mo turnover:", round(12*0.20*0.0025*100,2))
