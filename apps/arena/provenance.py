"""Private append-only pre-request snapshots; no API credentials or raw errors."""
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import arena as core


def reserve_snapshot(con, attempt, agent, context, snap):
    location=con.execute('PRAGMA database_list').fetchone()[2]
    if not location:raise ValueError('Audit requires a file database')
    folder=Path(location).parent/'llm-audit'
    folder.mkdir(mode=0o700,exist_ok=True)
    prompt=json.dumps({'instructions':core.SYSTEM,'schema':core.SIGNAL_SCHEMA},sort_keys=True)
    record={'audit_version':2,'response_policy':'strict-signal-v1','budget_policy':'eur-reservation-v1','attempt':attempt,'agent':agent,'market':snap.symbol,'model':os.getenv(
        'OPENAI_MODEL' if agent=='gpt' else 'ANTHROPIC_MODEL',
        'gpt-6.1-sol' if agent=='gpt' else 'claude-sonnet-5-5'),
        'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'context':context,
        'snapshot':{'fetched_at':snap.fetched_at,'quote':asdict(snap.quote),
                    'bars':{str(tf):[asdict(bar) for bar in bars] for tf,bars in snap.bars.items()}},
        'fee_rate':core.fee_rate(),'slippage':core.slip_rate(),'recorded_at':core.utcnow()}
    record['code_sha256']={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                           for name in ('arena.py','engine03.py','strategies.py')}
    payload=json.dumps(record,sort_keys=True,allow_nan=False).encode()
    path=folder/(Path(location).name+'-'+str(attempt)+'.json')
    from budget import audit_lock
    from backup import sync_directory
    with audit_lock(con):
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        sync_directory(folder)
    return {'attempt':attempt,'snapshot_sha256':hashlib.sha256(payload).hexdigest(),
            'prompt_sha256':record['prompt_sha256'],'model':record['model'],
            'token_usage':None,'api_cost_eur':None}


def capture_usage(response):
    """Only provider numeric usage fields; never persist response text/headers."""
    import threading
    if not hasattr(capture_usage,'local'):capture_usage.local=threading.local()
    usage=response.get('usage') if isinstance(response,dict) else None
    if not isinstance(usage,dict):usage={}
    clean={k:v for k,v in usage.items()
        if k in ('input_tokens','output_tokens','total_tokens','cache_creation_input_tokens','cache_read_input_tokens')
        and isinstance(v,int) and not isinstance(v,bool) and v>=0}
    for detail,keys in [('input_tokens_details',('cached_tokens','cache_write_tokens')),
                        ('output_tokens_details',('reasoning_tokens',))]:
        nested=usage.get(detail,{})
        if isinstance(nested,dict):
            for key in keys:
                value=nested.get(key)
                if isinstance(value,int) and not isinstance(value,bool) and value>=0:clean[key]=value
    capture_usage.local.usage=clean or None


def take_usage():
    local=getattr(capture_usage,'local',None)
    usage=getattr(local,'usage',None)
    if local is not None:local.usage=None
    return usage


def strict_response(response, url):
    """Validate raw JSON fields before the legacy adapter normalizes them."""
    if url=='https://api.openai.com/v1/responses':
        chunks=[part['text'] for msg in response.get('output',[]) for part in msg.get('content',[])
                if part.get('type')=='output_text']
    elif url=='https://api.anthropic.com/v1/messages':
        chunks=[part['text'] for part in response.get('content',[]) if part.get('type')=='text']
    else:return
    signal=json.loads(''.join(chunks))
    if not isinstance(signal,dict) or set(signal)!=set(core.SIGNAL_SCHEMA['required']):
        raise ValueError('Unexpected signal fields')
    core.validate_signal(signal)
    if (signal['action']=='SELL' and signal['target_fraction']!=0 or
        signal['action']=='BUY' and signal['target_fraction'] not in (.25,.45)):
        raise ValueError('Inconsistent action and target')
