"""Offline operational regression tests. All history is synthetic and temporary."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import arena as core
import backup
import engine03 as engine
import main as app
from operations import Health, WriterLock, health_report, inspect_db, read_db
from strategies import Candle, MultiSnapshot, INTERVALS


def snapshots(quotes):
    now=int(time.time())
    result={}
    for symbol,q in quotes.items():
        frames={}
        for tf in INTERVALS:
            end=(now//(tf*60)-1)*tf*60
            frames[tf]=tuple(Candle(end-(129-i)*tf*60,q.mid,q.mid+1,q.mid-1,q.mid,10) for i in range(130))
        result[symbol]=MultiSnapshot(symbol,frames,q,now)
    return result


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/'live.sqlite3'
        self.con=core.open_db(str(self.path))
        self.quotes={'BTCEUR':core.Quote(66000,66005),'ETHEUR':core.Quote(3200,3200.2)}

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def seed(self):
        core.record_live_quotes(self.con,self.quotes)
        engine.initialize_buyhold(self.con,self.quotes)

    def rows(self,con):
        return {t:[tuple(r) for r in con.execute('SELECT * FROM '+t)] for t in
                ('portfolios','decisions','trades','market','market_ticks','equity','llm_calls','logs')}

    def test_restart_preserves_all_history_and_no_duplicate_initial_buys(self):
        self.seed()
        before=self.rows(self.con)
        self.con.close()
        self.con=core.open_db(str(self.path))
        self.assertEqual(engine.initialize_buyhold(self.con,self.quotes),0)
        self.assertEqual(self.rows(self.con),before)
        self.assertEqual(inspect_db(self.path,mode='live')['counts']['trades'],2)

    def test_concurrent_benchmark_workers_do_not_duplicate_trades(self):
        core.record_live_quotes(self.con,self.quotes)
        barrier=threading.Barrier(2)
        failures=[]
        def worker():
            con=core.open_db(str(self.path))
            try:
                barrier.wait(timeout=5)
                engine.initialize_buyhold(con,self.quotes)
            except Exception as exc:failures.append(exc)
            finally:con.close()
        threads=[threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures,[])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],2)

    def test_failed_execution_rolls_back_decision_trade_and_portfolio(self):
        before=self.rows(self.con)
        with patch('engine03.core.mark_and_risk',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):engine.initialize_buyhold(self.con,self.quotes)
        self.assertEqual(self.rows(self.con),before)

    def test_backup_contains_committed_wal_and_not_uncommitted_writes(self):
        self.seed()
        before=self.rows(self.con)
        self.assertTrue(Path(str(self.path)+'-wal').exists())
        self.con.execute("UPDATE portfolios SET cash=1 WHERE agent='gpt'")
        dest=self.root/'snapshot.sqlite3'
        backup.backup_database(self.path,dest)
        self.con.rollback()
        snapshot=read_db(dest)
        try:self.assertEqual(self.rows(snapshot),before)
        finally:snapshot.close()
        self.assertEqual(backup.verify_backup(dest)['inventory']['counts']['trades'],2)

    def test_backup_failure_never_publishes_partial_file_or_prunes_old_backup(self):
        directory=self.root/'backups'
        first=backup.rotate_backups(self.path,directory,keep=1)
        before=set(p.name for p in directory.iterdir())
        with patch('backup.inspect_db',side_effect=ValueError('invalid')):
            with self.assertRaises(ValueError):backup.rotate_backups(self.path,directory,keep=1)
        self.assertEqual(set(p.name for p in directory.iterdir()),before)
        backup.verify_backup(directory/first['file'])

    def test_backup_refuses_overwrite_missing_source_and_invalid_retention(self):
        dest=self.root/'snapshot.sqlite3'
        backup.backup_database(self.path,dest)
        digest=backup.digest(dest)
        with self.assertRaises(FileExistsError):backup.backup_database(self.path,dest)
        with self.assertRaises(FileNotFoundError):backup.backup_database(self.root/'missing',self.root/'new.sqlite3')
        with self.assertRaises(ValueError):backup.rotate_backups(self.path,self.root/'backups',keep=0)
        self.assertEqual(backup.digest(dest),digest)
        self.assertFalse((self.root/'missing').exists())

    def test_retention_only_removes_own_managed_completed_backups(self):
        directory=self.root/'backups'
        directory.mkdir()
        manual=directory/'manual.sqlite3'
        backup.backup_database(self.path,manual)
        orphan=directory/'unrelated.sqlite3'
        orphan.write_bytes(b'keep me')
        for _ in range(4):backup.rotate_backups(self.path,directory,keep=2)
        managed=list(directory.glob('arena-*.sqlite3'))
        self.assertEqual(len(managed),2)
        for path in managed:backup.verify_backup(path)
        self.assertTrue(manual.exists())
        self.assertEqual(orphan.read_bytes(),b'keep me')

    def test_verified_restore_preserves_rows_and_refuses_existing_target(self):
        self.seed()
        before=self.rows(self.con)
        snapshot=self.root/'snapshot.sqlite3'
        backup.backup_database(self.path,snapshot)
        restored=self.root/'restored.sqlite3'
        backup.restore_backup(snapshot,restored)
        con=read_db(restored)
        try:self.assertEqual(self.rows(con),before)
        finally:con.close()
        with self.assertRaises(FileExistsError):backup.restore_backup(snapshot,restored)
        blocked=self.root/'blocked.sqlite3'
        Path(str(blocked)+'-wal').write_bytes(b'old WAL must not be replayed')
        with self.assertRaises(FileExistsError):backup.restore_backup(snapshot,blocked)
        self.assertFalse(blocked.exists())

    def test_backup_checksum_detects_tampering(self):
        dest=self.root/'snapshot.sqlite3'
        backup.backup_database(self.path,dest)
        with dest.open('ab') as f:f.write(b'tamper')
        with self.assertRaises(ValueError):backup.verify_backup(dest)

    def test_database_checks_do_not_create_or_repair_history(self):
        missing=self.root/'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):inspect_db(missing)
        self.assertFalse(missing.exists())
        with self.con:self.con.execute("DELETE FROM portfolios WHERE agent='gpt'")
        with self.assertRaises(ValueError):inspect_db(self.path)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM portfolios').fetchone()[0],6)

    def test_demo_content_rejected_as_live(self):
        self.seed()
        with self.con:self.con.execute("UPDATE market SET source='SYNTHETIC-DEMO'")
        with self.assertRaises(ValueError):inspect_db(self.path,mode='live')
        inspect_db(self.path,mode='demo')

    def test_missing_database_health_does_not_create_database(self):
        missing=self.root/'missing.sqlite3'
        report=health_report(missing,Health())
        self.assertEqual(report['status'],'error')
        self.assertFalse(missing.exists())

    def test_health_distinguishes_disabled_untested_failed_and_stalled(self):
        self.seed()
        now=[0.]
        health=Health(clock=lambda:now[0])
        for name in ('quotes','strategy','llm'):health.tick(name)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','ANTHROPIC_API_KEY':''}):
            report=health_report(self.path,health)
        self.assertTrue(report['ready'])
        self.assertEqual(report['providers']['gpt']['status'],'disabled')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only','ANTHROPIC_API_KEY':''}):
            report=health_report(self.path,health)
            self.assertEqual(report['providers']['gpt']['status'],'untested')
            with self.con:self.con.execute("INSERT INTO llm_calls(ts,agent,symbol,ref_mid,status) VALUES (?,?,?,?,?)",
                                           (core.utcnow(),'gpt','BTCEUR',66000,'ERROR'))
            self.assertEqual(health_report(self.path,health)['providers']['gpt']['status'],'degraded')
        now[0]=300
        self.assertFalse(health_report(self.path,health)['live'])

    def test_feed_failure_creates_no_trade_and_recovery_bootstraps_once(self):
        stop=threading.Event()
        health=Health()
        def failure():
            stop.set()
            raise OSError('simulated failure')
        with patch('main.bitvavo_quotes',side_effect=failure):app.quote_worker(str(self.path),stop,health)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],0)
        self.assertEqual(health.snapshot()['quotes']['status'],'degraded')
        for _ in range(2):
            stop.clear()
            def recover():
                stop.set()
                return self.quotes
            with patch('main.bitvavo_quotes',side_effect=recover):app.quote_worker(str(self.path),stop,health)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],2)

    def test_stale_feed_clears_cached_signals_without_llm_call(self):
        with app._latest_lock:app._latest_snaps.update(snapshots(self.quotes))
        stop=threading.Event()
        def wait(_):stop.set()
        health=Health()
        with patch.object(stop,'wait',side_effect=wait):app.signal_worker(str(self.path),stop,health)
        self.assertEqual(app._latest_snaps,{})
        self.assertEqual(health.snapshot()['strategy']['status'],'waiting-feed')

    def test_llm_failure_does_not_trade_or_leak_exception_body(self):
        self.seed()
        before=self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
        secret='fake-test-secret'
        def broken(*_):raise RuntimeError('provider echoed '+secret)
        with patch.dict(os.environ,{'OPENAI_API_KEY':secret,'ANTHROPIC_API_KEY':''}):
            engine.llm_cycle(self.con,snapshots(self.quotes),llm_fn=broken)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],before)
        self.assertNotIn(secret,str(self.rows(self.con)))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM llm_calls WHERE status='ERROR'").fetchone()[0],2)

    def test_shutdown_discards_inflight_model_answer_without_trade(self):
        self.seed()
        stop=threading.Event()
        def answer(*_):
            stop.set()
            return {'action':'BUY','target_fraction':.45,'confidence':1.,'reason':'test'},'test-model'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test','ANTHROPIC_API_KEY':''}):
            engine.llm_cycle(self.con,snapshots(self.quotes),llm_fn=answer,stop_event=stop)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0],2)
        self.assertEqual(self.con.execute('SELECT status FROM llm_calls').fetchone()[0],'CANCELLED')

    def test_supervisor_exits_nonzero_when_worker_dies(self):
        def broken(db,stop,health):raise RuntimeError('test worker death')
        self.assertEqual(app.run_live(str(self.path),0,worker_functions={'quotes':broken}),1)

    def test_health_http_and_readonly_dashboard_never_change_history(self):
        self.seed()
        health=Health()
        for name in ('quotes','strategy','llm'):health.tick(name)
        before=self.rows(self.con)
        server=app.make_server(str(self.path),False,0,health)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ,{'OPENAI_API_KEY':'','ANTHROPIC_API_KEY':''}):
                for route in ('/health/live','/health/ready','/api/state','/api/trades.csv'):
                    with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}'+route,timeout=3) as response:
                        self.assertEqual(response.status,200)
            self.assertEqual(server.server_address[0],'127.0.0.1')
            self.assertEqual(self.rows(self.con),before)
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()

    def test_process_lock_released_after_crash(self):
        code="from operations import WriterLock; import sys,time; lock=WriterLock(sys.argv[1]); lock.__enter__(); print('locked',flush=True); time.sleep(30)"
        proc=subprocess.Popen([sys.executable,'-c',code,str(self.path)],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(),'locked')
            with self.assertRaises(RuntimeError):
                with WriterLock(self.path):pass
        finally:
            proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
        with WriterLock(self.path):pass

    def test_uncommitted_process_crash_does_not_change_history(self):
        self.seed()
        before=self.rows(self.con)
        code="import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1]); c.execute(\"UPDATE portfolios SET cash=0 WHERE agent='gpt'\"); print('pending',flush=True); time.sleep(30)"
        proc=subprocess.Popen([sys.executable,'-c',code,str(self.path)],stdout=subprocess.PIPE,text=True)
        try:self.assertEqual(proc.stdout.readline().strip(),'pending')
        finally:
            proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
        self.assertEqual(self.rows(self.con),before)
        inspect_db(self.path,mode='live')

    @unittest.skipUnless(os.name=='posix','Real SIGTERM handling needs Linux/POSIX')
    def test_sigterm_stops_workers_and_releases_writer_lock(self):
        code="""import sys,time
import main
from operations import WriterLock
def worker(db,stop,health):
    while not stop.wait(.01): pass
with WriterLock(sys.argv[1]):
    result=main.run_live(sys.argv[1],0,worker_functions={'quotes':worker,'strategy':worker,'llm':worker})
sys.exit(result)
"""
        proc=subprocess.Popen([sys.executable,'-u','-c',code,str(self.path)],stdout=subprocess.PIPE,text=True)
        try:
            self.assertIn('Paper dashboard:',proc.stdout.readline())
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=5),0)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()
        with WriterLock(self.path):pass


if __name__=='__main__':unittest.main()
