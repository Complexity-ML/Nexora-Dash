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
