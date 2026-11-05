#!/usr/bin/env python3
"""Pi-only code update/rollback. Never rewinds or migrates trading history."""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
sys.path.insert(0, str(APP))
from arena import load_dotenv
from backup import backup_database, digest
from operations import WriterLock, inspect_db, safe_error

SERVICE = 'llm-trading-arena.service'
TIMER = 'llm-trading-arena-backup.timer'


def command(*args, cwd=REPO, capture=False, env=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          env=env).stdout


def active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=False).returncode == 0


def clean_test_env():
    # Candidate tests never receive real API credentials or runtime DB paths.
    return {k: v for k, v in os.environ.items()
            if k not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'LLM_TRADING_ARENA_DATA_DIR')}


def prepare_candidate(commit, folder):
    archive = subprocess.run(['git', 'archive', commit], cwd=REPO, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for entry in tar:
            target = (folder / entry.name).resolve()
            if not target.is_relative_to(folder.resolve()) or entry.issym() or entry.islnk():
                raise ValueError('Unsafe release archive')
            if entry.isdir(): target.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                name = target.name.lower()
                secret = name == '.env' or name.startswith('.env.') and name != '.env.example'
                runtime = re.search(r'\.(?:sqlite3?|db)(?:$|-(?:wal|shm|journal)$|\.manifest\.json$)', name)
                if secret or runtime:
                    raise ValueError('Release contains runtime data or secrets')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(entry) as f: target.write_bytes(f.read())
    candidate = folder / 'apps/arena'
    # This mechanism deliberately supports only the unchanged v0.3.1 schema family.
    if (candidate / 'deploy/OPERATIONS_VERSION').read_text().strip() != '1':
        raise ValueError('Unsupported operations/schema compatibility version')
    command(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v',
            cwd=candidate, env=clean_test_env())
    return candidate


def wait_live(port, *, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            pid = int(command('systemctl', 'show', SERVICE, '--property=MainPID', '--value', capture=True))
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/live', timeout=3) as response:
                data = json.load(response)
            if data.get('live') and data.get('process_id') == pid and pid > 0: return
        except (OSError, ValueError, subprocess.CalledProcessError): pass
        time.sleep(1)
    raise TimeoutError('New service failed liveness check')


def install_units():
    command('bash', str(APP / 'scripts/install_pi_service.sh'), '--units-only', cwd=APP)


def deploy(commit, data_dir, candidate, *, port):
    """Serialized maintenance with code-only recovery after any post-stop failure."""
    db = data_dir / 'live_v03_bitvavo.sqlite3'
    # Kept outside Git; serialize deployers before inspecting the current revision.
    with WriterLock(data_dir / 'deployment'):
        if command('git', 'status', '--porcelain', capture=True).strip():
            raise RuntimeError('Working tree changed during candidate validation')
        previous = command('git', 'rev-parse', 'HEAD', capture=True).strip()
        if not active(SERVICE):
            raise RuntimeError('Start/verify the existing service before an automated update')
        timer_active = active(TIMER)
        env_hash = digest(APP / '.env')
        try:
            command('sudo', 'systemctl', 'stop', TIMER)
            command('sudo', 'systemctl', 'stop', 'llm-trading-arena-backup.service')
            command('sudo', 'systemctl', 'stop', SERVICE)
            with WriterLock(db):
                inspect_db(db, mode='live')
                backup_database(db, data_dir / 'pre-update' / (uuid.uuid4().hex + '.sqlite3'))
                command(sys.executable, 'scripts/check_db.py', str(db), cwd=candidate, env=clean_test_env())
                command('git', 'checkout', '--detach', commit)
                if digest(APP / '.env') != env_hash: raise RuntimeError('Configuration changed')
                install_units()
            command('sudo', 'systemctl', 'start', SERVICE)
            wait_live(port)
            if timer_active: command('sudo', 'systemctl', 'start', TIMER)
        except BaseException:
            # Retain every trade made since the update. Never copy a backup over the DB.
            command('sudo', 'systemctl', 'stop', SERVICE)
            with WriterLock(db):
                command('git', 'checkout', '--detach', previous)
                inspect_db(db, mode='live')
                install_units()
            command('sudo', 'systemctl', 'start', SERVICE)
            wait_live(port)
            if timer_active: command('sudo', 'systemctl', 'start', TIMER)
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('revision', help='Reviewed commit SHA or tag; older compatible commits perform rollback')
    a = p.parse_args()
    if sys.platform != 'linux' or os.getuid() == 0: p.error('Run as the regular Pi user on Linux')
    if REPO != Path.home() / 'llm-trading-arena': p.error('Unexpected installation directory')
    if command('git', 'status', '--porcelain', capture=True).strip(): p.error('Working tree must be clean')
    if (APP / 'deploy/OPERATIONS_VERSION').read_text().strip() != '1': p.error('Incompatible current release')
    # Authenticate sudo before stopping a service; no unattended prompts halfway through backup.
    command('sudo', '-v')
    command('git', 'fetch', '--tags', 'origin')
    commit = command('git', 'rev-parse', '--verify', '--end-of-options', a.revision + '^{commit}', capture=True).strip()
    load_dotenv(str(APP / '.env'))
    data_dir = Path.home() / '.local/share/llm-trading-arena'
    configured = os.getenv('LLM_TRADING_ARENA_DATA_DIR')
    if configured and Path(configured).expanduser().resolve() != data_dir.resolve():
        p.error('Custom data directory requires a separately reviewed service configuration')
    with tempfile.TemporaryDirectory(prefix='arena-release-') as directory:
        candidate = prepare_candidate(commit, Path(directory))
        deploy(commit, data_dir, candidate, port=int(os.getenv('PORT', '8787')))
    print('Code release switched; history retained. Check /health/ready and provider status separately.')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Deployment failed: ' + safe_error(exc) + '; inspect service and journal before retrying.', file=sys.stderr)
        sys.exit(1)
