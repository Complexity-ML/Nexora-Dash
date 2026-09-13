"""Real PostgreSQL recovery and concurrency checks, dedicated test DB only."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal, Conflict, LeaseLost, STAGES, fingerprint


@pytest.fixture
def journal():
    url=os.environ.get('BUSINESS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Dedicated database required')
    return CollectionJournal(BusinessStore(url))


def register(journal, namespace=None, revision='1', content=b'payload'):
    return journal.register(namespace=namespace or str(uuid4()),source='digimon-mock',scope='group',
        snapshot_id='snapshot',source_revision=revision,fingerprint=fingerprint(content),
        mapping_version='1',schema_version='1')


def finish(journal, run, fence):
    for stage in STAGES:
        journal.checkpoint(run['id'],fence,stage,{'manifest_key':f"gold/{run['id']}/manifest.json",'version':0})


def test_duplicate_identity_and_explicit_correction(journal):
    namespace=str(uuid4())
    first=register(journal,namespace)
    assert register(journal,namespace)['id']==first['id']
    with pytest.raises(Conflict): register(journal,namespace,content=b'changed')
    assert register(journal,namespace,revision='2',content=b'changed')['id'] != first['id']


def test_resume_preserves_checkpoints_and_fences_old_worker(journal):
    run=register(journal); rid=run['id']; old=journal.claim(rid,'worker-a')
    journal.checkpoint(rid,old,'bronze',{'key':'bronze/payload','sha256':run['fingerprint']})
    with journal.store.connect() as db:
        db.execute("UPDATE collection_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(rid,))
    new=journal.claim(rid,'worker-b')
    assert new>old
    with pytest.raises(LeaseLost): journal.checkpoint(rid,old,'validated',{'valid':True})
    with pytest.raises(LeaseLost): journal.renew(rid,old)
    assert journal.checkpoints(rid)['bronze']['sha256']==run['fingerprint']
    journal.checkpoint(rid,new,'validated',{'valid':True})
    journal.checkpoint(rid,new,'validated',{'valid':True})
    with pytest.raises(Conflict): journal.checkpoint(rid,new,'validated',{'valid':False})
    with pytest.raises(Conflict): journal.publish(rid,new,expected_run=None,expected_manifest=None)
    assert journal.head(run['namespace'],'digimon-mock','group') is None


def test_only_one_worker_can_claim_and_failure_is_retryable(journal):
    run=register(journal)
    def claim(owner):
        try: return journal.claim(run['id'],owner)
        except Conflict: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(claim,['a','b']))
    assert len([r for r in results if r is not None])==1
    fence=next(r for r in results if r is not None)
    journal.fail(run['id'],fence,'SOURCE_TIMEOUT')
    next_fence=journal.claim(run['id'],'retry')
    assert next_fence>fence
    journal.fail(run['id'],next_fence,'INVALID_SCHEMA',retryable=False)
    with pytest.raises(Conflict): journal.claim(run['id'],'again')


def test_publish_is_atomic_and_rejects_stale_head(journal):
    namespace=str(uuid4()); first=register(journal,namespace); second=register(journal,namespace,revision='2')
    fences=[journal.claim(first['id'],'worker')]
    with pytest.raises(Conflict): journal.claim(second['id'],'concurrent')
    finish(journal,first,fences[0])
    journal.publish(first['id'],fences[0],expected_run=None,expected_manifest=None)
    fences.append(journal.claim(second['id'],'worker'))
    finish(journal,second,fences[1])
    with pytest.raises(Conflict): journal.publish(second['id'],fences[1],expected_run=None,expected_manifest=None)
    assert journal.head(namespace,'digimon-mock','group')['run_id']==first['id']
    with pytest.raises(Conflict):
        journal.publish(second['id'], fences[1], expected_run=first['id'],
                        expected_manifest='gold/obsolete/manifest.json')
    assert journal.head(namespace,'digimon-mock','group')['run_id'] == first['id']
    journal.publish(second['id'],fences[1],expected_run=first['id'],expected_manifest=f"gold/{first['id']}/manifest.json")
    assert journal.head(namespace,'digimon-mock','group')['manifest_key']==f"gold/{second['id']}/manifest.json"
    with pytest.raises(Conflict): journal.claim(second['id'],'repeat')


def test_stage_order_and_error_sanitization(journal):
    run=register(journal); fence=journal.claim(run['id'],'worker')
    with pytest.raises(Conflict): journal.checkpoint(run['id'],fence,'silver',{'version':1})
    with pytest.raises(ValueError): journal.fail(run['id'],fence,'credential=secret')
    assert journal.checkpoints(run['id'])=={}


def test_reconcile_detects_manifest_change_without_run_id_change(journal):
    namespace = str(uuid4())
    first = register(journal, namespace)
    fence = journal.claim(first['id'], 'worker')
    finish(journal, first, fence)
    journal.publish(first['id'], fence, expected_run=None, expected_manifest=None)
    second = register(journal, namespace, revision='2')
    fence = journal.claim(second['id'], 'worker')
    journal.checkpoint(second['id'], fence, 'bronze', {'key':'bronze/preserved.json'})
    journal.checkpoint(second['id'], fence, 'validated', {
        'expected_run':first['id'], 'base_manifest':f"gold/{first['id']}/manifest.json"})
    assert not journal.reconcile(second['id'], fence)
    with journal.store.connect() as db:
        db.execute('UPDATE collection_heads SET manifest_key=%s WHERE namespace=%s',
                   ('gold/maintenance/changed.json', namespace))
    assert journal.reconcile(second['id'], fence)
    assert set(journal.checkpoints(second['id'])) == {'bronze'}
    with journal.store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM collection_step_history WHERE run_id=%s',
                          (second['id'],)).fetchone()['n'] == 1


def test_maintenance_publication_preserves_history_and_refuses_stale_candidate(journal):
    run = register(journal)
    fence = journal.claim(run['id'], 'worker')
    finish(journal, run, fence)
    journal.publish(run['id'], fence, expected_run=None, expected_manifest=None)
    old = journal.checkpoints(run['id'])['gold']
    candidate = {'manifest_key':'gold/maintenance/new.json', 'fingerprint':'a'*64}
    assert journal.replace_published_manifest(run['id'], expected_manifest=old['manifest_key'], artifact=candidate)
    assert journal.head(run['namespace'], 'digimon-mock', 'group')['manifest_key'] == candidate['manifest_key']
    assert journal.checkpoints(run['id'])['gold'] == candidate
    with pytest.raises(Conflict):
        journal.replace_published_manifest(run['id'], expected_manifest=old['manifest_key'],
            artifact={'manifest_key':'gold/maintenance/stale.json','fingerprint':'b'*64})
    assert not journal.replace_published_manifest(run['id'], expected_manifest=candidate['manifest_key'], artifact=candidate)
    with journal.store.connect() as db:
        rows = db.execute('SELECT artifact,reason FROM collection_step_history WHERE run_id=%s', (run['id'],)).fetchall()
    assert rows == [{'artifact':old, 'reason':'MAINTENANCE_PUBLICATION'}]
