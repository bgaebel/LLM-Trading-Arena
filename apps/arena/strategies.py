"""Test hypotheses, not claims of profitable strategies. Closed bars only.
All indicators use pure standard-library Python; no exchange credentials.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import mean, pstdev
from typing import Mapping

INTERVALS = (1, 15, 60, 240)
MIN_BARS = {1: 45, 15: 110, 60: 110, 240: 55}
STRATEGY_TIMEFRAME = {'trend':60,'breakout':15,'meanrev':15,'ensemble':15,'buyhold':1}

@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True)
class MultiSnapshot:
    symbol: str
    bars: Mapping[int, tuple[Candle, ...]]
    quote: object
    fetched_at: int

    @property
    def bar_ts(self):
        return self.bars[1][-1].ts

    def validate(self, *, live=True):
        self.quote.validate()
        for tf in INTERVALS:
            seq = self.bars.get(tf, ())
            if len(seq) < MIN_BARS[tf]:
                raise ValueError(f'{self.symbol}: zu wenige abgeschlossene {tf}m-Kerzen ({len(seq)})')
            if any((not isfinite(x.close) or x.close<=0 or not isfinite(x.volume) or x.volume<0 or
                    x.low<=0 or x.high < max(x.open,x.close,x.low) or x.low>min(x.open,x.close,x.high)) for x in seq):
                raise ValueError(f'{self.symbol}: unplausible {tf}m-Kerzen')
            if any(seq[j].ts >= seq[j+1].ts for j in range(len(seq)-1)):
                raise ValueError(f'{self.symbol}: {tf}m-Zeitstempel nicht streng aufsteigend')
            # Don't treat missing candles as equal time steps (especially RSI/EMA/ADX).
            if any(seq[j+1].ts-seq[j].ts != tf*60 for j in range(len(seq)-min(60,len(seq)),len(seq)-1)):
                raise ValueError(f'{self.symbol}: Lücken in {tf}m-Kerzen – keine Handelsentscheidung')
            if live:
                age = self.fetched_at - (seq[-1].ts + tf*60)
                if age < -90 or age > tf*60+90:
                    raise ValueError(f'{self.symbol}: {tf}m-Daten veraltet / in Zukunft ({age}s)')
        if live and (abs(self.fetched_at-int(datetime.now(timezone.utc).timestamp())) > 120):
            raise ValueError('Zeitstempel ungültig')


def closes(bars): return [c.close for c in bars]

def ema(values, n):
    if not values or n<1: raise ValueError('EMA: keine Daten')
    weight = 2/(n+1)
    out=values[0]
    for v in values[1:]: out = weight*v+(1-weight)*out
    return out

def rsi(values,n=14):
    if len(values)<=n:return 50.
    d = [values[i]-values[i-1] for i in range(len(values)-n,len(values))]
    gain=sum(max(x,0) for x in d)/n
    loss=sum(max(-x,0) for x in d)/n
    if gain+loss == 0:return 50.
    return 100 if loss==0 else 100-100/(1+gain/loss)

def atr(bars,n=14):
    if len(bars)<n+1: return 0.
    rs=[]
    for i in range(len(bars)-n,len(bars)):
        b=bars[i]
        p=bars[i-1].close
        rs.append(max(b.high-b.low, abs(b.high-p), abs(b.low-p)))
    return mean(rs)

def adx(bars,n=14):
    """Wilder ADX, directional indicators using closed candles. Output 0..100."""
    if len(bars)<2*n+2:return (0.,0.,0.)
    tr, pos, neg = [],[],[]
    for i in range(1,len(bars)):
        cur,prev=bars[i],bars[i-1]
        up=cur.high-prev.high
        down=prev.low-cur.low
        pos.append(up if up>down and up>0 else 0.)
        neg.append(down if down>up and down>0 else 0.)
        tr.append(max(cur.high-cur.low,abs(cur.high-prev.close),abs(cur.low-prev.close)))
    tr_s=sum(tr[:n]); pos_s=sum(pos[:n]); neg_s=sum(neg[:n])
    dx=[]
    def compute():
        pdi=100*pos_s/tr_s if tr_s else 0
        ndi=100*neg_s/tr_s if tr_s else 0
        return pdi,ndi,100*abs(pdi-ndi)/(pdi+ndi) if pdi+ndi else 0
    pdi,ndi,v=compute();dx.append(v)
    for i in range(n,len(tr)):
        tr_s=tr_s-tr_s/n+tr[i]
        pos_s=pos_s-pos_s/n+pos[i]
        neg_s=neg_s-neg_s/n+neg[i]
        pdi,ndi,v=compute();dx.append(v)
    strength=mean(dx[:n])
    for value in dx[n:]: strength=(strength*(n-1)+value)/n
    return (strength,pdi,ndi)


def indicators(s: MultiSnapshot, roundtrip_cost_frac: float):
    v15=closes(s.bars[15]);v60=closes(s.bars[60]);v240=closes(s.bars[240])
    sd=pstdev(v15[-20:]); avg=mean(v15[-20:])
    a,pdi,ndi=adx(s.bars[60]);a1=atr(s.bars[60]);a15=atr(s.bars[15])
    e24,e72=ema(v60,24),ema(v60,72)
    e12_4h,e30_4h=ema(v240,12),ema(v240,30)
    regime='TREND' if a>=22 else 'RANGE' if a<18 else 'TRANSITION'
    return {
      'regime':regime,'adx_1h':a,'plus_di_1h':pdi,'minus_di_1h':ndi,
      'ema24_1h':e24,'ema72_1h':e72,'ema12_4h':e12_4h,'ema30_4h':e30_4h,
      'rsi14_15m':rsi(v15), 'sma20_15m':avg,'std20_15m':sd,
      'z20_15m': (v15[-1]-avg)/sd if sd>0 else 0,
      'atr14_1h_pct':a1/v60[-1], 'atr14_15m_pct':a15/v15[-1],
      'close_15m':v15[-1], 'close_1h':v60[-1], 'close_4h':v240[-1],
      'high_48h_excl_current':max(b.high for b in s.bars[60][-49:-1]),
      'low_48h_excl_current':min(b.low for b in s.bars[60][-49:-1]),
      'volume15_latest':s.bars[15][-1].volume,
      'volume15_mean20_prior':mean(b.volume for b in s.bars[15][-21:-1]),
      'roundtrip_cost_pct':roundtrip_cost_frac*100,
    }


def signal(action, reason, confidence=0.7, target=None):
    return dict(action=action, target_fraction=(.45 if action=='BUY' else 0.) if target is None else target,
                confidence=confidence,reason=reason)


def run_strategy(name: str, s: MultiSnapshot, i: dict, current_weight:float=0.):
    # These fixed parameters are experimental starting points, not optimized coefficients.
    a=i['adx_1h']
    up = i['close_1h']>i['ema24_1h']>i['ema72_1h'] and i['ema12_4h']>i['ema30_4h']
    down = i['ema24_1h']<i['ema72_1h'] and i['ema12_4h']<i['ema30_4h']
    cost=i['roundtrip_cost_pct']/100
    if name=='trend':
        if up and a>=20 and i['plus_di_1h']>i['minus_di_1h']:
            return signal('BUY',f'1h/4h-Aufwärtstrend; ADX {a:.1f}; nur abgeschlossene Kerzen')
        if down or (current_weight>.02 and i['close_1h']<i['ema72_1h']):
            return signal('SELL','1h/4h-Abwärtstrend oder 1h-Kurs unter EMA72')
        return signal('HOLD','Keine eindeutige 1h/4h-Trendbestätigung')
    if name=='breakout':
        last=i['close_15m'];high=i['high_48h_excl_current']
        vol_ok=i['volume15_mean20_prior']>0 and i['volume15_latest']/i['volume15_mean20_prior']>=1.25
        # ATR is NOT a forecast. Only used as a heuristic no-trade check relative to costs.
        movement_sufficient=i['atr14_1h_pct']*4 > cost
        if last>high*1.001 and a>=19 and vol_ok and movement_sufficient:
            return signal('BUY',f'15m-Ausbruch über 48h-Hoch; ADX {a:.1f}; Volumenbestätigung')
        if current_weight>.02 and (last<ema(closes(s.bars[15]),34) or last<i['low_48h_excl_current']):
            return signal('SELL','Ausbruch verloren; 15m-Kurs unter EMA34 / 48h-Tief')
        return signal('HOLD','Kein bestätigter Breakout (48h-Hoch/Volumen/Volatilität)')
    if name=='meanrev':
        last=i['close_15m'];sd=i['std20_15m'];mid=i['sma20_15m']
        # Entry only AFTER first rebound from an oversold close, never buy blindly while falling.
        prior=closes(s.bars[15])[-21:-1]
        prev_mid=mean(prior);prev_sd=pstdev(prior)
        oversold_prev = prev_sd>0 and s.bars[15][-2].close < prev_mid-2*prev_sd
        turned = last>s.bars[15][-2].close
        distance_to_mean=(mid-last)/last if last>0 else 0
        range_ok = a<18 and abs(i['ema24_1h']/i['ema72_1h']-1)<.012
        if current_weight>.02 and (last>mid-.25*sd or a>24 or i['rsi14_15m']>66):
            return signal('SELL','Rückkehr zum Mittelwert / Seitwärtsregime beendet')
        if range_ok and oversold_prev and turned and i['rsi14_15m']<42 and distance_to_mean>cost*1.25:
            return signal('BUY',f'15m-Erholung nach Übertreibung, ADX {a:.1f}; Distanz zum Mittelwert {distance_to_mean*100:.1f}%')
        return signal('HOLD','Keine gebührenrobuste Rückkehr-zum-Mittelwert-Konstellation')
    if name=='ensemble':
        tr=run_strategy('trend',s,i,current_weight)
        br=run_strategy('breakout',s,i,current_weight)
        mr=run_strategy('meanrev',s,i,current_weight)
        weights=({'trend':.60,'breakout':.30,'meanrev':.10} if i['regime']=='TREND' else
                 {'trend':.20,'breakout':.15,'meanrev':.65} if i['regime']=='RANGE' else
                 {'trend':.45,'breakout':.35,'meanrev':.20})
        votes={'trend':tr['action'],'breakout':br['action'],'meanrev':mr['action']}
        score=sum(weights[k]*({'BUY':1,'SELL':-1,'HOLD':0}[v]) for k,v in votes.items())
        reason=f"{i['regime']} ADX {a:.1f} | Score {score:+.2f} | Trend={tr['action']}, Breakout={br['action']}, MR={mr['action']}"
        if score>=.55 and i['atr14_1h_pct']*4>cost:
            return signal('BUY',reason,confidence=min(1.,abs(score)))
        if score<=-.40 and current_weight>.02:
            return signal('SELL',reason,confidence=min(1.,abs(score)))
        return signal('HOLD',reason,confidence=min(1.,abs(score)))
    if name=='buyhold':return signal('BUY','Passiver Vergleich; einmalig kaufen und halten')
    raise ValueError('Unbekannte Strategie: '+name)


def feature_payload(s, i, current_weight, fee_rate, slippage):
    """Compact, grounded LLM context. The LLM receives no invented news."""
    current=s.quote.mid
    return {
      'market':s.symbol, 'utc':datetime.fromtimestamp(s.fetched_at,timezone.utc).isoformat(),
      'closed_bars_utc':{str(tf):datetime.fromtimestamp(s.bars[tf][-1].ts,timezone.utc).isoformat() for tf in INTERVALS},
      'quote_bid':s.quote.bid,'quote_ask':s.quote.ask,'quote_spread_bps':round(s.quote.spread_bps,2),
      'latest_completed_1m_close':s.bars[1][-1].close,
      'filled_no_trade_1m_intervals_last_60':sum(b.volume==0 for b in s.bars[1][-60:]),
      'data_quality_note':'Missing 1m OHLCV rows may be filled (maximum 2 adjacent zero-volume minutes) with previous close; larger/recent stale gaps block signals',
      'returns_pct':{str(minutes):round(100*(current/closes(s.bars[tf])[-1-n]-1),3)
                     for minutes,tf,n in ((15,1,15),(60,15,4),(240,60,4),(1440,60,24))},
      'indicators':{k:round(v,5) if isinstance(v,float) else v for k,v in i.items()},
      'reference_signals':{name:run_strategy(name,s,i,current_weight)['action']
                           for name in ('trend','breakout','meanrev')},
      'current_weight':round(current_weight,4),'per_asset_max':.45,
      'allowed_weights':[0,.25,.45],
      'taker_fee_per_side_pct':round(100*fee_rate,3),'slippage_per_side_pct':round(100*slippage,3),
      'scope':'Only these quotes and completed OHLCV bars; no external news or order book in this version',
    }
