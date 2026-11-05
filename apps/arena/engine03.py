"""v0.3: multi-timeframe paper-trading research engine (NO REAL ORDER PATHS)."""
from __future__ import annotations
import json
import math
import os
import random
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import arena as core
from strategies import (Candle, INTERVALS, MultiSnapshot, STRATEGY_TIMEFRAME,
                        indicators, feature_payload, run_strategy)

QUANT_AGENTS = ('trend','breakout','meanrev','ensemble','buyhold')
LLM_AGENTS = ('gpt','claude')
from bitvavo import closed_candles as bitvavo_closed_candles, fill_tiny_gaps

def live_snapshots(cache:dict, quote_fetcher=None, candle_fetcher=bitvavo_closed_candles,
                   now_epoch:int|None=None, on_error=None) -> dict[str,MultiSnapshot]:
    """Use completed bars; isolate per-market failures instead of stopping both assets.

    on_error(symbol, exception) is only used in the live worker; the default
    remains fail-fast so tests and manual invocations expose data faults.
    """
    now_epoch=int(time.time()) if now_epoch is None else int(now_epoch)
    if quote_fetcher is None:
        from bitvavo import quotes
        quote_fetcher = lambda symbol: quotes()[symbol]
    snapshots={}
    for symbol in core.SYMBOLS:
        try:
            bars={}
            for tf in INTERVALS:
                key=(symbol,tf)
                expected=(now_epoch//(tf*60)-1)*tf*60
                latest=cache.get(key)
                if latest is None or not latest or latest[-1].ts<expected:
                    latest=candle_fetcher(symbol,tf)
                    # Bitvavo explicitly omits no-trade intervals. Reconstruct
                    # at most two consecutive absent minutes, using the last
                    # observed close and zero volume; larger gaps fail closed.
                    latest,_=fill_tiny_gaps(tuple(latest),tf,max_missing=2 if tf==1 else 0)
                    cache[key]=latest
                bars[tf]=latest
            q=quote_fetcher(symbol)
            snap=MultiSnapshot(symbol,bars,q,now_epoch)
            snap.validate(live=True)
            snapshots[symbol]=snap
        except Exception as exc:
            if on_error is None:
                raise
            on_error(symbol, exc)
    return snapshots


def cost_roundtrip(snap:MultiSnapshot):
    return 2*(core.fee_rate()+core.slip_rate()) + snap.quote.spread_bps/10000


def record_decision(con:sqlite3.Connection, agent:str, symbol:str, bar_ts:int, model:str,
                    sig:dict, data:dict, status='OK', now:str|None=None, qs:dict|None=None, *,demo=False):
    """Safe persist + optional virtual trade; fails closed on stale/missing quotes."""
    with con:
        con.execute("BEGIN IMMEDIATE")
        when=now or core.utcnow()
        p=core.balance(con,agent)
        sig=core.validate_signal(sig) if status=='OK' else sig
        action=sig['action'];target=sig['target_fraction']
        if status=='OK':
            if qs is None or set(qs)!=set(core.SYMBOLS):
                status='STALE_QUOTE';action='HOLD';target=0
            else:
                current=core.current_weight(p,symbol,qs)
                if action=='HOLD':target=current
                if action=='BUY' and target<current:target=current
                if action=='SELL' and target>current:target=current
                if agent=='buyhold' and p['btc' if symbol=='BTCEUR' else 'eth'] > 0:
                    action='HOLD';target=current
        cursor=con.execute('''INSERT OR IGNORE INTO decisions
          (ts,agent,symbol,bar_ts,model,action,target,confidence,reason,inputs,status)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
          (when,agent,symbol,bar_ts,model,action,target,sig.get('confidence',0.),
           sig['reason'],json.dumps(data,ensure_ascii=False),status))
        if cursor.rowcount and status=='OK' and action!='HOLD' and not p['halted']:
            core.trade_to_target(con,agent,symbol,target,qs,cursor.lastrowid,executed_at=when)
            core.mark_and_risk(con,agent,qs,when)
        return cursor.rowcount>0



def initialize_buyhold(con:sqlite3.Connection, qs:dict, *, when:str|None=None, demo=False) -> int:
    """Bootstrap BTC and ETH benchmark from FRESH bid/ask quotes, not candle history.

    This is intentionally independent of strategy snapshots and LLM availability.
    Durable per-symbol decisions prevent duplicate purchases across restarts.
    """
    if set(qs) != set(core.SYMBOLS):
        raise ValueError('Buy & Hold: beide frischen Geld-/Briefkurse erforderlich')
    for quote in qs.values():
        quote.validate()
    count = 0
    for symbol in core.SYMBOLS:
        # Also respect existing v0.3 trade history if the user reuses a DB.
        has_trade = con.execute(
            'SELECT 1 FROM trades WHERE agent=? AND symbol=? AND side=? LIMIT 1',
            ('buyhold', symbol, 'BUY')).fetchone()
        if has_trade:
            continue
        # Separate sentinel key (-1) from candle decisions: stable over restarts.
        context = {'strategy':'buy_and_hold', 'source':'SYNTHETIC-DEMO' if demo else 'BITVAVO-LIVE-QUOTE',
                   'initial_allocation_pct':45, 'requires_candles':False,
                   'bid':qs[symbol].bid, 'ask':qs[symbol].ask}
        sig = {'action':'BUY', 'target_fraction':.45, 'confidence':1.,
               'reason':'Passiver Benchmark: einmaliger Kauf auf frischem Geld-/Briefkurs'}
        if record_decision(con, 'buyhold',symbol,-1,'BUY&HOLD',sig,context,
                           qs=qs,now=when):
            count += 1
    return count


def update_market(con:sqlite3.Connection, snaps:dict, demo=False, when:str|None=None):
    now=when or core.utcnow()
    with con:
        for symbol,snap in snaps.items():
            q=snap.quote
            if demo:
                con.execute('''INSERT INTO market(symbol,ts,bar_ts,bid,ask,last_close,source)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                  ts=excluded.ts,bar_ts=excluded.bar_ts,bid=excluded.bid,ask=excluded.ask,
                  last_close=excluded.last_close,source=excluded.source''',
                  (symbol,now,snap.bar_ts,q.bid,q.ask,snap.bars[1][-1].close,'SYNTHETIC-DEMO'))
            else:
                con.execute('''UPDATE market SET bar_ts=?,last_close=? WHERE symbol=?''',
                            (snap.bar_ts,snap.bars[1][-1].close,symbol))


def quant_cycle(con:sqlite3.Connection, snaps:dict, *,demo=False, when:str|None=None) -> int:
    """One decision only on new CLOSED bars of each strategy's own timeframe."""
    if not snaps or not set(snaps).issubset(core.SYMBOLS):
        raise ValueError('Keine gültigen Strategie-Märkte')
    # The live risk engine always requires both current market quotes, even if
    # candle data are only available for one market.
    qs=({s:snaps[s].quote for s in core.SYMBOLS}
        if demo and set(snaps)==set(core.SYMBOLS)
        else core.latest_quotes(con,max_age_seconds=20))
    if qs is None:
        raise RuntimeError('Market quotes fehlen oder veraltet: keine neuen Orders')
    count=initialize_buyhold(con,qs,when=when,demo=True) if demo else 0
    for snap in snaps.values():snap.validate(live=not demo)
    update_market(con,snaps,demo=demo,when=when)
    for symbol,snap in snaps.items():
        analysis=indicators(snap,cost_roundtrip(snap))
        for agent in QUANT_AGENTS:
            if agent == 'buyhold':
                continue  # Independently initialized as soon as fresh quotes arrive.
            tf=STRATEGY_TIMEFRAME[agent]
            bar_ts=snap.bars[tf][-1].ts
            exists=con.execute('SELECT 1 FROM decisions WHERE agent=? AND symbol=? AND bar_ts=?',
                              (agent,symbol,bar_ts)).fetchone()
            if exists:continue
            p=core.balance(con,agent)
            if p['halted']:continue
            weight=core.current_weight(p,symbol,qs)
            sig=run_strategy(agent,snap,analysis,weight)
            context=feature_payload(snap,analysis,weight,core.fee_rate(),core.slip_rate())
            if record_decision(con,agent,symbol,bar_ts,agent.upper(),sig,context,qs=qs,
                               demo=demo,now=when):count+=1
    return count


def llm_due(con,agent,symbol,mid,now_epoch=None):
    now_epoch=time.time() if now_epoch is None else now_epoch
    row=con.execute('SELECT ts,ref_mid FROM llm_calls WHERE agent=? AND symbol=? ORDER BY id DESC LIMIT 1',
                    (agent,symbol)).fetchone()
    if not row:return True
    previous=datetime.fromisoformat(row['ts']).timestamp()
    elapsed=max(0,now_epoch-previous)
    interval=max(600,int(os.getenv('LLM_MIN_INTERVAL_SECONDS','1800')))
    if elapsed>=interval:return True
    event_delay=max(300,int(os.getenv('LLM_EVENT_COOLDOWN_SECONDS','600')))
    threshold=max(.005,float(os.getenv('LLM_EVENT_MOVE_THRESHOLD','.018')))
    return elapsed>=event_delay and row['ref_mid']>0 and abs(mid/row['ref_mid']-1)>=threshold


def llm_cycle(con:sqlite3.Connection,snaps:dict, *,llm_fn=core.llm_signal,
              now_epoch:float|None=None, stop_event=None) -> int:
    """LLM worker separate from quote and quant workers; max budget counts ATTEMPTS."""
    if not snaps or not set(snaps).issubset(core.SYMBOLS):return 0
    now_epoch=time.time() if now_epoch is None else now_epoch
    # A missing ETH candle does not stop BTC's LLM, but all portfolio exposure
    # must still be valued using TWO fresh market quotes.
    qs_live=core.latest_quotes(con,max_age_seconds=20)
    if qs_live is None:return 0
    total=0
    for agent in LLM_AGENTS:
        key=os.getenv('OPENAI_API_KEY' if agent=='gpt' else 'ANTHROPIC_API_KEY')
        if not key:continue
        max_calls=max(0,int(os.getenv('MAX_DAILY_LLM_CALLS','60')))
        for symbol,snap in snaps.items():
            if stop_event is not None and stop_event.is_set(): return total
            qs_live=core.latest_quotes(con,max_age_seconds=20)
            if qs_live is None:return total
            if time.time()-snap.fetched_at>120:continue
            # Expired snapshots and stalled market feed must NOT initiate LLM requests.
            if now_epoch - snap.fetched_at > 120 or snap.fetched_at-now_epoch>10:continue
            if not llm_due(con,agent,symbol,snap.quote.mid,now_epoch):continue
            used=con.execute('SELECT COUNT(*) FROM llm_calls WHERE agent=? AND ts>=?',
                             (agent,datetime.fromtimestamp(now_epoch,timezone.utc).strftime('%Y-%m-%d'))).fetchone()[0]
            if used>=max_calls:continue
            p=core.balance(con,agent)
            if p['halted']:continue
            reserved=False
            sent=False
            try:
                analysis=indicators(snap,cost_roundtrip(snap))
                context=feature_payload(snap,analysis,core.current_weight(p,symbol,qs_live),
                                        core.fee_rate(),core.slip_rate())
                # Reserve quota BEFORE the network call: errors/timeouts also count.
                with con:
                    cursor=con.execute('INSERT INTO llm_calls(ts,agent,symbol,ref_mid,status) VALUES(?,?,?,?,?)',
                                       (datetime.fromtimestamp(now_epoch,timezone.utc).isoformat(timespec='seconds'),agent,
                                        symbol,snap.quote.mid,'PENDING'))
                    attempt=cursor.lastrowid
                from budget import reserve, settle
                from provenance import reserve_snapshot, take_usage
                reserve(con,attempt,agent,now_epoch)
                reserved=True
                audit=reserve_snapshot(con,attempt,agent,context,snap)
                take_usage()  # Do not attribute usage from an earlier attempt.
                request_started=time.monotonic()
                returned=False
                try:
                    sent=True
                    sig,model=llm_fn(agent,context)
                    returned=True
                finally:
                    usage=take_usage()
                    receipt=settle(con,attempt,usage,'response_received' if returned else 'request_failed',
                                   time.monotonic()-request_started)
                audit['token_usage']=usage
                audit['api_cost_eur']=receipt['estimated_cost_eur']
                audit['budget_charge_eur']=receipt['charge_eur']
                audit['latency_seconds']=time.monotonic()-request_started
                context=dict(context,_audit=audit)
                if stop_event is not None and stop_event.is_set():
                    with con: con.execute('UPDATE llm_calls SET status=? WHERE id=?',('CANCELLED',attempt))
                    return total
                sig=core.validate_signal(sig)
                qs=core.latest_quotes(con,max_age_seconds=20)
                status='OK'
                if qs is None or time.time()-snap.fetched_at>120 or abs(qs[symbol].mid/snap.quote.mid-1)>.02:
                    status='STALE_QUOTE'
                # Timestamp is signal-generation time, not the now-outdated candle timestamp.
                # llm_calls' id gives a unique key so event-driven calls in the same minute are retained.
                unique_ts= int(now_epoch)*10000+attempt  # unique per attempt; not actual bar timestamp
                record_decision(con,agent,symbol,unique_ts,model,sig,context,qs=qs if status=='OK' else None,status=status)
                with con:con.execute('UPDATE llm_calls SET status=? WHERE id=?',(status,attempt))
                total+=1
            except Exception as exc:
                # Sanitized errors only. Never log keys or raw HTTP authentication headers.
                message=type(exc).__name__
                if reserved and not sent:
                    settle(con,attempt,None,'not_sent',0,not_sent=True)
                if 'attempt' in locals():
                    with con:con.execute('UPDATE llm_calls SET status=?,message=? WHERE id=?',('BUDGET_BLOCKED' if message=='BudgetBlocked' else 'NOT_SENT' if not sent else 'ERROR',message,attempt))
                core.log(con,f'{agent}/{symbol}: {message}','ERROR',agent)
            finally:
                # Important when first symbol errors before attempt allocation.
                if 'attempt' in locals():del attempt
    return total


def build_synthetic_demo(con:sqlite3.Connection):
    """Explicitly fake data for UI only; no simulated LLM performance."""
    if con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]:
        raise RuntimeError('Demo besteht bereits; Original-Daten nicht überschreiben.')
    rng=random.Random(70305)
    n=16*24*60
    now=int(time.time())//60*60
    start=now-n*60
    allbars={}
    for symbol,price in (('BTCEUR',65000.),('ETHEUR',3300.)):
        rows=[]
        for j in range(n):
            minute=start+j*60
            drift = .000014 if j%(5*1440)<3*1440 else -.00003
            move=rng.gauss(drift,.001 if symbol=='ETHEUR' else .0007)
            nxt=price*math.exp(move)
            wick=abs(rng.gauss(.00025,.00012))
            rows.append(Candle(minute,price,max(price,nxt)*(1+wick),
                               min(price,nxt)*(1-wick),nxt,abs(rng.gauss(25,8))))
            price=nxt
        allbars[symbol]=rows
    def aggregate(rows,tf):
        groups={}
        for b in rows:
            start_ts=(b.ts//(tf*60))*(tf*60)
            groups.setdefault(start_ts,[]).append(b)
        return tuple(Candle(ts,grp[0].open,max(x.high for x in grp),min(x.low for x in grp),
                            grp[-1].close,sum(x.volume for x in grp))
                     for ts,grp in sorted(groups.items()) if len(grp)==tf)
    aggregated={symbol:{tf:aggregate(bars,tf) for tf in INTERVALS}
                for symbol,bars in allbars.items()}
    # Show an evolving illustrative scenario over the last 3 hours in 15m steps.
    for offset in range(12,0,-1):
        at=now-offset*15*60
        snaps={}
        for symbol,seqs in aggregated.items():
            frames={tf:tuple(b for b in seq if b.ts+tf*60<=at) for tf,seq in seqs.items()}
            end=frames[1][-1].close
            snaps[symbol]=MultiSnapshot(symbol,frames,core.Quote(end*.99985,end*1.00015),at)
        when=datetime.fromtimestamp(at,timezone.utc).isoformat(timespec='seconds')
        update_market(con,snaps,demo=True,when=when)
        with con:
            for symbol,snap in snaps.items():
                con.execute('INSERT INTO market_ticks(ts,symbol,mid) VALUES(?,?,?)',
                            (when,symbol,snap.quote.mid))
        quant_cycle(con,snaps,demo=True,when=when)
        with con:
            q={s:snaps[s].quote for s in core.SYMBOLS}
            for agent in core.AGENTS:core.mark_and_risk(con,agent,q,when)
    core.log(con,'SYNTHETIC DEMO: KEINE Börsenpreise, KEINE LLM-Aufrufe, KEINE Performance-Aussage.')


def state(con:sqlite3.Connection, *, demo=False) ->dict:
    # Self-contained state; no v0.2 assumptions or fabricated model activity.
    markets={r['symbol']:dict(r) for r in con.execute('SELECT * FROM market')}
    quotes={s:core.Quote(v['bid'],v['ask']) for s,v in markets.items()}
    ps=[]
    for agent in core.AGENTS:
        p=core.balance(con,agent)
        eq=core.value(p,quotes) if len(quotes)==len(core.SYMBOLS) else p['cash']
        ps.append({'agent':agent,'cash':p['cash'],'equity':eq,'btc':p['btc'],'eth':p['eth'],
                   'peak':p['peak'],'halted':bool(p['halted']),
                   'available':agent not in LLM_AGENTS or (not demo and bool(os.getenv('OPENAI_API_KEY' if agent=='gpt' else 'ANTHROPIC_API_KEY'))),
                   'return_pct':(eq/core.START_CASH-1)*100,
                   'num_trades':con.execute('SELECT COUNT(*) FROM trades WHERE agent=?',(agent,)).fetchone()[0],
                   'fees_paid':con.execute('SELECT COALESCE(SUM(fee),0) FROM trades WHERE agent=?',(agent,)).fetchone()[0]})
    def rows(sql):return [dict(r) for r in con.execute(sql)]
    return {'mode':'SYNTHETISCHE DEMO – NICHT LIVE' if demo else 'BITVAVO LIVE / VIRTUELLE ORDERS',
            'demo':demo,'version':'0.3.1','capital':core.START_CASH,'fee_rate':core.fee_rate(),'slippage':core.slip_rate(),
            'markets':markets,'portfolios':ps,'strategy_timeframes':STRATEGY_TIMEFRAME,
            'llm_usage':{k:con.execute('SELECT COUNT(*) FROM llm_calls WHERE agent=? AND ts>=?',
                                    (k,core.utcnow()[:10])).fetchone()[0] for k in LLM_AGENTS},
            'price_history':{symbol:[dict(r) for r in con.execute(
                'SELECT ts,symbol,mid FROM (SELECT id,ts,symbol,mid FROM market_ticks WHERE symbol=? ORDER BY id DESC LIMIT 360) ORDER BY id',
                (symbol,))] for symbol in core.SYMBOLS},
            'equity':rows('SELECT ts,agent,value FROM equity ORDER BY id DESC LIMIT 4500')[::-1],
            'trades':rows('SELECT ts,agent,symbol,side,qty,fill,notional,fee FROM trades ORDER BY id DESC LIMIT 100'),
            'decisions':rows('SELECT ts,agent,symbol,bar_ts,model,action,target,confidence,reason,status FROM decisions ORDER BY id DESC LIMIT 120'),
            'logs':rows('SELECT ts,level,agent,message FROM logs ORDER BY id DESC LIMIT 25')}
