from types import SimpleNamespace
from bi_scenarios import ReaderClient
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.bi import reader_service as api
from app.bi.auth import issue_reader, revoke_reader
from app.bi.catalog import prepare_pool_snapshot, publish_snapshot


def client(context, monkeypatch, enabled=True):
    pipeline,journal=context
    monkeypatch.setattr(api,'get_settings',lambda:SimpleNamespace(bi_enabled=enabled,
        bi_namespace=pipeline.store.prefix,database_url=journal.store.url))
    return ReaderClient()


def test_disabled_route_does_not_open_database(context, monkeypatch):
    http=client(context,monkeypatch,False)
    monkeypatch.setattr(api,'BusinessStore',lambda _: (_ for _ in ()).throw(AssertionError('DB accessed')))
    assert http.get('/api/bi/publication').status_code == 404


def test_api_uses_bearer_audience_and_refuses_revocation(context, monkeypatch):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    prepared=prepare_pool_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])
    publish_snapshot(pipeline.store,journal,prepared['snapshot_id'],expected_snapshot=None)
    allowed=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    other=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='other')
    http=client(context,monkeypatch)
    assert http.get('/api/bi/publication').status_code == 401
    assert http.get('/api/bi/publication',headers={'Authorization':'Bearer bad'}).status_code == 401
    response=http.get('/api/bi/publication',headers={'Authorization':'Bearer '+allowed['token']})
    assert response.status_code == 200 and response.json()['snapshot_id'] == prepared['snapshot_id']
    assert response.headers['cache-control'] == 'no-store'
    # A query parameter cannot override the audience carried by the token.
    assert http.get('/api/bi/publication?audience=cad',headers={'Authorization':'Bearer '+other['token']}).status_code == 404
    revoke_reader(journal.store,namespace=pipeline.store.prefix,reader_id=allowed['id'])
    response=http.get('/api/bi/publication',headers={'Authorization':'Bearer '+allowed['token']})
    assert response.status_code == 401 and response.headers['www-authenticate'] == 'Bearer'


def test_csv_is_pinned_and_scoped(context, monkeypatch):
    import csv
    from io import StringIO
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    first=prepare_pool_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])
    publish_snapshot(pipeline.store,journal,first['snapshot_id'],expected_snapshot=None)
    allowed=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    other=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='other')
    http=client(context,monkeypatch)
    monkeypatch.setattr(api,'bi_lake',lambda _:pipeline.store)
    url='/api/bi/pool-usage.csv?snapshot_id='+first['snapshot_id']
    headers={'Authorization':'Bearer '+allowed['token']}
    assert http.get(url).status_code == 401
    assert http.get(url,headers={'Authorization':'Bearer '+other['token']}).status_code == 404
    response=http.get(url,headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    from hashlib import sha256
    assert response.headers['x-nexora-snapshot-id'] == first['snapshot_id']
    assert response.headers['x-nexora-content-sha256'] == sha256(response.content).hexdigest()
    rows=list(csv.DictReader(StringIO(response.text)))
    assert len(rows) == 1 and rows[0]['license_pool_id'] == 'flex-cad'
    second=prepare_pool_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])
    publish_snapshot(pipeline.store,journal,second['snapshot_id'],expected_snapshot=first['snapshot_id'])
    assert http.get(url,headers=headers).status_code == 409
    revoke_reader(journal.store,namespace=pipeline.store.prefix,reader_id=allowed['id'])
    assert http.get(url,headers=headers).status_code == 401


def test_csv_rejects_manifest_corruption(context, monkeypatch):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    prepared=prepare_pool_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])
    publish_snapshot(pipeline.store,journal,prepared['snapshot_id'],expected_snapshot=None)
    allowed=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    pipeline.store.put_json(prepared['manifest_key'],{'sensitive':'must not leak'})
    http=client(context,monkeypatch)
    monkeypatch.setattr(api,'bi_lake',lambda _:pipeline.store)
    response=http.get('/api/bi/pool-usage.csv?snapshot_id='+prepared['snapshot_id'],
                      headers={'Authorization':'Bearer '+allowed['token']})
    assert response.status_code == 503 and 'sensitive' not in response.text


def test_inventory_csv_scopes_subsidiaries_and_refuses_pool_route(context,monkeypatch):
    import csv
    from io import StringIO
    from app.collection.reader import PublishedCollection
    from app.bi.catalog import prepare_inventory_snapshot
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    inventory=PublishedCollection(pipeline.store,journal,'digimon-mock','group').inventory()
    chosen=inventory.sites[0].subsidiary_id
    sites={s.site_id for s in inventory.sites if s.subsidiary_id==chosen}
    candidate=prepare_inventory_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',
        audience='inventory',subsidiary_ids=[chosen])
    publish_snapshot(pipeline.store,journal,candidate['snapshot_id'],expected_snapshot=None)
    credential=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='inventory')
    http=client(context,monkeypatch)
    monkeypatch.setattr(api,'bi_lake',lambda _:pipeline.store)
    headers={'Authorization':'Bearer '+credential['token']}
    query='?snapshot_id='+candidate['snapshot_id']
    assert http.get('/api/bi/inventory-counts.csv'+query).status_code == 401
    response=http.get('/api/bi/inventory-counts.csv'+query,headers=headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    rows=list(csv.DictReader(StringIO(response.text)))
    assert {r['subsidiary_id'] for r in rows} == {chosen}
    assert sum(int(r['machines']) for r in rows) == sum(m.site_id in sites for m in inventory.machines)
    assert http.get('/api/bi/pool-usage.csv'+query,headers=headers).status_code == 404


def test_description_exposes_schema_without_storage_paths(context,monkeypatch):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    candidate=prepare_pool_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])
    publish_snapshot(pipeline.store,journal,candidate['snapshot_id'],expected_snapshot=None)
    credential=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    http=client(context,monkeypatch)
    monkeypatch.setattr(api,'bi_lake',lambda _:pipeline.store)
    query='?snapshot_id='+candidate['snapshot_id']
    assert http.get('/api/bi/description'+query).status_code == 401
    result=http.get('/api/bi/description'+query,headers={'Authorization':'Bearer '+credential['token']})
    assert result.status_code == 200
    body=result.json()
    assert body['pool_ids'] == ['flex-cad'] and body['rows'] == 1
    assert body['tables']['pool_usage']['columns'][0] == {'name':'day','type':'date32[day]'}
    assert 'gold/' not in result.text and 'silver/' not in result.text
    assert result.headers['cache-control'] == 'no-store'
