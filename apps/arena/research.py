"""Read-only research reports and isolated replay of unchanged strategy rules."""
import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from datetime import datetime

import arena as core
import engine03 as engine
from operations import read_db
from strategies import Candle, MultiSnapshot, INTERVALS


def performance(con, start=None, end=None):
    """Common equity timestamps; returns include unrealized positions, exclude API costs."""
    where=[]; params=[]
    for bound,operator in ((start, '>='),(end,'<=')):
        if bound:
            datetime.fromisoformat(bound)
            where.append('ts '+operator+' ?');params.append(bound)
    clause=' WHERE '+' AND '.join(where) if where else ''
    rows=con.execute('SELECT ts,agent,value,cash,btc,eth FROM equity'+clause+' ORDER BY ts,id',params).fetchall()
    grouped={agent:{} for agent in core.AGENTS}
    for row in rows:grouped[row['agent']][row['ts']]=row
    common=set.intersection(*(set(v) for v in grouped.values()))
    if not common:return {'status':'insufficient-common-history','portfolios':[]}
    times=sorted(common);first,last=times[0],times[-1]
    output=[]
    for agent in core.AGENTS:
        points=[grouped[agent][ts] for ts in times]
        values=[float(p['value']) for p in points]
        if any(not math.isfinite(v) or v<=0 for v in values):raise ValueError('Invalid equity series')
        peak=values[0];drawdown=0.
        for value in values:
            peak=max(peak,value);drawdown=max(drawdown,1-value/peak)
        trades=con.execute('SELECT fee,notional FROM trades WHERE agent=? AND ts>? AND ts<=?',(agent,first,last)).fetchall()
        output.append({'agent':agent,'start_equity':values[0],'end_equity':values[-1],
            'net_return_pct':100*(values[-1]/values[0]-1),'max_drawdown_pct':100*drawdown,
            'fees_eur':sum(r['fee'] for r in trades),'trade_count':len(trades),
            'turnover':sum(abs(r['notional']) for r in trades)/values[0],
            'mean_exposure_pct':100*sum((p['value']-p['cash'])/p['value'] for p in points)/len(points),
            'open_btc':points[-1]['btc'],'open_eth':points[-1]['eth']})
    benchmark=next(p['net_return_pct'] for p in output if p['agent']=='buyhold')
    for p in output:p['excess_buyhold_pct']=p['net_return_pct']-benchmark
    return {'status':'ok','start':first,'end':last,'observations':len(times),'portfolios':output,
            'limitations':['API costs not included','Exposure is observation-weighted',
                            'Trades at start are already reflected in starting equity',
                            'Drawdown measured only at shared stored observations']}


def load_replay(path):
    """JSON snapshots must contain only bars closed at the historical observation time."""
    raw=Path(path).read_bytes();records=json.loads(raw)
    previous=None;result=[]
    for record in records:
        at=record['at']
        if isinstance(at,bool) or not isinstance(at,int) or previous is not None and at<=previous:
            raise ValueError('Replay timestamps must strictly increase')
        previous=at;snaps={}
        if set(record['markets'])!=set(core.SYMBOLS):raise ValueError('Both markets required')
        for symbol,data in record['markets'].items():
            frames={int(tf):tuple(Candle(*bar) for bar in bars) for tf,bars in data['bars'].items()}
            if any(bar.ts+tf*60>at for tf,bars in frames.items() for bar in bars):
                raise ValueError('Future or incomplete replay candle')
            snap=MultiSnapshot(symbol,frames,core.Quote(data['bid'],data['ask']),at)
            snap.validate(live=False);snaps[symbol]=snap
        result.append((at,snaps))
    if not result:raise ValueError('Empty replay')
    return result,hashlib.sha256(raw).hexdigest()


def replay(records):
    """Temporary DB only. Existing execution/strategy functions, no LLM/network calls."""
    from datetime import timezone
    with tempfile.TemporaryDirectory(prefix='arena-research-') as folder:
        con=core.open_db(str(Path(folder)/'backtest.sqlite3'))
        try:
            for at,snaps in records:
                when=datetime.fromtimestamp(at,timezone.utc).isoformat(timespec='seconds')
                engine.quant_cycle(con,snaps,demo=True,when=when)
                qs={symbol:snap.quote for symbol,snap in snaps.items()}
                with con:
                    for agent in core.AGENTS:core.mark_and_risk(con,agent,qs,when)
            report=performance(con)
            report['mode']='HISTORICAL REPLAY / VIRTUAL ORDERS / NO LLM'
            report['inactive_agents']=['gpt','claude']
            return report
        finally:con.close()


def walk_forward(records, train_size, test_size):
    """Disjoint test windows; fixed unoptimized strategies; fresh capital per fold."""
    if train_size<1 or test_size<2:raise ValueError('Invalid fold sizes')
    folds=[]
    for index in range(train_size,len(records)-test_size+1,test_size):
        test=records[index:index+test_size]
        folds.append({'train_start':records[index-train_size][0],'train_end':records[index-1][0],
                      'test_start':test[0][0],'test_end':test[-1][0],'report':replay(test)})
    if not folds:raise ValueError('Insufficient records for a fold')
    return folds


def sensitivity(records):
    import os
    from unittest.mock import patch
    results=[]
    for fee in (.001,.0025,.005):
        for slip in (.0001,.0003,.001):
            with patch.dict(os.environ,{'TAKER_FEE':str(fee),'SLIPPAGE':str(slip)}):
                results.append({'fee_rate':fee,'slippage':slip,'report':replay(records)})
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['report','replay','walk-forward','sensitivity'])
    p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--start');p.add_argument('--end')
    p.add_argument('--train',type=int,default=100);p.add_argument('--test',type=int,default=20)
    a=p.parse_args()
    if a.mode=='report':
        con=read_db(a.source)
        try:
            con.execute('BEGIN');result=performance(con,a.start,a.end)
        finally:con.close()
    else:
        records,digest=load_replay(a.source)
        result={'dataset_sha256':digest,'fee_rate':core.fee_rate(),'slippage':core.slip_rate(),
                'result':replay(records) if a.mode=='replay' else sensitivity(records) if a.mode=='sensitivity' else walk_forward(records,a.train,a.test)}
    # Never overwrite another result or a source file.
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)


if __name__=='__main__':main()
