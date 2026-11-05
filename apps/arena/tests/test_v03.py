import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

import arena as core
import bitvavo
import engine03 as eng
from strategies import Candle, MultiSnapshot, INTERVALS, MIN_BARS, indicators, run_strategy

class V03Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.db=core.open_db(str(Path(self.t.name)/'v03.sqlite3'))
        self.now=int(time.time())

    def tearDown(self):
        self.db.close()
        self.t.cleanup()

    def make_snap(self, symbol, value=100.0, *,now=None):
        now=self.now if now is None else now
        result={}
        for tf in INTERVALS:
            secs=tf*60
            latest=(now//secs-1)*secs
            rows=[]
            for ix in range(130):
                ts=latest-(129-ix)*secs
                price=value*(1+.0003*ix)
                rows.append(Candle(ts,price,price*1.002,price*.998,price,10.+ix/10))
            result[tf]=tuple(rows)
        return MultiSnapshot(symbol,result,core.Quote(value*1.037,value*1.0372),now)

    def snaps(self):
        return {symbol:self.make_snap(symbol, value=100 if symbol=='BTCEUR' else 50)
                for symbol in core.SYMBOLS}

    def test_bitvavo_symbols_and_fees(self):
        self.assertEqual(core.PAIRS, {'BTCEUR':'BTC-EUR','ETHEUR':'ETH-EUR'})
        with patch.dict(os.environ, {'TAKER_FEE':'0.0025','SLIPPAGE':'0.0003'}):
            self.assertEqual(core.fee_rate(),.0025)
            self.assertEqual(core.slip_rate(),.0003)

    def test_public_quote_parse_both_markets(self):
        fake=[{'market':'BTC-EUR','bid':'70250','ask':'70253'},
              {'market':'ETH-EUR','bid':'3200','ask':'3201'},
              {'market':'FOO-EUR','bid':'10','ask':'11'}]
        with patch('bitvavo.core.http_json',return_value=fake) as fn:
            qs=bitvavo.quotes()
        self.assertEqual(set(qs),set(core.SYMBOLS))
        self.assertEqual(qs['BTCEUR'].bid,70250)
        self.assertIn('api.bitvavo.com/v2/ticker/book',fn.call_args.args[0])

    def test_quote_failure_raises_and_no_mark(self):
        with patch('bitvavo.core.http_json',return_value=[{'market':'BTC-EUR','bid':'10','ask':'11'}]):
            with self.assertRaises(ValueError):bitvavo.quotes()
        self.assertEqual(0,self.db.execute('select count(*) from market').fetchone()[0])

    def test_closed_candle_filter_and_sort(self):
        now=1_800_000_055
        bucket=(now//60)*60
        rows=[[str((bucket-60)*1000),'100','101','99','100','5'],
              [str(bucket*1000),'100','102','98','101','3'],
              [str((bucket-120)*1000),'99','101','98','100','2']]
        with patch('bitvavo.core.http_json',return_value=rows):
            candles=bitvavo.closed_candles('BTCEUR',1,now_epoch=now)
        self.assertEqual(len(candles),2)
        self.assertEqual([c.ts for c in candles],[bucket-120,bucket-60])

    def test_live_snapshots_only_completed_bars(self):
        snaps=self.snaps()
        with patch('engine03.bitvavo_closed_candles') as get:
            get.side_effect=lambda s,tf:snaps[s].bars[tf]
            out=eng.live_snapshots({},quote_fetcher=lambda s:snaps[s].quote,candle_fetcher=get,now_epoch=self.now)
        self.assertEqual(len(out),2)
        self.assertEqual(get.call_count,8)
        for snap in out.values():snap.validate(live=True)

    def test_agent_portfolios_separate_and_quant_idempotent(self):
        snaps=self.snaps()
        with patch.dict(os.environ,{'TAKER_FEE':'0.0025','SLIPPAGE':'0.0003'}):
            a=eng.quant_cycle(self.db,snaps,demo=True)
            b=eng.quant_cycle(self.db,snaps,demo=True)
        self.assertEqual(a,10)
        self.assertEqual(b,0)
        self.assertEqual(self.db.execute('select count(*) from trades where agent="buyhold"').fetchone()[0],2)
        self.assertEqual(self.db.execute('select count(*) from portfolios').fetchone()[0],7)

    def test_without_exchange_key_and_without_llm_keys_no_llm_calls(self):
        core.record_live_quotes(self.db,{s:snap.quote for s,snap in self.snaps().items()})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','ANTHROPIC_API_KEY':''}):
            self.assertEqual(eng.llm_cycle(self.db,self.snaps()),0)
        self.assertEqual(0,self.db.execute('select count(*) from llm_calls').fetchone()[0])

    def test_no_duplicate_llm_request_inside_interval(self):
        ts=datetime.fromtimestamp(self.now,timezone.utc).isoformat(timespec='seconds')
        self.db.execute('insert into llm_calls(ts,agent,symbol,ref_mid,status) values(?,?,?,?,?)',
                        (ts,'gpt','BTCEUR',103.71,'OK'))
        self.db.commit()
        with patch.dict(os.environ,{'LLM_MIN_INTERVAL_SECONDS':'1800','LLM_EVENT_COOLDOWN_SECONDS':'600'}):
            self.assertFalse(eng.llm_due(self.db,'gpt','BTCEUR',103.8,now_epoch=self.now+60))

    def test_risk_drawdown_kill_and_no_reentry(self):
        snaps=self.snaps()
        eng.quant_cycle(self.db,snaps,demo=True)
        q={s:core.Quote(45,45.01) for s in core.SYMBOLS}
        with self.db:core.mark_and_risk(self.db,'buyhold',q,core.utcnow())
        self.assertEqual(core.balance(self.db,'buyhold')['halted'],0) # Passive benchmark has no kill
        with self.db:core.trade_to_target(self.db,'trend','BTCEUR',.45,{s:snaps[s].quote for s in core.SYMBOLS},1)
        with self.db:core.mark_and_risk(self.db,'trend',q,core.utcnow())
        self.assertEqual(core.balance(self.db,'trend')['halted'],1)

    def test_llm_invalid_schema_rejected(self):
        with self.assertRaises(ValueError):core.validate_signal({'action':'SHORT','target_fraction':-.45,'confidence':.9,'reason':'wrong'})

    def test_all_five_strategies_explicit(self):
        s=self.make_snap('BTCEUR')
        i=indicators(s,.006)
        for name in eng.QUANT_AGENTS:
            sig=run_strategy(name,s,i,0.0)
            self.assertIn(sig['action'], ('BUY','SELL','HOLD'))
            core.validate_signal(sig)

    def test_state_is_bitvavo_and_eur(self):
        data=eng.state(self.db)
        self.assertIn('BITVAVO',data['mode'])
        self.assertEqual(data['capital'],10000.0)

if __name__=='__main__':unittest.main()
