"""Restore a synthetic PostgreSQL journal/index and its Delta lake in isolation."""
import argparse
import json
import select
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', default='docker')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(repo/'nexora'))
    from app.collection.backup_archive import digest,seal_archive,verify_archive
    prefix = [args.docker, 'compose']
    source = 'restore_source_' + uuid4().hex
    target = 'restore_target_' + uuid4().hex
    def run(parts, **kwargs):
        return subprocess.run(prefix + parts, cwd=repo, check=True, **kwargs)
    def db_tool(tool, *params, **kwargs):
        return run(['exec', '-T', 'postgres', tool, '-U', 'sam', *params], **kwargs)
    with tempfile.TemporaryDirectory(prefix='nexora-restore-') as folder:
        root = Path(folder)
        holder = None
        try:
            db_tool('createdb', source)
            db_tool('createdb', target)
            def backend(database, command):
                run(['run', '--rm', '--no-deps', '-e', 'COLLECTION_ENABLED=false',
                    '-e', 'RESTORE_TEST_DATABASE=' + database, '-v', str(repo/'nexora')+':/app',
                    '-v', str(root)+':/restore-proof', 'dash', 'sh', '-c',
                    'export DATABASE_URL="${DATABASE_URL%/*}/$RESTORE_TEST_DATABASE"; ' + command])
            backend(source, 'python -m alembic upgrade head && python -m scripts.verify_collection_restore seed --root /restore-proof')
            holder = subprocess.Popen(prefix + ['run', '--rm', '--no-deps', '-T',
                '-e', 'RESTORE_TEST_DATABASE='+source, '-v', str(repo/'nexora')+':/app',
                'dash', 'sh', '-c', 'export DATABASE_URL="${DATABASE_URL%/*}/$RESTORE_TEST_DATABASE"; exec python -m scripts.hold_backup_snapshot --namespace restore-proof/'],
                cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
            if not select.select([holder.stdout], [], [], 30)[0]:
                raise RuntimeError('Backup snapshot holder did not become ready')
            snapshot_metadata = json.loads(holder.stdout.readline())
            snapshot = snapshot_metadata['snapshot']
            (root/'snapshot.json').write_text(json.dumps(snapshot_metadata))
            # Writes after this point must not leak into the exported database snapshot.
            backend(source, 'python -m scripts.verify_collection_restore mutate --root /restore-proof')
            backend(source, 'python -m scripts.verify_collection_restore copy --root /restore-proof')
            with (root/'database.dump').open('wb') as stream:
                db_tool('pg_dump', '-Fc', '--snapshot='+snapshot, source, stdout=stream)
            holder.communicate(input=b'close\n', timeout=30)
            if holder.returncode:
                raise RuntimeError('Backup snapshot holder failed')
            proof=json.loads((root/'proof.json').read_text())
            expected={'restored/'+key:value for key,value in proof['hashes'].items()}
            for name in ('database.dump','snapshot.json','proof.json'):
                expected[name]=digest(root/name)
            seal_archive(root,expected)
            db_tool('dropdb', source)
            shutil.rmtree(root/'source')
            verify_archive(root)
            with (root/'database.dump').open('rb') as stream:
                db_tool('pg_restore', '--exit-on-error', '--no-owner', '-d', target, stdin=stream)
            backend(target, 'python -m scripts.verify_collection_restore verify --root /restore-proof')
        finally:
            if holder is not None and holder.poll() is None:
                holder.communicate(input=b'close\n', timeout=30)
            for database in (source, target):
                subprocess.run(prefix + ['exec', '-T', 'postgres', 'dropdb', '-U', 'sam', '--if-exists', database], cwd=repo, check=False)


if __name__ == '__main__':
    main()
