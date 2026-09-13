"""Transactional business storage. Analytics remain in the Parquet lake."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import psycopg
from psycopg.rows import dict_row
import time


def now():
    return datetime.now(timezone.utc).isoformat()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


# Computed once at process startup, never once per unknown login.
DUMMY_PASSWORD_HASH = password_hash(secrets.token_urlsafe(32))


class BusinessStore:
    def __init__(self, url):
        self.url = url

    @contextmanager
    def connect(self):
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            yield db

    def seed_demo(self, password):
        """Known accounts only for explicitly enabled fictional deployments."""
        if len(password) < 16:
            raise ValueError('SAM_DEMO_PASSWORD must be configured with at least 16 characters')
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(734921)')
            for uid, email, name, role in (
                ('demo-admin', 'admin@sam.demo', 'SAM Martin', 'admin'),
                ('demo-analyst', 'analyst@sam.demo', 'Camille Analyste', 'analyst'),
                ('demo-reader', 'reader@sam.demo', 'Lecteur démo', 'reader'),
            ):
                existing = db.execute('SELECT password FROM users WHERE id=%s', (uid,)).fetchone()
                if not existing:
                    db.execute('INSERT INTO users VALUES (%s,%s,%s,%s)', (uid, email, name, password_hash(password)))
                elif not hmac.compare_digest(existing['password'], password_hash(password, existing['password'].split(':')[0])):
                    db.execute('UPDATE users SET password=%s WHERE id=%s', (password_hash(password), uid))
                    db.execute('DELETE FROM sessions WHERE user_id=%s', (uid,))
            db.execute("UPDATE users SET name=%s WHERE id=%s AND name=%s",
                       ('Lecteur démo', 'demo-reader', 'Alex Lecteur'))
            db.execute('INSERT INTO workspaces VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', ('demo', 'Nexora Groupe', now()))
            for uid, role in [('demo-admin','admin'), ('demo-analyst','analyst'), ('demo-reader','reader')]:
                db.execute('INSERT INTO members VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', ('demo', uid, role))

    def login(self, email, password):
        with self.connect() as db:
            user = db.execute('SELECT * FROM users WHERE email=%s', (email.lower(),)).fetchone()
            # Same expensive verification for unknown accounts.
            stored = user['password'] if user else DUMMY_PASSWORD_HASH
            valid = hmac.compare_digest(stored, password_hash(password, stored.split(':')[0]))
            if not user or not valid:
                return None
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<%s', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (%s,%s,%s)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], time.time()+28800))
            return token

    def user_for_token(self, token):
        with self.connect() as db:
            row = db.execute('SELECT u.id,u.email,u.name FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.digest=%s AND s.expires>%s',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    @staticmethod
    def event(db, workspace, case_id, actor, action, payload):
        db.execute('INSERT INTO events(workspace_id,case_id,actor_id,action,payload,created_at) VALUES (%s,%s,%s,%s,%s,%s)',
                   (workspace, case_id, actor, action, json.dumps(payload, ensure_ascii=False), now()))
