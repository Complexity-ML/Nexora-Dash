"""Cooperative database-wide exclusion between backup readers and lake deletion.

The transaction must remain open until every copy/deletion finishes. This is
not a storage ACL and cannot stop external VACUUM or object-store lifecycle jobs.
"""
# Stable two-integer PostgreSQL advisory lock key, shared across namespaces.
_LOCK_KEY = (1313167439, 1279347525)


def protect_backup(db):
    acquired = db.execute('SELECT pg_try_advisory_xact_lock_shared(%s,%s) AS acquired',
                          _LOCK_KEY).fetchone()['acquired']
    if not acquired:
        raise RuntimeError('Lake maintenance is active; retry backup later')


def protect_deletion(db):
    acquired = db.execute('SELECT pg_try_advisory_xact_lock(%s,%s) AS acquired',
                          _LOCK_KEY).fetchone()['acquired']
    if not acquired:
        raise RuntimeError('Lake backup or maintenance is active; deletion refused')
