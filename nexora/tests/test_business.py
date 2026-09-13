"""Integration tests against a migrated, dedicated PostgreSQL database.
Run with BUSINESS_TEST_DATABASE_URL; never point it at an application database.
"""
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from service_scenarios import ScenarioClient as TestClient
from service_scenarios import app
from app.business.workspace_service import get_business_store
from app.business.store import BusinessStore


@pytest.fixture
def business():
    url = os.environ.get('BUSINESS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requires dedicated PostgreSQL integration database')
    store = BusinessStore(url)
    password = secrets.token_urlsafe(24)
    store.seed_demo(password)
    previous = app.dependency_overrides.get(get_business_store)
    app.dependency_overrides[get_business_store] = lambda: store
    with TestClient(app) as client:
        headers = {}
        for role in ('admin', 'analyst', 'reader'):
            response = client.post('/api/v1/business/login', json={'email': f'{role}@sam.demo', 'password': password})
            assert response.status_code == 200, response.text
            headers[role] = {'Authorization': f"Bearer {response.json()['token']}"}
        # Tests keep their own workspace; no truncation of shared tables.
        response = client.post('/api/v1/business/workspaces', headers=headers['admin'], json={'name': f'Test {uuid4()}'})
        wid = response.json()['id']
        base = f'/api/v1/business/workspaces/{wid}'
        for role in ('analyst', 'reader'):
            assert client.put(base+'/members', headers=headers['admin'], json={'email': f'{role}@sam.demo', 'role': role}).status_code == 200
        yield client, headers, base, store
    if previous is None:
        app.dependency_overrides.pop(get_business_store, None)
    else:
        app.dependency_overrides[get_business_store] = previous


def new_case(client, headers, base, pool_id="flex-cad"):
    response = client.post(base+'/cases', headers=headers['analyst'], json={
        'pool_id': pool_id, 'title': 'Examen Autodesk', 'quantity': 522,
        'annual_unit_cents': 24000, 'evidence': '365 jours fictifs : 522 licences candidates, validation requise.'})
    assert response.status_code == 201, response.text
    return response.json()


def test_session_revocation_and_no_anonymous_access(business):
    client, headers, base, store = business
    assert client.get(base+'/cases').status_code == 401
    assert client.post('/api/v1/business/login', json={'email': 'admin@sam.demo', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/v1/business/logout', headers=headers['reader']).status_code == 200
    assert client.get(base+'/cases', headers=headers['reader']).status_code == 401


def test_workflow_audit_persistence_and_optimistic_concurrency(business, monkeypatch):
    client, h, base, store = business
    case = new_case(client, h, base)
    path = base+'/cases/'+case['id']
    patch = {'version': 1, 'assignee_id': 'demo-analyst', 'quantity': 500, 'annual_unit_cents': 24000}
    assert client.patch(path, headers=h['analyst'], json=patch).status_code == 200
    assert client.patch(path, headers=h['analyst'], json=patch).status_code == 409
    assert client.post(path+'/comments', headers=h['analyst'], json={'text':'Vérifier les contrats avant décision.'}).status_code == 201
    from datetime import date, timedelta
    from app.business import workspace_service as api
    today = date(2026, 9, 12)
    monkeypatch.setattr(api, "business_today", lambda zone: today)
    def move(version, status, **extra):
        return client.post(path+'/transition', headers=h['analyst'], json={
            'version': version, 'status': status, 'reason': 'Justificatif externe fictif', **extra})
    fields = {'document_reference': '<script>alert(1)</script>', 'occurred_on': today.isoformat()}
    assert move(2, 'completed', **fields, actual_quantity=1).status_code == 409
    assert move(2, 'sent').status_code == 422
    assert move(2, 'sent', **{**fields,'occurred_on': (today+timedelta(days=1)).isoformat()}).status_code == 422
    assert move(2, 'sent', **fields).status_code == 200
    assert move(2, 'response_received', **fields, external_decision='accepted').status_code == 409
    assert client.patch(path, headers=h['admin'], json={**patch, 'version':3}).status_code == 409
    assert client.post(path+'/transition', headers=h['reader'], json={'version':3,'status':'response_received','reason':'Retour externe','external_decision':'accepted',**fields}).status_code == 403
    assert move(3, 'response_received', **{**fields, 'occurred_on': '2000-01-01'}, external_decision='accepted').status_code == 422
    assert move(3, 'response_received', **fields, external_decision='refused').status_code == 200
    assert move(4, 'completed', **fields, actual_quantity=1).status_code == 409
    assert move(4, 'preparing').status_code == 200
    reset = client.get(path, headers=h['reader']).json()
    assert reset['external_decision'] is None and reset['sent_on'] is None
    assert move(5, 'sent', **fields).status_code == 200
    assert move(6, 'response_received', **fields, external_decision='accepted').status_code == 200
    assert move(7, 'completed', **fields, actual_quantity=501).status_code == 422
    assert move(7, 'completed', **fields, actual_quantity=0).status_code == 422
    assert move(7, 'completed', **fields, actual_quantity=400).status_code == 200
    app.dependency_overrides[get_business_store] = lambda: BusinessStore(store.url)
    detail = client.get(path, headers=h['reader']).json()
    assert detail['status'] == 'completed' and detail['actual_quantity'] == 400
    assert detail['quantity'] == 500
    assert len(detail['events']) == 9
    assert detail['events'][1]['payload']['before']['quantity'] == 522
    assert detail['events'][5]['payload']['previous_followup']['external_decision'] == 'refused'
    exported = client.get(path+'/export', headers=h['reader'])
    assert exported.status_code == 200
    assert '<script>' not in exported.json()['content']
    assert '&lt;script&gt;' in exported.json()['content']
    assert 'Terminé' in exported.json()['content']


def test_workspace_isolation_reader_enforcement_and_last_admin(business):
    client, h, base, store = business
    case = new_case(client,h,base)
    private = client.post('/api/v1/business/workspaces', headers=h['admin'], json={'name':'Espace privé'}).json()['id']
    other = '/api/v1/business/workspaces/'+private
    assert client.get(other+'/cases', headers=h['reader']).status_code == 404
    assert client.get(other+'/cases/'+case['id'], headers=h['admin']).status_code == 404
    assert client.get(other+'/cases/'+case['id']+'/export', headers=h['admin']).status_code == 404
    assert client.patch(base, headers=h['reader'], json={'name':'Vol'}).status_code == 403
    assert client.post(base+'/cases', headers=h['reader'], json={'pool_id':'x','title':'x','quantity':1,'evidence':'x'}).status_code == 403
    assert client.post(base+'/cases/'+case['id']+'/comments', headers=h['reader'], json={'text':'Non autorisé'}).status_code == 403
    assert client.put(base+'/members', headers=h['analyst'], json={'email':'reader@sam.demo','role':'admin'}).status_code == 403
    assert client.put(base+'/members', headers=h['admin'], json={'email':'admin@sam.demo','role':'reader'}).status_code == 409
    patch = {'version':1,'assignee_id':'demo-reader','quantity':1,'annual_unit_cents':0}
    assert client.patch(base+'/cases/'+case['id'], headers=h['admin'], json=patch).status_code == 422


def test_concurrent_edits_cannot_silently_overwrite(business):
    client,h,base,store = business
    case = new_case(client,h,base)
    def edit(quantity):
        with TestClient(app) as concurrent_client:
            return concurrent_client.patch(base+'/cases/'+case['id'],headers=h['analyst'],json={'version':1,'quantity':quantity,'annual_unit_cents':1}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(edit, [300,400]))
    assert sorted(statuses) == [200,409]


def test_shared_lake_requires_login_and_owner_admin(business):
    client,h,base,store = business
    from app.dependencies import get_pipeline
    from app.models.canonical import UsageSnapshot
    from datetime import datetime, timezone
    class Pipeline:
        async def sync(self):
            return UsageSnapshot(snapshot_id='auth-test', timestamp=datetime.now(timezone.utc), source='mock', usage=[], stock=[])
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: Pipeline()
    try:
        assert client.get('/api/v1/stock').status_code == 401
        assert client.post('/api/v1/sync').status_code == 401
        assert client.post('/api/v1/sync',headers=h['reader']).status_code == 403
        assert client.post('/api/v1/sync',headers=h['analyst']).status_code == 403
        assert client.post('/api/v1/demo/generate',headers=h['analyst'],json={'days':365}).status_code == 403
        assert client.post('/api/v1/sync',headers=h['admin']).status_code == 200
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline,None)
        else: app.dependency_overrides[get_pipeline] = previous


def test_password_rotation_invalidates_previous_sessions(business):
    client,h,base,store=business
    fresh=secrets.token_urlsafe(24)
    store.seed_demo(fresh)
    assert client.get('/api/v1/business/me',headers=h['admin']).status_code==401
    response=client.post('/api/v1/business/login',json={'email':'admin@sam.demo','password':fresh})
    assert response.status_code==200


def test_known_and_unknown_login_each_run_one_password_derivation(business, monkeypatch):
    client,h,base,store=business
    from app.business import store as module
    original=module.password_hash
    calls=[]
    def counted(password,salt=None):
        calls.append(1)
        return original(password,salt)
    monkeypatch.setattr(module,'password_hash',counted)
    assert store.login('unknown@sam.demo','incorrect') is None
    assert len(calls)==1
    calls.clear()
    assert store.login('admin@sam.demo','incorrect') is None
    assert len(calls)==1


def test_comment_edit_delete_permissions_versions_and_audit(business):
    client, h, base, store = business
    case = new_case(client, h, base)
    path = base+'/cases/'+case['id']
    assert client.post(path+'/comments', headers=h['analyst'], json={'text':'Texte original'}).status_code == 201
    original = client.get(path, headers=h['reader']).json()['events'][-1]
    endpoint = path+'/comments/'+str(original['id'])
    body = {'version':original['id'], 'text':'Texte corrigé'}
    assert client.patch(endpoint, headers=h['reader'], json=body).status_code == 403
    assert client.patch(endpoint, headers=h['admin'], json=body).status_code == 403
    assert client.patch(endpoint, headers=h['analyst'], json={**body,'text':'   '}).status_code == 422
    assert client.patch(endpoint, headers=h['analyst'], json=body).status_code == 200
    assert client.patch(endpoint, headers=h['analyst'], json=body).status_code == 409
    events = client.get(path, headers=h['reader']).json()['events']
    comment = next(e for e in events if e['id'] == original['id'])
    assert comment['comment']['text'] == 'Texte corrigé'
    assert comment['payload']['text'] == 'Texte original'
    assert events[-1]['action'] == 'comment.edited'
    revision = comment['comment']['version']
    # The same event ID cannot be accessed through another case.
    other = new_case(client, h, base, "flex-other")
    assert client.patch(base+'/cases/'+other['id']+'/comments/'+str(original['id']), headers=h['analyst'], json={**body,'version':revision}).status_code == 404
    assert client.request('DELETE', endpoint, headers=h['reader'], json={'version':revision}).status_code == 403
    assert client.request('DELETE', endpoint, headers=h['admin'], json={'version':revision}).status_code == 200
    events = client.get(path, headers=h['reader']).json()['events']
    comment = next(e for e in events if e['id'] == original['id'])
    assert comment['comment']['deleted'] and comment['comment']['text'] == ''
    assert events[-1]['actor_id'] == 'demo-admin'
    import json
    assert 'Texte original' not in json.dumps(events) and 'Texte corrigé' not in json.dumps(events)
    with store.connect() as db:
        payloads = str(db.execute('SELECT payload FROM events WHERE case_id=%s', (case['id'],)).fetchall())
    assert 'Texte original' not in payloads and 'Texte corrigé' not in payloads

    exported = client.get(path+'/export', headers=h['reader']).json()['content']
    current = exported.split('<h2>Notes</h2>')[1].split('<h2>Suivi du dossier')[0]
    assert 'Commentaire supprimé' not in current
    assert 'Texte original' not in current and 'Texte corrigé' not in current
    assert client.patch(endpoint, headers=h['analyst'], json={**body,'version':comment['comment']['version']}).status_code == 409
    assert client.request('DELETE', endpoint, headers=h['admin'], json={'version':comment['comment']['version']}).status_code == 409
    # An author can also delete their own comment.
    assert client.post(path+'/comments', headers=h['analyst'], json={'text':'Autre commentaire'}).status_code == 201
    own = client.get(path, headers=h['reader']).json()['events'][-1]
    assert client.request('DELETE', path+'/comments/'+str(own['id']), headers=h['analyst'], json={'version':own['id']}).status_code == 200


def test_shared_analysis_settings_permissions_persistence_and_pipeline(business, monkeypatch):
    client, h, base, store = business
    endpoint = '/api/v1/business/analysis-settings'
    assert client.get(endpoint).status_code == 401
    original = client.get(endpoint, headers=h['admin']).json()
    assert original['can_edit']
    assert not client.get(endpoint, headers=h['analyst']).json()['can_edit']
    value = {'threshold':0.42,'buffer':0.15,'version':original['version']}
    assert client.put(endpoint, headers=h['analyst'], json=value).status_code == 403
    assert client.put(endpoint, headers=h['reader'], json=value).status_code == 403
    assert client.put(endpoint, headers=h['admin'], json={**value,'threshold':0}).status_code == 422
    assert client.put(endpoint, headers=h['admin'], json={**value,'buffer':1.1}).status_code == 422
    saved = client.put(endpoint, headers=h['admin'], json=value)
    assert saved.status_code == 200
    assert client.put(endpoint, headers=h['admin'], json=value).status_code == 409
    from app.business.settings_service import read_settings
    assert read_settings(BusinessStore(store.url))['threshold'] == 0.42
    # Every newly constructed pipeline uses the durable settings, not a cached env default.
    from app import dependencies
    from app.config import get_settings
    settings = get_settings().model_copy(update={'database_url':store.url})
    monkeypatch.setattr(dependencies, 'get_settings', lambda: settings)
    monkeypatch.setattr(dependencies, 'S3ParquetStore', lambda *args: object())
    captured = []
    monkeypatch.setattr(dependencies, 'SparkAnalytics', lambda *args: captured.append(args) or object())
    dependencies.get_pipeline()
    assert captured[-1][1:] == (0.42,0.15)
    with store.connect() as db:
        event = db.execute('SELECT * FROM analysis_settings_events ORDER BY id DESC LIMIT 1').fetchone()
        assert event['actor_id'] == 'demo-admin'
    assert client.put(endpoint, headers=h['admin'], json={'threshold':original['threshold'],'buffer':original['buffer'],'version':saved.json()['version']}).status_code == 200


@pytest.mark.parametrize('zone,instant,local_date,future', [
    ('Europe/Paris','2026-09-11T22:30:00+00:00','2026-09-12','2026-09-13'),
    ('America/Los_Angeles','2026-09-12T02:30:00+00:00','2026-09-11','2026-09-12'),
])
def test_followup_uses_business_day_at_utc_boundary(business, monkeypatch, zone, instant, local_date, future):
    from datetime import datetime
    from types import SimpleNamespace
    from app.business import workspace_service as api
    from app.business.calendar import business_today
    client, h, base, store = business
    monkeypatch.setattr(api, 'get_settings', lambda: SimpleNamespace(business_timezone=zone))
    monkeypatch.setattr(api, 'business_today', lambda name: business_today(name,datetime.fromisoformat(instant)))
    case = new_case(client,h,base)
    path = base+'/cases/'+case['id']+'/transition'
    body = {'version':1,'status':'sent','reason':'Transmission locale','document_reference':'DEMO-01'}
    assert client.post(path, headers=h['analyst'], json={**body,'occurred_on':future}).status_code == 422
    assert client.post(path, headers=h['analyst'], json={**body,'occurred_on':local_date}).status_code == 200
    assert client.get('/api/v1/business/me',headers=h['analyst']).json()['business_timezone'] == zone


def test_workspace_costs_are_shared_isolated_versioned_and_snapshotted(business):
    client,h,base,store=business
    endpoint=base+'/costs/flex-cad'
    assert client.get(base+'/costs').status_code==401
    assert client.get(base+'/costs',headers=h['reader']).json()==[]
    value={'version':0,'annual_unit_cents':24000}
    assert client.put(endpoint,headers=h['reader'],json=value).status_code==403
    assert client.put(endpoint,headers=h['analyst'],json={**value,'annual_unit_cents':-1}).status_code==422
    assert client.put(endpoint,headers=h['analyst'],json=value).status_code==200
    assert client.put(endpoint,headers=h['admin'],json=value).status_code==409
    assert client.get(base+'/costs',headers=h['reader']).json()[0]['annual_unit_cents']==24000
    app.dependency_overrides[get_business_store]=lambda:BusinessStore(store.url)
    create={'pool_id':'flex-cad','title':'Copie du coût','quantity':3,'evidence':'Données fictives'}
    case=client.post(base+'/cases',headers=h['analyst'],json=create).json()
    assert case['annual_unit_cents']==24000
    assert client.put(endpoint,headers=h['admin'],json={'version':1,'annual_unit_cents':0}).status_code==200
    assert client.get(base+'/cases/'+case['id'],headers=h['reader']).json()['annual_unit_cents']==24000
    assert client.get(base+'/costs',headers=h['reader']).json()[0]['annual_unit_cents']==0
    assert client.put(endpoint,headers=h['admin'],json={'version':2,'annual_unit_cents':None}).status_code==200
    assert client.get(base+'/costs',headers=h['reader']).json()[0]['annual_unit_cents'] is None
    other=client.post('/api/v1/business/workspaces',headers=h['admin'],json={'name':'Coûts privés'}).json()['id']
    private='/api/v1/business/workspaces/'+other
    assert client.get(private+'/costs',headers=h['admin']).json()==[]
    assert client.get(private+'/costs',headers=h['analyst']).status_code==404
    assert client.put(private+'/costs/flex-cad',headers=h['analyst'],json=value).status_code==404
    with store.connect() as db:
        assert db.execute("SELECT count(*) n FROM events WHERE workspace_id=%s AND action='cost.updated'",(base.rsplit('/',1)[1],)).fetchone()['n']==3


def test_portfolio_selection_is_shared_and_applied_by_api(business, monkeypatch):
    monkeypatch.setattr("app.business.portfolio_service.read_summary", lambda p:p.run_analytics())
    from types import SimpleNamespace
    from app.dependencies import get_pipeline
    client,h,base,store=business
    calls=[]
    class Pipeline:
        async def bootstrap_mock_history(self): pass
        def run_analytics(self,pools=None):
            calls.append(pools)
            from app.models.canonical import AnalyticsSummary, Trend
            from datetime import datetime, timezone
            stamp=datetime.now(timezone.utc)
            item=Trend(license_pool_id='flex-adobe',software_name='Adobe',capacity=2000,period_start=stamp,period_end=stamp,average_used=100,maximum_used=100,p95_used=100,utilization_rate=.05,previous_period_change=None,daily=[])
            return AnalyticsSummary(generated_at=stamp,total_capacity=2000,total_used=100,total_available=1900,utilization_rate=.05,pools_at_risk=0,pools_total=1,recovery_potential=0,trends=[item],inactive=[],risks=[])
    previous=app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline]=lambda:Pipeline()
    try:
        assert client.get(base+'/portfolio',headers=h['admin']).json()['pool_ids']==[]
        body={'all_catalog':False,'pool_ids':['flex-adobe'],'version':1}
        assert client.put(base+'/portfolio',headers=h['analyst'],json=body).status_code==403
        assert client.put(base+'/portfolio',headers=h['reader'],json=body).status_code==403
        assert client.put(base+'/portfolio',headers=h['admin'],json={**body,'pool_ids':['unknown']}).status_code==422
        assert client.put(base+'/portfolio',headers=h['admin'],json=body).status_code==200
        assert client.put(base+'/portfolio',headers=h['admin'],json=body).status_code==409
        assert client.get(base+'/portfolio',headers=h['reader']).json()['pool_ids']==['flex-adobe']
        from app.business.portfolio_service import selected_pools
        user=store.user_for_token(h['reader']['Authorization'].split()[1])
        assert selected_pools(base.rsplit('/',1)[1],user,store)==['flex-adobe']
        response=client.get('/api/v1/analytics/summary?workspace_id='+base.rsplit('/',1)[1],headers=h['reader'])
        assert response.status_code==200 and calls[-1]==['flex-adobe']
        assert selected_pools(None,user,store) is None
        assert client.get('/api/v1/business/catalog',headers=h['reader']).json()[0]['pool_id']=='flex-adobe'
        private=client.post('/api/v1/business/workspaces',headers=h['admin'],json={'name':'Autre SAM'}).json()['id']
        assert client.get('/api/v1/stock?workspace_id='+private,headers=h['reader']).status_code==404
        assert client.get('/api/v1/business/workspaces/'+private+'/portfolio',headers=h['reader']).status_code==404
        assert client.put(base+'/portfolio',headers=h['admin'],json={'all_catalog':True,'pool_ids':[],'version':2}).status_code==200
        assert selected_pools(base.rsplit('/',1)[1],user,store) is None
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline,None)
        else: app.dependency_overrides[get_pipeline]=previous


def test_member_removal_revokes_workspace_access_and_preserves_history(business):
    client,h,base,store=business
    case=new_case(client,h,base)
    path=base+'/cases/'+case['id']
    assert client.patch(path,headers=h['admin'],json={'version':1,'assignee_id':'demo-analyst','quantity':1,'annual_unit_cents':0}).status_code==200
    endpoint=base+'/members/demo-analyst'
    assert client.request('DELETE',endpoint,headers=h['reader'],json={'expected_role':'analyst'}).status_code==403
    assert client.request('DELETE',endpoint,headers=h['admin'],json={'expected_role':'reader'}).status_code==409
    assert client.request('DELETE',base+'/members/demo-admin',headers=h['admin'],json={'expected_role':'admin'}).status_code==409
    assert client.request('DELETE',endpoint,headers=h['admin'],json={'expected_role':'analyst'}).status_code==200
    assert client.get(path,headers=h['analyst']).status_code==404
    assert client.get(base+'/costs',headers=h['analyst']).status_code==404
    assert client.get(base+'/portfolio',headers=h['analyst']).status_code==404
    assert client.get('/api/v1/business/me',headers=h['analyst']).status_code==200
    detail=client.get(path,headers=h['admin']).json()
    assert detail['assignee_id'] is None and detail['version']==3
    assert detail['events'][-1]['action']=='case.unassigned'
    assert detail['events'][-1]['payload']['previous_assignee']=='demo-analyst'
    assert client.put(base+'/members',headers=h['admin'],json={'email':'reader@sam.demo','role':'admin'}).status_code==200
    assert client.request('DELETE',base+'/members/demo-admin',headers=h['admin'],json={'expected_role':'admin'}).status_code==200
    assert client.get(path,headers=h['admin']).status_code==404
    assert client.get(path,headers=h['reader']).status_code==200
    assert client.request('DELETE',base+'/members/demo-reader',headers=h['reader'],json={'expected_role':'admin'}).status_code==409


@pytest.mark.parametrize('previous_role',['analyst','admin'])
def test_demotion_to_reader_unassigns_cases_atomically_with_audit(business,previous_role):
    client,h,base,store=business
    assert client.put(base+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':previous_role}).status_code==200
    case=new_case(client,h,base)
    path=base+'/cases/'+case['id']
    patch={'version':1,'assignee_id':'demo-analyst','quantity':2,'annual_unit_cents':500}
    assert client.patch(path,headers=h['admin'],json=patch).status_code==200
    private=client.post('/api/v1/business/workspaces',headers=h['admin'],json={'name':'Autre affectation'}).json()['id']
    other='/api/v1/business/workspaces/'+private
    assert client.put(other+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':'analyst'}).status_code==200
    second=new_case(client,h,other)
    assert client.patch(other+'/cases/'+second['id'],headers=h['admin'],json=patch).status_code==200
    # Moving between writing roles must retain the assignment and version.
    assert client.put(base+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':'analyst'}).status_code==200
    assert client.get(path,headers=h['admin']).json()['version']==2
    assert client.put(base+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':previous_role}).status_code==200
    assert client.put(base+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':'reader'}).status_code==200
    detail=client.get(path,headers=h['analyst']).json()
    assert detail['assignee_id'] is None and detail['version']==3
    assert detail['quantity']==2 and detail['annual_unit_cents']==500
    assert detail['events'][-1]['action']=='case.unassigned'
    assert detail['events'][-1]['payload']=={'previous_assignee':'demo-analyst','reason':'Membre passé au rôle lecteur'}
    assert client.patch(path,headers=h['admin'],json={**patch,'version':2}).status_code==409
    assert client.patch(path,headers=h['analyst'],json={**patch,'version':3}).status_code==403
    untouched=client.get(other+'/cases/'+second['id'],headers=h['analyst']).json()
    assert untouched['assignee_id']=='demo-analyst' and untouched['version']==2
    assert client.put(base+'/members',headers=h['admin'],json={'email':'analyst@sam.demo','role':'reader'}).status_code==200
    assert client.get(path,headers=h['admin']).json()['version']==3

def test_create_account_role_isolation_and_no_existing_account_takeover(business):
    client, h, base, store = business
    password = secrets.token_urlsafe(24)
    email = f'fictional-{uuid4()}@sam.demo'
    body = {'email':email, 'name':'Compte fictif', 'password':password, 'role':'reader'}
    path = base+'/accounts'
    assert client.post(path, json=body).status_code == 401
    for role in ('reader','analyst'):
        assert client.post(path, headers=h[role], json=body).status_code == 403
    created = client.post(path, headers=h['admin'], json=body)
    assert created.status_code == 201, created.text
    assert 'password' not in created.json()
    duplicate = client.post(path, headers=h['admin'], json={**body,'password':secrets.token_urlsafe(24),'role':'admin'})
    assert duplicate.status_code == 409
    login = client.post('/api/v1/business/login', json={'email':email,'password':password})
    assert login.status_code == 200
    account = {'Authorization':'Bearer '+login.json()['token']}
    assert client.get('/api/v1/business/me', headers=account).json()['workspaces'] == [
        {**client.get('/api/v1/business/me', headers=account).json()['workspaces'][0], 'id':base.split('/')[-1], 'role':'reader'}
    ]
    assert client.get(base+'/cases', headers=account).status_code == 200
    assert client.get('/api/v1/business/workspaces/demo/cases', headers=account).status_code == 404
    assert client.put(base+'/members', headers=account, json={'email':email,'role':'admin'}).status_code == 403
    with store.connect() as db:
        stored = db.execute('SELECT password FROM users WHERE id=%s',(created.json()['id'],)).fetchone()['password']
        events = db.execute('SELECT payload FROM events WHERE workspace_id=%s',(base.split('/')[-1],)).fetchall()
    assert stored != password
    assert all(password not in e['payload'] for e in events)

def test_simple_progress_preserves_audit_and_requires_valid_result(business):
    client, h, base, store = business
    case = new_case(client, h, base)
    path = base+'/cases/'+case['id']+'/progress'
    def move(version, status, **extra):
        return client.post(path, headers=h['analyst'], json={'version':version,'status':status,'reason':'Examen du portefeuille',**extra})
    assert client.post(path, headers=h['reader'], json={'version':1,'status':'in_progress','reason':'Examen'}).status_code == 403
    assert move(1,'completed',outcome='no_action').status_code == 409
    assert move(1,'in_progress').status_code == 200
    assert move(1,'completed',outcome='no_action').status_code == 409
    assert move(2,'completed').status_code == 422
    assert move(2,'completed',outcome='recovered',actual_quantity=523).status_code == 422
    assert move(2,'completed',outcome='no_action').json()['actual_quantity'] == 0
    assert move(3,'preparing').status_code == 200
    assert move(4,'in_progress').status_code == 200
    assert move(5,'completed',outcome='recovered',actual_quantity=20).json()['actual_quantity'] == 20
    detail = client.get(base+'/cases/'+case['id'], headers=h['reader']).json()
    assert detail['events'][-1]['payload']['outcome'] == 'recovered'
    assert detail['events'][-3]['payload']['previous_followup']['actual_quantity'] == '0'


def test_export_in_progress_hides_deleted_comment_content(business):
    client, h, base, store = business
    case = new_case(client, h, base)
    path = base+'/cases/'+case['id']
    assert client.post(path+'/progress', headers=h['analyst'], json={'version':1,'status':'in_progress','reason':'Analyse en cours'}).status_code == 200
    posted = client.post(path+'/comments', headers=h['analyst'], json={'text':'obsolete-comment-marker'})
    assert posted.status_code == 201
    detail = client.get(path, headers=h['analyst']).json()
    event = next(e for e in detail['events'] if e.get('comment'))
    assert client.request('DELETE',path+'/comments/'+str(event['id']), headers=h['analyst'], json={'version':event['comment']['version']}).status_code == 200
    exported = client.get(path+'/export', headers=h['reader'])
    assert exported.status_code == 200
    assert 'En cours' in exported.json()['content']
    assert 'obsolete-comment-marker' not in exported.text


def test_only_one_active_case_per_pool_even_concurrently(business):
    client, h, base, store = business
    body = {'pool_id': 'flex-unique', 'title': 'Examen unique', 'quantity': 10, 'evidence': 'Jeu de test fictif'}
    def create():
        return client.post(base+'/cases', headers=h['analyst'], json=body)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: create(), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    original = next(r.json() for r in responses if r.status_code == 201)
    path = base+'/cases/'+original['id']
    assert client.post(path+'/progress', headers=h['analyst'], json={'version':1,'status':'in_progress','reason':'Examen lancé'}).status_code == 200
    assert client.post(path+'/progress', headers=h['analyst'], json={'version':2,'status':'completed','reason':'Examen terminé','outcome':'no_action'}).status_code == 200
    assert create().status_code == 201
    for endpoint in ('progress', 'transition'):
        assert client.post(path+'/'+endpoint, headers=h['analyst'], json={'version':3,'status':'preparing','reason':'Nouvel examen'}).status_code == 409
    other = client.post('/api/v1/business/workspaces', headers=h['admin'], json={'name':'Autre périmètre'}).json()['id']
    assert client.post('/api/v1/business/workspaces/'+other+'/cases', headers=h['admin'], json=body).status_code == 201
    assert client.post(base+'/cases', headers=h['reader'], json=body).status_code == 403


def test_migration_erases_old_deleted_notes_without_touching_active_notes(business):
    import importlib.util
    import json
    from pathlib import Path
    from types import SimpleNamespace
    client, h, base, store = business
    case = new_case(client, h, base)
    wid = base.rsplit('/', 1)[-1]
    with store.connect() as db:
        store.event(db, wid, case['id'], 'demo-analyst', 'case.comment', {'text':'legacy erased text'})
        eid = db.execute("SELECT max(id) AS id FROM events WHERE case_id=%s", (case['id'],)).fetchone()['id']
        store.event(db, wid, case['id'], 'demo-analyst', 'comment.edited', {'comment_id':eid,'text':'legacy revised text'})
        store.event(db, wid, case['id'], 'demo-analyst', 'comment.deleted', {'comment_id':eid})
        store.event(db, wid, case['id'], 'demo-analyst', 'case.comment', {'text':'active note retained'})
        spec = importlib.util.spec_from_file_location('erase_notes', Path(__file__).parents[1]/'migrations/versions/0008_erase_deleted_notes.py')
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = SimpleNamespace(execute=db.execute)
        migration.upgrade()
        migration.upgrade()  # Safe to reapply the cleanup.
        rows = db.execute('SELECT action,payload FROM events WHERE case_id=%s', (case['id'],)).fetchall()
        content = json.dumps(rows)
        assert 'legacy erased text' not in content and 'legacy revised text' not in content
        assert 'active note retained' in content and 'case.created' in content


@pytest.mark.parametrize(('revision', 'target', 'reason'), [
    ('0008_erase_deleted_notes', '0007_simple_case_progress', 'Note erasure is irreversible'),
    ('0010_collection_journal', '0009_inventory_index', 'Collection recovery metadata must not be discarded'),
    ('0011_collection_rebases', '0010_collection_journal', 'Recovery lineage must not be discarded'),
    ('0016_bi_publications', '0015_daily_collection_polls', 'BI publication lineage must not be discarded'),
    ('0017_bi_readers', '0016_bi_publications', 'BI reader revocations must not be discarded'),
    ('0018_worker_roles', '0017_bi_readers', 'Worker roles must not be discarded'),
])
def test_note_erasure_downgrade_fails_without_changing_database_revision(business, revision, target, reason):
    import subprocess
    from pathlib import Path
    from sqlalchemy.engine import make_url
    from psycopg import sql
    _, _, _, store = business
    # Start at the migration under test, never downgrade the shared test database.
    schema = 'rollback_test_' + uuid4().hex
    isolated_url = make_url(store.url).update_query_dict(
        {'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    isolated = BusinessStore(isolated_url)
    with store.connect() as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        def alembic(*args):
            return subprocess.run(['alembic', *args], cwd=Path(__file__).parents[1],
                env={**os.environ, 'DATABASE_URL': isolated_url}, capture_output=True, text=True)
        upgraded = alembic('upgrade', revision)
        assert upgraded.returncode == 0, upgraded.stderr
        with isolated.connect() as db:
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == revision
        result = alembic('downgrade', target)
        assert result.returncode != 0
        assert reason in result.stderr
        with isolated.connect() as db:
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == revision
    finally:
        with store.connect() as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_inventory_access_portfolio_and_persisted_snapshot(business):
    from datetime import datetime, timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from enterprise_fixture import snapshot
    from app.models.inventory import map_inventory_payload
    model = map_inventory_payload(snapshot(datetime(2026,9,11,tzinfo=timezone.utc)))
    output = BytesIO()
    pq.write_table(pa.Table.from_pylist([model.model_dump(mode='json')]),output)
    storage = SimpleNamespace(list_keys=lambda prefix:['silver/inventory/date=2026-09-11/demo.parquet'],
                              get_bytes=lambda key:output.getvalue())
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=storage)
    client, headers, base, store = business
    try:
        assert client.get(base+'/inventory').status_code == 401
        assert client.get('/api/v1/business/workspaces/unknown/inventory',headers=headers['reader']).status_code == 404
        assert client.get(base+'/inventory',headers=headers['reader']).json()['total'] == 0
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET pool_ids=%s WHERE workspace_id=%s', ('["flex-cad"]',base.split('/')[-1]))
        response = client.get(base+'/inventory?country=Canada&limit=5',headers=headers['reader'])
        assert response.status_code == 200
        assert response.json()['total'] > 0
        assert all(r['software'] == ['flex-cad'] and r['country'] == 'Canada' for r in response.json()['rows'])
        assert client.get(base+'/inventory?limit=10000',headers=headers['reader']).status_code == 422
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_pipeline,None)
        else:
            app.dependency_overrides[get_pipeline] = previous


def test_inventory_index_scope_pagination_and_details(business):
    from datetime import datetime, timezone
    from app.business.inventory_index import publish_index,read_index
    from enterprise_fixture import snapshot
    from app.models.inventory import map_inventory_payload
    client, headers, base, store = business
    namespace = str(uuid4())
    model = map_inventory_payload(snapshot(datetime(2026,9,11,tzinfo=timezone.utc)))
    publish_index(store,namespace,model,'test/manifest.json')
    with store.connect() as db:
        result = read_index(db,namespace,None,'machines','',0,5,{})
        assert result['total'] == 138 and len(result['rows']) == 5
        assert all('relationships' not in row for row in result['rows'])
        second = read_index(db,namespace,None,'machines','',5,5,{})
        assert not {r['machine_id'] for r in result['rows']} & {r['machine_id'] for r in second['rows']}
        assert read_index(db,namespace,[],'machines','',0,5,{})['total'] == 0
        scoped = read_index(db,namespace,['flex-cad'],'users','',0,5,{})
        assert scoped['rows'] and all(r['software']==['flex-cad'] for r in scoped['rows'])
        detail = read_index(db,namespace,['flex-cad'],'users','',0,1,{},scoped['rows'][0]['user_id'])
        assert all(r['license_pool_id']=='flex-cad' for r in detail['rows'][0]['relationships'])
        assert read_index(db,namespace,None,'users','',0,25,{'country':'Canada'})['total'] > 0
        assert read_index(db,namespace,None,'machines','',0,25,{'kind':'virtual'})['total'] == 20
        assert read_index(db,'missing',None,'machines','',0,25,{}) is None


def test_inventory_software_catalog_respects_workspace(business):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.dependencies import get_pipeline
    from app.business.inventory_index import publish_index
    from enterprise_fixture import snapshot
    from app.models.inventory import map_inventory_payload
    client, headers, base, store = business
    namespace = str(uuid4())
    model = map_inventory_payload(snapshot(datetime(2026,9,11,tzinfo=timezone.utc)))
    publish_index(store,namespace,model,'test/manifest.json')
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=SimpleNamespace(prefix=namespace))
    try:
        assert client.get(base+'/inventory/software').status_code == 401
        assert client.get(base+'/inventory/software',headers=headers['reader']).json() == []
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET all_catalog=true WHERE workspace_id=%s',(base.split('/')[-1],))
        response = client.get(base+'/inventory/software',headers=headers['reader'])
        assert response.status_code == 200
        assert sum(row['machines'] for row in response.json()) == 910
        assert client.get('/api/v1/business/workspaces/unknown/inventory/software',headers=headers['reader']).status_code == 404
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline,None)
        else: app.dependency_overrides[get_pipeline] = previous


def test_installation_usage_report_is_scoped_to_selected_pools(business):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from io import BytesIO
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    client, headers, base, store = business
    namespace = str(uuid4())
    publish_index(store,namespace,InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock'),'gold/enterprise/test/manifest.json')
    table = BytesIO()
    pq.write_table(pa.Table.from_pylist([{'license_pool_id':'flex-cad','name':'Autodesk'},{'license_pool_id':'flex-adobe','name':'Adobe'}]),table)
    objects = {
        'gold/enterprise/test/manifest.json':json.dumps({'dimensions':{'products':{'key':'products'}},'installation_usage':{'key':'report'}}).encode(),
        'products':table.getvalue(),
        'report':json.dumps({'days':365,'products':[{'license_pool_id':'flex-cad','installations_without_usage':3},{'license_pool_id':'flex-adobe','installations_without_usage':5}],'detail_key':'private-detail'}).encode(),
    }
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=SimpleNamespace(prefix=namespace,get_bytes=lambda key:objects[key]))
    try:
        path = base+'/inventory/installation-usage'
        assert client.get(path).status_code == 401
        assert client.get(path,headers=headers['reader']).json()['products'] == []
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET pool_ids=%s WHERE workspace_id=%s',(json.dumps(['flex-cad']),base.split('/')[-1]))
        result = client.get(path,headers=headers['reader']).json()
        assert [p['license_pool_id'] for p in result['products']] == ['flex-cad']
        assert result['products'][0]['software_name'] == 'Autodesk'
        assert 'detail_key' not in result
    finally:
        if previous is None:app.dependency_overrides.pop(get_pipeline,None)
        else:app.dependency_overrides[get_pipeline] = previous


def test_delete_case_erases_notes_and_keeps_other_cases(business):
    client, h, base, store = business
    case = new_case(client, h, base)
    other = new_case(client, h, base, 'other-pool')
    path = base + '/cases/' + case['id']
    assert client.post(path + '/comments', headers=h['analyst'], json={'text': 'Remove with dossier'}).status_code == 201
    assert client.request('DELETE', path, headers=h['reader'], json={'version': 1}).status_code == 403
    private = client.post('/api/v1/business/workspaces', headers=h['admin'], json={'name': 'Isolated'}).json()['id']
    assert client.request('DELETE', '/api/v1/business/workspaces/' + private + '/cases/' + case['id'], headers=h['admin'], json={'version': 1}).status_code == 404
    assert client.request('DELETE', path, headers=h['analyst'], json={'version': 2}).status_code == 409
    assert client.request('DELETE', path, headers=h['analyst'], json={'version': 1}).status_code == 200
    assert client.get(path, headers=h['admin']).status_code == 404
    assert client.get(base + '/cases/' + other['id'], headers=h['admin']).status_code == 200
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM events WHERE case_id=%s', (case['id'],)).fetchone()['n'] == 0
    assert new_case(client, h, base)['id'] != case['id']


def test_system_only_portfolio_selects_rhel_and_filters_index(business, monkeypatch):
    monkeypatch.setattr("app.business.portfolio_service.read_summary", lambda p:p.run_analytics())
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from io import BytesIO
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.connectors.enterprise_software import software_dimensions
    from app.models.inventory import InventorySnapshot
    from app.business.inventory_index import publish_index
    client, h, base, store = business
    at = datetime(2026, 9, 11, tzinfo=timezone.utc)
    raw = enterprise_inventory(at, employees=30, workstations=20, physical_servers=2, virtual_servers=6, contractors=4)
    raw.update(software_dimensions(raw))
    model = InventorySnapshot(captured_at=at, source='digimon-mock', **raw)
    namespace = str(uuid4())
    key = 'gold/enterprise/test/manifest.json'
    objects = {}
    for name in ('products','entitlements'):
        out = BytesIO(); pq.write_table(pa.Table.from_pylist(raw[name]), out)
        objects[name] = out.getvalue()
    objects[key] = json.dumps({'dimensions':{name:{'key':name} for name in ('products','entitlements')}}).encode()
    publish_index(store, namespace, model, key)
    storage = SimpleNamespace(prefix=namespace, get_bytes=lambda key:objects[key])
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=storage, run_analytics=lambda:SimpleNamespace(trends=[]))
    try:
        catalog = client.get('/api/v1/business/catalog', headers=h['reader']).json()
        rhel = next(p for p in catalog if p['name']=='Red Hat Enterprise Linux 9')
        assert rhel['capacity'] is None
        body = {'all_catalog':False, 'pool_ids':[rhel['pool_id']], 'version':1}
        assert client.put(base+'/portfolio', headers=h['reader'], json=body).status_code == 403
        result = client.put(base+'/portfolio', headers=h['admin'], json=body)
        assert result.status_code == 200, result.text
        view = client.get(base+'/inventory?entity=machines', headers=h['reader']).json()
        expected = {i.machine_id for i in model.installations if i.software_id==rhel['pool_id']}
        assert view['total'] == len(expected)
        assert {m['machine_id'] for m in view['rows']} == expected
        products = client.get(base+'/inventory/software', headers=h['reader']).json()
        assert [p['name'] for p in products] == ['Red Hat Enterprise Linux 9']
        windows = next(m.machine_id for m in model.machines if m.machine_id not in expected)
        hidden = client.get(base+'/inventory?entity=machines&detail='+windows, headers=h['reader']).json()
        assert hidden['rows'] == []
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline, None)
        else: app.dependency_overrides[get_pipeline] = previous


def test_unused_installations_paginate_complete_evidence_and_respect_scope(business):
    import json
    from datetime import datetime, timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    client, headers, base, store = business
    namespace = str(uuid4())
    ids = ['unused-a','unused-b','active','incomplete','wrong-period','other-pool']
    snapshot = InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock',
        machines=[{'machine_id':i,'name':i,'kind':'physical','operating_system':'Windows'} for i in ids],
        observations=[{'machine_id':i,'license_pool_id':'flex-adobe' if i == 'other-pool' else 'flex-cad','used':i == 'active'} for i in ids])
    publish_index(store,namespace,snapshot,'gold/enterprise/test/manifest.json')
    evidence = [{'machine_id':i,'license_pool_id':'flex-cad','active_days':1 if i == 'active' else 0,
                 'observed_days':364 if i == 'incomplete' else 365,'period_days':366 if i == 'wrong-period' else 365,
                 'complete_coverage':i != 'incomplete'} for i in [*ids,'removed-machine']]
    table = BytesIO(); pq.write_table(pa.Table.from_pylist(evidence),table)
    objects = {'gold/enterprise/test/manifest.json':json.dumps({'installation_usage':{'key':'report','detail_key':'details'}}).encode(),
               'report':json.dumps({'days':365,'period_start':'2025-09-12','period_end':'2026-09-11'}).encode(),
               'details':table.getvalue()}
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=SimpleNamespace(prefix=namespace,get_bytes=lambda key:objects[key]))
    try:
        path = base+'/inventory/installation-usage/machines?pool=flex-cad&limit=1'
        assert client.get(path).status_code == 401
        assert client.get(path,headers=headers['reader']).json()['rows'] == []
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET pool_ids=%s WHERE workspace_id=%s',(json.dumps(['flex-cad']),base.split('/')[-1]))
        response = client.get(path,headers=headers['reader'])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['total'] == 2
        assert [r['machine_id'] for r in result['rows']] == ['unused-a']
        assert client.get(path+'&offset=1',headers=headers['reader']).json()['rows'][0]['machine_id'] == 'unused-b'
        assert client.get(path+'&offset=2',headers=headers['reader']).json()['rows'] == []
        assert client.get(path.replace('flex-cad','flex-adobe'),headers=headers['reader']).json()['rows'] == []
        assert client.get(path.replace(base,'/api/v1/business/workspaces/unknown'),headers=headers['reader']).status_code == 404
        assert 'detail_key' not in result
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline,None)
        else: app.dependency_overrides[get_pipeline] = previous


def test_software_falls_back_to_silver_without_an_index(business, monkeypatch):
    monkeypatch.setattr("app.business.portfolio_service.read_summary", lambda p:p.run_analytics())
    import json
    from datetime import datetime, timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    client, headers, base, store = business
    snapshot = {'captured_at':datetime(2026,9,11,tzinfo=timezone.utc),'source':'digimon-mock',
        'machines':[{'machine_id':'linux','name':'Linux host','kind':'physical','operating_system':'RHEL'},
                    {'machine_id':'windows','name':'Windows host','kind':'physical','operating_system':'Windows'}]}
    buffer = BytesIO(); pq.write_table(pa.Table.from_pylist([snapshot]),buffer)
    key = 'silver/inventory/date=2026-09-11/snapshot.parquet'
    lake = SimpleNamespace(prefix=str(uuid4()),list_keys=lambda prefix:[key],get_bytes=lambda k:buffer.getvalue())
    previous = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: SimpleNamespace(store=lake,run_analytics=lambda:SimpleNamespace(trends=[]))
    try:
        path = base+'/inventory/software'
        assert client.get(path).status_code == 401
        assert client.get(path,headers=headers['reader']).json() == []
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET all_catalog=true WHERE workspace_id=%s',(base.split('/')[-1],))
        rows = client.get(path,headers=headers['reader']).json()
        assert {r['name'] for r in rows} == {'RHEL','Windows'}
        assert all(r['machines'] == 1 for r in rows)
        catalog = client.get('/api/v1/business/catalog',headers=headers['reader']).json()
        rhel = next(r['pool_id'] for r in catalog if r['name'] == 'RHEL')
        portfolio = client.get(base+'/portfolio',headers=headers['admin']).json()
        assert client.put(base+'/portfolio',headers=headers['admin'],json={'all_catalog':False,'pool_ids':[rhel],'version':portfolio['version']}).status_code == 200
        assert [r['name'] for r in client.get(path,headers=headers['reader']).json()] == ['RHEL']
        machines = client.get(base+'/inventory',headers=headers['reader']).json()
        assert [r['machine_id'] for r in machines['rows']] == ['linux']
        assert client.get(path.replace(base,'/api/v1/business/workspaces/missing'),headers=headers['reader']).status_code == 404
    finally:
        if previous is None: app.dependency_overrides.pop(get_pipeline,None)
        else: app.dependency_overrides[get_pipeline] = previous


def test_reindex_rejects_concurrent_usage_manifest_update(business):
    from datetime import datetime, timezone
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    _, _, _, store = business
    namespace = str(uuid4())
    snapshot = InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock')
    original = 'gold/enterprise/test/manifest.json'
    updated = 'gold/enterprise/test/manifest-with-usage.json'
    run = publish_index(store,namespace,snapshot,original)
    # Analyzer updates the same run while reindexing is reading its Parquet data.
    with store.connect() as db:
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s',(updated,run))
    with pytest.raises(RuntimeError,match='usage manifest changed'):
        publish_index(store,namespace,snapshot,original,expected_run=run,expected_manifest=original)
    with store.connect() as db:
        head = db.execute('SELECT r.id,r.manifest_key FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(namespace,)).fetchone()
        assert str(head['id']) == run
        assert head['manifest_key'] == updated
    replacement = publish_index(store,namespace,snapshot,updated,expected_run=run,expected_manifest=updated)
    assert replacement != run


def test_same_named_products_keep_identity_in_silver_and_index(business):
    import json
    from datetime import datetime, timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    client, headers, base, store = business
    model = InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock',
        products=[{'software_id':'product-a','name':'Same product','category':'application','license_pool_id':'pool-a'},
                  {'software_id':'product-b','name':'Same product','category':'application','license_pool_id':'pool-b'}],
        machines=[{'machine_id':'machine-a','name':'A','kind':'physical','operating_system':'Linux'},
                  {'machine_id':'machine-b','name':'B','kind':'physical','operating_system':'Linux'}],
        installations=[{'installation_id':'install-a','software_id':'product-a','machine_id':'machine-a'},
                       {'installation_id':'install-b','software_id':'product-b','machine_id':'machine-b'}],
        entitlements=[{'entitlement_id':'right-a','software_id':'product-a','metric':'device','quantity':3},
                      {'entitlement_id':'right-b','software_id':'product-b','metric':'device','quantity':9}])
    def parquet(rows):
        buffer=BytesIO();pq.write_table(pa.Table.from_pylist(rows),buffer);return buffer.getvalue()
    silver = 'silver/inventory/date=2026-09-11/snapshot.parquet'
    manifest = 'gold/enterprise/test/manifest.json'
    objects = {silver:parquet([model.model_dump(mode='json')]),
               'products':parquet([p.model_dump() for p in model.products]),
               'entitlements':parquet([r.model_dump() for r in model.entitlements]),
               manifest:json.dumps({'dimensions':{'products':{'key':'products'},'entitlements':{'key':'entitlements'}}}).encode()}
    namespace=str(uuid4())
    lake=SimpleNamespace(prefix=namespace,list_keys=lambda prefix:[silver],get_bytes=lambda key:objects[key])
    previous=app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline]=lambda:SimpleNamespace(store=lake,run_analytics=lambda:SimpleNamespace(trends=[]))
    try:
        for indexed in (False,True):
            if indexed:publish_index(store,namespace,model,manifest)
            with store.connect() as db:
                db.execute('UPDATE workspace_portfolios SET all_catalog=true WHERE workspace_id=%s',(base.split('/')[-1],))
            response=client.get(base+'/inventory/software',headers=headers['reader'])
            assert response.status_code==200,response.text
            rows={r['software_id']:r for r in response.json() if r['name']=='Same product'}
            assert set(rows)=={'product-a','product-b'}
            assert rows['product-a']['machines']==rows['product-b']['machines']==1
            assert rows['product-a']['entitlements'][0]['quantity']==3
            assert rows['product-b']['entitlements'][0]['quantity']==9
            with store.connect() as db:
                db.execute('UPDATE workspace_portfolios SET all_catalog=false,pool_ids=%s WHERE workspace_id=%s',(json.dumps(['pool-a']),base.split('/')[-1]))
            rows=client.get(base+'/inventory/software',headers=headers['reader']).json()
            assert [r['software_id'] for r in rows]==['product-a']
            assert rows[0]['entitlements']==[]
            for query in ('Same product','product-a','pool-a'):
                result=client.get(base+'/inventory',params={'q':query},headers=headers['reader']).json()
                assert [r['machine_id'] for r in result['rows']]==['machine-a']
            assert client.get(base+'/inventory',params={'q':'product-b'},headers=headers['reader']).json()['rows']==[]
    finally:
        if previous is None:app.dependency_overrides.pop(get_pipeline,None)
        else:app.dependency_overrides[get_pipeline]=previous


def test_non_pool_product_usage_can_be_examined_in_its_own_workspace(business):
    import json
    from datetime import datetime, timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.dependencies import get_pipeline
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    client,headers,base,store=business
    model=InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock',
        machines=[{'machine_id':'host','name':'Host','kind':'physical','operating_system':'RHEL'}],
        products=[{'software_id':'rhel','name':'RHEL','category':'operating_system'}],
        installations=[{'installation_id':'host:rhel','machine_id':'host','software_id':'rhel'}])
    namespace=str(uuid4());manifest='gold/enterprise/test/manifest.json'
    publish_index(store,namespace,model,manifest)
    def parquet(rows):
        buf=BytesIO();pq.write_table(pa.Table.from_pylist(rows),buf);return buf.getvalue()
    objects={manifest:json.dumps({'dimensions':{'products':{'key':'products'}},'installation_usage':{'key':'report','detail_key':'details'}}).encode(),
             'products':parquet([p.model_dump() for p in model.products]),
             'report':json.dumps({'days':365,'products':[{'software_id':'rhel','license_pool_id':None,'measurement':'system_uptime','installations_without_usage':1}]}).encode(),
             'details':parquet([{'software_id':'rhel','license_pool_id':None,'machine_id':'host','active_days':0,'observed_days':365,'period_days':365,'complete_coverage':True}])}
    previous=app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline]=lambda:SimpleNamespace(store=SimpleNamespace(prefix=namespace,get_bytes=lambda key:objects[key]))
    try:
        path=base+'/inventory/installation-usage'
        assert client.get(path,headers=headers['reader']).json()['products']==[]
        with store.connect() as db:
            db.execute('UPDATE workspace_portfolios SET pool_ids=%s WHERE workspace_id=%s',(json.dumps(['rhel']),base.split('/')[-1]))
        response=client.get(path,headers=headers['reader'])
        assert response.status_code==200,response.text
        assert response.json()['products'][0]['software_name']=='RHEL'
        details=client.get(path+'/machines?pool=rhel',headers=headers['reader'])
        assert details.status_code==200,details.text
        assert details.json()['total']==1
        assert details.json()['rows'][0]['machine_id']=='host'
        assert client.get(path+'/machines?pool=outside',headers=headers['reader']).json()['rows']==[]
    finally:
        if previous is None:app.dependency_overrides.pop(get_pipeline,None)
        else:app.dependency_overrides[get_pipeline]=previous


def test_product_usage_generation_preserves_legacy_report_and_publishes_after_validation(business, monkeypatch, tmp_path):
    import json
    from datetime import datetime,timezone
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.business.inventory_index import publish_index
    from app.models.inventory import InventorySnapshot
    from devtools.demo import seed_enterprise_product_usage as producer
    _,_,_,store=business
    objects={}
    class Lake:
        prefix=str(uuid4())
        def get_bytes(self,key):return objects[key]
        def list_keys(self,prefix):return [key for key in objects if key.startswith(prefix)]
        def put_json(self,key,value):objects[key]=json.dumps(value).encode()
        def put_parquet(self,key,rows):
            output=BytesIO();pq.write_table(rows if isinstance(rows,pa.Table) else pa.Table.from_pylist(rows),output);objects[key]=output.getvalue()
    lake=Lake()
    model=InventorySnapshot(captured_at=datetime.now(timezone.utc),source='digimon-mock',
        machines=[{'machine_id':'pc','name':'PC','kind':'physical','asset_type':'workstation','operating_system':'Windows'}],
        products=[{'software_id':'windows','name':'Windows','category':'operating_system'}, {'software_id':'cad','name':'CAD','category':'application','license_pool_id':'flex-cad'}],
        installations=[{'installation_id':'pc:windows','machine_id':'pc','software_id':'windows'},{'installation_id':'pc:cad','machine_id':'pc','software_id':'cad'}])
    from app.storage.delta_tables import DeltaTables
    from app.storage.table_reader import read_table
    lake.delta = DeltaTables(str(tmp_path))
    dims={}
    for name in ('machines','products','installations'):
        rows=[r.model_dump() for r in getattr(model,name)];lake.put_parquet(name,rows);dims[name]={'key':name,'rows':len(rows)}
    lake.put_parquet('legacy-detail',[{'machine_id':'pc','license_pool_id':'flex-cad','active_days':1,'observed_days':2,'period_days':2,'complete_coverage':True,'last_used_on':'2026-09-01'}])
    lake.put_json('legacy-report',{'days':2,'period_start':'2026-09-01','period_end':'2026-09-02','detail_key':'legacy-detail',
        'products':[{'license_pool_id':'flex-cad','installations_observed':1,'installations_active':1,'installations_without_usage':0,'installations_incomplete':0}]})
    original='gold/enterprise/test/manifest.json'
    lake.put_json(original,{'version':'test','dimensions':dims,'daily':[{'date':'2026-09-01'},{'date':'2026-09-02'}],
        'installation_usage':{'key':'legacy-report','detail_key':'legacy-detail'}})
    run=publish_index(store,lake.prefix,model,original)
    monkeypatch.setattr(producer,'get_settings',lambda:SimpleNamespace(sam_data_source='mock',database_url='unused'))
    monkeypatch.setattr(producer,'get_pipeline',lambda:SimpleNamespace(store=lake))
    monkeypatch.setattr(producer,'BusinessStore',lambda _:store)
    producer.main()
    with store.connect() as db:
        active=db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s',(run,)).fetchone()['manifest_key']
    updated=json.loads(objects[active]);report=json.loads(objects[updated['installation_usage']['key']])
    assert updated['dimensions']==dims
    assert updated['product_usage_observations']==2
    assert len(updated['product_usage_daily'])==2
    assert {r['software_id'] for r in report['products']}=={'cad','windows'}
    old=next(r for r in report['products'] if r['software_id']=='cad')
    assert old['installations_active']==1
    details=read_table(lake, updated['installation_usage']['detail_key']).to_pylist()
    assert len(details)==2
    assert next(r for r in details if r['software_id']=='cad')['active_days']==1
    producer.main()  # Reuse the persisted daily payloads, without duplicating legacy products.
    with store.connect() as db:
        latest=db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s',(run,)).fetchone()['manifest_key']
    assert latest!=active  # Published manifests are immutable.
    latest_manifest=json.loads(objects[latest])
    assert len(json.loads(objects[latest_manifest['installation_usage']['key']])['products'])==2
    put_json=lake.put_json
    def concurrent_publish(key,value):
        put_json(key,value)
        if key.endswith('/manifest.json'):
            put_json('concurrent-manifest',value)
            with store.connect() as db:
                db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s',('concurrent-manifest',run))
    monkeypatch.setattr(lake,'put_json',concurrent_publish)
    with pytest.raises(RuntimeError,match='Analysis changed'):
        producer.main()
    with store.connect() as db:
        assert db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s',(run,)).fetchone()['manifest_key']=='concurrent-manifest'
