"""Run tests in a unique disposable PostgreSQL database, then remove only that database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main():
    source = os.environ.get('DATABASE_URL')
    if not source:
        raise RuntimeError('DATABASE_URL must identify the local PostgreSQL server')
    name = 'nexora_test_' + uuid4().hex
    target = make_url(source).set(database=name).render_as_string(hide_password=False)
    environment = {**os.environ, 'DATABASE_URL': target, 'BUSINESS_TEST_DATABASE_URL': target}
    root = Path(__file__).resolve().parents[2]
    # The caller's database is never a cleanup target. No name can be supplied.
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        print('Created isolated test database: '+name, flush=True)
        try:
            migrated = subprocess.run(['alembic','upgrade','head'], cwd=root, env=environment)
            if migrated.returncode:
                return migrated.returncode
            with tempfile.TemporaryDirectory(prefix='nexora-tests-') as temporary:
                result = subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider',
                    '--basetemp',temporary,*sys.argv[1:]], cwd=root, env=environment)
                return result.returncode
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            print('Removed isolated test database: '+name, flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
