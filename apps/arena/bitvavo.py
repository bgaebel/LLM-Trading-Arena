"""Read-only public Bitvavo data client. Does not support orders or private API auth."""
from __future__ import annotations
import math
import time
from urllib.parse import quote as url_quote, urlencode

import arena as core
from strategies import Candle

API = "https://api.bitvavo.com/v2"
TIMEFRAMES = {1:"1m", 15:"15m", 60:"1h", 240:"4h"}

def quotes():
    # One public request for both pairs, bounded to well under the public rate limit.
    result = {}
    data = core.http_json(API + '/ticker/book')
    if not isinstance(data,list):
        raise ValueError('Bitvavo ticker/book: unerwartetes Datenformat')
    for item in data:
        if not isinstance(item,dict):continue
        for symbol,market in core.PAIRS.items():
            if item.get('market') == market:
                q=core.Quote(float(item['bid']),float(item['ask']))
                q.validate()
                result[symbol]=q
    if set(result)!=set(core.SYMBOLS):
        raise ValueError('Bitvavo ticker/book: BTC-EUR oder ETH-EUR fehlt')
    return result

def fill_tiny_gaps(rows: tuple[Candle,...], interval: int, *, max_missing: int=2):
    """Bounded zero-volume reconstruction for Bitvavo's documented no-trade gaps.

    Larger gaps are preserved and later rejected by the snapshot validator.
    Never interpolate future prices or gaps at the end of the available data.
    Returns (candles, number_of_synthetic_zero_volume_bars).
    """
    if not rows:
        return rows, 0
    step=interval*60
    output=[rows[0]]
    filled=0
    for bar in rows[1:]:
        prior=output[-1]
        delta=bar.ts-prior.ts
        if delta>step and delta%step==0 and (delta//step)-1 <= max_missing:
            for ts in range(prior.ts+step,bar.ts,step):
                output.append(Candle(ts,prior.close,prior.close,prior.close,prior.close,0.))
                filled+=1
        output.append(bar)
    return tuple(output),filled

def closed_candles(symbol: str, interval: int, *,now_epoch: int|None = None):
    if symbol not in core.PAIRS or interval not in TIMEFRAMES:
        raise ValueError('Unbekannter Markt oder Zeitraum')
    now_epoch=int(time.time()) if now_epoch is None else int(now_epoch)
    market=core.PAIRS[symbol]
    url=API+'/'+url_quote(market,safe='')+'/candles?'+urlencode({'interval':TIMEFRAMES[interval],'limit':500})
    rows=core.http_json(url)
    if not isinstance(rows,list):raise ValueError('Bitvavo-Kerzen: Datenformat falsch')
    out=[]
    seen={}
    for row in rows:
        if not isinstance(row,(list,tuple)) or len(row)<6:
            raise ValueError('Bitvavo-Kerzen: unvollständige OHLCV-Zeile')
        ts=int(row[0])//1000
        # Do not leak forming candles into strategies. Also ignore future data.
        if ts + interval*60 > now_epoch:continue
        item=Candle(ts,*map(float,row[1:6]))
        if not all(math.isfinite(x) and x>0 for x in (item.open,item.high,item.low,item.close)):
            raise ValueError('Bitvavo-Kerzen: ungültige Preise')
        if not math.isfinite(item.volume) or item.volume < 0:
            raise ValueError('Bitvavo-Kerzen: ungültiges Volumen')
        if ts % (interval*60):raise ValueError('Misaligned candle timestamp')
        if item.low>min(item.open,item.close) or item.high<max(item.open,item.close,item.low):
            raise ValueError('Invalid OHLC range')
        if ts in seen and seen[ts]!=item:raise ValueError('Conflicting duplicate candle')
        seen[ts]=item
        out.append(item)
    return tuple(sorted({r.ts:r for r in out}.values(),key=lambda r:r.ts))
