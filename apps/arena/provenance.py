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
    record={'attempt':attempt,'agent':agent,'market':snap.symbol,'model':os.getenv(
        'OPENAI_MODEL' if agent=='gpt' else 'ANTHROPIC_MODEL',
        'gpt-6.1-sol' if agent=='gpt' else 'claude-sonnet-5-5'),
        'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'context':context,
        'snapshot':{'fetched_at':snap.fetched_at,'quote':asdict(snap.quote),
                    'bars':{str(tf):[asdict(bar) for bar in bars] for tf,bars in snap.bars.items()}},
        'fee_rate':core.fee_rate(),'slippage':core.slip_rate(),'recorded_at':core.utcnow()}
    payload=json.dumps(record,sort_keys=True,allow_nan=False).encode()
    path=folder/(Path(location).name+'-'+str(attempt)+'.json')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(payload);f.flush();os.fsync(f.fileno())
    return {'attempt':attempt,'snapshot_sha256':hashlib.sha256(payload).hexdigest(),
            'prompt_sha256':record['prompt_sha256'],'model':record['model'],
            'token_usage':None,'api_cost_eur':None}


def capture_usage(response):
    """Only provider numeric usage fields; never persist response text/headers."""
    import threading
    if not hasattr(capture_usage,'local'):capture_usage.local=threading.local()
    usage=response.get('usage') if isinstance(response,dict) else None
    capture_usage.local.usage={k:v for k,v in (usage or {}).items()
        if k in ('input_tokens','output_tokens','total_tokens','cache_creation_input_tokens','cache_read_input_tokens')
        and isinstance(v,int) and not isinstance(v,bool) and v>=0} or None


def take_usage():
    local=getattr(capture_usage,'local',None)
    usage=getattr(local,'usage',None)
    if local is not None:local.usage=None
    return usage
