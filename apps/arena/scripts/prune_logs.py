#!/usr/bin/env python3
"""Remove old operational messages only, AFTER a successful scheduled backup."""
import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def prune(path, days=30):
    if days < 1: raise ValueError('Retention days must be positive')
    con = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw', uri=True, timeout=10)
    try:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(timespec='seconds')
        with con: con.execute('DELETE FROM logs WHERE ts < ?', (cutoff,))
    finally: con.close()


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path)
    p.add_argument('--days',type=int,default=30)
    a=p.parse_args()
    prune(a.database,a.days)
