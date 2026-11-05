"""Commands: python main.py demo | start | once | serve --demo"""
import argparse
import csv
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from arena import SYMBOLS, record_live_quotes, load_dotenv, open_db, log, latest_quotes
from bitvavo import quotes as bitvavo_quotes
from engine03 import (live_snapshots, quant_cycle, llm_cycle, build_synthetic_demo,
                      initialize_buyhold, state)

ROOT=Path(__file__).resolve().parent


def db_file(name: str) -> str:
    """Writable per-user data, even if the application sits under Program Files."""
    override = os.getenv('LLM_TRADING_ARENA_DATA_DIR')
    local = os.getenv('LOCALAPPDATA')
    data_dir = (Path(override).expanduser() if override else
                Path(local) / 'LLMTradingArena' / 'data' if local else
                ROOT / 'data')
    data_dir.mkdir(parents=True, exist_ok=True)
    result = data_dir / f'{name}.sqlite3'
    return str(result)


def server(db_path: str, demo: bool, port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/', '/index.html'):
                content=(ROOT/'static'/'index.html').read_bytes()
                ct='text/html; charset=utf-8'
            elif path=='/api/state':
                con=open_db(db_path)
                try: data=state(con,demo=demo)
                finally: con.close()
                content=json.dumps(data,ensure_ascii=False).encode()
                ct='application/json; charset=utf-8'
            elif path=='/api/trades.csv':
                con=open_db(db_path)
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
            self.send_response(200)
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
    print(f'Dashboard: http://{host}:{port}   |   Datenbank: {db_path}', flush=True)
    try: httpd.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: print('\nDashboard beendet.')
    finally: httpd.server_close()


def quote_worker(db_path: str, stop: threading.Event):
    """Continuous risk monitoring independent from slow model inference."""
    interval = max(3., float(os.getenv('MARKET_POLL_SECONDS','5')))
    con = open_db(db_path)
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                quotes=bitvavo_quotes()
                record_live_quotes(con,quotes)
                new=initialize_buyhold(con,quotes)
                if new:
                    message=f'Buy & Hold initialisiert: {new} virtuelle Käufe auf frischen Bitvavo-Quotes'
                    log(con,message,'INFO')
                    print(message,flush=True)
            except Exception as exc:
                msg=f'Quote-/Risikopoll fehlgeschlagen: {exc}'
                try: log(con,msg,'ERROR')
                except Exception: pass
                print(msg,flush=True)
            stop.wait(max(.1,interval-(time.monotonic()-started)))
    finally: con.close()


# Shared candle cache accessed only by the signal worker; LLM snapshot handoff is guarded.
_latest_lock=threading.Lock()
_latest_snaps={}

def signal_worker(db_path: str, stop: threading.Event):
    """Process each asset independently; an ETH candle fault cannot block BTC.

    Quote-worker and the passive benchmark continue even when this worker is
    waiting for the first healthy OHLCV snapshot.
    """
    con=open_db(db_path)
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
                    warn_once('quotes','Warte auf frische Bitvavo-Geld-/Briefkurse')
                else:
                    def bad_market(symbol,exc):
                        warn_once(symbol,f'{symbol}: Kerzendaten nicht verfügbar ({exc}); nur dieses Symbol pausiert')
                    snaps=live_snapshots(cache,quote_fetcher=lambda symbol:q[symbol],
                                         on_error=bad_market)
                    with _latest_lock:
                        _latest_snaps.clear()
                        _latest_snaps.update(snaps)
                    if snaps:
                        count=quant_cycle(con,snaps)
                        if count:print(f'{count} quantitative Strategieentscheidungen geprüft',flush=True)
                    else:
                        warn_once('no_snapshots','Warte auf gültige, abgeschlossene Kerzendaten; Buy & Hold läuft unabhängig')
            except Exception as exc:
                message=f'Strategie-Zyklus ausgefallen (keine quantitativen Orders): {exc}'
                warn_once('cycle',message,period=120)
            stop.wait(max(.2,60-(time.monotonic()-started)))
    finally:con.close()

def llm_worker(db_path: str, stop: threading.Event):
    """LLM calls never block quote/risk monitoring or quantitative signals."""
    con=open_db(db_path)
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                with _latest_lock:snaps=dict(_latest_snaps)
                if snaps:llm_cycle(con,snaps)
            except Exception as exc:
                message=f'LLM-Zyklus fehlgeschlagen (keine Orders): {exc}'
                try:log(con,message,'ERROR')
                except Exception:pass
                print(message,flush=True)
            stop.wait(max(.2,20-(time.monotonic()-started)))
    finally:con.close()


def main():
    os.chdir(ROOT)
    load_dotenv()
    parser=argparse.ArgumentParser(description='LLM Trading Arena (ausschließlich virtuell)')
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('demo',help='Offline-Demo mit SYNTHETISCHEN Preisen erzeugen')
    sub.add_parser('once',help='Einmaliger Live-Datenzyklus (ohne Echtgeld)')
    sub.add_parser('start',help='Dashboard + Bitvavo Quote-Poller (~5s) + Multi-Timeframe + LLM Worker')
    serve=sub.add_parser('serve',help='Nur Dashboard anzeigen')
    serve.add_argument('--demo',action='store_true',help='Demo statt Live anzeigen')
    args=parser.parse_args()
    if args.cmd=='demo':
        db=db_file('demo_v03_bitvavo')
        con=open_db(db)
        try:
            if con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0:
                build_synthetic_demo(con)
        finally: con.close()
        print('Synthetische Demo bereit. Start: python main.py serve --demo')
    elif args.cmd=='once':
        db=db_file('live_v03_bitvavo')
        con=open_db(db)
        try:
            q=bitvavo_quotes()
            record_live_quotes(con,q)
            initial=initialize_buyhold(con,q)
            snapshots=live_snapshots({},quote_fetcher=lambda symbol:q[symbol])
            print({'markets':list(snapshots), 'benchmark_buys':initial, 'decisions':quant_cycle(con,snapshots),'llm_calls':llm_cycle(con,snapshots)})
        finally: con.close()
    elif args.cmd=='serve':
        db=db_file('demo_v03_bitvavo') if args.demo else db_file('live_v03_bitvavo')
        if args.demo:
            con=open_db(db)
            try:
                if con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0:
                    build_synthetic_demo(con)
            finally:con.close()
        server(db,args.demo,int(os.getenv('PORT','8787')))
    else:
        db=db_file('live_v03_bitvavo')
        # Initialize schema before both workers start, avoiding first-launch schema races.
        initial=open_db(db)
        initial.close()
        stop=threading.Event()
        threads=[threading.Thread(target=quote_worker,args=(db,stop),daemon=True),
                 threading.Thread(target=signal_worker,args=(db,stop),daemon=True),
                 threading.Thread(target=llm_worker,args=(db,stop),daemon=True)]
        for thread in threads: thread.start()
        try: server(db,False,int(os.getenv('PORT','8787')))
        finally:
            stop.set()
            for thread in threads: thread.join(timeout=2)


if __name__=='__main__': main()
