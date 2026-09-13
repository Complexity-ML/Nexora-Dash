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
