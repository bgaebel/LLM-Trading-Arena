"""Synthetic fixtures only; research must never write to a live source."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import arena as core
import bitvavo
import research
from test_operations import snapshots


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.con=core.open_db(str(self.root/'test.sqlite3'))
    def tearDown(self):self.con.close();self.tmp.cleanup()

    def test_shared_period_drawdown_and_costs(self):
        with self.con:
            for ts,value in [('2026-01-01T00:00:00+00:00',10000),('2026-01-02T00:00:00+00:00',8000),('2026-01-03T00:00:00+00:00',11000)]:
                for agent in core.AGENTS:
                    self.con.execute('INSERT INTO equity(ts,agent,value,cash,btc,eth) VALUES(?,?,?,?,0,0)',(ts,agent,value,value))
        result=research.performance(self.con)
        p=result['portfolios'][0]
        self.assertAlmostEqual(p['net_return_pct'],10)
        self.assertAlmostEqual(p['max_drawdown_pct'],20)
        self.assertEqual(p['excess_buyhold_pct'],0)
        self.assertEqual(research.performance(self.con,'2027-01-01')['status'],'insufficient-common-history')

    def test_replay_has_no_network_and_no_source_mutation(self):
        qs={'BTCEUR':core.Quote(66000,66005),'ETHEUR':core.Quote(3200,3200.2)}
        snaps=snapshots(qs);at=snaps['BTCEUR'].fetched_at
        with patch('arena.http_json',side_effect=AssertionError('network forbidden')):
            result=research.replay([(at,snaps),(at+60,snaps)])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],0)

    def test_replay_loader_rejects_future_bars(self):
        path=self.root/'input.json'
        qs={'BTCEUR':core.Quote(66000,66005),'ETHEUR':core.Quote(3200,3200.2)}
        snaps=snapshots(qs);at=snaps['BTCEUR'].fetched_at
        data=[{'at':at,'markets':{s:{'bid':q.bid,'ask':q.ask,'bars':{str(tf):[[b.ts,b.open,b.high,b.low,b.close,b.volume] for b in bars] for tf,bars in snaps[s].bars.items()}} for s,q in qs.items()}}]
        data[0]['markets']['BTCEUR']['bars']['1'][-1][0]=at
        path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):research.load_replay(path)

    def test_conflicting_duplicate_market_candles_rejected(self):
        now=1800000120
        rows=[[1800000000000,100,101,99,100,5],[1800000000000,100,102,99,101,5]]
        with patch('arena.http_json',return_value=rows):
            with self.assertRaises(ValueError):bitvavo.closed_candles('BTCEUR',1,now_epoch=now)

    def test_identical_duplicate_market_candles_deduplicated(self):
        rows=[[1800000000000,100,101,99,100,5]]*2
        with patch('arena.http_json',return_value=rows):
            self.assertEqual(len(bitvavo.closed_candles('BTCEUR',1,now_epoch=1800000120)),1)

    def test_provider_usage_is_numeric_and_does_not_leak_response(self):
        from provenance import capture_usage,take_usage
        capture_usage({'usage':{'input_tokens':12,'output_tokens':5,'raw':'secret','total_tokens':True},'text':'secret'})
        self.assertEqual(take_usage(),{'input_tokens':12,'output_tokens':5})
        self.assertIsNone(take_usage())

    def test_walk_forward_windows_are_disjoint(self):
        records=[(i,{}) for i in range(12)]
        with patch('research.replay',return_value={'status':'fixture'}):
            folds=research.walk_forward(records,4,2)
        self.assertEqual([(f['test_start'],f['test_end']) for f in folds],[(4,5),(6,7),(8,9),(10,11)])
        self.assertTrue(all(f['train_end']<f['test_start'] for f in folds))

    def test_fifo_realized_profit_allocates_buy_and_sell_fees(self):
        from reporting import accounting
        with self.con:
            for ts,side,qty,notional,fee in [('2026-01-01T00:00:00+00:00','BUY',1,100,1),
                                              ('2026-01-02T00:00:00+00:00','SELL',.5,60,.6)]:
                self.con.execute('INSERT INTO trades(ts,agent,symbol,side,qty,fill,notional,fee,slip_rate) VALUES(?,?,?,?,?,?,?,?,0)',
                                 (ts,'gpt','BTCEUR',side,qty,notional/qty,notional,fee))
        result=accounting(self.con,'gpt','2026-01-01T00:00:00+00:00','2026-01-03T00:00:00+00:00')
        self.assertAlmostEqual(result['realized_pnl_eur'],8.9)
        self.assertAlmostEqual(result['open_lots']['BTCEUR']['cost_basis_eur'],50.5)
        self.assertEqual(result['open_lots']['BTCEUR']['quantity'],.5)

    def test_missing_opening_trade_does_not_fabricate_realized_profit(self):
        from reporting import accounting
        with self.con:
            self.con.execute("INSERT INTO trades(ts,agent,symbol,side,qty,fill,notional,fee,slip_rate) VALUES('2026-01-02T00:00:00+00:00','gpt','BTCEUR','SELL',1,100,100,1,0)")
        result=accounting(self.con,'gpt','2026-01-01T00:00:00+00:00','2026-01-03T00:00:00+00:00')
        self.assertIsNone(result['realized_pnl_eur'])
        self.assertTrue(result['opening_inventory_unknown'])

    def test_missing_api_receipt_marks_cost_as_unknown(self):
        from reporting import api_costs
        with self.con:
            self.con.execute("INSERT INTO llm_calls(ts,agent,symbol,ref_mid,status) VALUES('2026-01-02T00:00:00+00:00','gpt','BTCEUR',100,'ERROR')")
        result=api_costs(self.con,'gpt','2026-01-01T00:00:00+00:00','2026-01-03T00:00:00+00:00')
        self.assertEqual(result['unknown_cost_attempts'],1)
        self.assertIsNone(result['complete_estimated_cost_eur'])

    def test_full_loss_is_a_valid_drawdown(self):
        with self.con:
            for ts,value in [('2026-01-01T00:00:00+00:00',10000),('2026-01-02T00:00:00+00:00',0)]:
                for agent in core.AGENTS:
                    self.con.execute('INSERT INTO equity(ts,agent,value,cash,btc,eth) VALUES(?,?,?,?,0,0)',(ts,agent,value,value))
        result=research.performance(self.con)['portfolios'][0]
        self.assertEqual(result['net_return_pct'],-100)
        self.assertEqual(result['max_drawdown_pct'],100)


if __name__=='__main__':unittest.main()
