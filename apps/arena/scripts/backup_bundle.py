#!/usr/bin/env python3
"""Backup/verify/restore database plus private LLM audit and budget records."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle import backup_bundle, verify_bundle, restore_bundle, rotate_bundles
from operations import safe_error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--destination', type=Path)
    group.add_argument('--directory', type=Path)
    group.add_argument('--restore-directory', type=Path)
    group.add_argument('--verify', action='store_true')
    p.add_argument('--keep', type=int, default=14)
    a = p.parse_args()
    if a.verify: verify_bundle(a.source)
    elif a.restore_directory: restore_bundle(a.source, a.restore_directory)
    elif a.directory: rotate_bundles(a.source, a.directory, a.keep)
    else: backup_bundle(a.source, a.destination)
    print('Database/audit bundle operation completed and verified.')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Bundle operation refused/failed: ' + safe_error(exc), file=sys.stderr)
        sys.exit(1)
