#!/usr/bin/env python3
"""Read-only schema/integrity/mode check; never creates or repairs a database."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations import inspect_db, safe_error

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--mode', choices=('live', 'demo'), default='live')
    args = parser.parse_args()
    try:
        inspect_db(args.database, mode=args.mode)
        print('Database schema, integrity, references and mode checks passed.')
    except Exception as exc:
        print('Database check failed: ' + safe_error(exc), file=sys.stderr)
        sys.exit(1)
