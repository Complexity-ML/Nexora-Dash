"""Synthetic fixture for the Docker database-and-lake restoration verification."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from app.analytics import SparkAnalytics
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal
from app.collection.runner import CollectionRunner
from app.collection.reader import PublishedCollection
from app.collection.recovery import recover_once
from app.collection.worker_monitor import WorkerMonitor
from app.business.software_counts import read_counts, compute_counts
from threading import Event
from app.collection.dependencies import dependency_inventory
from app.collection.backup import delta_backup_files
from app.config import get_settings
from app.connectors.demo import snapshot
from app.storage.delta_tables import DeltaTables, DeltaReference
from app.bi.auth import issue_reader, revoke_reader, authenticate_reader, BIUnauthorized, revoke_namespace_readers
from app.bi.catalog import prepare_pool_snapshot, prepare_inventory_snapshot, prepare_license_snapshot, publish_snapshot, publication


def restore_snapshot(at):
    raw=snapshot(at)
    # Stable synthetic license dimensions across every day of the recovery exercise.
    raw['inventory']['observations']=[]
    raw['inventory']['products']=[{'software_id':'restore-rhel','name':'Fixture RHEL','category':'operating_system'}]
    raw['inventory']['entitlements']=[{'entitlement_id':'restore-right','software_id':'restore-rhel',
        'metric':'device','quantity':80,'subsidiary_id':'demo-subsidiary-1','synthetic':True}]
    return raw


class FixtureLake:
    prefix = 'restore-proof/'
    def __init__(self, root):
        self.root = root
        self.delta = DeltaTables(str(root))
    def put_json(self, key, value):
        path = self.root/key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    def get_bytes(self, key):
        return (self.root/key).read_bytes()
    def list_keys(self, prefix):
        return [str(p.relative_to(self.root)) for p in (self.root/prefix).rglob('*') if p.is_file()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['seed', 'copy', 'mutate', 'verify'])
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    journal = CollectionJournal(BusinessStore(get_settings().database_url))
    if args.phase == 'seed':
        import secrets
        password = secrets.token_urlsafe(24)
        journal.store.seed_demo(password)
        with journal.store.connect() as db:
            db.execute("INSERT INTO workspace_costs VALUES ('demo','flex-cad',12345,1,clock_timestamp())")
            journal.store.event(db,'demo',None,'demo-admin','restore.fixture',{'text':'synthetic note'})
        lake = FixtureLake(args.root/'source')
        pipeline = SimpleNamespace(store=lake, analytics=SparkAnalytics('local[1]', .35, .1))
        manifest = CollectionRunner(pipeline, journal).run(restore_snapshot(datetime(2026,1,1,tzinfo=timezone.utc)),
            source='digimon-mock', scope='group', snapshot_id='restoration', source_revision='1')
        artifact = journal.checkpoints(manifest['run_id'])['gold']
        def crash(stage):
            if stage == 'after_checkpoint_bronze':
                raise RuntimeError('RESTORE_FIXTURE_INTERRUPTION')
        try:
            CollectionRunner(pipeline, journal, crash).run(restore_snapshot(datetime(2026,1,2,tzinfo=timezone.utc)),
                source='digimon-mock', scope='group', snapshot_id='interrupted', source_revision='1')
        except RuntimeError as exc:
            assert str(exc) == 'RESTORE_FIXTURE_INTERRUPTION'
        else:
            raise AssertionError('Fixture interruption did not occur')
        pending = journal.recovery_candidates(lake.prefix, 'digimon-mock', 'group', rotate=True)[0]
        assert pending['recovery_checked_at'] is not None
        monitor = WorkerMonitor(journal.store, lake.prefix, 'digimon-mock', 'group', Event()).start()
        monitor.begin()
        monitor.done.set()
        monitor.thread.join(timeout=5)
        # Simulate a vanished worker; its presence must not become healthy on restore.
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET heartbeat_at=clock_timestamp()-interval '100 seconds' WHERE id=%s", (monitor.id,))
        bi = prepare_pool_snapshot(lake, journal, source='digimon-mock', scope='group', audience='restore-cad', pool_ids=['flex-cad'])
        publish_snapshot(lake, journal, bi['snapshot_id'], expected_snapshot=None)
        bi_pending = prepare_pool_snapshot(lake, journal, source='digimon-mock', scope='group', audience='restore-cad', pool_ids=['flex-cad'])
        stale = issue_reader(journal.store, namespace=lake.prefix, audience='restore-cad')
        inventory_bi=prepare_inventory_snapshot(lake,journal,source='digimon-mock',scope='group',
            audience='restore-inventory',subsidiary_ids=['demo-subsidiary-1'])
        licenses_bi=prepare_license_snapshot(lake,journal,source='digimon-mock',scope='group',
            audience='restore-licenses',software_ids=['restore-rhel'],subsidiary_ids=['demo-subsidiary-1'])
        for candidate in (inventory_bi,licenses_bi):
            publish_snapshot(lake,journal,candidate['snapshot_id'],expected_snapshot=None)
        revoked = issue_reader(journal.store, namespace=lake.prefix, audience='restore-cad')
        revoke_reader(journal.store, namespace=lake.prefix, reader_id=revoked['id'])
        daily = WorkerMonitor(journal.store, lake.prefix, 'digimon-mock', 'group', Event(), kind='daily').start()
        daily.close(failed=True)
        (args.root/'proof.json').write_text(json.dumps({'inventory_bi':inventory_bi['snapshot_id'],'licenses_bi':licenses_bi['snapshot_id'],'stale_token':stale['token'], 'stale_id':stale['id'], 'revoked_token':revoked['token'], 'daily_worker':daily.id, 'bi_snapshot':bi['snapshot_id'], 'bi_pending':bi_pending['snapshot_id'], 'run_id':manifest['run_id'],'pending_run':pending['id'],'worker_id':monitor.id,'artifact':artifact,'test_password':password}))
        print(json.dumps({'phase':'seed'}))
    elif args.phase == 'copy':
        lake = FixtureLake(args.root/'source')
        roots = json.loads((args.root/'snapshot.json').read_text())
        dependencies = dependency_inventory(lake, roots['artifacts'])
        files = sorted(set(dependencies['objects']) | set(delta_backup_files(lake, dependencies['delta_versions'])))
        roots['required_archive_members'] = ['database.dump','snapshot.json','proof.json'] + ['restored/'+key for key in files]
        (args.root/'snapshot.json').write_text(json.dumps(roots))
        import hashlib
        hashes = {}
        for key in files:
            target = args.root/'restored'/key
            target.parent.mkdir(parents=True, exist_ok=True)
            data = lake.get_bytes(key)
            target.write_bytes(data)
            hashes[key] = hashlib.sha256(data).hexdigest()
        proof = json.loads((args.root/'proof.json').read_text())
        proof['hashes'] = hashes
        (args.root/'proof.json').write_text(json.dumps(proof))
        print(json.dumps({'phase':'copy','files':len(files)}))
    elif args.phase == 'mutate':
        with journal.store.connect() as db:
            db.execute("UPDATE workspace_costs SET annual_unit_cents=99999 WHERE workspace_id='demo' AND pool_id='flex-cad'")
        lake = FixtureLake(args.root/'source')
        pipeline = SimpleNamespace(store=lake, analytics=SparkAnalytics('local[1]', .35, .1))
        manifest = CollectionRunner(pipeline, journal).run(restore_snapshot(datetime(2026,1,3,tzinfo=timezone.utc)),
            source='digimon-mock', scope='group', snapshot_id='after-backup-snapshot', source_revision='1')
        assert '2026-01-03' in manifest['daily']
        old = publication(journal, namespace=lake.prefix, audience='restore-cad')
        bi = prepare_pool_snapshot(lake, journal, source='digimon-mock', scope='group', audience='restore-cad', pool_ids=['flex-cad'])
        publish_snapshot(lake, journal, bi['snapshot_id'], expected_snapshot=old['snapshot_id'])
        late = issue_reader(journal.store, namespace=lake.prefix, audience='restore-cad')
        proof = json.loads((args.root/'proof.json').read_text())
        revoke_reader(journal.store, namespace=lake.prefix, reader_id=proof['stale_id'])
        proof['late_token'] = late['token']
        (args.root/'proof.json').write_text(json.dumps(proof))
        print(json.dumps({'phase':'concurrent_mutation','new_day_published':True}))
    else:
        assert not (args.root/'source').exists(), 'Original lake must be unavailable'
        proof = json.loads((args.root/'proof.json').read_text())
        token = journal.store.login('admin@sam.demo', proof['test_password'])
        assert token and journal.store.user_for_token(token)['id'] == 'demo-admin'
        with journal.store.connect() as db:
            assert db.execute("SELECT annual_unit_cents FROM workspace_costs WHERE workspace_id='demo' AND pool_id='flex-cad'").fetchone()['annual_unit_cents'] == 12345
            assert db.execute("SELECT count(*) AS n FROM members WHERE workspace_id='demo'").fetchone()['n'] == 3
            before = db.execute('SELECT max(id) AS id FROM events').fetchone()['id']
            journal.store.event(db,'demo',None,'demo-admin','restore.after',{})
            assert db.execute('SELECT max(id) AS id FROM events').fetchone()['id'] > before
        lake = FixtureLake(args.root/'restored')
        import hashlib
        for key, expected in proof['hashes'].items():
            assert hashlib.sha256(lake.get_bytes(key)).hexdigest() == expected
        bi = publication(journal, namespace=lake.prefix, audience='restore-cad')
        assert bi['snapshot_id'] == proof['bi_snapshot']
        with journal.store.connect() as db:
            ids = {r['id'] for r in db.execute('SELECT id FROM bi_snapshots WHERE namespace=%s', (lake.prefix,)).fetchall()}
        assert ids == {proof['bi_snapshot'], proof['bi_pending'],proof['inventory_bi'],proof['licenses_bi']}
        for denied_token in (proof['revoked_token'], proof['late_token']):
            try:
                authenticate_reader(journal.store, namespace=lake.prefix, token=denied_token)
            except BIUnauthorized:
                pass
            else:
                raise AssertionError('Restored BI access should be denied')
        assert authenticate_reader(journal.store, namespace=lake.prefix, token=proof['stale_token'])
        assert revoke_namespace_readers(journal.store, namespace=lake.prefix, apply=True)['readers'] == 1
        try:
            authenticate_reader(journal.store, namespace=lake.prefix, token=proof['stale_token'])
        except BIUnauthorized:
            pass
        else:
            raise AssertionError('Reconciliation must retire pre-restore credentials')
        bi_manifest = json.loads(lake.get_bytes(bi['artifact']['manifest_key']))
        assert lake.delta.read(DeltaReference(**bi_manifest['tables']['pool_usage'])).num_rows == 1
        from app.bi.download import snapshot_csv
        import csv
        from io import StringIO
        inventory_pub=publication(journal,namespace=lake.prefix,audience='restore-inventory')
        license_pub=publication(journal,namespace=lake.prefix,audience='restore-licenses')
        assert inventory_pub['snapshot_id'] == proof['inventory_bi']
        assert license_pub['snapshot_id'] == proof['licenses_bi']
        inventory_rows=list(csv.DictReader(StringIO(snapshot_csv(lake,inventory_pub['artifact'],'restore-inventory','inventory_counts'))))
        license_rows=list(csv.DictReader(StringIO(snapshot_csv(lake,license_pub['artifact'],'restore-licenses','license_entitlements'))))
        expected_machines=sum(m['site_id']=='demo-site-1' for m in restore_snapshot(datetime(2026,1,1,tzinfo=timezone.utc))['inventory']['machines'])
        assert sum(int(r['machines']) for r in inventory_rows) == expected_machines
        assert {r['subsidiary_id'] for r in inventory_rows} == {'demo-subsidiary-1'}
        assert len(license_rows) == 1 and license_rows[0]['quantity'] == '80' and license_rows[0]['metric'] == 'device'
        reader = PublishedCollection(lake, journal, 'digimon-mock', 'group')
        assert reader.manifest['run_id'] == proof['run_id']
        assert reader.summary().pools_total == 12
        assert reader.usage().num_rows == 12
        assert len(reader.inventory().machines) == 120
        assert len(reader.latest_snapshot().stock) == 12
        with journal.store.connect() as db:
            count = db.execute("SELECT count(*) AS n FROM inventory_entities WHERE run_id=%s AND entity='machines'", (reader.manifest['index_run'],)).fetchone()['n']
            cached = read_counts(db, reader.manifest['index_run'])
            assert cached == compute_counts(db, reader.manifest['index_run']) and cached
            assert db.execute('SELECT products FROM inventory_software_summaries WHERE run_id=%s',
                              (reader.manifest['index_run'],)).fetchone() is not None
            pending = db.execute('SELECT recovery_checked_at,state FROM collection_runs WHERE id=%s',
                                 (proof['pending_run'],)).fetchone()
            assert pending['recovery_checked_at'] and pending['state'] == 'retryable'
        from app.collection.status import collection_status
        from datetime import date
        state = collection_status(lake, journal, source='digimon-mock', scope='group',
                                  start=date(2026,1,1), end=date(2026,1,2), require_worker=True, require_daily_worker=True)
        assert state['recovery_worker']['id'] == proof['worker_id']
        assert state['recovery_worker']['silent'] and state['recovery_workers']['missing_required']
        assert state['daily_worker']['id'] == proof['daily_worker']
        assert state['daily_worker']['state'] == 'failed' and state['daily_workers']['missing_required']
        assert state['missing_days'] == ['2026-01-02']
        pipeline = SimpleNamespace(store=lake, analytics=SparkAnalytics('local[1]', .35, .1))
        resumed = recover_once(pipeline, journal, source='digimon-mock', scope='group')
        assert resumed == [{'run_id': proof['pending_run'], 'status': 'published'}]
        restored = PublishedCollection(lake, journal, 'digimon-mock', 'group')
        assert restored.usage().num_rows == 24
        assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == []
        assert count == 120
        print(json.dumps({'phase':'verified','machines':count,'pools':12,'files_verified':len(proof['hashes']),'interrupted_run_resumed':True,'restored_observations':24,'stale_worker_detected':True,'bi_snapshots_restored':4,'inventory_and_license_csv_restored':True,'revoked_bi_access_denied':True,'post_snapshot_bi_access_denied':True,'daily_failure_restored':True,'bi_access_reconciled':True}))


if __name__ == '__main__':
    main()
