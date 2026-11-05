"""Operational safeguards; no strategy rules or broker operations."""
from __future__ import annotations

import os
import hashlib
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

TABLES = ('portfolios', 'decisions', 'trades', 'market', 'market_ticks',
          'equity', 'llm_calls', 'logs')
WORKER_LIMITS = {'quotes': 45, 'strategy': 180, 'llm': 240}


def safe_error(exc):
    # Never persist provider response bodies, URLs, headers or exception messages.
    return type(exc).__name__


def read_db(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def open_existing_db(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=10000')
    con.execute('PRAGMA journal_mode=WAL')
    return con


def inspect_db(path, *, full=True, mode=None):
    """Read-only consistent inventory. Reject foreign/corrupt/mixed-mode databases."""
    con = read_db(path)
    try:
        con.execute('BEGIN')
        check = con.execute('PRAGMA integrity_check' if full else 'PRAGMA quick_check').fetchall()
        if [r[0] for r in check] != ['ok']:
            raise ValueError('SQLite integrity check failed')
        if con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite foreign key check failed')
        # Explicit required columns; no automatic schema repair on existing history.
        from arena import AGENTS
        required = {
            'portfolios': 'agent cash btc eth peak halted',
            'decisions': 'id ts agent symbol bar_ts model action target confidence reason inputs status',
            'trades': 'id ts agent symbol side qty fill notional fee slip_rate decision_id',
            'market': 'symbol ts bar_ts bid ask last_close source',
            'market_ticks': 'id ts symbol mid', 'equity': 'id ts agent value cash btc eth',
            'llm_calls': 'id ts agent symbol ref_mid status message',
            'logs': 'id ts level agent message',
        }
        for table, columns in required.items():
            actual = {r['name'] for r in con.execute(f'PRAGMA table_info({table})')}
            if not set(columns.split()) <= actual:
                raise ValueError('Unsupported schema: ' + table)
        if {r[0] for r in con.execute('SELECT agent FROM portfolios')} != set(AGENTS):
            raise ValueError('Unexpected portfolio set; manual investigation required')
        if con.execute('PRAGMA user_version').fetchone()[0] != 0:
            raise ValueError('Unsupported schema version; no automatic migrations')
        for table, expected in [('decisions', ['agent','symbol','bar_ts']), ('equity', ['ts','agent'])]:
            unique_columns=[]
            for index in con.execute(f'PRAGMA index_list({table})'):
                if index['unique'] and not index['partial']:
                    escaped=index['name'].replace(chr(34),chr(34)*2)
                    unique_columns.append([r['name'] for r in con.execute(f'PRAGMA index_info("{escaped}")')])
            if expected not in unique_columns: raise ValueError('Missing idempotency constraint')
        sources = {r[0] for r in con.execute('SELECT DISTINCT source FROM market')}
        # Also inspect historical inputs, not only the most recent market row.
        demo_history = con.execute("SELECT 1 FROM decisions WHERE inputs LIKE '%SYNTHETIC%' LIMIT 1").fetchone()
        if mode == 'live' and (demo_history or any(s != 'BITVAVO-LIVE' for s in sources)):
            raise ValueError('Non-live data in live database')
        if mode == 'demo' and any(s != 'SYNTHETIC-DEMO' for s in sources):
            raise ValueError('Non-demo data in demo database')
        return {
            'schema_sha256': hashlib.sha256('\n'.join(r[0] or '' for r in con.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name")).encode()).hexdigest(),
            'integrity': 'ok', 'user_version': con.execute('PRAGMA user_version').fetchone()[0],
            'counts': {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES},
            'latest_trade': con.execute('SELECT MAX(ts) FROM trades').fetchone()[0],
            'latest_decision': con.execute('SELECT MAX(ts) FROM decisions').fetchone()[0],
            'sources': sorted(sources),
        }
    finally:
        con.close()


class WriterLock:
    """OS-owned advisory lock, automatically released on exit/crash; never unlink it."""
    def __init__(self, db_path):
        self.path = Path(str(Path(db_path).resolve()) + '.writer.lock')
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError('Another writer/maintenance process owns this database') from None
        return self

    def __exit__(self, *args):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


class Health:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()
        self.limits = dict(WORKER_LIMITS)
        self.limits['quotes'] = max(45,3*float(os.getenv('MARKET_POLL_SECONDS','5')))
        self.workers = {name: {'last_tick': self.started, 'status': 'starting',
                               'last_success': None, 'error': None} for name in WORKER_LIMITS}

    def tick(self, name, status='ok', error=None):
        with self.lock:
            row = self.workers[name]
            row.update(last_tick=self.clock(), status=status, error=safe_error(error) if error else None)
            if status == 'ok':
                row['last_success'] = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def snapshot(self):
        with self.lock:
            result = {k: dict(v) for k, v in self.workers.items()}
        for name, row in result.items():
            row['age_seconds'] = round(max(0, self.clock() - row.pop('last_tick')), 1)
            if row['age_seconds'] > self.limits[name]:
                row['status'] = 'stalled'
        return result


def health_report(db_path, health=None, *, demo=False):
    """Passive checks only: no billable API requests and no database writes."""
    result = {'process_id': os.getpid(), 'mode': 'demo' if demo else 'paper-live', 'status': 'ok',
              'workers': health.snapshot() if health else {}, 'providers': {}}
    try:
        con = read_db(db_path)
        try:
            con.execute('BEGIN')
            con.execute('SELECT 1 FROM portfolios LIMIT 1').fetchone()
            result['sqlite'] = {'status': 'ok'}
            result['last_decision'] = con.execute('SELECT MAX(ts) FROM decisions').fetchone()[0]
            markets = {}
            for row in con.execute('SELECT symbol,ts,source FROM market'):
                age = time.time() - datetime.fromisoformat(row['ts']).timestamp()
                markets[row['symbol']] = {'age_seconds': round(age, 1),
                    'status': 'ok' if 0 <= age <= 20 and row['source'] == 'BITVAVO-LIVE' else 'stale'}
            from arena import latest_quotes, SYMBOLS
            valid_quotes = latest_quotes(con, max_age_seconds=20) is not None
            result['bitvavo'] = {'status': 'disabled' if demo else
                'ok' if valid_quotes and all(v['status'] == 'ok' for v in markets.values()) else 'degraded',
                'markets': markets}
            for agent, key in [('gpt', 'OPENAI_API_KEY'), ('claude', 'ANTHROPIC_API_KEY')]:
                row = con.execute('SELECT ts,status FROM llm_calls WHERE agent=? ORDER BY id DESC LIMIT 1', (agent,)).fetchone()
                observations = {}
                for symbol in SYMBOLS:
                    last = con.execute('SELECT ts,status FROM llm_calls WHERE agent=? AND symbol=? ORDER BY id DESC LIMIT 1',
                                       (agent, symbol)).fetchone()
                    status = 'disabled' if demo or not os.getenv(key) else 'untested' if last is None else (
                        'ok' if last['status'] in ('OK', 'STALE_QUOTE') else
                        'pending' if last['status'] == 'PENDING' and 0 <= time.time()-datetime.fromisoformat(last['ts']).timestamp() <= 120
                        else 'degraded')
                    observations[symbol] = {'status': status, 'last_attempt': last['ts'] if last else None,
                                            'last_result': last['status'] if last else None}
                statuses = {item['status'] for item in observations.values()}
                aggregate = next(status for status in ('degraded', 'untested', 'pending', 'ok', 'disabled')
                                 if status in statuses)
                result['providers'][agent] = {'status': aggregate, 'last_attempt': row['ts'] if row else None,
                                               'last_result': row['status'] if row else None,
                                               'markets': observations}
        finally:
            con.close()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        result['sqlite'] = {'status': 'error', 'error': safe_error(exc)}
    if not health:
        result['status'] = 'read-only'
    if result['sqlite']['status'] != 'ok' or any(v['status'] in ('stalled', 'failed') for v in result['workers'].values()):
        result['status'] = 'error'
    elif health and (result['bitvavo']['status'] == 'degraded' or
                    any(v['status'] != 'ok' for v in result['workers'].values()) or
                    any(v['status'] in ('degraded', 'untested') for v in result['providers'].values())):
        result['status'] = 'degraded'
    result['ready'] = bool(health) and result['status'] == 'ok'
    result['live'] = result['sqlite']['status'] == 'ok' and bool(health) and result['status'] != 'error'
    return result
