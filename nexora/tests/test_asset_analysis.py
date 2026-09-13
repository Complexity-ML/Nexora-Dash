from types import SimpleNamespace
import json
import pyarrow as pa
from app.business import asset_analysis as service


def test_activity_groups_do_not_turn_missing_days_into_inactivity():
    rows=[dict(active_days=a,observed_days=o,period_days=10,complete_coverage=c) for a,o,c in [(2,4,False),(0,4,False),(0,10,True)]]
    assert service.activity_groups(rows)=={'active':1,'unknown':1,'inactive':1}


def test_product_projection_filters_stable_id_and_uses_pinned_references(monkeypatch):
    product={'software_id':'p1','name':'Same name','license_pool_id':None}
    manifest={'dimensions':{k:{'key':k,'version':7} for k in ['installations','machines','sites','subsidiaries']},'installation_usage':{'key':'report','detail_key':{'key':'evidence','version':7}}}
    monkeypatch.setattr(service,'_publication',lambda *args:(manifest,{'p1':product}))
    rows={
      'evidence':[dict(software_id='p1',machine_id='m1',active_days=3,observed_days=10,period_days=10,complete_coverage=True),dict(software_id='p2',machine_id='m2',active_days=0,observed_days=10,period_days=10,complete_coverage=True)],
      'installations':[dict(software_id='p1',machine_id='m1'),dict(software_id='p2',machine_id='m2')],
      'machines':[dict(machine_id='m1',site_id='s1'),dict(machine_id='m2',site_id='s2')],
      'sites':[dict(site_id='s1',subsidiary_id='a'),dict(site_id='s2',subsidiary_id='b')],
      'subsidiaries':[dict(subsidiary_id='a',name='Selected'),dict(subsidiary_id='b',name='Other')]}
    calls=[]
    def read(lake,ref,columns=None,filters=None):
        assert ref['version']==7
        calls.append((ref['key'],filters))
        values=rows[ref['key']]
        for key,op,value in filters or []:
            values=[r for r in values if (r[key] in value if op=='in' else r[key]==value)]
        return pa.Table.from_pylist(values)
    monkeypatch.setattr(service,'read_table',read)
    report={'products':[product],'days':10,'period_start':'2026-01-01','period_end':'2026-01-10'}
    pipeline=SimpleNamespace(store=SimpleNamespace(get_bytes=lambda key:json.dumps(report).encode()))
    result=service.product_analysis('w','p1',pipeline=pipeline)
    assert result['footprint']==[('Selected',1)]
    assert result['frequency']==[(3,1)]
    assert result['activity']=={'active':1}
    assert ('evidence',[('software_id','=','p1')]) in calls
    before=len(calls)
    assert service.product_analysis('w','p2',pipeline=pipeline)=={'available':False}
    assert len(calls)==before
