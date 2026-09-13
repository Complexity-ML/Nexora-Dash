import csv
from datetime import datetime,timezone
from io import StringIO
from test_collection_runner import context
from test_bi_reader_service import client
from app.connectors.demo import snapshot
from app.collection.runner import CollectionRunner
from app.bi.catalog import prepare_license_snapshot,publish_snapshot
from app.bi.auth import issue_reader
from app.bi import reader_service as api


def test_license_export_keeps_units_nulls_identity_and_subsidiary(context,monkeypatch):
    pipeline,journal=context
    raw=snapshot(datetime(2026,1,1,tzinfo=timezone.utc))
    raw['inventory']['observations']=[]
    raw['inventory']['products']=[{'software_id':p,'name':'Same display name','category':'application'} for p in ('first','second')]
    raw['inventory']['entitlements']=[
        {'entitlement_id':'core','software_id':'first','metric':'core','quantity':7,'subsidiary_id':'demo-subsidiary-1'},
        {'entitlement_id':'host','software_id':'first','metric':'host','quantity':3,'subsidiary_id':'demo-subsidiary-1'},
        {'entitlement_id':'unknown','software_id':'first','metric':'device','quantity':None,'subsidiary_id':'demo-subsidiary-1'},
        {'entitlement_id':'global','software_id':'first','metric':'device','quantity':100},
        {'entitlement_id':'other','software_id':'first','metric':'device','quantity':99,'subsidiary_id':'demo-subsidiary-2'},
        {'entitlement_id':'same-name','software_id':'second','metric':'device','quantity':80,'subsidiary_id':'demo-subsidiary-1'}]
    CollectionRunner(pipeline,journal).run(raw,source='digimon-mock',scope='group',snapshot_id='licenses',source_revision='1')
    candidate=prepare_license_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='licenses',
        software_ids=['first'],subsidiary_ids=['demo-subsidiary-1'])
    publish_snapshot(pipeline.store,journal,candidate['snapshot_id'],expected_snapshot=None)
    credential=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='licenses')
    http=client(context,monkeypatch)
    monkeypatch.setattr(api,'bi_lake',lambda _:pipeline.store)
    response=http.get('/api/bi/license-entitlements.csv?snapshot_id='+candidate['snapshot_id'],
        headers={'Authorization':'Bearer '+credential['token']})
    assert response.status_code == 200
    rows={r['entitlement_id']:r for r in csv.DictReader(StringIO(response.text))}
    assert set(rows) == {'core','host','unknown'}
    assert rows['core']['quantity'] == '7' and rows['core']['metric'] == 'core'
    assert rows['host']['quantity'] == '3' and rows['host']['metric'] == 'host'
    assert rows['unknown']['quantity'] == ''
    import json
    manifest=json.loads(pipeline.store.get_bytes(candidate['manifest_key']))
    assert manifest['excluded_global_entitlements'] == 1

    # A distinct, explicitly authorized selection can expose global rows only.
    from app.bi.license_snapshot import export_license_snapshot
    from app.bi.download import snapshot_csv
    global_export=export_license_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',
        audience='global-licenses',software_ids=['first'],subsidiary_ids=[],include_global=True)
    global_rows=list(csv.DictReader(StringIO(snapshot_csv(pipeline.store,global_export,'global-licenses','license_entitlements'))))
    assert len(global_rows) == 1 and global_rows[0]['entitlement_id'] == 'global'
    assert global_rows[0]['quantity'] == '100' and global_rows[0]['subsidiary_id'] == ''
    assert global_export['manifest']['includes_global_entitlements'] is True
    assert global_export['manifest']['excluded_global_entitlements'] == 0


def test_global_selection_requires_explicit_boolean():
    import pytest
    from app.bi.license_snapshot import export_license_snapshot
    for value in ('false',1,None):
        with pytest.raises(ValueError,match='boolean'):
            export_license_snapshot(None,None,source='test',scope='test',audience='licenses',
                software_ids=['product'],subsidiary_ids=[],include_global=value)
