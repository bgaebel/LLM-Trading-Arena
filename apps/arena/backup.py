"""SQLite online snapshots, atomic publication, private manifests and scoped retention."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from operations import WriterLock, inspect_db, read_db


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def sync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def publish_new(temporary, destination):
    # Atomic publication WITHOUT replacing an existing target.
    os.link(temporary, destination)
    Path(temporary).unlink()
    sync_directory(Path(destination).parent)


def backup_database(source, destination, *, timeout=120, managed=False):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file(): raise FileNotFoundError('Source database missing')
    if destination.exists() or destination.is_symlink(): raise FileExistsError('Backup target exists')
    if timeout <= 0: raise ValueError('Backup timeout must be positive')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.arena-backup-', suffix='.tmp', dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary)
    deadline = time.monotonic() + timeout
    def progress(*_):
        if time.monotonic() > deadline: raise TimeoutError('Backup deadline exceeded')
    try:
        source_con = read_db(source)
        target = sqlite3.connect(temporary)
        try:
            source_con.backup(target, pages=256, progress=progress, sleep=.05)
            target.execute('PRAGMA journal_mode=DELETE')
        finally:
            target.close()
            source_con.close()
        inventory = inspect_db(temporary)
        with temporary.open('r+b') as f: os.fsync(f.fileno())
        metadata = {'format': 1, 'file': destination.name, 'sha256': digest(temporary),
                    'created_utc': datetime.now(timezone.utc).isoformat(),
                    'source_id': hashlib.sha256(str(source).encode()).hexdigest(),
                    'managed': managed, 'inventory': inventory}
        publish_new(temporary, destination)
        # A crash here leaves an intact snapshot without a manifest; retention ignores it.
        manifest = destination.with_name(destination.name + '.manifest.json')
        fd, temp_manifest = tempfile.mkstemp(prefix='.arena-manifest-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            publish_new(temp_manifest, manifest)
        finally:
            Path(temp_manifest).unlink(missing_ok=True)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(temporary) + suffix).unlink(missing_ok=True)


def rotate_backups(source, directory, *, keep=14):
    """Create first; prune only this source's completed managed snapshots afterwards."""
    if keep < 1: raise ValueError('Retention must keep at least one backup')
    source, directory = Path(source).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_id = hashlib.sha256(str(source).encode()).hexdigest()
    prefix = 'arena-' + source_id[:12] + '-'
    with WriterLock(directory / 'backup-rotation'):
        name = prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex + '.sqlite3'
        metadata = backup_database(source, directory / name, managed=True)
        candidates = []
        pattern = re.compile(re.escape(prefix) + r'\d{8}T\d{12}Z-[0-9a-f]{32}\.sqlite3')
        for path in directory.iterdir():
            if not pattern.fullmatch(path.name) or path.is_symlink() or not path.is_file(): continue
            manifest = path.with_name(path.name + '.manifest.json')
            if manifest.is_symlink(): continue
            try:
                data = json.loads(manifest.read_text(encoding='utf-8'))
                if data['source_id'] == source_id and data['managed'] is True and data['file'] == path.name:
                    candidates.append(path)
            except (OSError, ValueError, KeyError, TypeError): continue
        for path in sorted(candidates, key=lambda p: p.name, reverse=True)[keep:]:
            path.unlink()
            path.with_name(path.name + '.manifest.json').unlink()
        sync_directory(directory)
        return metadata


def verify_backup(path):
    path = Path(path)
    metadata = json.loads(path.with_name(path.name + '.manifest.json').read_text(encoding='utf-8'))
    if metadata['file'] != path.name or digest(path) != metadata['sha256']:
        raise ValueError('Backup checksum mismatch')
    if inspect_db(path) != metadata['inventory']:
        raise ValueError('Backup inventory mismatch')
    return metadata


def restore_backup(source, destination):
    """Verified import into a NEW path only. Existing history is never overwritten."""
    source, destination = Path(source), Path(destination)
    with WriterLock(destination):
        for suffix in ('', '-wal', '-shm', '-journal', '.manifest.json'):
            path = Path(str(destination) + suffix)
            if path.exists() or path.is_symlink():
                raise FileExistsError('Restore target or SQLite sidecar exists')
        original = verify_backup(source)
        inspect_db(source, mode='live')
        restored = backup_database(source, destination)
        if restored['inventory'] != original['inventory']:
            raise ValueError('Restored inventory differs; do not start the service')
        return restored
