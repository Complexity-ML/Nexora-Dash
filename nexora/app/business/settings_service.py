from app.business.errors import BusinessError
import json
from pydantic import Field
from app.business.workspace_service import Input, current_user, get_business_store, member
from app.business.store import now
from app.business.analysis_preferences import read_settings



class Update(Input):
    threshold: float = Field(gt=0, le=1, allow_inf_nan=False)
    buffer: float = Field(ge=0, le=1, allow_inf_nan=False)
    version: int = Field(ge=0)

def get(user=None, store=None):
    settings = read_settings(store)
    with store.connect() as db:
        role = db.execute("SELECT role FROM members WHERE workspace_id='demo' AND user_id=%s", (user['id'],)).fetchone()
    return {**settings, 'can_edit': bool(role and role['role']=='admin')}

def update(body: Update, user=None, store=None):
    with store.connect() as db:
        member(db, 'demo', user, admin=True)
        # Serializes the first insert as well as later revisions.
        db.execute('SELECT pg_advisory_xact_lock(739201)')
        previous = db.execute('SELECT threshold,buffer,version FROM analysis_settings WHERE id=1').fetchone()
        version = previous['version'] if previous else 0
        if version != body.version:
            raise BusinessError(409, 'Réglages modifiés par un autre utilisateur. Rechargez-les.')
        db.execute('INSERT INTO analysis_settings VALUES(1,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET threshold=EXCLUDED.threshold,buffer=EXCLUDED.buffer,version=EXCLUDED.version', (body.threshold, body.buffer,version+1))
        db.execute('INSERT INTO analysis_settings_events(actor_id,created_at,payload) VALUES(%s,%s,%s)', (user['id'],now(),json.dumps({'before':dict(previous) if previous else None, 'after':body.model_dump()})))
    return {**body.model_dump(), 'version':version+1, 'can_edit':True}
