#!/usr/bin/env python3
"""Fail before trading if time synchronization, configuration or history is invalid."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena import load_dotenv, fee_rate, slip_rate
from main import db_file
from operations import inspect_db, safe_error


def check():
    load_dotenv(str(Path(__file__).resolve().parents[1] / '.env'))
    if sys.version_info < (3, 11): raise RuntimeError('Python 3.11 required')
    synced = subprocess.run(['timedatectl', 'show', '--property=NTPSynchronized', '--value'],
                            check=True, capture_output=True, text=True, timeout=10)
    if synced.stdout.strip() != 'yes': raise RuntimeError('NTP not synchronized')
    if not 1024 <= int(os.getenv('PORT','8787')) <= 65535: raise ValueError('Invalid port')
    fee_rate()
    slip_rate()
    inspect_db(db_file('live_v03_bitvavo'), mode='live')


if __name__ == '__main__':
    try: check()
    except Exception as exc:
        print('Preflight failed (check NTP, config, DB): ' + safe_error(exc), file=sys.stderr)
        sys.exit(1)
