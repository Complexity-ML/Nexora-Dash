"""Recoverable candidate pipeline using immutable per-attempt Delta outputs.

Opt-in until API readers use collection_heads. It never changes legacy pointers.
"""
import json
from uuid import uuid4
import pyarrow as pa
from app.collection.journal import Conflict, LeaseLost, fingerprint
from app.collection.lease import LeaseHeartbeat
from app.collection.quality import CoveragePolicy, CoverageRejected, snapshot_profile, compare_coverage
from app.connectors.digimon import map_digimon_payload
from app.models.inventory import map_inventory_payload, InventorySnapshot
from app.storage.inventory_tables import inventory_table
from app.models.canonical import AnalyticsSummary
from app.storage.table_reader import read_table


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


class DayRevisionConflict(ValueError):
    """A later registered payload already occupies this day; source order is unknown."""


class CollectionRunner:
    def __init__(self, pipeline, journal, hook=None, lease_seconds=120):
        self.run_id = None
        self.lease_seconds = lease_seconds
        self.pipeline, self.journal = pipeline, journal
        self.lake = pipeline.store
        self.hook = hook or (lambda event: None)

    def _json(self, key):
        return json.loads(self.lake.get_bytes(key))

    def run(self, raw, *, source, scope, snapshot_id, source_revision,
            mapping_version='1', schema_version='1', owner=None, expected_day=None):
        self.run_id = None
        body = encoded(raw)
        policy = CoveragePolicy.model_validate(getattr(self.pipeline, 'collection_quality_policy', {}))
        # Analysis settings are part of the transformation identity as well.
        identity_settings = {'mapping':mapping_version, 'threshold':self.pipeline.analytics.threshold,
            'reserve':self.pipeline.analytics.buffer_rate, 'coverage_policy':policy.identity()}
        if expected_day is not None:
            identity_settings['expected_day'] = expected_day
        transform = fingerprint(encoded(identity_settings))
        run = self.journal.register(namespace=self.lake.prefix, source=source, scope=scope,
            snapshot_id=snapshot_id, source_revision=source_revision, fingerprint=fingerprint(body),
            mapping_version=transform, schema_version=schema_version)
        rid = run['id']
        self.run_id = rid
        if run['state'] == 'published':
            return self._verified_manifest(self.journal.checkpoints(rid)['gold'])
        fence = self.journal.claim(rid, owner or str(uuid4()), seconds=self.lease_seconds)
        heartbeat = LeaseHeartbeat(self.journal,rid,fence,self.lease_seconds).start()
        try:
            self.journal.reconcile(rid,fence)
            checkpoints = self.journal.checkpoints(rid)
            # A stale worker can only write beneath its own isolated attempt path.
            suffix = f'collections/{rid}/attempt-{fence}'
            def checkpoint(stage, artifact):
                heartbeat.check()
                self.hook('after_write_'+stage)
                self.journal.checkpoint(rid,fence,stage,artifact)
                checkpoints[stage] = artifact
                self.hook('after_checkpoint_'+stage)

            if 'bronze' not in checkpoints:
                key = f'bronze/{suffix}/payload.json'
                self.lake.put_json(key, {'payload_json':body.decode(), 'fingerprint':run['fingerprint'],
                    'replay':{'mapping_version':mapping_version,'schema_version':schema_version,
                              **({'expected_day':expected_day} if expected_day is not None else {})}})
                checkpoint('bronze', {'key':key,'fingerprint':run['fingerprint']})
            bronze = self._json(checkpoints['bronze']['key'])
            if fingerprint(bronze['payload_json'].encode()) != run['fingerprint']:
                raise ValueError('Bronze fingerprint mismatch')
            source_raw = json.loads(bronze['payload_json'])
            snapshot = map_digimon_payload(source_raw)
            inventory = map_inventory_payload(source_raw)
            if snapshot.source != source:
                raise ValueError('Unexpected source')
            if not snapshot.usage:
                raise ValueError('Empty usage snapshot requires an explicit source contract')
            day = snapshot.timestamp.date().isoformat()
            if expected_day is not None and day != expected_day:
                raise ValueError('Source snapshot does not match requested day')
            coverage = snapshot_profile(inventory)
            if 'validated' not in checkpoints:
                head = self.journal.head(self.lake.prefix,source,scope)
                prior = self._verified_manifest(self.journal.checkpoints(head['run_id'])['gold']) if head else {}
                previous_bronze = prior.get('daily', {}).get(day, {}).get('bronze', {})
                if previous_bronze.get('fingerprint') != run['fingerprint'] and previous_bronze.get('key'):
                    with self.journal.store.connect() as db:
                        replacement = db.execute("""SELECT r.id FROM collection_steps s
                            JOIN collection_runs r ON r.id=s.run_id
                            WHERE s.stage='bronze' AND s.artifact->>'key'=%s
                            AND r.namespace=%s AND r.source=%s AND r.scope=%s
                            AND r.created_at > %s LIMIT 1""",
                            (previous_bronze['key'], self.lake.prefix, source, scope, run['created_at'])).fetchone()
                    if replacement:
                        raise DayRevisionConflict('A later registered payload already replaced this day')
                # Compare historical corrections to the same day's profile, not today's park.
                previous = prior.get('daily', {}).get(day, {}).get('coverage')
                if previous is None:
                    previous = prior.get('coverage', {}) if not prior.get('daily') or day >= max(prior['daily']) else {}
                quality = compare_coverage(previous, coverage, policy)
                checkpoint('validated', {'quality':quality,'day':day,'usage_rows':len(snapshot.usage),
                    'expected_run':head['run_id'] if head else None,
                    'base_manifest':head['manifest_key'] if head else None,
                    'mapping_version':mapping_version,'schema_version':schema_version})
            valid = checkpoints['validated']
            if not valid.get('quality', {}).get('accepted', True):
                raise CoverageRejected('Inventory coverage decreased beyond publication policy')
            if valid['day'] != day:
                raise ValueError('Checkpoint observation date mismatch')
            head = self.journal.head(self.lake.prefix,source,scope)
            if (head['run_id'] if head else None) != valid['expected_run']:
                raise Conflict('Collection baseline was superseded; reconciliation required')
            baseline = self._verified_manifest(self.journal.checkpoints(valid['expected_run'])['gold']) if valid['expected_run'] else {'daily':{}}
            if 'silver' not in checkpoints:
                table = pa.Table.from_pylist([u.model_dump(mode='json') for u in snapshot.usage])
                usage = self.lake.delta.replace(f'silver/{suffix}/usage',table).to_dict()
                inv = None
                if inventory is not None:
                    inv = self.lake.delta.replace(f'silver/{suffix}/inventory',
                        pa.table({'snapshot_json':[inventory.model_dump_json()]})).to_dict()
                dimensions = {}
                if inventory is not None:
                    for name in ('products','installations','entitlements','subsidiaries'):
                        dimensions[name] = self.lake.delta.replace(f'silver/{suffix}/{name}',
                            inventory_table(name,[v.model_dump(mode='json') for v in getattr(inventory,name)])).to_dict()
                checkpoint('silver', {'usage':usage,'inventory':inv,'rows':len(table),
                    'dimensions':dimensions,'bronze':checkpoints['bronze'],'coverage':coverage})
            silver = checkpoints['silver']
            usage_table = read_table(self.lake,silver['usage'])
            if len(usage_table) != valid['usage_rows'] or sorted(usage_table.to_pylist(), key=encoded) != sorted([u.model_dump(mode='json') for u in snapshot.usage], key=encoded):
                raise ValueError('Silver content does not match validated source')
            if silver['inventory'] is not None:
                stored = read_table(self.lake,silver['inventory']).to_pylist()
                if stored != [{'snapshot_json':inventory.model_dump_json()}]:
                    raise ValueError('Inventory content does not match validated source')
            daily = {**baseline['daily'],day:silver}
            if 'gold' not in checkpoints:
                tables = [read_table(self.lake,item['usage']) for _,item in sorted(daily.items())]
                summary = self.pipeline.analytics.compute_table(pa.concat_tables([t.drop(['observation_date']) if 'observation_date' in t.column_names else t for t in tables]))
                gold = self.lake.delta.replace(f'gold/{suffix}/analytics',
                    pa.table({'summary_json':[summary.model_dump_json()]})).to_dict()
                index_namespace = None
                index_run = None
                index_manifest = None
                enterprise_manifest = None
                inventory_captured_at = None
                latest_day = max(daily)
                latest = daily[latest_day]
                # A correction to an older pool day must preserve the imported
                # current inventory, which lives in separate enterprise tables.
                if latest_day != day and latest == baseline['daily'].get(latest_day):
                    index_namespace = baseline.get('index_namespace')
                    index_run = baseline.get('index_run')
                    index_manifest = baseline.get('index_manifest_key')
                    enterprise_manifest = baseline.get('enterprise_manifest')
                    inventory_captured_at = baseline.get('inventory_captured_at')
                if latest['inventory'] is not None:
                    from app.business.inventory_index import publish_index
                    latest_inventory = InventorySnapshot.model_validate_json(
                        read_table(self.lake,latest['inventory']).to_pylist()[0]['snapshot_json'])
                    index_namespace = self.lake.prefix + suffix
                    index_manifest = f'gold/enterprise/{suffix}/inventory.json'
                    self.lake.put_json(index_manifest,{'dimensions':latest['dimensions']})
                    index_run = publish_index(self.journal.store,index_namespace,latest_inventory,index_manifest)
                manifest = {'index_namespace':index_namespace,'index_run':index_run,
                    'index_manifest_key':index_manifest if index_run else None,
                    'coverage':latest.get('coverage', baseline.get('coverage', {})),
                    'enterprise_manifest':enterprise_manifest,
                    'inventory_captured_at':inventory_captured_at,
                    'analysis_settings':{'threshold':self.pipeline.analytics.threshold,'reserve':self.pipeline.analytics.buffer_rate},
                    'run_id':rid,'source':source,'scope':scope,'daily':daily,
                    'gold':gold,'bronze':checkpoints['bronze'],'previous_manifest':valid['base_manifest'],
                    'mapping_version':mapping_version,'schema_version':schema_version}
                key = f'gold/{suffix}/manifest.json'
                self.lake.put_json(key,manifest)
                checkpoint('gold',{'manifest_key':key,'fingerprint':fingerprint(encoded(manifest))})
            manifest = self._verified_manifest(checkpoints['gold'])
            self.hook('before_publish')
            heartbeat.check()
            self.journal.publish(rid,fence,expected_run=valid['expected_run'], expected_manifest=valid['base_manifest'])
            self.hook('after_publish')
            return manifest
        except Exception as exc:
            try:
                self.journal.fail(rid,fence,'DAY_REVISION_CONFLICT' if isinstance(exc,DayRevisionConflict) else 'COVERAGE_DECREASE' if isinstance(exc,CoverageRejected) else 'INVALID_ARTIFACT' if isinstance(exc,ValueError) else 'PROCESSING_FAILED',
                                  retryable=not isinstance(exc,ValueError))
            except LeaseLost:
                pass  # Includes a lost response after successful publication.
            raise
        finally:
            heartbeat.close()

    def _verified_manifest(self, artifact):
        manifest = self._json(artifact['manifest_key'])
        if fingerprint(encoded(manifest)) != artifact['fingerprint']:
            raise ValueError('Published manifest fingerprint mismatch')
        rows = read_table(self.lake,manifest['gold']).to_pylist()
        if len(rows) != 1:
            raise ValueError('Invalid Gold summary')
        AnalyticsSummary.model_validate_json(rows[0]['summary_json'])
        # Check every pinned dependency before accepting a recovered publication.
        for item in manifest['daily'].values():
            if read_table(self.lake,item['usage']).num_rows != item['rows']:
                raise ValueError('Unreadable or incomplete history')
            if item['inventory'] is not None:
                read_table(self.lake,item['inventory'])
        return manifest
