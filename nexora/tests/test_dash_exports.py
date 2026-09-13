import csv
from io import StringIO
import pytest
from app.dash_ui.exports import export_table, csv_document
from app.business.errors import BusinessError


class Context:
    wid='selected-space'
    def call(self, function, wid, **kwargs):
        assert wid==self.wid and kwargs['lake'] is True
        return [
            {'software_id':'a','license_pool_id':'flex-cad','name':'CAD','machines':30,'entitlements':[
                {'metric':'concurrent','quantity':8,'subsidiary_id':'one','subsidiary_name':'Filiale 1'},
                {'metric':'core','quantity':16,'subsidiary_id':'two','subsidiary_name':'Filiale 2'},
                {'metric':'concurrent','quantity':None,'subsidiary_id':'three'}]},
            {'software_id':'b','name':'Runtime','machines':10,'entitlements':[{'metric':'unmetered','quantity':None}]},
            {'software_id':'c','name':'Unknown','machines':None,'entitlements':[]}]


def parse(result):
    return list(csv.reader(StringIO(result['content'].lstrip('\ufeff')),delimiter=';'))


def test_licenses_export_preserves_units_missing_and_unmetered():
    data=parse(export_table(Context(),'licenses',{}))
    assert data[1][4:]==['8','usages simultanés','Reçue']
    assert data[2][4:]==['16','cœurs','Reçue']
    assert data[3][4:]==['','usages simultanés','Remontée manquante']
    assert data[4][4:]==['','Sans décompte','Sans décompte']
    assert data[5][-1]=='Non reçue dans ce périmètre'


def test_catalog_export_pool_search_and_all_filtered_pages():
    data=parse(export_table(Context(),'software',{'q':'FLEX-CAD','offset':'25'}))
    assert data[1:]==[['CAD','a','flex-cad','30']]
    assert len(parse(export_table(Context(),'software',{'offset':'25'})))==4
    assert len(parse(export_table(Context(),'licenses',{'product':'not-in-scope'})))==1
    with pytest.raises(BusinessError): export_table(Context(),'settings',{})


def test_csv_source_text_cannot_become_a_formula():
    result=csv_document(['Name','Number'],[[' =HYPERLINK("bad")',-2],['@formula',0],['Normal; quoted',None]])
    rows=list(csv.reader(StringIO(result.lstrip('\ufeff')),delimiter=';'))
    assert rows[1]==['\' =HYPERLINK("bad")','-2']
    assert rows[2]==["'@formula",'0']
    assert rows[3]==['Normal; quoted','']


def test_analysis_export_keeps_unknown_cost_distinct_from_zero():
    from types import SimpleNamespace
    from app.business import workspace_service
    class AnalysisContext:
        wid='space'
        def summary(self):
            return SimpleNamespace(inactive=[SimpleNamespace(software_name=name,license_pool_id=name,recovery_potential=4) for name in ('Missing','Free','Paid')])
        def call(self, function, wid):
            assert function is workspace_service.costs and wid==self.wid
            return [{'pool_id':'Free','annual_unit_cents':0},{'pool_id':'Paid','annual_unit_cents':125}]
    rows=parse(export_table(AnalysisContext(),'savings',{'view':'pools'}))
    assert rows[1][3:5]==['','']
    assert rows[2][3:5]==['0.0','0.0']
    assert rows[3][3:5]==['1.25','5.0']
    assert all(r[-1]=='Simulation, sans gain réalisé' for r in rows[1:])


def test_installation_analysis_export_preserves_coverage_and_access_denial():
    from app.business import inventory_service
    class AnalysisContext:
        wid='scoped-space'
        def call(self, function, wid, **kwargs):
            assert function is inventory_service.installation_usage and wid==self.wid and kwargs=={'lake':True}
            return {'period_start':'2026-01-01','period_end':'2026-01-31','days':31,'products':[
                {'software_name':'OS','software_id':'os','license_pool_id':None,'installations_observed':10,
                 'installations_active':7,'installations_without_usage':1,'installations_incomplete':3}]}
    rows=parse(export_table(AnalysisContext(),'savings',{}))
    assert rows[1]==['OS','os','','10','7','1','3','2026-01-01','2026-01-31','31']
    assert len(parse(export_table(AnalysisContext(),'savings',{'product':'outside'})))==1
    class Revoked(AnalysisContext):
        def call(self,*args,**kwargs): raise BusinessError(403,'Revoked')
    with pytest.raises(BusinessError): export_table(Revoked(),'savings',{})
