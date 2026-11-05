"""Durable local spend reservations. Prices are explicit user estimates, never invoices."""
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from operations import WriterLock


class BudgetBlocked(RuntimeError):
    pass


def audit_folder(con):
    name = con.execute('PRAGMA database_list').fetchone()[2]
    if not name:
        raise ValueError('Persistent audit requires a file database')
    database = Path(name)
    folder = database.parent / 'llm-audit'
    folder.mkdir(mode=0o700, exist_ok=True)
    return database, folder


def audit_lock(con):
    _, folder = audit_folder(con)
    return WriterLock(folder / 'maintenance')


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.ledger-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid monetary setting')
    return result


def settings(agent):
    prefix = 'OPENAI' if agent == 'gpt' else 'ANTHROPIC'
    names = [prefix + '_INPUT_EUR_PER_MILLION', prefix + '_OUTPUT_EUR_PER_MILLION']
    rates = [os.getenv(name) for name in names]
    if any(rate is not None for rate in rates) and not all(rate is not None for rate in rates):
        raise ValueError('Both input and output prices are required')
    return [str(amount(rate)) for rate in rates] if all(rate is not None for rate in rates) else None


def ledger(con):
    database, folder = audit_folder(con)
    path = folder / (database.name + '.ledger.json')
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'format': 1, 'entries': {}}
    if data.get('format') != 1 or not isinstance(data.get('entries'), dict):
        raise ValueError('Invalid budget ledger')
    return path, data


def reserve(con, attempt, agent, now_epoch=None):
    day = datetime.fromtimestamp(now_epoch, timezone.utc).date().isoformat() if now_epoch is not None else datetime.now(timezone.utc).date().isoformat()
    rates = settings(agent)
    cap = amount(os.environ['LLM_DAILY_BUDGET_EUR']) if 'LLM_DAILY_BUDGET_EUR' in os.environ else None
    hold = amount(os.environ['LLM_CALL_RESERVE_EUR']) if 'LLM_CALL_RESERVE_EUR' in os.environ else None
    if cap is not None and (hold is None or hold <= 0 or rates is None):
        raise BudgetBlocked('Budget requires positive call reservation and explicit prices')
    with audit_lock(con):
        path, data = ledger(con)
        if data.get('restored_day')==day:
            raise BudgetBlocked('Restored history: same-day external spend is uncertain')
        if str(attempt) in data['entries']:
            raise BudgetBlocked('Attempt already reserved')
        if cap is not None:
            prior = con.execute("SELECT id FROM llm_calls WHERE ts>=? AND ts<? AND id!=? AND status NOT IN ('BUDGET_BLOCKED','NOT_SENT')",
                                (day, (datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat(), attempt)).fetchall()
            if any(str(row[0]) not in data['entries'] for row in prior):
                raise BudgetBlocked('Earlier attempts have unknown cost')
            used = Decimal(0)
            for entry in data['entries'].values():
                if entry['day'] != day:
                    continue
                if entry.get('reservation_exceeded'):
                    raise BudgetBlocked('Call cost exceeded its reservation')
                value = entry.get('charge_eur')
                if value is None:
                    raise BudgetBlocked('Earlier cost is unknown')
                used += amount(value)
            if used + hold > cap:
                raise BudgetBlocked('Daily reservation limit reached')
        entry = {'day': day, 'agent': agent, 'state': 'reserved', 'rates': rates,
                 'reserved_eur': str(hold) if hold is not None else None,
                 'charge_eur': str(hold) if hold is not None else None,
                 'usage': None, 'estimated_cost_eur': None}
        data['entries'][str(attempt)] = entry
        atomic_json(path, data)
        return entry


def settle(con, attempt, usage, status, latency, *, not_sent=False):
    """Unknown usage retains the reservation, including timeouts and process crashes."""
    with audit_lock(con):
        path, data = ledger(con)
        entry = data['entries'][str(attempt)]
        entry.update(state=status, latency_seconds=latency, usage=usage)
        cost = None
        if not_sent:
            cost = Decimal(0)
        elif usage and entry['rates'] and all(key in usage for key in ('input_tokens', 'output_tokens')):
            # Caching has provider/model-specific tariffs: do not invent a price for it.
            if not any(usage.get(key, 0) for key in ('cache_creation_input_tokens', 'cache_read_input_tokens', 'cached_tokens', 'cache_write_tokens')):
                cost = (amount(usage['input_tokens']) * amount(entry['rates'][0]) +
                        amount(usage['output_tokens']) * amount(entry['rates'][1])) / Decimal(1_000_000)
        if cost is not None:
            entry.update(estimated_cost_eur=str(cost), charge_eur=str(cost))
        if cost is not None and entry['reserved_eur'] is not None and cost > amount(entry['reserved_eur']):
            entry['reservation_exceeded'] = True
        atomic_json(path, data)
        return dict(entry)


def summary(con):
    """Read-only status; no ledger creation when browsing a legacy database."""
    database = Path(con.execute('PRAGMA database_list').fetchone()[2])
    path = database.parent / 'llm-audit' / (database.name + '.ledger.json')
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'entries': {}}
    today = datetime.now(timezone.utc).date().isoformat()
    entries = [e for e in data['entries'].values() if e['day'] == today]
    known = sum((amount(e['estimated_cost_eur']) for e in entries if e.get('estimated_cost_eur') is not None), Decimal(0))
    held = sum((amount(e['charge_eur']) for e in entries if e.get('charge_eur') is not None), Decimal(0))
    prior=con.execute("SELECT id FROM llm_calls WHERE ts>=? AND ts<? AND status NOT IN ('BUDGET_BLOCKED','NOT_SENT')",
                      (today,(datetime.fromisoformat(today)+timedelta(days=1)).date().isoformat())).fetchall()
    legacy=sum(str(row[0]) not in data['entries'] for row in prior)
    configured=[agent for agent,key in [('gpt','OPENAI_API_KEY'),('claude','ANTHROPIC_API_KEY')] if os.getenv(key)]
    enabled='LLM_DAILY_BUDGET_EUR' in os.environ
    blocked=data.get('restored_day')==today
    if enabled:
        cap=amount(os.environ['LLM_DAILY_BUDGET_EUR'])
        hold=amount(os.environ['LLM_CALL_RESERVE_EUR']) if 'LLM_CALL_RESERVE_EUR' in os.environ else None
        blocked=blocked or (hold is None or hold<=0 or legacy>0 or any(e.get('charge_eur') is None or e.get('reservation_exceeded') for e in entries)
                 or held+(hold or Decimal(0))>cap or any(settings(agent) is None for agent in configured))
    return {'restore_day_block':data.get('restored_day')==today,'providers_configured':bool(configured),'status':'blocked' if blocked else 'enabled' if enabled else 'not_configured',
            'day': today, 'cap_eur': os.getenv('LLM_DAILY_BUDGET_EUR'),
            'estimated_cost_eur': str(known), 'charged_or_reserved_eur': str(held),
            'unknown_cost_attempts': legacy+sum(e.get('estimated_cost_eur') is None for e in entries),
            'reservation_exceeded': any(e.get('reservation_exceeded') for e in entries),
            'basis': 'configured estimates, not provider invoices'}
