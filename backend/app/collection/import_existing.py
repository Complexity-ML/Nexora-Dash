"""Import pinned existing Delta history without rewriting inventory/observations.

Legacy collectors must be stopped for final publication: they do not participate
in collection stream leases. Preparation itself changes no active pointer.
"""
import json
from io import BytesIO
from collections import defaultdict
import pyarrow as pa
import pyarrow.parquet as pq
from app.collection.journal import fingerprint, LeaseLost
from app.collection.lease import LeaseHeartbeat
from app.collection.runner import encoded
from app.connectors.digimon import map_digimon_payload
from app.storage import pool_tables
from app.collection.enterprise_validation import verify_enterprise
from app.collection.quality import enterprise_profile


def prepare_existing(pipeline, journal, *, source, scope):
    lake=pipeline.store
    ref=pool_tables.reference(lake)
    if ref is None:
        raise ValueError('Existing Delta pool history required')
    with journal.store.connect() as db:
        head=db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(lake.prefix,)).fetchone()
    if head is None:
        raise ValueError('Existing inventory index required')
    enterprise=json.loads(lake.get_bytes(head['manifest_key']))
    evidence={'pool_reference':ref.to_dict(),'index_run':head['id'],
        'index_manifest':head['manifest_key'],'index_fingerprint':fingerprint(encoded(enterprise)),
        'source':source,'scope':scope,'analysis_settings':{'threshold':pipeline.analytics.threshold,'reserve':pipeline.analytics.buffer_rate}}
    run=journal.register(namespace=lake.prefix,source=source,scope=scope,snapshot_id='legacy-import',
        source_revision=fingerprint(encoded(evidence)),fingerprint=fingerprint(encoded(evidence)),
        mapping_version='legacy-import-2',schema_version='1')
    checkpoint=journal.checkpoints(run['id'])
    if 'gold' in checkpoint:
        return checkpoint['gold']
    fence=journal.claim(run['id'],'legacy-import',seconds=3600)
    heartbeat = LeaseHeartbeat(journal, run['id'], fence, 3600).start()
    suffix=f"collections/{run['id']}/import-{fence}"
    try:
        if 'bronze' not in checkpoint:
            evidence_key=f'bronze/{suffix}/import-evidence.json'
            lake.put_json(evidence_key,evidence)
            journal.checkpoint(run['id'],fence,'bronze',{'key':evidence_key,'fingerprint':fingerprint(encoded(evidence))})
        table=lake.delta.read(ref)
        grouped=defaultdict(list)
        for row in table.to_pylist():
            day=str(row.pop('observation_date'))
            grouped[day].append(row)
        if not grouped:
            raise ValueError('Cannot import empty history')
        last=max(grouped)
        matched=None
        for key in lake.list_keys(f'bronze/digimon/date={last}/'):
            for row_index,row in enumerate(pq.read_table(BytesIO(lake.get_bytes(key))).to_pylist()):
                raw=json.loads(row['payload_json'])
                snapshot=map_digimon_payload(raw)
                usage=[v.model_dump(mode='json') for v in snapshot.usage]
                if snapshot.source==source and sorted(usage,key=encoded)==sorted(grouped[last],key=encoded):
                    matched={'key':key,'format':'parquet','row_index':row_index,'fingerprint':fingerprint(row['payload_json'].encode())}
                    break
            if matched: break
        if matched is None:
            raise ValueError('Latest pool snapshot has no matching archived source')
        enterprise_checks = verify_enterprise(lake, enterprise)
        inventory_copy=checkpoint.get('silver',{}).get('enterprise_manifest') or f'gold/enterprise/{suffix}/inventory.json'
        if 'silver' not in checkpoint:
            lake.put_json(inventory_copy,enterprise)
        if 'validated' not in checkpoint:
            journal.checkpoint(run['id'],fence,'validated',{'pool_rows':len(table),
                'days':len(grouped),'expected_run':None,'source_evidence':evidence,
                'enterprise_checks':enterprise_checks})
        daily={day:{'usage':{**ref.to_dict(),'observation_date':day},'inventory':None,
            'rows':len(rows),'dimensions':{},'bronze':matched if day==last else None}
            for day,rows in sorted(grouped.items())}
        if 'silver' not in checkpoint:
            journal.checkpoint(run['id'],fence,'silver',{'daily':daily,'enterprise_manifest':inventory_copy})
        summary=pipeline.analytics.compute_table(table)
        gold=lake.delta.replace(f'gold/{suffix}/analytics',pa.table({'summary_json':[summary.model_dump_json()]})).to_dict()
        manifest={'run_id':run['id'],'source':source,'scope':scope,'daily':daily,'gold':gold,
            'index_namespace':lake.prefix,'index_run':head['id'],'index_manifest_key':inventory_copy,
            'enterprise_manifest':inventory_copy,'inventory_captured_at':head['captured_at'].isoformat(),
            'analysis_settings':{'threshold':pipeline.analytics.threshold,'reserve':pipeline.analytics.buffer_rate},
            'previous_manifest':None,'mapping_version':'legacy-import-2','schema_version':'1',
            'source_evidence':evidence,'coverage':enterprise_profile(lake,enterprise)}
        key=f'gold/{suffix}/manifest.json'; lake.put_json(key,manifest)
        artifact={'manifest_key':key,'fingerprint':fingerprint(encoded(manifest))}
        heartbeat.check()
        journal.checkpoint(run['id'],fence,'gold',artifact)
        # Prepared only. Leave retryable so activation can claim its own lease.
        journal.fail(run['id'],fence,'AWAITING_ACTIVATION')
        return artifact
    except Exception:
        try: journal.fail(run['id'],fence,'IMPORT_FAILED')
        except LeaseLost: pass
        raise
    finally:
        heartbeat.close()


def verify_existing(pipeline,journal,artifact):
    from app.collection.runner import CollectionRunner
    lake=pipeline.store
    manifest=CollectionRunner(pipeline,journal)._verified_manifest(artifact)
    evidence=manifest['source_evidence']
    if evidence['analysis_settings'] != {'threshold':pipeline.analytics.threshold,'reserve':pipeline.analytics.buffer_rate}:
        raise ValueError('Analysis settings changed after preparation')
    enterprise=json.loads(lake.get_bytes(manifest['enterprise_manifest']))
    checks=verify_enterprise(lake,enterprise)
    validated=journal.checkpoints(manifest['run_id'])['validated']
    if checks != validated['enterprise_checks']:
        raise ValueError('Enterprise dependencies changed after preparation')
    reference=pool_tables.reference(lake)
    if reference is None or reference.to_dict()!=evidence['pool_reference']:
        raise ValueError('Pool history changed after preparation')
    with journal.store.connect() as db:
        head=db.execute('SELECT r.id,r.manifest_key FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(lake.prefix,)).fetchone()
    if not head or head['id']!=evidence['index_run'] or head['manifest_key']!=evidence['index_manifest']:
        raise ValueError('Inventory changed after preparation')
    if fingerprint(encoded(json.loads(lake.get_bytes(head['manifest_key']))))!=evidence['index_fingerprint']:
        raise ValueError('Inventory manifest content changed')
    return manifest


def activate_existing(pipeline,journal,artifact):
    manifest=verify_existing(pipeline,journal,artifact)
    lake=pipeline.store
    current=journal.head(lake.prefix,manifest['source'],manifest['scope'])
    if current and current['run_id']==manifest['run_id']:
        return manifest
    fence=journal.claim(manifest['run_id'],'legacy-activation',seconds=3600)
    try:
        journal.publish(manifest['run_id'],fence,expected_run=None,expected_manifest=None)
        return manifest
    except Exception:
        try:
            journal.fail(manifest['run_id'],fence,'ACTIVATION_FAILED')
        except LeaseLost:
            pass
        raise
