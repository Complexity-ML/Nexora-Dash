"""Reference scenarios and atomic activation, using the dedicated business DB."""
import asyncio
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_business import business, new_case
from app.business import demo_service as reset
from app.analytics import SparkAnalytics
from app.connectors.digimon import MockDigimonConnector
from app.services.pipeline import SamPipeline
from test_demo import MemoryStore


def test_reference_year_real_parquet_and_spark(tmp_path):
    objects = MemoryStore()
    manifest = asyncio.run(SamPipeline(MockDigimonConnector(), objects, None).generate_demo_history(365, reset.REFERENCE_END))
    rows = [row for key, values in objects.objects.items() if key.startswith('silver/usage/') for row in values]
    assert manifest['usage_rows'] == len(rows) == 4380
    path = tmp_path / 'reference.parquet'
    pq.write_table(pa.Table.from_pylist(rows), path)
    summary = SparkAnalytics('local[1]', .35, .1).compute([str(path)])
    assert reset.verify_reference(summary)['checks'] == 'passed'
    from app.storage.delta_tables import DeltaTables
    delta = DeltaTables(str(tmp_path / 'delta'))
    ref = delta.replace('silver/pool_usage', pa.Table.from_pylist(rows))
    replay = SparkAnalytics('local[1]', .35, .1).compute_table(delta.read(ref))
    assert replay.model_dump(exclude={'generated_at'}) == summary.model_dump(exclude={'generated_at'})
    summary.total_capacity += 1
    with pytest.raises(ValueError, match='6 124'):
        reset.verify_reference(summary)


def test_reset_permissions_validation_and_atomic_publication(business, monkeypatch):
    client, h, base, store = business
    monkeypatch.setattr(reset.get_settings(), 'demo_tools_enabled', True)
    case = new_case(client, h, base)
    path = '/api/v1/business/demo-reset'
    before = reset.generation(store)
    request = {'version': before['version'], 'confirmation': 'REINITIALISER LA DEMO'}
    stages = []
    class Stage:
        def __init__(self, *args):
            stages.append(self)
        async def generate_demo_history(self, days, end):
            assert days == 365 and end == reset.REFERENCE_END
        def run_analytics(self):
            return None
    monkeypatch.setattr(reset, 'S3ParquetStore', lambda *args: None)
    monkeypatch.setattr(reset, 'SamPipeline', Stage)
    assert client.post(path, json=request).status_code == 401
    for role in ('analyst', 'reader'):
        assert client.post(path, headers=h[role], json=request).status_code == 403
    assert not stages
    assert client.post(path, headers=h['admin'], json={**request, 'confirmation':'wrong'}).status_code == 422
    def fail(_):
        raise ValueError('invalid fixture')
    monkeypatch.setattr(reset, 'verify_reference', fail)
    assert client.post(path, headers=h['admin'], json=request).status_code == 409
    assert reset.generation(store) == before
    monkeypatch.setattr(reset, 'verify_reference', lambda _: {'checks':'passed'})
    response = client.post(path, headers=h['admin'], json=request)
    assert response.status_code == 200, response.text
    active = reset.generation(store)
    assert active['version'] == before['version'] + 1
    assert active['prefix'].startswith('demo-generations/')
    assert client.get(base+'/cases/'+case['id'], headers=h['reader']).json()['quantity'] == 522
    assert client.post(path, headers=h['admin'], json=request).status_code == 409
    with store.connect() as db:
        event = db.execute('SELECT payload FROM demo_generation_events ORDER BY id DESC LIMIT 1').fetchone()['payload']
    assert event['before'] == before
    assert event['after_prefix'] == active['prefix']


def test_reset_disabled_by_default_even_with_mock(business, monkeypatch):
    client, h, base, store = business
    monkeypatch.setattr(reset.get_settings(), 'demo_tools_enabled', False)
    assert client.get('/api/v1/business/demo-reset', headers=h['admin']).status_code == 409
    assert client.post('/api/v1/business/demo-reset', headers=h['admin'], json={
        'version':0, 'confirmation':'REINITIALISER LA DEMO'}).status_code == 409
