#!/usr/bin/env python3
"""Consistent SQLite backup for paper-trading DB. Stop source service for migration."""
import argparse
import sqlite3
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('destination', type=Path)
a = p.parse_args()
if not a.source.is_file():
    p.error(f'Source not found: {a.source}')
if a.destination.exists():
    p.error(f'Destination already exists (no overwrite): {a.destination}')
a.destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f'file:{a.source.resolve()}?mode=ro', uri=True) as source:
    with sqlite3.connect(str(a.destination)) as target:
        source.backup(target)
        check = target.execute('PRAGMA integrity_check').fetchone()[0]
        if check != 'ok':
            raise RuntimeError(f'Backup integrity check failed: {check}')
print(f'Backup created: {a.destination}')
