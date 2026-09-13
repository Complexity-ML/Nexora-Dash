import json
from types import SimpleNamespace
import pytest
from plotly.utils import PlotlyJSONEncoder
from app.business.errors import BusinessError
from app.dash_ui.pages import software


def test_catalog_remains_available_without_published_analytics(monkeypatch):
    product={'software_id':'rhel','name':'RHEL','machines':2,'entitlements':[]}
    monkeypatch.setattr(software,'products',lambda *args:[product])
    def unavailable(): raise BusinessError(409,'No published Gold')
    ctx=SimpleNamespace(summary=unavailable,wid='workspace')
    rendered=json.dumps(software.layout(ctx,{}),cls=PlotlyJSONEncoder)
    assert 'RHEL' in rendered and 'Inventaire des installations' in rendered
    def denied(): raise BusinessError(403,'Access denied')
    ctx.summary=denied
    with pytest.raises(BusinessError) as error:software.layout(ctx,{})
    assert error.value.status_code==403


def test_license_list_is_paginated_and_details_respect_scope(monkeypatch):
    items=[{'software_id':str(i),'name':f'Product {i:03}', 'entitlements':[
        {'metric':'device','quantity':1,'subsidiary_name':'Scoped subsidiary'}]} for i in range(30)]
    monkeypatch.setattr(software,'products',lambda *args:items)
    ctx=SimpleNamespace()
    first=json.dumps(software.licenses(ctx,{}),cls=PlotlyJSONEncoder)
    assert 'Product 024' in first and 'Product 025' not in first
    assert 'Scoped subsidiary' not in first
    second=json.dumps(software.licenses(ctx,{'offset':'25'}),cls=PlotlyJSONEncoder)
    assert 'Product 025' in second and 'offset=0' in second
    detail=json.dumps(software.licenses(ctx,{'product':'1'}),cls=PlotlyJSONEncoder)
    assert 'Scoped subsidiary' in detail
    unavailable=json.dumps(software.licenses(ctx,{'product':'outside'}),cls=PlotlyJSONEncoder)
    assert 'Scoped subsidiary' not in unavailable


def test_overview_shows_inventory_when_gold_is_not_published():
    from app.dash_ui.pages import overview
    def unavailable():raise BusinessError(409,'No Gold')
    ctx=SimpleNamespace(wid='workspace',summary=unavailable,
        call=lambda *args,**kwargs:{'counts':{'machines':12,'users':8,'sites':2}})
    content=json.dumps(overview.layout(ctx,{}),cls=PlotlyJSONEncoder)
    assert '12' in content and 'Explorer le parc' in content
    assert 'pas encore publi' in content


def test_product_without_pool_has_analysis_on_the_same_page():
    data={'available':True,'period_start':'2026-01-01','period_end':'2026-01-10',
          'analyzed':3,'activity':{'active':1,'inactive':1,'unknown':1},
          'footprint':[('Filiale',3)],'frequency':[(0,1),(3,1)],
          'coverage':[{'observed':10,'expected':10,'count':2},{'observed':4,'expected':10,'count':1}]}
    ctx=SimpleNamespace(wid='workspace',call=lambda *args,**kwargs:data)
    p={'software_id':'firefox','name':'Firefox','machines':3,'entitlements':[{'metric':'unmetered'}]}
    page=software.detail(ctx,p,None)
    rendered=json.dumps(page,cls=PlotlyJSONEncoder)
    assert rendered.count('"type": "Graph"')==4
    assert '#/savings' not in rendered
    assert 'Sans d' not in rendered  # no repeated per-subsidiary unmetered table
    assert '2026-01-10' in rendered


def test_overview_compares_in_place_and_preserves_scope():
    from app.dash_ui.pages import overview
    from app.business import exploration
    seen=[]
    def call(fn,*args,**kwargs):
        if fn is exploration.aggregate:
            seen.append(kwargs.get('filters'))
            return {'rows':[{'key0':'s1','label0':'Filiale A','key1':'Linux','label1':'Linux','value':10}], 'groups':1}
        return {'counts':{'machines':10,'users':8,'sites':1}}
    ctx=SimpleNamespace(wid='w',call=call,summary=lambda:SimpleNamespace(inactive=[],pools_total=0,trends=[],recovery_potential=0,pools_at_risk=0))
    page=overview.layout(ctx,{'subsidiary':'s1','comparison':'share'})
    rendered=json.dumps(page,cls=PlotlyJSONEncoder)
    assert seen==[{'subsidiary':'s1'}]*3
    assert 'Comprendre les usages' not in rendered
    assert '#/overview?subsidiary=s1' in rendered
    assert '"barnorm": "percent"' in rendered
