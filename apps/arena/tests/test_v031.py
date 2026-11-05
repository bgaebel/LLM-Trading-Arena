"""Regression tests for blocked buy-and-hold and independent candle data."""
import tempfile
import time
import unittest
import threading
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

import arena as core
import engine03 as engine
import main as app
from bitvavo import fill_tiny_gaps
from strategies import Candle, MultiSnapshot, INTERVALS

class FixTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.con=core.open_db(str(Path(self.directory.name)/'live.sqlite3'))
        self.now=int(time.time())
        self.quotes={'BTCEUR':core.Quote(66000,66005),'ETHEUR':core.Quote(3200,3200.2)}

    def tearDown(self):
        self.con.close()
        self.directory.cleanup()

    def synthetic_bars(self,symbol,tf):
        latest=(self.now//(tf*60)-1)*tf*60
        price=66000 if symbol=='BTCEUR' else 3200
        return tuple(Candle(latest-(129-j)*tf*60,price,price+5,price-5,price,5) for j in range(130))

    def test_buyhold_from_quotes_even_if_all_candles_missing(self):
        core.record_live_quotes(self.con,self.quotes)
        self.assertEqual(engine.initialize_buyhold(self.con,self.quotes),2)
        p=core.balance(self.con,'buyhold')
        self.assertGreater(p['btc'],0)
        self.assertGreater(p['eth'],0)
        self.assertLess(p['cash'],1500)
        self.assertEqual(self.con.execute('select count(*) from trades where agent="buyhold"').fetchone()[0],2)
        self.assertEqual(self.con.execute('select count(*) from decisions where agent="trend"').fetchone()[0],0)
        self.assertEqual(engine.initialize_buyhold(self.con,self.quotes),0)
        self.assertEqual(self.con.execute('select count(*) from trades where agent="buyhold"').fetchone()[0],2)

    def test_quote_worker_bootstraps_benchmark_without_ohlcv(self):
        self.con.close()
        db_path=str(Path(self.directory.name)/'live.sqlite3')
        stop=threading.Event()
        def sample_quotes():
            stop.set()  # run exactly one quote iteration
            return self.quotes
        with patch('main.bitvavo_quotes',side_effect=sample_quotes):
            app.quote_worker(db_path,stop)
        self.con=core.open_db(db_path)
        self.assertEqual(self.con.execute('select count(*) from trades where agent="buyhold"').fetchone()[0],2)

    def test_buyhold_survives_restart_with_same_db(self):
        core.record_live_quotes(self.con,self.quotes)
        self.assertEqual(engine.initialize_buyhold(self.con,self.quotes),2)
        con2=core.open_db(str(Path(self.directory.name)/'live.sqlite3'))
        try:
            self.assertEqual(engine.initialize_buyhold(con2,self.quotes),0)
            self.assertEqual(con2.execute('select count(*) from trades where agent="buyhold"').fetchone()[0],2)
        finally:con2.close()

    def test_bitvavo_small_no_trade_gap_filled_with_zero_volume(self):
        latest=self.now//60*60-60
        bar1=Candle(latest-120,100,101,99,100,10)
        bar3=Candle(latest,103,104,102,103,10)
        bars,count=fill_tiny_gaps((bar1,bar3),1)
        self.assertEqual(count,1)
        self.assertEqual([b.ts for b in bars],[bar1.ts,bar1.ts+60,bar3.ts])
        self.assertEqual(bars[1].volume,0.)
        self.assertEqual(bars[1].close,100)

    def test_larger_gaps_remain_unfilled(self):
        b1=Candle(60,100,101,99,100,10)
        b2=Candle(60*5,102,103,101,102,2)
        bars,count=fill_tiny_gaps((b1,b2),1)
        self.assertEqual(count,0)
        self.assertEqual(bars,(b1,b2))

    def test_live_snapshot_partial_when_eth_has_gap(self):
        cache={}
        def source(symbol,tf):
            if symbol=='ETHEUR' and tf==1:
                raise RuntimeError('Simulierter ETH-OHLCV-Ausfall')
            return self.synthetic_bars(symbol,tf)
        problems=[]
        snaps=engine.live_snapshots(cache,quote_fetcher=lambda symbol:self.quotes[symbol],
            candle_fetcher=source,now_epoch=self.now,on_error=lambda s,e:problems.append((s,str(e))))
        self.assertEqual(set(snaps),{'BTCEUR'})
        self.assertEqual(problems,[('ETHEUR','Simulierter ETH-OHLCV-Ausfall')])
        core.record_live_quotes(self.con,self.quotes)
        self.assertEqual(engine.initialize_buyhold(self.con,self.quotes),2)
        self.assertEqual(engine.quant_cycle(self.con,snaps),4)
        self.assertEqual(self.con.execute('select count(*) from decisions where symbol="ETHEUR" and agent!="buyhold"').fetchone()[0],0)

    def test_no_benchmark_buys_on_stale_quotes(self):
        ts=datetime.fromtimestamp(self.now-180,timezone.utc).isoformat(timespec='seconds')
        core.record_live_quotes(self.con,self.quotes,now=ts)
        self.assertIsNone(core.latest_quotes(self.con,max_age_seconds=20))
        self.assertEqual(self.con.execute('select count(*) from trades').fetchone()[0],0)

if __name__=='__main__':unittest.main()
