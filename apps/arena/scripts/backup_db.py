#!/usr/bin/env python3
"""Private atomic SQLite backups; migration requires the old writer to be stopped."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import backup_database, rotate_backups, verify_backup
from operations import safe_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--keep', type=int, default=14)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify_backup(args.source)
        print('Backup checksum and inventory verified.')
    elif args.directory and not args.destination:
        rotate_backups(args.source, args.directory, keep=args.keep)
        print('Atomic backup and retention completed.')
    elif args.destination and not args.directory:
        backup_database(args.source, args.destination)
        print('Atomic backup and private checksum/inventory manifest created.')
    else:
        parser.error('Choose destination, --directory, or --verify')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Backup failed: ' + safe_error(exc), file=sys.stderr)
        sys.exit(1)
