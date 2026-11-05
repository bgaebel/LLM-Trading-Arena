"""LLM Trading Arena - strictly virtual spot-trading research MVP.
Python 3.11+, standard library only. No broker order endpoints exist here.
"""
from __future__ import annotations
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENTS = ('gpt', 'claude', 'trend', 'breakout', 'meanrev', 'ensemble', 'buyhold')
SYMBOLS = ('BTCEUR', 'ETHEUR')
PAIRS = {'BTCEUR': 'BTC-EUR', 'ETHEUR': 'ETH-EUR'}
INTERVAL_MINUTES = 1
START_CASH = 10_000.0
MAX_SYMBOL_WEIGHT = .45
MAX_TOTAL_WEIGHT = .90
MIN_TRADE_EUR = 50.0
MAX_SPREAD_BPS = 50.0
DRAWDOWN_KILL = .10
SYSTEM = (
    'You are an experimental crypto paper-trading signal analyst, NOT a broker, order executor, '
    'risk engine or guaranteed forecaster. Use ONLY the supplied multi-timeframe CLOSED candle '
    'indicators and quotes; do not claim to know news, funding, other exchange order books or '
    'unseen future prices. Choose BUY, SELL or HOLD and a target allocation of 0, 0.25, or 0.45. '
    'Trades have explicitly stated taker fees, spread and slippage; avoiding overtrading is valuable. '
    'BUY must use 0.25 or 0.45, SELL must use 0.0; HOLD retains existing weight. '
    'Explain the specific evidence and uncertainty briefly. Return ONLY the prescribed JSON schema. '
    'Your signal is advisory; a deterministic sandbox risk engine controls every virtual order.'
)
SIGNAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['BUY', 'SELL', 'HOLD']},
        'target_fraction': {'type': 'number', 'enum': [0, .25, .45]},
        'confidence': {'type': 'number'},
        'reason': {'type': 'string'},
    },
    'required': ['action', 'target_fraction', 'confidence', 'reason'],
    'additionalProperties': False,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load_dotenv(path: str = '.env') -> None:
    if not os.path.isfile(path):
        return
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def http_json(url: str, *, payload: dict | None = None, headers: dict | None = None) -> dict:
    raw = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=raw, headers={
        'User-Agent': 'LLMTradingArenaResearch/0.3',
        'Accept': 'application/json',
        **({'Content-Type': 'application/json'} if raw else {}),
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=35 if raw else 12) as resp:
            result=json.loads(resp.read(2_000_000).decode('utf-8'))
            if raw:
                from provenance import capture_usage
                capture_usage(result)
            return result
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}') from None


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> float:
        return 10_000 * (self.ask - self.bid) / self.mid

    def validate(self) -> None:
        if not (math.isfinite(self.bid) and math.isfinite(self.ask) and 0 < self.bid <= self.ask):
            raise ValueError('Ungültiger Geld-/Briefkurs')
        if self.spread_bps > MAX_SPREAD_BPS:
            raise ValueError(f'Spread zu groß: {self.spread_bps:.1f} bp')


def record_live_quotes(con: sqlite3.Connection, qs: dict[str, Quote], *, now: str | None = None) -> None:
    'Update positions and enforce risk even while the LLM worker is waiting.'
    if set(qs) != set(SYMBOLS): raise ValueError('Beide Quotes für Risikoprüfung erforderlich')
    for q in qs.values(): q.validate()
    now = now or utcnow()
    with con:
        con.execute('BEGIN IMMEDIATE')
        for symbol in SYMBOLS:
            q=qs[symbol]
            con.execute('''INSERT INTO market(symbol,ts,bar_ts,bid,ask,last_close,source)
                        VALUES (?,?,0,?,?,?,'BITVAVO-LIVE')
                        ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts,
                        bid=excluded.bid,ask=excluded.ask,source=excluded.source''',
                        (symbol,now,q.bid,q.ask,q.mid))
        for symbol in SYMBOLS:
            con.execute('INSERT INTO market_ticks(ts,symbol,mid) VALUES (?,?,?)', (now,symbol,qs[symbol].mid))
        if int(time.time()) % 600 < 5:
            from datetime import timedelta
            cutoff=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat(timespec='seconds')
            con.execute('DELETE FROM market_ticks WHERE ts < ?', (cutoff,))
        for agent in AGENTS:
            mark_and_risk(con,agent,qs,now)


def latest_quotes(con: sqlite3.Connection, *, max_age_seconds: int = 15) -> dict[str, Quote] | None:
    rows=con.execute('SELECT symbol,ts,bid,ask FROM market').fetchall()
    if len(rows) != len(SYMBOLS): return None
    qs={}
    for r in rows:
        try:
            age = time.time()-datetime.fromisoformat(r['ts']).timestamp()
            if not 0 <= age <= max_age_seconds: return None
            qs[r['symbol']]=Quote(float(r['bid']),float(r['ask']))
            qs[r['symbol']].validate()
        except (TypeError, ValueError): return None
    return qs if set(qs)==set(SYMBOLS) else None

def fee_rate() -> float:
    # Initial standard Bitvavo EUR spot taker tier assumption: 0.25% per side.
    x = float(os.getenv('TAKER_FEE', '.0025'))
    if not 0 <= x <= .05: raise ValueError('TAKER_FEE außerhalb [0, 0.05]')
    return x


def slip_rate() -> float:
    x = float(os.getenv('SLIPPAGE', '.0005'))
    if not 0 <= x <= .05: raise ValueError('SLIPPAGE außerhalb [0, 0.05]')
    return x


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA busy_timeout=10000')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS portfolios (
      agent TEXT PRIMARY KEY, cash REAL NOT NULL, btc REAL NOT NULL DEFAULT 0,
      eth REAL NOT NULL DEFAULT 0, peak REAL NOT NULL, halted INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS decisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, agent TEXT NOT NULL,
      symbol TEXT NOT NULL, bar_ts INTEGER NOT NULL, model TEXT NOT NULL,
      action TEXT NOT NULL, target REAL, confidence REAL, reason TEXT NOT NULL,
      inputs TEXT NOT NULL, status TEXT NOT NULL,
      UNIQUE(agent,symbol,bar_ts));
    CREATE TABLE IF NOT EXISTS trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, agent TEXT NOT NULL,
      symbol TEXT NOT NULL, side TEXT NOT NULL, qty REAL NOT NULL, fill REAL NOT NULL,
      notional REAL NOT NULL, fee REAL NOT NULL, slip_rate REAL NOT NULL,
      decision_id INTEGER, FOREIGN KEY(decision_id) REFERENCES decisions(id));
    CREATE TABLE IF NOT EXISTS market (
      symbol TEXT PRIMARY KEY, ts TEXT NOT NULL, bar_ts INTEGER NOT NULL,
      bid REAL NOT NULL, ask REAL NOT NULL, last_close REAL NOT NULL, source TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS market_ticks (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL, mid REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_id ON market_ticks(symbol,id);
    CREATE TABLE IF NOT EXISTS equity (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, agent TEXT NOT NULL,
      value REAL NOT NULL, cash REAL NOT NULL, btc REAL NOT NULL, eth REAL NOT NULL,
      UNIQUE(ts,agent));
    CREATE TABLE IF NOT EXISTS llm_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, agent TEXT NOT NULL,
      symbol TEXT NOT NULL, ref_mid REAL NOT NULL, status TEXT NOT NULL, message TEXT);
    CREATE INDEX IF NOT EXISTS idx_llm_calls_agent_symbol ON llm_calls(agent,symbol,id);
    CREATE TABLE IF NOT EXISTS logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL,
      agent TEXT, message TEXT NOT NULL);
    ''')
    for name in AGENTS:
        con.execute('INSERT OR IGNORE INTO portfolios (agent,cash,peak) VALUES (?,?,?)', (name,START_CASH,START_CASH))
    con.commit()
    return con


def log(con: sqlite3.Connection, msg: str, level: str = 'INFO', agent: str | None = None):
    con.execute('INSERT INTO logs(ts,level,agent,message) VALUES (?,?,?,?)', (utcnow(), level, agent, msg[:450]))
    con.commit()


def balance(con: sqlite3.Connection, agent: str) -> dict:
    return dict(con.execute('SELECT * FROM portfolios WHERE agent=?', (agent,)).fetchone())


def value(p: dict, qs: dict[str, Quote]) -> float:
    return p['cash'] + sum(p['btc' if symbol == 'BTCEUR' else 'eth'] * qs[symbol].mid for symbol in SYMBOLS)


def current_weight(p: dict, symbol: str, qs: dict[str, Quote]) -> float:
    equity = value(p, qs)
    return (p['btc' if symbol == 'BTCEUR' else 'eth'] * qs[symbol].mid / equity) if equity > 0 else 0


def validate_signal(data: dict) -> dict:
    if not isinstance(data, dict) or data.get('action') not in ('BUY','SELL','HOLD'):
        raise ValueError('LLM: action ungültig')
    target = data.get('target_fraction')
    if not isinstance(target, (int,float)) or isinstance(target, bool) or target not in (0, .25, .45):
        raise ValueError('LLM: target_fraction ungültig')
    confidence = data.get('confidence')
    if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('LLM: confidence ungültig')
    reason = data.get('reason')
    if not isinstance(reason,str) or not reason.strip():
        raise ValueError('LLM: reason fehlt')
    return {'action': data['action'], 'target_fraction': float(target),
            'confidence': float(confidence), 'reason': reason.strip()[:550]}


def llm_signal(agent: str, data: dict) -> tuple[dict,str]:
    user = json.dumps(data, ensure_ascii=False, separators=(',',':'))
    if agent == 'gpt':
        key = os.getenv('OPENAI_API_KEY')
        if not key: raise RuntimeError('OPENAI_API_KEY nicht gesetzt')
        model = os.getenv('OPENAI_MODEL','gpt-6.1-sol')
        result = http_json('https://api.openai.com/v1/responses',
            headers={'Authorization':'Bearer '+key}, payload={
            'model':model, 'instructions':SYSTEM, 'input':user,
            'max_output_tokens':1500,
            'text':{'format':{'type':'json_schema','name':'trade_signal','strict':True,'schema':SIGNAL_SCHEMA}},
        })
        chunks = [part['text'] for msg in result.get('output',[]) for part in msg.get('content',[])
                  if part.get('type') == 'output_text']
        if not chunks: raise ValueError('OpenAI: kein output_text im Ergebnis')
        return validate_signal(json.loads(''.join(chunks))), model
    if agent == 'claude':
        key = os.getenv('ANTHROPIC_API_KEY')
        if not key: raise RuntimeError('ANTHROPIC_API_KEY nicht gesetzt')
        model = os.getenv('ANTHROPIC_MODEL','claude-sonnet-5-5')
        result = http_json('https://api.anthropic.com/v1/messages',
            headers={'x-api-key':key, 'anthropic-version':'2023-06-01'}, payload={
            'model':model, 'max_tokens':1000, 'system':SYSTEM,
            'messages':[{'role':'user','content':user}],
            'output_config':{'format':{'type':'json_schema','schema':SIGNAL_SCHEMA}},
        })
        chunks = [part['text'] for part in result.get('content',[]) if part.get('type')=='text']
        if not chunks: raise ValueError('Claude: kein Text im Ergebnis')
        return validate_signal(json.loads(''.join(chunks))), model
    raise ValueError('Unbekannter LLM-Agent')


def trade_to_target(con: sqlite3.Connection, agent: str, symbol: str, target: float,
                    qs: dict[str, Quote], decision_id: int, *, allow_buy=True,
                    executed_at: str | None=None) -> None:
    p = balance(con, agent)
    if p['halted'] and target > current_weight(p, symbol, qs): return
    col = 'btc' if symbol == 'BTCEUR' else 'eth'
    q = qs[symbol]
    eq = value(p, qs)
    present = p[col] * q.mid
    desired = min(MAX_SYMBOL_WEIGHT, max(0., target)) * eq
    diff = desired - present
    # Avoid unnecessary repeated trades due to minor fluctuations/rebalancing noise.
    if abs(diff) < max(MIN_TRADE_EUR, .02*eq): return
    rate = fee_rate()
    slip = slip_rate()
    now = executed_at or utcnow()
    if diff > 0:
        if not allow_buy: return
        other = sum(p['btc' if s=='BTCEUR' else 'eth'] * qs[s].mid
                    for s in SYMBOLS if s != symbol)
        max_portfolio_notional = max(0., MAX_TOTAL_WEIGHT * eq - other - present)
        spend = min(diff, max_portfolio_notional, p['cash'] / (1+rate))
        if spend < MIN_TRADE_EUR: return
        fill = q.ask * (1+slip)
        qty = spend / fill
        fee = spend*rate
        con.execute(f'UPDATE portfolios SET cash=cash-?,{col}={col}+? WHERE agent=?',
                    (spend+fee,qty,agent))
        side, notional = 'BUY',spend
    else:
        fill = q.bid * (1-slip)
        qty = min(p[col], abs(diff) / q.mid)
        notional = qty * fill
        if notional < MIN_TRADE_EUR: return
        fee = notional*rate
        con.execute(f'UPDATE portfolios SET cash=cash+?,{col}=MAX(0,{col}-?) WHERE agent=?',
                    (notional-fee, qty, agent))
        side = 'SELL'
    con.execute('''INSERT INTO trades(ts,agent,symbol,side,qty,fill,notional,fee,slip_rate,decision_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (now,agent,symbol,side,qty,fill,notional,fee,slip,decision_id))


def mark_and_risk(con: sqlite3.Connection, agent: str, qs: dict[str, Quote], now: str):
    p = balance(con, agent)
    eq = value(p,qs)
    peak = max(eq,p['peak'])
    con.execute('UPDATE portfolios SET peak=? WHERE agent=?',(peak,agent))
    if agent != 'buyhold' and not p['halted'] and peak > 0 and eq < peak*(1-DRAWDOWN_KILL):
        con.execute('UPDATE portfolios SET halted=1 WHERE agent=?',(agent,))
        con.execute('INSERT INTO logs(ts,level,agent,message) VALUES (?,?,?,?)',
                    (now,'ALERT',agent,f'10%-Drawdown-Limit: Zwangsliquidation; vorher Equity={eq:.2f}'))
        # Simulate market sells even if smaller than the standard min trade.
        for symbol in SYMBOLS:
            p = balance(con,agent)
            col = 'btc' if symbol == 'BTCEUR' else 'eth'
            qty = p[col]
            if qty <= 0: continue
            fill = qs[symbol].bid * (1-slip_rate())
            gross = qty * fill
            fee = gross * fee_rate()
            con.execute(f'UPDATE portfolios SET cash=cash+?,{col}=0 WHERE agent=?', (gross-fee,agent))
            con.execute('''INSERT INTO trades(ts,agent,symbol,side,qty,fill,notional,fee,slip_rate,decision_id)
                           VALUES (?,?,?,?,?,?,?,?,?,NULL)''',
                        (now,agent,symbol,'RISK_SELL',qty,fill,gross,fee,slip_rate()))
        p = balance(con,agent)
        eq = value(p,qs)
    # Each agent one point per cycle timestamp; not per symbol.
    con.execute('''INSERT OR REPLACE INTO equity(ts,agent,value,cash,btc,eth)
                   VALUES (?,?,?,?,?,?)''',(now,agent,eq,p['cash'],p['btc'],p['eth']))


