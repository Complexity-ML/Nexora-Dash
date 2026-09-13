from app.business.errors import BusinessError
"""Workspace-scoped API with server-side membership and workflow enforcement."""
from functools import lru_cache
from datetime import date
from app.business.calendar import business_today
import hashlib
import json
from typing import Literal, Annotated
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from app.config import get_settings
from app.business.store import BusinessStore, now, password_hash



@lru_cache
def get_business_store():
    settings = get_settings()
    store = BusinessStore(settings.database_url)
    if settings.sam_data_source == 'mock' and settings.demo_accounts_enabled:
        store.seed_demo(settings.sam_demo_password)
    return store


def current_user(auth: str | None = None, store=None):
    user = store.user_for_token(auth) if auth else None
    if not user:
        raise BusinessError(401, 'Connexion requise ou session expirée.')
    return user


def source_operator(user=None, store=None):
    # The lake is a shared fixture; only admins of its owning space may mutate it.
    with store.connect() as db:
        role = db.execute("SELECT role FROM members WHERE workspace_id='demo' AND user_id=%s", (user['id'],)).fetchone()
        if not role or role['role'] != 'admin':
            raise BusinessError(403, 'La collecte du lac commun exige un administrateur de Nexora Groupe.')
    return user


def member(db, workspace, user, write=False, admin=False):
    if write or admin:
        db.execute('SELECT id FROM workspaces WHERE id=%s FOR UPDATE', (workspace,)).fetchone()
    row = db.execute('SELECT role FROM members WHERE workspace_id=%s AND user_id=%s', (workspace, user['id'])).fetchone()
    if not row:
        raise BusinessError(404, 'Espace introuvable.')
    if (write and row['role'] == 'reader') or (admin and row['role'] != 'admin'):
        raise BusinessError(403, 'Droits insuffisants.')
    return row['role']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=256)]


class Name(Input):
    name: str = Field(min_length=1, max_length=60)


class Member(Input):
    email: str = Field(min_length=3, max_length=254)
    role: Literal['admin', 'analyst', 'reader']


class AccountCreate(Member):
    name: str = Field(min_length=1, max_length=60)
    password: Annotated[str, StringConstraints(strip_whitespace=False, min_length=16, max_length=256)]


def create_account(wid: str, body: AccountCreate, user=None, store=None):
    email = body.email.lower()
    if email.count('@') != 1 or any(c.isspace() for c in email) or not all(email.split('@')):
        raise BusinessError(422, 'Adresse e-mail invalide.')
    uid = str(uuid4())
    with store.connect() as db:
        member(db, wid, user, admin=True)
        created = db.execute(
            'INSERT INTO users(id,email,name,password) VALUES(%s,%s,%s,%s) ON CONFLICT(email) DO NOTHING RETURNING id',
            (uid, email, body.name, password_hash(body.password)),
        ).fetchone()
        if not created:
            raise BusinessError(409, 'Ce compte existe déjà. Utilisez Ajouter un compte existant.')
        db.execute('INSERT INTO members VALUES(%s,%s,%s)', (wid, uid, body.role))
        store.event(db, wid, None, user['id'], 'member.created', {'user_id':uid, 'role':body.role})
    return {'id':uid, 'email':email, 'name':body.name, 'role':body.role}


class CaseCreate(Input):
    pool_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    quantity: int = Field(ge=0, le=10000000)
    annual_unit_cents: int = Field(default=0, ge=0, le=1000000000)
    evidence: str = Field(min_length=1, max_length=10000)


class CaseUpdate(Input):
    version: int = Field(ge=1)
    assignee_id: str | None = None
    quantity: int = Field(ge=0, le=10000000)
    annual_unit_cents: int = Field(ge=0, le=1000000000)


class Decision(Input):
    version: int = Field(ge=1)
    status: Literal['preparing', 'sent', 'response_received', 'completed']
    reason: str = Field(min_length=3, max_length=4000)
    document_reference: str | None = Field(default=None, min_length=1, max_length=300)
    occurred_on: date | None = None
    external_decision: Literal['accepted', 'refused', 'revision_requested'] | None = None
    actual_quantity: int | None = Field(default=None, ge=1, le=10000000)


class Comment(Input):
    text: str = Field(min_length=1, max_length=4000)


def login(body: Login, store=None):
    token = store.login(body.email, body.password)
    if not token:
        raise BusinessError(401, 'Identifiants incorrects.')
    return {'token': token, 'user': store.user_for_token(token)}


def logout(auth: str = None, user=None, store=None):
    with store.connect() as db:
        db.execute('DELETE FROM sessions WHERE digest=%s', (hashlib.sha256(auth.encode()).hexdigest(),))
    return {'ok': True}


def me(user=None, store=None):
    with store.connect() as db:
        spaces = [dict(row) for row in db.execute('SELECT w.*,m.role FROM workspaces w JOIN members m ON m.workspace_id=w.id WHERE m.user_id=%s ORDER BY w.created_at,w.id', (user['id'],))]
    return {'user': user, 'workspaces': spaces, 'business_timezone': get_settings().business_timezone}


def rename_user(body: Name, user=None, store=None):
    with store.connect() as db:
        db.execute('UPDATE users SET name=%s WHERE id=%s', (body.name, user['id']))
    return {**user, 'name': body.name}


def create_workspace(body: Name, user=None, store=None):
    wid = str(uuid4())
    with store.connect() as db:
        db.execute('INSERT INTO workspaces VALUES (%s,%s,%s)', (wid, body.name, now()))
        db.execute('INSERT INTO members VALUES (%s,%s,%s)', (wid, user['id'], 'admin'))
        db.execute("INSERT INTO workspace_portfolios VALUES (%s,false,'[]',1)", (wid,))
        store.event(db, wid, None, user['id'], 'workspace.created', {'name': body.name})
    return {'id': wid, 'name': body.name, 'role': 'admin'}


def rename_workspace(wid: str, body: Name, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user, admin=True)
        db.execute('UPDATE workspaces SET name=%s WHERE id=%s', (body.name, wid))
        store.event(db, wid, None, user['id'], 'workspace.renamed', {'name': body.name})
    return {'ok': True}


def members(wid: str, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user)
        return [dict(row) for row in db.execute('SELECT u.id,u.email,u.name,m.role FROM members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s ORDER BY u.name', (wid,))]


def set_member(wid: str, body: Member, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user, admin=True)
        target = db.execute('SELECT id FROM users WHERE email=%s', (body.email.lower(),)).fetchone()
        if not target:
            raise BusinessError(404, 'Compte introuvable.')
        old = db.execute('SELECT role FROM members WHERE workspace_id=%s AND user_id=%s', (wid, target['id'])).fetchone()
        count = db.execute("SELECT COUNT(*) AS count FROM members WHERE workspace_id=%s AND role='admin'", (wid,)).fetchone()['count']
        if old and old['role'] == 'admin' and body.role != 'admin' and count == 1:
            raise BusinessError(409, 'L’espace doit conserver un administrateur.')
        db.execute('INSERT INTO members VALUES (%s,%s,%s) ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role', (wid, target['id'], body.role))
        if body.role == 'reader':
            unassign_member_cases(db, store, wid, target['id'], user['id'], 'Membre passé au rôle lecteur')
        store.event(db, wid, None, user['id'], 'membership.changed', body.model_dump())
    return {'ok': True}


def case_row(db, wid, cid):
    row = db.execute('SELECT * FROM cases WHERE workspace_id=%s AND id=%s', (wid, cid)).fetchone()
    if not row:
        raise BusinessError(404, 'Dossier introuvable.')
    return dict(row)


def cases(wid: str, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user)
        return [dict(row) for row in db.execute('SELECT * FROM cases WHERE workspace_id=%s ORDER BY updated_at DESC,id', (wid,))]


def ensure_no_active_case(db, wid, pool_id, exclude_id=''):
    # Serialize creations and reopenings within this workspace, including concurrent requests.
    db.execute('SELECT id FROM workspaces WHERE id=%s FOR UPDATE', (wid,)).fetchone()
    existing = db.execute("SELECT id FROM cases WHERE workspace_id=%s AND pool_id=%s AND status <> 'completed' AND id <> %s LIMIT 1", (wid, pool_id, exclude_id)).fetchone()
    if existing:
        raise BusinessError(409, 'Un dossier est déjà ouvert pour ce logiciel dans cet espace. Consultez le dossier existant.')


def create_case(wid: str, body: CaseCreate, user=None, store=None):
    cid, stamp = str(uuid4()), now()
    with store.connect() as db:
        member(db, wid, user, write=True)
        ensure_no_active_case(db, wid, body.pool_id)
        if 'annual_unit_cents' not in body.model_fields_set:
            shared = db.execute('SELECT annual_unit_cents FROM workspace_costs WHERE workspace_id=%s AND pool_id=%s', (wid,body.pool_id)).fetchone()
            body = body.model_copy(update={'annual_unit_cents':shared['annual_unit_cents'] if shared and shared['annual_unit_cents'] is not None else 0})
        db.execute('INSERT INTO cases(id,workspace_id,pool_id,title,status,assignee_id,quantity,annual_unit_cents,evidence,version,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (cid, wid, body.pool_id, body.title, 'preparing', None, body.quantity, body.annual_unit_cents, body.evidence, 1, stamp, stamp))
        store.event(db, wid, cid, user['id'], 'case.created', body.model_dump())
        return case_row(db, wid, cid)


def detail(wid: str, cid: str, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user)
        case = case_row(db, wid, cid)
        events = [dict(row) for row in db.execute('SELECT e.*,u.name AS actor_name FROM events e JOIN users u ON u.id=e.actor_id WHERE e.workspace_id=%s AND e.case_id=%s ORDER BY e.id', (wid, cid))]
        for event in events:
            event['payload'] = json.loads(event['payload'])
        from app.business.comments import project_comments
        return {**case, 'events': project_comments(events)}


def mutable(db, wid, cid, user, version):
    role = member(db, wid, user, write=True)
    case = case_row(db, wid, cid)
    if case['version'] != version:
        raise BusinessError(409, 'Dossier modifié par un autre utilisateur. Rechargez-le.')
    return case, role


class CaseDelete(Input):
    version: int = Field(ge=1)


def delete_case(wid: str, cid: str, body: CaseDelete, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user, write=True)
        db.execute('SELECT id FROM workspaces WHERE id=%s FOR UPDATE', (wid,)).fetchone()
        row = db.execute('SELECT version FROM cases WHERE workspace_id=%s AND id=%s FOR UPDATE', (wid, cid)).fetchone()
        if not row:
            raise BusinessError(404, 'Dossier introuvable.')
        if row['version'] != body.version:
            raise BusinessError(409, 'Dossier modifié par un autre utilisateur. Rechargez-le.')
        db.execute('DELETE FROM events WHERE workspace_id=%s AND case_id=%s', (wid, cid))
        db.execute('DELETE FROM cases WHERE workspace_id=%s AND id=%s', (wid, cid))
    return {'ok': True}


def update_case(wid: str, cid: str, body: CaseUpdate, user=None, store=None):
    with store.connect() as db:
        case, role = mutable(db, wid, cid, user, body.version)
        if case['status'] not in ('preparing','in_progress'):
            raise BusinessError(409, 'Repassez le dossier en préparation avant de modifier les hypothèses transmises.')
        if body.assignee_id and not db.execute("SELECT 1 FROM members WHERE workspace_id=%s AND user_id=%s AND role IN ('admin','analyst')", (wid, body.assignee_id)).fetchone():
            raise BusinessError(422, 'L’assignation exige un analyste ou administrateur de cet espace.')
        db.execute('UPDATE cases SET assignee_id=%s,quantity=%s,annual_unit_cents=%s,version=version+1,updated_at=%s WHERE id=%s', (body.assignee_id, body.quantity, body.annual_unit_cents, now(), cid))
        store.event(db, wid, cid, user['id'], 'case.updated', {'before': {key: case[key] for key in ('assignee_id','quantity','annual_unit_cents')}, 'after': body.model_dump(exclude={'version'})})
        return case_row(db, wid, cid)


class Progress(Input):
    version: int = Field(ge=1)
    status: Literal['preparing', 'in_progress', 'completed']
    reason: str = Field(min_length=3, max_length=4000)
    outcome: Literal['recovered', 'no_action'] | None = None
    actual_quantity: int | None = Field(default=None, ge=1, le=10000000)


def progress(wid: str, cid: str, body: Progress, user=None, store=None):
    with store.connect() as db:
        db.execute('SELECT id FROM workspaces WHERE id=%s FOR UPDATE', (wid,)).fetchone()
        case, role = mutable(db, wid, cid, user, body.version)
        current = case['status']
        if case['status'] == 'completed' and body.status == 'preparing':
            ensure_no_active_case(db, wid, case['pool_id'], cid)
        allowed = {
            'preparing': ['in_progress'],
            'in_progress': ['preparing', 'completed'],
            'sent': ['preparing', 'completed'],
            'response_received': ['preparing', 'completed'],
            'completed': ['preparing'],
        }
        if body.status not in allowed.get(current, []):
            raise BusinessError(409, 'Transition non autorisée depuis cet état.')
        quantity = None
        completed = None
        if body.status == 'completed':
            if body.outcome is None:
                raise BusinessError(422, 'Précisez le résultat du dossier.')
            if body.outcome == 'recovered':
                if body.actual_quantity is None or body.actual_quantity > case['quantity']:
                    raise BusinessError(422, 'Indiquez la quantité récupérée, sans dépasser la quantité examinée.')
                quantity = body.actual_quantity
            else:
                if body.actual_quantity is not None:
                    raise BusinessError(422, 'Aucune quantité récupérée pour une clôture sans suite.')
                quantity = 0
            completed = business_today(get_settings().business_timezone)
        elif body.outcome is not None or body.actual_quantity is not None:
            raise BusinessError(422, 'Le résultat se renseigne uniquement à la clôture.')
        db.execute('UPDATE cases SET status=%s,actual_quantity=%s,completed_on=%s,version=version+1,updated_at=%s WHERE id=%s',
                   (body.status, quantity, completed, now(), cid))
        store.event(db, wid, cid, user['id'], 'case.transition', {
            'from': current, 'to': body.status, **body.model_dump(exclude={'version','status'}, exclude_none=True),
            'previous_followup': {key: str(case[key]) if case[key] is not None else None for key in
                ('document_reference','external_decision','sent_on','responded_on','completed_on','actual_quantity')},
        })
        return case_row(db, wid, cid)


def transition(wid: str, cid: str, body: Decision, user=None, store=None):
    with store.connect() as db:
        db.execute('SELECT id FROM workspaces WHERE id=%s FOR UPDATE', (wid,)).fetchone()
        case, role = mutable(db, wid, cid, user, body.version)
        if case['status'] == 'completed' and body.status == 'preparing':
            ensure_no_active_case(db, wid, case['pool_id'], cid)
        allowed = {'preparing': ['sent'], 'sent': ['response_received', 'preparing'],
                   'response_received': ['completed', 'preparing'], 'completed': ['preparing']}
        if body.status not in allowed.get(case['status'], []):
            raise BusinessError(409, 'Transition non autorisée depuis cet état.')
        if body.status == 'preparing':
            if any(value is not None for value in (body.occurred_on, body.document_reference, body.external_decision, body.actual_quantity)):
                raise BusinessError(422, 'Une reprise ne doit pas contenir une nouvelle décision ou action.')
            db.execute("UPDATE cases SET status='preparing',document_reference=NULL,external_decision=NULL,sent_on=NULL,responded_on=NULL,completed_on=NULL,actual_quantity=NULL,legacy_status=NULL,version=version+1,updated_at=%s WHERE id=%s", (now(), cid))
        else:
            if not body.occurred_on or not body.document_reference:
                raise BusinessError(422, 'La date et la référence du document externe sont obligatoires.')
            if body.occurred_on > business_today(get_settings().business_timezone):
                raise BusinessError(422, 'La date ne peut pas être future.')
            if body.status == 'sent':
                if body.external_decision is not None or body.actual_quantity is not None:
                    raise BusinessError(422, 'La transmission ne constitue ni une décision ni une action effectuée.')
                db.execute("UPDATE cases SET sent_on=%s,document_reference=%s WHERE id=%s", (body.occurred_on, body.document_reference, cid))
            elif body.status == 'response_received':
                if not body.external_decision or body.actual_quantity is not None:
                    raise BusinessError(422, 'Précisez la décision reçue ; aucune action n’est encore déclarée.')
                if body.occurred_on < case['sent_on']:
                    raise BusinessError(422, 'Le retour doit être daté après la transmission.')
                db.execute("UPDATE cases SET responded_on=%s,external_decision=%s,document_reference=%s WHERE id=%s", (body.occurred_on, body.external_decision, body.document_reference, cid))
            else:
                if case['external_decision'] != 'accepted':
                    raise BusinessError(409, 'Une action ne peut être déclarée qu’après un accord externe enregistré.')
                if body.external_decision is not None or body.actual_quantity is None or body.actual_quantity > case['quantity']:
                    raise BusinessError(422, 'Indiquez une quantité réalisée positive ne dépassant pas la proposition transmise.')
                if body.occurred_on < case['responded_on']:
                    raise BusinessError(422, 'L’action doit être datée après le retour externe.')
                db.execute("UPDATE cases SET completed_on=%s,actual_quantity=%s,document_reference=%s WHERE id=%s", (body.occurred_on, body.actual_quantity, body.document_reference, cid))
            db.execute('UPDATE cases SET status=%s,legacy_status=NULL,version=version+1,updated_at=%s WHERE id=%s', (body.status, now(), cid))
        store.event(db, wid, cid, user['id'], 'case.transition', {
            'from': case['status'], 'to': body.status,
            **body.model_dump(mode='json', exclude={'version', 'status'}, exclude_none=True),
            'previous_followup': {key: str(case[key]) if case[key] is not None else None for key in
                                  ('document_reference','external_decision','sent_on','responded_on','completed_on','actual_quantity','legacy_status')},
        })
        return case_row(db, wid, cid)


def comment(wid: str, cid: str, body: Comment, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user, write=True)
        case_row(db, wid, cid)
        store.event(db, wid, cid, user['id'], 'case.comment', body.model_dump())
    return {'ok': True}


def export_case(wid: str, cid: str, user=None, store=None):
    from app.business.export import dossier_html
    case = detail(wid, cid, user, store)
    with store.connect() as db:
        member(db, wid, user)
        workspace = db.execute('SELECT name FROM workspaces WHERE id=%s', (wid,)).fetchone()['name']
        assignee = db.execute('SELECT name FROM users WHERE id=%s', (case['assignee_id'],)).fetchone() if case['assignee_id'] else None
        case['assignee_name'] = assignee['name'] if assignee else None
    return {'filename': f'sam-dossier-{cid}.html', 'content': dossier_html(case, workspace, now())}


class CommentRevision(Input):
    version: int = Field(ge=1)


class CommentEdit(CommentRevision):
    text: str = Field(min_length=1, max_length=4000)


def revise_comment(wid, cid, eid, body, user, store, deleting=False):
    with store.connect() as db:
        role = member(db, wid, user, write=True)
        case_row(db, wid, cid)
        original = db.execute(
            "SELECT * FROM events WHERE id=%s AND workspace_id=%s AND case_id=%s AND action='case.comment'",
            (eid, wid, cid)).fetchone()
        if not original:
            raise BusinessError(404, 'Note introuvable.')
        if original['actor_id'] != user['id'] and not (deleting and role == 'admin'):
            raise BusinessError(403, 'Seul l’auteur peut modifier sa note ; un administrateur peut la supprimer.')
        # Workspace write lock serializes edits and deletions, including concurrent requests.
        revisions = db.execute(
            "SELECT id,action,payload FROM events WHERE workspace_id=%s AND case_id=%s AND action IN ('comment.edited','comment.deleted') ORDER BY id",
            (wid, cid)).fetchall()
        latest = next((row for row in reversed(revisions) if json.loads(row['payload'])['comment_id'] == eid), original)
        if latest['id'] != body.version or latest['action'] == 'comment.deleted':
            raise BusinessError(409, 'Note modifiée ou supprimée. Rechargez le dossier.')
        if deleting:
            # Erase the original note and every edited text; keep only version metadata.
            db.execute("UPDATE events SET payload=(payload::jsonb - 'text')::text WHERE workspace_id=%s AND case_id=%s AND (id=%s OR (action='comment.edited' AND payload::jsonb->>'comment_id'=%s))",
                       (wid, cid, eid, str(eid)))
        payload = {'comment_id': eid, 'previous_version': latest['id']}
        if not deleting:
            payload['text'] = body.text
        store.event(db, wid, cid, user['id'], 'comment.deleted' if deleting else 'comment.edited', payload)
    return {'ok': True}


def edit_comment(wid: str, cid: str, eid: int, body: CommentEdit, user=None, store=None):
    return revise_comment(wid, cid, eid, body, user, store)


def delete_comment(wid: str, cid: str, eid: int, body: CommentRevision, user=None, store=None):
    return revise_comment(wid, cid, eid, body, user, store, deleting=True)


class CostUpdate(Input):
    version: int = Field(ge=0)
    annual_unit_cents: int | None = Field(ge=0, le=1000000000)


def costs(wid: str, user=None, store=None):
    with store.connect() as db:
        member(db, wid, user)
        return [dict(row) for row in db.execute('SELECT * FROM workspace_costs WHERE workspace_id=%s ORDER BY pool_id', (wid,))]


def save_cost(wid: str, pool_id: str, body: CostUpdate, user=None, store=None):
    if not pool_id.strip() or len(pool_id)>200:
        raise BusinessError(422, 'Identifiant logiciel invalide.')
    with store.connect() as db:
        member(db, wid, user, write=True)
        previous = db.execute('SELECT * FROM workspace_costs WHERE workspace_id=%s AND pool_id=%s', (wid,pool_id)).fetchone()
        version = previous['version'] if previous else 0
        if version != body.version:
            raise BusinessError(409, 'Coût modifié par un autre membre. Rechargez les valeurs.')
        db.execute('INSERT INTO workspace_costs VALUES(%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,pool_id) DO UPDATE SET annual_unit_cents=EXCLUDED.annual_unit_cents,version=EXCLUDED.version,updated_at=EXCLUDED.updated_at', (wid,pool_id,body.annual_unit_cents,version+1,now()))
        store.event(db,wid,None,user['id'],'cost.updated',{'pool_id':pool_id,'before_cents':previous['annual_unit_cents'] if previous else None,'after_cents':body.annual_unit_cents,'version':version+1})
        return dict(db.execute('SELECT * FROM workspace_costs WHERE workspace_id=%s AND pool_id=%s', (wid,pool_id)).fetchone())


class MemberRemoval(Input):
    expected_role: Literal['admin','analyst','reader']


def remove_member(wid: str,uid: str,body: MemberRemoval,user=None,store=None):
    with store.connect() as db:
        member(db,wid,user,admin=True)
        target=db.execute('SELECT role FROM members WHERE workspace_id=%s AND user_id=%s',(wid,uid)).fetchone()
        if not target:
            raise BusinessError(404,'Membre introuvable dans cet espace.')
        if target['role']!=body.expected_role:
            raise BusinessError(409,'Le rôle du membre a changé. Rechargez la liste.')
        count=db.execute("SELECT count(*) n FROM members WHERE workspace_id=%s AND role='admin'",(wid,)).fetchone()['n']
        if target['role']=='admin' and count==1:
            raise BusinessError(409,'L’espace doit conserver un administrateur.')
        unassign_member_cases(db, store, wid, uid, user['id'], 'Membre retiré de l’espace')
        db.execute('DELETE FROM members WHERE workspace_id=%s AND user_id=%s',(wid,uid))
        store.event(db,wid,None,user['id'],'member.removed',{'user_id':uid,'previous_role':target['role']})
    return {'ok':True}


def unassign_member_cases(db, store, wid, uid, actor_id, reason):
    """Called under the workspace lock in the same transaction as the role change."""
    assigned = db.execute('UPDATE cases SET assignee_id=NULL,version=version+1,updated_at=%s WHERE workspace_id=%s AND assignee_id=%s RETURNING id', (now(),wid,uid)).fetchall()
    for case in assigned:
        store.event(db,wid,case['id'],actor_id,'case.unassigned',{'previous_assignee':uid,'reason':reason})
