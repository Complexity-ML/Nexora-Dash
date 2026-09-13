"""Dash session boundaries and callbacks exercise real shared business services."""
import json
import os
import secrets
from uuid import uuid4
import pytest
from app.business.store import BusinessStore
from app.business import workspace_service as service
from app.dash_ui.app import create_app


def pattern(value): return json.dumps(value,sort_keys=True,separators=(',',':'))


@pytest.fixture
def dash_context():
    url=os.environ.get('BUSINESS_TEST_DATABASE_URL')
    if not url: pytest.skip('Requires isolated business DB')
    store=BusinessStore(url)
    password=secrets.token_urlsafe(24)
    store.seed_demo(password)
    app=create_app(testing=True,store=store)
    return app,store,password


def command(app,client,name,fields,origin='http://localhost'):
    key=next(k for k in app.callback_map if 'message.children' in k)
    action={'type':'action','name':name}
    ids=[{'type':'field','key':k} for k in fields]
    state=[{'id':pattern({'type':'action','name':['ALL']}),'property':'id','value':[action]},
        {'id':pattern({'type':'field','key':['ALL']}),'property':'value','value':list(fields.values())},
        {'id':pattern({'type':'field','key':['ALL']}),'property':'id','value':ids},
        {'id':'revision','property':'data','value':0}]
    return client.post('/_dash-update-component',json={'output':key,
        'outputs':[{'id':'message','property':'children'},{'id':'revision','property':'data'},{'id':'location','property':'hash'}],
        'inputs':[{'id':pattern({'type':'action','name':['ALL']}),'property':'n_clicks','value':[1]}],
        'state':state,'changedPropIds':[pattern(action)+'.n_clicks']},headers={'Origin':origin})


def render(client,page='settings'):
    return client.post('/_dash-update-component',json={'output':'shell.children','outputs':{'id':'shell','property':'children'},
        'inputs':[{'id':'location','property':'hash','value':'#/'+page},{'id':'revision','property':'data','value':0}],
        'state':[],'changedPropIds':['location.hash']},headers={'Origin':'http://localhost'})


def login(app,client,password,role='admin'):
    response=command(app,client,'login',{'email':role+'@sam.demo','password':password})
    assert response.status_code==200,response.text
    assert response.json['response']['message']['children']=='Connexion établie.',response.json


def test_dash_exposes_no_rest_and_anonymous_layout_contains_no_data(dash_context):
    app,store,password=dash_context
    client=app.server.test_client()
    assert not any(str(rule).startswith('/api/') for rule in app.server.url_map.iter_rules())
    response=render(client)
    assert response.status_code==200
    assert 'Votre espace' in response.text and 'admin@sam.demo' not in response.text
    assert 'workspaces' not in client.get('/_dash-layout').text


def test_cross_origin_commands_and_login_csrf_rejected(dash_context):
    app,store,password=dash_context
    client=app.server.test_client()
    for origin in ('https://untrusted.example','null',''):
        assert command(app,client,'login',{'email':'admin@sam.demo','password':password},origin).status_code==403
    with client.session_transaction() as session: assert 'token' not in session


def test_sessions_roles_and_shared_note_erasure_without_rest(dash_context):
    app,store,password=dash_context
    admin=app.server.test_client();reader=app.server.test_client()
    login(app,admin,password);login(app,reader,password,'reader')
    with admin.session_transaction() as session:
        token=session['token'];user=store.user_for_token(token)
        space=service.create_workspace(service.Name(name='Dash test '+str(uuid4())),user,store)
        session['workspace']=space['id']
    service.set_member(space['id'],service.Member(email='reader@sam.demo',role='reader'),user,store)
    with reader.session_transaction() as session: session['workspace']=space['id']
    denied=command(app,reader,'workspace-save',{'workspace-name':'Forbidden'})
    assert 'Droits insuffisants' in denied.json['response']['message']['children']
    assert command(app,admin,'workspace-save',{'workspace-name':'Renamed Dash test'}).status_code==200
    assert 'Renamed Dash test' in render(reader).text
    case=service.create_case(space['id'],service.CaseCreate(pool_id='demo-product',title='Analysis',quantity=1,evidence='Test only'),user,store)
    assert command(app,admin,'note-create',{'case-id':case['id'],'new-note':'A note'}).status_code==200
    note=service.detail(space['id'],case['id'],user,store)['events'][-1]
    fields={'case-id':case['id'],'note-version:'+str(note['id']):note['id'],'note-text:'+str(note['id']):'Updated note'}
    command(app,admin,'note-edit:'+str(note['id']),fields)
    detail=service.detail(space['id'],case['id'],user,store)
    projected=next(e['comment'] for e in detail['events'] if e.get('comment'))
    assert projected['text']=='Updated note'
    fields['note-version:'+str(note['id'])]=projected['version']
    command(app,admin,'note-delete:'+str(note['id']),fields)
    assert 'Updated note' not in render(admin,'cases?id='+case['id']).text
    command(app,admin,'logout',{})
    assert store.user_for_token(token) is None
    assert 'Se connecter' in render(admin).text


def test_membership_revocation_cannot_be_bypassed_by_forged_callback(dash_context):
    app,store,password=dash_context
    client=app.server.test_client();login(app,client,password,'analyst')
    with client.session_transaction() as session:
        user=store.user_for_token(session['token'])
        space=service.create_workspace(service.Name(name='Temporary scope'),user,store)
        session['workspace']=space['id']
    with store.connect() as db: db.execute('DELETE FROM members WHERE workspace_id=%s',(space['id'],))
    response=command(app,client,'workspace-save',{'workspace-name':'Must not persist'})
    assert 'plus accessible' in response.json['response']['message']['children']
    with store.connect() as db:
        assert db.execute('SELECT name FROM workspaces WHERE id=%s',(space['id'],)).fetchone()['name']=='Temporary scope'


def test_cookie_flags_and_tokens_never_in_callback_response(dash_context):
    app,store,password=dash_context
    client=app.server.test_client();login(app,client,password)
    with client.session_transaction() as session: token=session['token']
    assert token not in render(client).text
    assert app.server.config['SESSION_COOKIE_HTTPONLY']
    assert app.server.config['SESSION_COOKIE_SAMESITE']=='Lax'


def test_member_forms_use_independent_account_fields(dash_context):
    app,store,password=dash_context
    client=app.server.test_client();login(app,client,password)
    with client.session_transaction() as session:
        user=store.user_for_token(session['token'])
        space=service.create_workspace(service.Name(name='Member forms'),user,store)
        session['workspace']=space['id']
    email='dash-'+str(uuid4())+'@example.invalid'
    response=command(app,client,'account-create',{
        'account-name':'New member','account-email':email,'account-role':'reader',
        'account-password':secrets.token_urlsafe(24),
        'member-email':'unrelated@example.invalid','member-role':'admin'})
    assert response.status_code==200
    members=service.members(space['id'],user,store)
    created=next(m for m in members if m['email']==email)
    assert created['role']=='reader'
    assert not any(m['email']=='unrelated@example.invalid' for m in members)
    response=command(app,client,'member-add',{'member-email':'analyst@sam.demo','member-role':'analyst'})
    assert response.status_code==200
    assert any(m['email']=='analyst@sam.demo' and m['role']=='analyst' for m in service.members(space['id'],user,store))


def test_plotly_click_navigates_only_to_allowed_detail_pages(dash_context):
    app,_,_=dash_context
    client=app.server.test_client()
    key=next(k for k,v in app.callback_map.items() if any(i['id']==pattern({'type':'insight-chart','key':['ALL']}) for i in v['inputs']))
    identifier={'type':'insight-chart','key':'pressure'}
    def click(target):
        return client.post('/_dash-update-component',json={
            'output':key,'outputs':{'id':'location','property':'hash'},
            'inputs':[{'id':pattern({'type':'insight-chart','key':['ALL']}),'property':'clickData','value':[{'points':[{'customdata':target}]}]}],
            'state':[{'id':pattern({'type':'insight-chart','key':['ALL']}),'property':'id','value':[identifier]}],
            'changedPropIds':[pattern(identifier)+'.clickData']},headers={'Origin':'http://localhost'})
    response=click('#/software?pool=flex-cad')
    assert response.status_code==200
    assert response.json['response']['location']['hash']=='#/software?pool=flex-cad'
    assert click('https://example.invalid').status_code==204
    assert click('#/settings').status_code==204
