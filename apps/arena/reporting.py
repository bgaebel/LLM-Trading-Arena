"""Validated filters shared by reports, history and exports."""
from datetime import datetime, timezone
from arena import AGENTS, SYMBOLS
from collections import deque
from pathlib import Path
import json
import math


def utc_bound(value):
    if value is None or value == '':
        return None
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc).isoformat(timespec='seconds')


def filters(query):
    result = {name: query.get(name, [None])[0] or None for name in ('start', 'end', 'agent', 'symbol')}
    result['start'], result['end'] = utc_bound(result['start']), utc_bound(result['end'])
    if result['start'] and result['end'] and result['start'] > result['end']:
        raise ValueError('Start after end')
    if result['agent'] and result['agent'] not in AGENTS:
        raise ValueError('Unknown agent')
    if result['symbol'] and result['symbol'] not in SYMBOLS:
        raise ValueError('Unknown market')
    return result


def select_rows(con, table, selected, limit=None):
    if table not in ('trades', 'decisions'):
        raise ValueError('Unsupported report table')
    conditions, params = [], []
    for key, comparison in (('start', 'ts>=?'), ('end', 'ts<=?'), ('agent', 'agent=?'), ('symbol', 'symbol=?')):
        if selected.get(key):
            conditions.append(comparison)
            params.append(selected[key])
    clause = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    sql = 'SELECT * FROM ' + table + clause + ' ORDER BY id DESC'
    if limit is not None:
        sql += ' LIMIT ?'
        params.append(limit)
    return [dict(row) for row in con.execute(sql, params)]


def history(con, selected, limit=500):
    result = {'filters': selected, 'portfolio_metrics_scope': 'whole portfolio; symbol filters history only'}
    for table in ('trades', 'decisions'):
        rows = select_rows(con, table, selected, limit + 1)
        result[table] = rows[:limit]
        result[table + '_truncated'] = len(rows) > limit
    return result


def accounting(con, agent, start, end):
    """FIFO realized net PnL, preserving fee allocation and unknown opening inventory."""
    lots = {symbol: deque() for symbol in SYMBOLS}
    realized = 0.
    sell_events = 0
    missing = False
    for row in con.execute('SELECT * FROM trades WHERE agent=? AND ts<=? ORDER BY id', (agent, end)):
        qty = float(row['qty'])
        if not math.isfinite(qty) or qty <= 0 or row['symbol'] not in lots:
            raise ValueError('Invalid trade history')
        unit = (row['notional'] + row['fee'] if row['side'] == 'BUY' else row['notional'] - row['fee']) / qty
        if not math.isfinite(unit):
            raise ValueError('Invalid trade value')
        queue = lots[row['symbol']]
        if row['side'] == 'BUY':
            queue.append([qty, unit])
        elif row['side'] in ('SELL', 'RISK_SELL'):
            in_period = start < row['ts'] <= end
            if in_period: sell_events += 1
            while qty > 1e-10 and queue:
                matched = min(qty, queue[0][0])
                if in_period: realized += matched * (unit - queue[0][1])
                qty -= matched
                queue[0][0] -= matched
                if queue[0][0] <= 1e-10: queue.popleft()
            if qty > 1e-10: missing = True
        else:
            raise ValueError('Unsupported virtual trade side')
    return {'realized_pnl_eur': None if missing else realized,
            'sell_events': sell_events, 'opening_inventory_unknown': missing,
            'open_lots': {symbol: {'quantity': sum(qty for qty, _ in queue),
                                   'cost_basis_eur': sum(qty * cost for qty, cost in queue)}
                          for symbol, queue in lots.items()}, 'cost_basis_method': 'FIFO, fees included'}


def api_costs(con, agent, start, end):
    """Known estimates and explicit unknowns, attributed to request-start timestamps."""
    database = Path(con.execute('PRAGMA database_list').fetchone()[2])
    path = database.parent / 'llm-audit' / (database.name + '.ledger.json')
    ledger = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'entries': {}}
    total, unknown = 0., 0
    for row in con.execute("SELECT id FROM llm_calls WHERE agent=? AND ts>? AND ts<=? AND status NOT IN ('BUDGET_BLOCKED','NOT_SENT')",
                           (agent, start, end)):
        entry = ledger['entries'].get(str(row[0]), {})
        cost = entry.get('estimated_cost_eur')
        if cost is None: unknown += 1
        else:
            from budget import amount
            total += float(amount(cost))
    return {'known_estimated_cost_eur': total, 'unknown_cost_attempts': unknown,
            'complete_estimated_cost_eur': total if unknown == 0 else None,
            'basis': 'configured EUR prices; attributed to request start; not invoices'}
