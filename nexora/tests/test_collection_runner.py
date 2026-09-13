"""Fault injection with real PostgreSQL journal and local Delta files."""
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal
from app.collection.runner import CollectionRunner
from enterprise_fixture import snapshot
from app.models.canonical import AnalyticsSummary
from app.storage.delta_tables import DeltaTables
from app.storage.table_reader import read_table


class Lake:
    def __init__(self, root):
        self.root=root; self.prefix='test-'+str(uuid4()); self.delta=DeltaTables(str(root))
    def put_json(self,key,value):
        path=self.root/key; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value))
    def get_bytes(self,key): return (self.root/key).read_bytes()


class Analytics:
    threshold=.35; buffer_rate=.1
    def compute_table(self,table):
        return AnalyticsSummary(generated_at=datetime.now(timezone.utc),total_capacity=table.num_rows,
            total_used=0,total_available=0,utilization_rate=0,pools_at_risk=0,pools_total=12,
            recovery_potential=0,trends=[],inactive=[],risks=[])


@pytest.fixture
def context(tmp_path):
    url=os.environ.get('BUSINESS_TEST_DATABASE_URL')
    if not url: pytest.skip('Dedicated database required')
    return SimpleNamespace(store=Lake(tmp_path),analytics=Analytics()),CollectionJournal(BusinessStore(url))


def collect(runner,day=1,revision='1'):
    raw=snapshot(datetime(2026,1,day,tzinfo=timezone.utc))
    return runner.run(raw,source='digimon-mock',scope='group',snapshot_id=str(day),source_revision=revision)


@pytest.mark.parametrize('event',[f'{moment}_{stage}' for stage in ('bronze','validated','silver','gold')
    for moment in ('after_write','after_checkpoint')] + ['before_publish','after_publish'])
def test_restart_at_each_boundary_preserves_publication(context,event):
    pipeline,journal=context
    baseline=collect(CollectionRunner(pipeline,journal))
    def crash(point):
        if point==event: raise RuntimeError('Injected crash')
    with pytest.raises(RuntimeError,match='Injected'):
        collect(CollectionRunner(pipeline,journal,crash),day=2)
    head=journal.head(pipeline.store.prefix,'digimon-mock','group')
    if event!='after_publish': assert head['run_id']==baseline['run_id']
    resumed=collect(CollectionRunner(pipeline,journal),day=2)
    assert set(resumed['daily'])=={'2026-01-01','2026-01-02'}
    assert sum(read_table(pipeline.store,item['usage']).num_rows for item in resumed['daily'].values())==24
    assert journal.head(pipeline.store.prefix,'digimon-mock','group')['run_id']==resumed['run_id']
    assert collect(CollectionRunner(pipeline,journal),day=2)==resumed


def test_correction_replaces_one_day_without_losing_other_days(context):
    pipeline,journal=context; runner=CollectionRunner(pipeline,journal)
    collect(runner); before=collect(runner,day=2)
    raw=snapshot(datetime(2026,1,1,tzinfo=timezone.utc)); raw['pools'][0]['consumed']=7
    corrected=runner.run(raw,source='digimon-mock',scope='group',snapshot_id='1',source_revision='2')
    assert corrected['daily']['2026-01-02']==before['daily']['2026-01-02']
    rows=read_table(pipeline.store,corrected['daily']['2026-01-01']['usage']).to_pylist()
    assert len(rows)==12 and rows[0]['used']==7


def test_invalid_source_is_archived_without_publication(context):
    pipeline,journal=context
    raw=snapshot(datetime(2026,1,1,tzinfo=timezone.utc)); raw['pools'][0]['entitlement']=-1
    with pytest.raises(ValueError):
        CollectionRunner(pipeline,journal).run(raw,source='digimon-mock',scope='group',snapshot_id='bad',source_revision='1')
    assert list(pipeline.store.root.glob('bronze/**/payload.json'))
    assert journal.head(pipeline.store.prefix,'digimon-mock','group') is None


def test_runner_with_real_spark(context):
    from app.analytics import SparkAnalytics
    pipeline,journal=context
    pipeline.analytics=SparkAnalytics('local[1]',.35,.1)
    manifest=collect(CollectionRunner(pipeline,journal))
    summary=json.loads(read_table(pipeline.store,manifest['gold']).to_pylist()[0]['summary_json'])
    assert summary['pools_total']==12
    assert len(summary['trends'])==12


def test_expired_worker_cannot_replace_recovered_publication(context):
    from app.collection.journal import LeaseLost
    pipeline,journal=context
    recovered=[]
    def replace_worker(event):
        if event=='after_write_silver':
            with journal.store.connect() as db:
                db.execute("UPDATE collection_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE namespace=%s AND state='running'",(pipeline.store.prefix,))
            recovered.append(collect(CollectionRunner(pipeline,journal)))
    with pytest.raises(LeaseLost): collect(CollectionRunner(pipeline,journal,replace_worker))
    assert journal.head(pipeline.store.prefix,'digimon-mock','group')['run_id']==recovered[0]['run_id']
    assert collect(CollectionRunner(pipeline,journal))==recovered[0]


@pytest.mark.skipif(os.environ.get('TEST_DELTA_MINIO')!='1',reason='Opt-in MinIO validation')
def test_recovery_against_minio(context):
    from app.config import get_settings
    from app.storage.object_store import S3ParquetStore
    pipeline,journal=context; s=get_settings()
    pipeline.store=S3ParquetStore(s.s3_endpoint_url,s.s3_access_key,s.s3_secret_key,
        s.s3_bucket,s.s3_region,prefix='recovery-validation/'+str(uuid4())+'/')
    before=collect(CollectionRunner(pipeline,journal))
    def crash(event):
        if event=='after_write_silver': raise RuntimeError('Injected MinIO interruption')
    with pytest.raises(RuntimeError): collect(CollectionRunner(pipeline,journal,crash),day=2)
    assert journal.head(pipeline.store.prefix,'digimon-mock','group')['run_id']==before['run_id']
    after=collect(CollectionRunner(pipeline,journal),day=2)
    assert len(after['daily'])==2
    assert sum(read_table(pipeline.store,item['usage']).num_rows for item in after['daily'].values())==24
    assert collect(CollectionRunner(pipeline,journal),day=2)==after


def test_rebase_after_another_day_was_published_preserves_lineage(context):
    pipeline,journal=context
    first=collect(CollectionRunner(pipeline,journal))
    def crash(event):
        if event=='after_checkpoint_gold': raise RuntimeError('Pause before publication')
    with pytest.raises(RuntimeError): collect(CollectionRunner(pipeline,journal,crash),day=2)
    third=collect(CollectionRunner(pipeline,journal),day=3)
    resumed=collect(CollectionRunner(pipeline,journal),day=2)
    assert set(resumed['daily'])=={'2026-01-01','2026-01-02','2026-01-03'}
    assert resumed['daily']['2026-01-03']==third['daily']['2026-01-03']
    with journal.store.connect() as db:
        history=db.execute('SELECT stage,artifact,reason FROM collection_step_history WHERE run_id=%s',(resumed['run_id'],)).fetchall()
    assert {r['stage'] for r in history}=={'validated','silver','gold'}
    assert all(r['reason']=='BASELINE_CHANGED' for r in history)
    assert next(r['artifact'] for r in history if r['stage']=='validated')['expected_run']==first['run_id']


def test_lease_is_renewed_during_long_work(context):
    from threading import Event
    pipeline,journal=context
    def slow_stage(event):
        if event=='after_write_silver': Event().wait(2.2)
    manifest=collect(CollectionRunner(pipeline,journal,slow_stage,lease_seconds=1))
    assert journal.head(pipeline.store.prefix,'digimon-mock','group')['run_id']==manifest['run_id']


def test_reader_remains_on_one_publication_during_new_collection(context):
    from app.collection.reader import PublishedCollection
    pipeline,journal=context
    assert PublishedCollection(pipeline.store,journal,'digimon-mock','group').summary() is None
    collect(CollectionRunner(pipeline,journal))
    pinned=PublishedCollection(pipeline.store,journal,'digimon-mock','group')
    collect(CollectionRunner(pipeline,journal),day=2)
    latest=PublishedCollection(pipeline.store,journal,'digimon-mock','group')
    assert pinned.usage().num_rows==12 and pinned.summary().total_capacity==12
    assert latest.usage().num_rows==24 and latest.summary().total_capacity==24
    assert latest.inventory().captured_at.day == 2
    raw=snapshot(datetime(2026,1,3,tzinfo=timezone.utc)); raw.pop('inventory',None)
    from app.collection.quality import CoverageRejected
    with pytest.raises(CoverageRejected):
        CollectionRunner(pipeline,journal).run(raw,source='digimon-mock',scope='group',snapshot_id='3',source_revision='1')
    assert PublishedCollection(pipeline.store,journal,'digimon-mock','group').inventory().captured_at.day == 2
    assert PublishedCollection(pipeline.store,journal,'digimon-mock','other').summary() is None


def test_reader_rejects_tampered_manifest(context):
    from app.collection.reader import PublishedCollection
    pipeline,journal=context
    manifest=collect(CollectionRunner(pipeline,journal))
    head=journal.head(pipeline.store.prefix,'digimon-mock','group')
    pipeline.store.put_json(head['manifest_key'],{**manifest,'scope':'other'})
    with pytest.raises(ValueError,match='integrity'):
        PublishedCollection(pipeline.store,journal,'digimon-mock','group')


def test_api_reads_published_data_and_index_without_live_source(context):
    import asyncio
    from service_scenarios import ScenarioContext
    from service_scenarios import ScenarioClient as TestClient
    from app.business.workspace_service import current_user
    from app.business.portfolio_service import selected_pools
    from app.business.inventory_service import inventory_namespace, latest_inventory
    from app.business.inventory_index import read_index
    from app.dependencies import get_pipeline
    from app.collection.reader import PublishedCollection
    from app.services.pipeline import SamPipeline
    from app.analytics import SparkAnalytics
    pipeline,journal=context
    pipeline.analytics=SparkAnalytics('local[1]',.35,.1)
    collect(CollectionRunner(pipeline,journal))
    class OfflineSource:
        async def get_current_usage(self): raise AssertionError('Must not contact live source')
        async def get_license_stock(self): raise AssertionError('Must not contact live source')
    served=SamPipeline(OfflineSource(),pipeline.store,pipeline.analytics)
    served.store.collection=PublishedCollection(pipeline.store,journal,'digimon-mock','group')
    app=ScenarioContext()
    app.dependency_overrides[get_pipeline]=lambda:served
    app.dependency_overrides[current_user]=lambda:{'id':'reader'}
    app.dependency_overrides[selected_pools]=lambda:None
    with TestClient(app) as client:
        summary=client.get('/api/v1/analytics/summary')
        assert summary.status_code==200 and summary.json()['pools_total']==12
        assert len(client.get('/api/v1/stock').json())==12
        assert len(client.get('/api/v1/live').json())==12
        assert len(client.get('/api/v1/history').json())==12
        app.dependency_overrides[selected_pools]=lambda:['flex-cad']
        assert len(client.get('/api/v1/stock').json())==1
        assert len(client.get('/api/v1/live').json())==1
        assert len(client.get('/api/v1/history').json())==1
    assert latest_inventory(served.store).captured_at.day==1
    with journal.store.connect() as db:
        index=read_index(db,inventory_namespace(served.store),None,'machines','',0,25,{})
    assert index['total']==138


def test_journaled_sync_returns_stable_identity_and_yields_event_loop(context):
    import asyncio
    from threading import Event
    from app.services.pipeline import SamPipeline
    from app.connectors.digimon import MockDigimonConnector
    pipeline,journal=context
    entered=Event(); release=Event()
    class Source(MockDigimonConnector):
        async def get_raw_snapshot(self): return snapshot(datetime(2026,1,1,tzinfo=timezone.utc))
    served=SamPipeline(Source(),pipeline.store,pipeline.analytics)
    served.collection_journal=journal; served.collection_source='digimon-mock'; served.collection_scope='group'
    original=served.collect_recoverable
    def delayed(*args,**kwargs):
        entered.set()
        assert release.wait(5), 'Event loop did not progress while collection ran'
        return original(*args,**kwargs)
    served.collect_recoverable=delayed
    async def check():
        job=asyncio.create_task(served.sync())
        await asyncio.to_thread(entered.wait,3)
        release.set()
        first=await job
        second=await served.sync()
        assert first.snapshot_id==second.snapshot_id
    asyncio.run(check())


def test_published_inventory_index_is_pinned_by_run_id(context):
    from app.collection.reader import PublishedCollection
    from app.business.inventory_service import inventory_head, inventory_namespace
    from app.business.inventory_index import publish_index, read_index
    from app.models.inventory import InventorySnapshot
    pipeline,journal=context
    manifest=collect(CollectionRunner(pipeline,journal))
    pipeline.store.collection=PublishedCollection(pipeline.store,journal,'digimon-mock','group')
    publish_index(journal.store,manifest['index_namespace'],
        InventorySnapshot(captured_at=datetime.now(timezone.utc),source='test'), 'test/unpublished')
    with journal.store.connect() as db:
        assert inventory_head(db,pipeline.store)['id']==manifest['index_run']
        rows=read_index(db,inventory_namespace(pipeline.store),None,'machines','',0,25,{},expected_run=manifest['index_run'])
    assert rows['total']==138


@pytest.mark.parametrize('same_values', [True, False])
def test_overlapping_pool_rows_are_archived_and_rejected(context, same_values):
    from copy import deepcopy
    pipeline, journal = context
    baseline = collect(CollectionRunner(pipeline, journal))
    raw = snapshot(datetime(2026,1,2,tzinfo=timezone.utc))
    duplicate = deepcopy(raw['pools'][0])
    if not same_values:
        duplicate['consumed'] += 1
    raw['pools'].append(duplicate)
    with pytest.raises(ValueError, match='duplicate license pool'):
        CollectionRunner(pipeline, journal).run(raw, source='digimon-mock', scope='group',
            snapshot_id='overlap', source_revision='1')
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group')['run_id'] == baseline['run_id']
    with journal.store.connect() as db:
        rejected = db.execute("SELECT id,state,error_code FROM collection_runs WHERE namespace=%s AND snapshot_id='overlap'", (pipeline.store.prefix,)).fetchone()
    assert rejected['state'] == 'rejected' and rejected['error_code'] == 'INVALID_ARTIFACT'
    steps = journal.checkpoints(rejected['id'])
    assert set(steps) == {'bronze'}
    archived = json.loads(pipeline.store.get_bytes(steps['bronze']['key']))
    assert len(json.loads(archived['payload_json'])['pools']) == 13


@pytest.mark.parametrize('field,value', [('entitlement', 800.5), ('consumed', True)])
def test_invalid_quantity_is_preserved_in_bronze_without_changing_publication(context, field, value):
    pipeline, journal = context
    baseline = collect(CollectionRunner(pipeline, journal))
    raw = snapshot(datetime(2026,1,2,tzinfo=timezone.utc))
    raw['pools'][0][field] = value
    with pytest.raises(ValueError, match='integral pool quantity'):
        CollectionRunner(pipeline, journal).run(raw, source='digimon-mock', scope='group',
            snapshot_id='bad-quantity', source_revision='1')
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group')['run_id'] == baseline['run_id']
    with journal.store.connect() as db:
        run = db.execute("SELECT id,state FROM collection_runs WHERE namespace=%s AND snapshot_id='bad-quantity'", (pipeline.store.prefix,)).fetchone()
    assert run['state'] == 'rejected'
    steps = journal.checkpoints(run['id'])
    assert set(steps) == {'bronze'}
    body = json.loads(pipeline.store.get_bytes(steps['bronze']['key']))['payload_json']
    assert json.loads(body)['pools'][0][field] == value


@pytest.mark.parametrize('defect', ['missing_capacity', 'missing_product', 'invalid_pool_list', 'null_pool_id', 'null_product_id'])
def test_malformed_source_is_rejected_instead_of_retried_forever(context, defect):
    pipeline, journal = context
    raw = snapshot(datetime(2026,1,1,tzinfo=timezone.utc))
    if defect == 'missing_capacity':
        del raw['pools'][0]['entitlement']
    elif defect == 'null_pool_id':
        raw['pools'][0]['poolKey'] = None
    elif defect == 'null_product_id':
        raw['pools'][0]['product']['key'] = None
    elif defect == 'missing_product':
        raw['pools'][0]['product'] = None
    else:
        raw['pools'] = None
    with pytest.raises(ValueError):
        collect_runner = CollectionRunner(pipeline, journal)
        collect_runner.run(raw, source='digimon-mock', scope='group', snapshot_id=defect, source_revision='1')
    with journal.store.connect() as db:
        run = db.execute('SELECT id,state,error_code FROM collection_runs WHERE namespace=%s AND snapshot_id=%s',
                         (pipeline.store.prefix, defect)).fetchone()
    assert run['state'] == 'rejected' and run['error_code'] == 'INVALID_ARTIFACT'
    assert set(journal.checkpoints(run['id'])) == {'bronze'}
    assert journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group') == []
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None
