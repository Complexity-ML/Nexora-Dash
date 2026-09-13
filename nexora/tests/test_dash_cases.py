from types import SimpleNamespace
import pytest
from app.business.errors import BusinessError
from app.dash_ui.pages import cases


def product_field(component):
    if getattr(component, 'id', None) == {'type':'field','key':'case-product'}:
        return component
    children = getattr(component, 'children', None)
    for child in children if isinstance(children, list) else [children]:
        if child is not None and not isinstance(child, (str, int)):
            result = product_field(child)
            if result is not None:
                return result


def test_case_products_include_scoped_capacity_without_installations(monkeypatch):
    monkeypatch.setattr(cases, 'products', lambda *args: [{'software_id':'sw-cad','license_pool_id':'cad','name':'CAD'}])
    ctx = SimpleNamespace(wid='space', writable=True, call=lambda *args: [],
        summary=lambda:SimpleNamespace(trends=[SimpleNamespace(license_pool_id=key,software_name=key) for key in ['cad','pool-only']]))
    field = product_field(cases.layout(ctx, {'pool':'pool-only'}))
    assert field.options == [{'label':'CAD','value':'cad'},{'label':'pool-only','value':'pool-only'}]
    assert field.value == 'pool-only'


def test_case_products_without_gold_and_access_errors(monkeypatch):
    monkeypatch.setattr(cases, 'products', lambda *args: [{'software_id':'os','name':'Operating system'}])
    def missing(): raise BusinessError(409, 'No publication')
    ctx = SimpleNamespace(wid='space', writable=True, call=lambda *args: [], summary=missing)
    assert product_field(cases.layout(ctx, {})).value == 'os'
    def forbidden(): raise BusinessError(403, 'Access revoked')
    ctx.summary = forbidden
    with pytest.raises(BusinessError, match='Access revoked'):
        cases.layout(ctx, {})


def test_case_creation_uses_same_scoped_subjects_as_form(monkeypatch):
    from app.dash_ui import actions
    from app.business import workspace_service
    monkeypatch.setattr(cases, 'products', lambda *args: [])
    saved=[]
    def call(function, wid, body):
        assert function is workspace_service.create_case and wid=='space'
        saved.append(body)
        return {'id':'created'}
    ctx=SimpleNamespace(wid='space',call=call,summary=lambda:SimpleNamespace(trends=[SimpleNamespace(license_pool_id='cad',software_name='CAD')]))
    monkeypatch.setattr(actions,'current_context',lambda:ctx)
    values={'case-product':'cad','case-quantity':10,'case-evidence':'QA'}
    assert actions.execute('case-create',values)==('Dossier créé.','#/cases?id=created')
    assert saved[0].pool_id=='cad' and saved[0].title=='Examen CAD'
    values['case-product']='outside'
    with pytest.raises(BusinessError):actions.execute('case-create',values)
    assert len(saved)==1
