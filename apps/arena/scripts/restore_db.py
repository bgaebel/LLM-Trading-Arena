#!/usr/bin/env python3
"""Restore verified paper-live backup to an absent target; never overwrite history."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import restore_backup
from operations import safe_error

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        restore_backup(args.source, args.destination)
        print('Verified restore completed; portfolio/trade inventory preserved.')
    except Exception as exc:
        print('Restore refused/failed: ' + safe_error(exc), file=sys.stderr)
        sys.exit(1)
