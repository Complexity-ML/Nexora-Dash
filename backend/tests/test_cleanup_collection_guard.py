"""Legacy cleanup must not race with the first journal registration."""
import os
from uuid import uuid4
import pytest
from psycopg import connect, sql
from scripts.cleanup_migrated_demo import require_legacy_only


@pytest.fixture
def isolated():
    url = os.environ.get('BUSINESS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Dedicated PostgreSQL required')
    schema = 'cleanup_guard_' + uuid4().hex
    with connect(url, autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        yield url, schema
    finally:
        with connect(url, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def connection(url, schema):
    from psycopg.rows import dict_row
    return connect(url, options='-csearch_path=' + schema, row_factory=dict_row)


def test_cleanup_refuses_missing_journal_schema(isolated):
    with connection(*isolated) as db:
        with pytest.raises(RuntimeError, match='Migrate recovery'):
            require_legacy_only(db)


def test_cleanup_refuses_even_unpublished_collection(isolated):
    with connection(*isolated) as db:
        db.execute('CREATE TABLE collection_runs (id text PRIMARY KEY)')
        db.execute("INSERT INTO collection_runs VALUES ('prepared-import')")
        with pytest.raises(RuntimeError, match='journal-aware'):
            require_legacy_only(db)


def test_cleanup_locks_out_registration_until_transaction_ends(isolated):
    from psycopg.errors import LockNotAvailable
    with connection(*isolated) as db:
        db.execute('CREATE TABLE collection_runs (id text PRIMARY KEY)')
    with connection(*isolated) as cleanup:
        require_legacy_only(cleanup)
        with connection(*isolated) as writer:
            writer.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(LockNotAvailable):
                writer.execute("INSERT INTO collection_runs VALUES ('new-run')")
            writer.rollback()
    with connection(*isolated) as writer:
        writer.execute("INSERT INTO collection_runs VALUES ('new-run')")
        assert writer.execute('SELECT count(*) AS n FROM collection_runs').fetchone()['n'] == 1
