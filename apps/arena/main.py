"""Commands: python main.py demo | start | once | serve --demo"""
import argparse
import csv
import io
import json
import os
import signal
import sys
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from arena import SYMBOLS, record_live_quotes, load_dotenv, open_db, log, latest_quotes
from bitvavo import quotes as bitvavo_quotes
from engine03 import (live_snapshots, quant_cycle, llm_cycle, build_synthetic_demo,
                      initialize_buyhold, state)

from operations import Health, WriterLock, health_report, inspect_db, read_db, open_existing_db, safe_error

ROOT=Path(__file__).resolve().parent


def db_file(name: str) -> str:
    """Writable per-user data, even if the application sits under Program Files."""
    override = os.getenv('LLM_TRADING_ARENA_DATA_DIR')
    local = os.getenv('LOCALAPPDATA')
    data_dir = (Path(override).expanduser() if override else
                Path(local) / 'LLMTradingArena' / 'data' if local else
                Path.home() / '.local/share/llm-trading-arena')
    data_dir.mkdir(parents=True, exist_ok=True)
    result = data_dir / f'{name}.sqlite3'
    return str(result)


def make_server(db_path: str, demo: bool, port: int, health=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            status_code = 200
            if path in ('/', '/index.html'):
                content=(ROOT/'static'/'index.html').read_bytes()
                ct='text/html; charset=utf-8'
            elif path in ('/health/live', '/health/ready', '/api/health'):
                data=health_report(db_path,health,demo=demo)
                good=data['ready'] if path=='/health/ready' else data['live']
                status_code=200 if good else 503
                content=json.dumps(data).encode()
                ct='application/json; charset=utf-8'
            elif path=='/api/state':
                con=read_db(db_path)
                try: data=state(con,demo=demo)
                finally: con.close()
                content=json.dumps(data,ensure_ascii=False).encode()
                ct='application/json; charset=utf-8'
            elif path=='/api/trades.csv':
                con=read_db(db_path)
                try:
                    rows=con.execute('SELECT ts,agent,symbol,side,qty,fill,notional,fee FROM trades ORDER BY id').fetchall()
                finally: con.close()
                out=io.StringIO()
                writer=csv.writer(out)
                writer.writerow(['timestamp_utc','agent','symbol','side','qty','fill_eur','notional_eur','fee_eur'])
                writer.writerows(tuple(r) for r in rows)
                content=out.getvalue().encode('utf-8-sig')
                ct='text/csv; charset=utf-8'
            else:
                self.send_error(404,'Not found')
                return
            self.send_response(status_code)
            self.send_header('Content-Type',ct)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'unsafe-inline' 'self'; script-src 'unsafe-inline' 'self'; connect-src 'self'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            pass
    host='127.0.0.1'  # Never expose publicly; there is no login/auth.
    httpd=ThreadingHTTPServer((host,port),Handler)
    httpd.timeout=.5
    return httpd


def server(db_path: str, demo: bool, port: int):
    httpd=make_server(db_path,demo,port)
    try: httpd.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: pass
    finally: httpd.server_close()


def emit_failure(con, message, exc):
    message=f'{message}: {safe_error(exc)}'
    try: log(con,message,'ERROR')
    except sqlite3.Error: pass
    print(message,flush=True)


def beat(health, name, status='ok', exc=None):
    if health: health.tick(name,status,exc)


def quote_worker(db_path: str, stop: threading.Event, health=None):
    """Continuous risk monitoring independent from slow model inference."""
    interval = max(3., float(os.getenv('MARKET_POLL_SECONDS','5')))
    con = open_existing_db(db_path)
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                quotes=bitvavo_quotes()
                record_live_quotes(con,quotes)
                new=initialize_buyhold(con,quotes)
                beat(health,'quotes')
                if new:
                    message=f'Buy & Hold initialisiert: {new} virtuelle Käufe auf frischen Bitvavo-Quotes'
                    log(con,message,'INFO')
                    print(message,flush=True)
            except Exception as exc:
                beat(health,'quotes','degraded',exc)
                emit_failure(con,'Quote-/Risikopoll fehlgeschlagen',exc)
            stop.wait(max(.1,interval-(time.monotonic()-started)))
    finally: con.close()


# Shared candle cache accessed only by the signal worker; LLM snapshot handoff is guarded.
_latest_lock=threading.Lock()
_latest_snaps={}

def signal_worker(db_path: str, stop: threading.Event, health=None):
    """Process each asset independently; an ETH candle fault cannot block BTC.

    Quote-worker and the passive benchmark continue even when this worker is
    waiting for the first healthy OHLCV snapshot.
    """
    con=open_existing_db(db_path)
    cache={}
    warnings={}
    def warn_once(key, message, *, period=300):
        now=time.monotonic()
        previous=warnings.get(key)
        if previous is None or previous[0]!=message or now-previous[1]>=period:
            log(con,message,'WARN')
            print(message,flush=True)
            warnings[key]=(message,now)
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                q=latest_quotes(con,max_age_seconds=20)
                if q is None:
                    with _latest_lock: _latest_snaps.clear()
                    beat(health,'strategy','waiting-feed')
                    warn_once('quotes','Warte auf frische Bitvavo-Geld-/Briefkurse')
                else:
                    failures=[]
                    def bad_market(symbol,exc):
                        failures.append(symbol)
                        warn_once(symbol,f'{symbol}: Kerzendaten nicht verfügbar ({safe_error(exc)}); nur dieses Symbol pausiert')
                    snaps=live_snapshots(cache,quote_fetcher=lambda symbol:q[symbol],
                                         on_error=bad_market)
                    if stop.is_set(): break
                    with _latest_lock:
                        _latest_snaps.clear()
                        _latest_snaps.update(snaps)
                    if snaps:
                        count=quant_cycle(con,snaps)
                        beat(health,'strategy','degraded' if failures else 'ok')
                        if count:print(f'{count} quantitative Strategieentscheidungen geprüft',flush=True)
                    else:
                        beat(health,'strategy','waiting-candles')
                        warn_once('no_snapshots','Warte auf gültige, abgeschlossene Kerzendaten; Buy & Hold läuft unabhängig')
            except Exception as exc:
                with _latest_lock: _latest_snaps.clear()
                beat(health,'strategy','degraded',exc)
                message=f'Strategie-Zyklus ausgefallen: {safe_error(exc)}'
                warn_once('cycle',message,period=120)
            stop.wait(max(.2,60-(time.monotonic()-started)))
    finally:con.close()

def llm_worker(db_path: str, stop: threading.Event, health=None):
    """LLM calls never block quote/risk monitoring or quantitative signals."""
    con=open_existing_db(db_path)
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                with _latest_lock:snaps=dict(_latest_snaps)
                if snaps:llm_cycle(con,snaps,stop_event=stop)
                beat(health,'llm')
            except Exception as exc:
                beat(health,'llm','degraded',exc)
                emit_failure(con,'LLM-Zyklus fehlgeschlagen',exc)
            stop.wait(max(.2,20-(time.monotonic()-started)))
    finally:con.close()


def run_live(db, port, *, worker_functions=None, shutdown_seconds=45):
    """SIGTERM stops intake; dead/stalled workers cause a nonzero service exit."""
    health=Health()
    stop=threading.Event()
    with _latest_lock: _latest_snaps.clear()
    httpd=make_server(db,False,port,health)  # Fail before worker writes if port is occupied.
    failures=[]
    functions=worker_functions or {'quotes':quote_worker, 'strategy':signal_worker, 'llm':llm_worker}
    def guarded(name, fn):
        try: fn(db,stop,health)
        except BaseException as exc:
            beat(health,name,'failed',exc)
            failures.append(name)
            stop.set()
    threads=[threading.Thread(target=guarded,args=(name,fn),name=name,daemon=True)
             for name,fn in functions.items()]
    old_handlers={}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT,signal.SIGTERM):
            old_handlers[sig]=signal.signal(sig,lambda *_:stop.set())
    print(f'Paper dashboard: http://127.0.0.1:{httpd.server_port}',flush=True)
    try:
        for thread in threads: thread.start()
        while not stop.is_set():
            httpd.handle_request()
            stalled=any(v['status']=='stalled' for v in health.snapshot().values())
            if stalled or any(not t.is_alive() for t in threads):
                failures.append('worker-stalled-or-exited')
                stop.set()
    finally:
        stop.set()
        httpd.server_close()
        deadline=time.monotonic()+shutdown_seconds
        for thread in threads: thread.join(max(0,deadline-time.monotonic()))
        for sig,handler in old_handlers.items(): signal.signal(sig,handler)
        if any(t.is_alive() for t in threads):
            # Do not release the writer lock while a surviving daemon can write.
            print('Shutdown deadline exceeded; terminating process for safe restart',flush=True)
            os._exit(1)
    return 1 if failures else 0


def main():
    if os.name != 'nt': os.umask(0o077)
    os.chdir(ROOT)
    load_dotenv()
    parser=argparse.ArgumentParser(description='LLM Trading Arena (ausschließlich virtuell)')
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init-live',help='Explizit NEUE leere Live-Paper-Historie anlegen; nie für Migration')
    sub.add_parser('demo',help='Offline-Demo mit SYNTHETISCHEN Preisen erzeugen')
    sub.add_parser('once',help='Einmaliger Live-Datenzyklus (ohne Echtgeld)')
    sub.add_parser('start',help='Dashboard und überwachte Paper-Trading-Worker')
    serve=sub.add_parser('serve',help='Nur Dashboard anzeigen (read-only)')
    serve.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    demo=args.cmd=='demo' or (args.cmd=='serve' and args.demo)
    db=db_file('demo_v03_bitvavo' if demo else 'live_v03_bitvavo')
    if args.cmd=='serve':
        inspect_db(db,mode='demo' if demo else 'live')
        server(db,demo,int(os.getenv('PORT','8787')))
        return 0
    with WriterLock(db):
        if args.cmd=='init-live':
            if Path(db).exists(): raise FileExistsError('Existing database will not be overwritten')
            con=open_db(db)
            con.close()
            print('Neue Paper-Historie angelegt; keine Marktabfrage und keine Orders.')
            return 0
        if args.cmd=='demo' and not Path(db).exists():
            con=open_db(db)
            con.close()
        inspect_db(db,mode='demo' if demo else 'live')
        if args.cmd=='start': return run_live(db,int(os.getenv('PORT','8787')))
        con=open_existing_db(db)
        try:
            if args.cmd=='demo':
                if con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0:
                    build_synthetic_demo(con)
                print('Synthetische Demo bereit. Start: python main.py serve --demo')
            else:
                q=bitvavo_quotes()
                record_live_quotes(con,q)
                initial=initialize_buyhold(con,q)
                snapshots=live_snapshots({},quote_fetcher=lambda symbol:q[symbol])
                print({'markets':list(snapshots), 'benchmark_buys':initial,
                       'decisions':quant_cycle(con,snapshots),'llm_calls':llm_cycle(con,snapshots)})
        finally: con.close()
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print(f'Start/command failed: {safe_error(exc)}. Check database, configuration and writer lock.',file=sys.stderr)
        sys.exit(1)
