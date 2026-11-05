"""Verified private backup bundles: consistent SQLite plus associated LLM audit files."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backup import backup_database, digest, publish_new, sync_directory
from budget import audit_lock
from operations import WriterLock, inspect_db, read_db


def backup_bundle(source, destination, *, managed=False):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Bundle target exists')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.arena-bundle-', dir=destination.parent) as directory:
        stage = Path(directory)
        con = read_db(source)
        try:
            # Mutations of audit/ledger files pause only while staging, not during compression.
            with audit_lock(con):
                metadata = backup_database(source, stage / 'database.sqlite3')
                snapshot = read_db(stage / 'database.sqlite3')
                try:
                    maximum = snapshot.execute('SELECT COALESCE(MAX(id),0) FROM llm_calls').fetchone()[0]
                    references = []
                    for row in snapshot.execute('SELECT inputs FROM decisions'):
                        audit = json.loads(row[0]).get('_audit')
                        if audit:
                            references.append(audit)
                finally:
                    snapshot.close()
                audit_source = source.parent / 'llm-audit'
                audit_stage = stage / 'audit'
                audit_stage.mkdir(mode=0o700)
                for path in audit_source.glob(source.name + '*'):
                    match = re.fullmatch(re.escape(source.name) + r'-(\d+)\.json', path.name)
                    is_ledger = path.name == source.name + '.ledger.json'
                    if not is_ledger and (not match or int(match[1]) > maximum):
                        continue
                    if path.is_symlink() or not path.is_file():
                        raise ValueError('Invalid audit artifact')
                    target = audit_stage / path.name
                    if is_ledger:
                        ledger = json.loads(path.read_text(encoding='utf-8'))
                        ledger['entries'] = {key: value for key, value in ledger['entries'].items() if int(key) <= maximum}
                        target.write_text(json.dumps(ledger), encoding='utf-8')
                    else:
                        shutil.copyfile(path, target)
                for audit in references:
                    path = audit_stage / (source.name + '-' + str(audit['attempt']) + '.json')
                    if not path.is_file() or digest(path) != audit['snapshot_sha256']:
                        raise ValueError('A decision snapshot is missing or modified')
        finally:
            con.close()
        entries = {}
        for path in stage.rglob('*'):
            if path.is_file():
                entries[path.relative_to(stage).as_posix()] = digest(path)
        manifest = {'format': 1, 'source_database': source.name,
                    'source_id': hashlib.sha256(str(source).encode()).hexdigest(),
                    'managed': managed, 'entries': entries, 'inventory': metadata['inventory']}
        archive = stage / 'bundle.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for name in entries:
                output.write(stage / name, name)
            output.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
        os.chmod(archive,0o600)
        with archive.open('r+b') as stream:
            os.fsync(stream.fileno())
        verify_bundle(archive)
        publish_new(archive, destination)
        return manifest


def verify_bundle(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Duplicate or missing bundle entries')
        manifest = json.loads(archive.read('manifest.json'))
        database = manifest['source_database']
        if manifest.get('format') != 1 or Path(database).name != database or '/' in database or '\\' in database:
            raise ValueError('Invalid source database name')
        if set(names) != set(manifest['entries']) | {'manifest.json'}:
            raise ValueError('Unexpected bundle contents')
        required = {'database.sqlite3', 'database.sqlite3.manifest.json'}
        if not required <= set(names):
            raise ValueError('Missing database snapshot')
        for name, expected in manifest['entries'].items():
            if name not in required and not re.fullmatch('audit/' + re.escape(database) + r'(?:-\d+|\.ledger)\.json', name):
                raise ValueError('Unsafe bundle member')
            h = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
            if h.hexdigest() != expected:
                raise ValueError('Bundle checksum mismatch')
        inner=json.loads(archive.read('database.sqlite3.manifest.json'))
        if inner.get('sha256')!=manifest['entries']['database.sqlite3'] or inner.get('inventory')!=manifest['inventory']:
            raise ValueError('Inner and outer database manifests disagree')
        with tempfile.TemporaryDirectory(prefix='arena-verify-') as folder:
            database_path = Path(folder) / 'snapshot.sqlite3'
            with archive.open('database.sqlite3') as src, database_path.open('wb') as target:
                shutil.copyfileobj(src, target)
            if inspect_db(database_path) != manifest['inventory']:
                raise ValueError('Bundle database inventory mismatch')
        return manifest


def restore_bundle(source, destination):
    """Publish a complete NEW data directory; never merge into existing history."""
    destination = Path(destination).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with WriterLock(destination):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('Restore directory exists')
        with tempfile.TemporaryDirectory(prefix='.arena-restore-bundle-', dir=destination.parent) as folder:
            stage = Path(folder)
            # Verify a private immutable copy, binding verification to extraction.
            copy = stage / 'source.zip'
            shutil.copyfile(source, copy)
            manifest = verify_bundle(copy)
            output = stage / 'data'
            output.mkdir(mode=0o700)
            with zipfile.ZipFile(copy) as archive:
                for name in manifest['entries']:
                    if name == 'database.sqlite3':
                        target = output / manifest['source_database']
                    elif name.startswith('audit/'):
                        target = output / 'llm-audit' / name.split('/')[1]
                    else:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'wb') as stream, archive.open(name) as src:
                        shutil.copyfileobj(src, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
            from budget import atomic_json
            audit_directory=output/'llm-audit'
            audit_directory.mkdir(exist_ok=True,mode=0o700)
            ledger_path=audit_directory/(manifest['source_database']+'.ledger.json')
            ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {'format':1,'entries':{}}
            ledger['restored_day']=datetime.now(timezone.utc).date().isoformat()
            ledger['restore_bundle_sha256']=digest(copy)
            atomic_json(ledger_path,ledger)
            inspect_db(output / manifest['source_database'], mode='live')
            for subdirectory in output.iterdir():
                if subdirectory.is_dir():
                    sync_directory(subdirectory)
            sync_directory(output)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError('Restore directory appeared')
            output.rename(destination)
            sync_directory(destination.parent)
            return manifest


def rotate_bundles(source, directory, keep=14):
    if keep < 1:
        raise ValueError('Retention must keep at least one bundle')
    source, directory = Path(source).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_id = hashlib.sha256(str(source).encode()).hexdigest()
    prefix = 'arena-bundle-' + source_id[:12] + '-'
    with WriterLock(directory / 'bundle-rotation'):
        name = prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex + '.zip'
        result = backup_bundle(source, directory / name, managed=True)
        candidates = []
        for path in directory.glob(prefix + '*.zip'):
            if path.is_symlink():
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    info = json.loads(archive.read('manifest.json'))
                if info['source_id'] == source_id and info['managed'] is True:
                    candidates.append(path)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        # Keep the just-created snapshot even if the wall clock stepped backwards.
        older = sorted((p for p in candidates if p.name != name), reverse=True)
        for path in older[keep - 1:]:
            path.unlink()
        sync_directory(directory)
        return result
