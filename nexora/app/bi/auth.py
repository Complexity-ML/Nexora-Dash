"""Internal credential management; no public token issuance endpoint."""
from hashlib import sha256
import re
import secrets
from uuid import uuid4


class BIUnauthorized(ValueError):
    pass


def issue_reader(store, *, namespace, audience, lifetime_hours=24, deliver=None):
    if not isinstance(namespace, str) or (namespace and not namespace.strip()) or not isinstance(audience, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', audience):
        raise ValueError('Expected namespace and explicit BI audience')
    if type(lifetime_hours) is not int or not 1 <= lifetime_hours <= 2160:
        raise ValueError('Expected a reader lifetime of 1..2160 hours')
    token = 'nexora_bi_' + secrets.token_urlsafe(32)
    identity = str(uuid4())
    with store.connect() as db:
        result = db.execute('''INSERT INTO bi_readers(id,namespace,audience,token_hash,expires_at)
            VALUES (%s,%s,%s,%s,clock_timestamp()+(%s * interval '1 hour')) RETURNING expires_at''',
            (identity, namespace, audience, sha256(token.encode()).hexdigest(), lifetime_hours)).fetchone()
        credential = {'id':identity, 'token':token, 'expires_at':result['expires_at'].isoformat()}
        # A delivery failure rolls back issuance before the reader is visible.
        if deliver is not None:
            deliver(credential)
    return credential


def authenticate_reader(store, *, namespace, token):
    if not isinstance(token, str) or not re.fullmatch(r'nexora_bi_[A-Za-z0-9_-]{43}', token):
        raise BIUnauthorized('Invalid BI credentials')
    with store.connect() as db:
        principal = db.execute('''SELECT id,namespace,audience FROM bi_readers
            WHERE namespace=%s AND token_hash=%s AND revoked_at IS NULL
              AND expires_at > clock_timestamp()''', (namespace,sha256(token.encode()).hexdigest())).fetchone()
    if principal is None:
        raise BIUnauthorized('Invalid BI credentials')
    return principal


def revoke_reader(store, *, namespace, reader_id):
    with store.connect() as db:
        return db.execute('''UPDATE bi_readers SET revoked_at=COALESCE(revoked_at,clock_timestamp())
            WHERE namespace=%s AND id=%s RETURNING id''', (namespace,reader_id)).fetchone() is not None


def reader_publication(journal, *, namespace, token):
    from app.bi.catalog import publication
    principal = authenticate_reader(journal.store, namespace=namespace, token=token)
    return publication(journal, namespace=principal['namespace'], audience=principal['audience'])


def revoke_namespace_readers(store, *, namespace, apply=False):
    """Retire restored credentials before reopening BI; never change another namespace.

    The operator must keep BI traffic and credential provisioning stopped during
    restore/reconciliation. Credentials issued after this transaction are new.
    """
    if not isinstance(namespace, str) or (namespace and not namespace.strip()):
        raise ValueError('An explicit namespace is required; empty string denotes the lake root')
    with store.connect() as db:
        if apply:
            # Serialize with in-flight issuance; newly provisioned readers belong
            # after the reconciliation boundary, never inside its snapshot.
            db.execute('LOCK TABLE bi_readers IN SHARE ROW EXCLUSIVE MODE')
            result = db.execute('''WITH retired AS (
                UPDATE bi_readers SET revoked_at=clock_timestamp()
                WHERE namespace=%s AND revoked_at IS NULL RETURNING id)
                SELECT count(*) AS count FROM retired''', (namespace,)).fetchone()
        else:
            result = db.execute('SELECT count(*) AS count FROM bi_readers WHERE namespace=%s AND revoked_at IS NULL',
                                (namespace,)).fetchone()
    return {'applied':apply, 'readers':result['count']}
