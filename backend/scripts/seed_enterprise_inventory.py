"""Build a one-year fictitious enterprise lake, then publish its read index atomically."""
import argparse
import hashlib
import json
from uuid import uuid4
from app.storage.inventory_tables import inventory_table
from app.storage.table_reader import read_table
from datetime import datetime, timedelta, timezone
from time import perf_counter
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.business.inventory_index import publish_index
from app.connectors.enterprise_inventory import enterprise_inventory, daily_observation, CONTRACTORS
from app.models.inventory import InventorySnapshot
from app.connectors.enterprise_software import software_dimensions

VERSION = 'enterprise-v7'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',type=int,default=365)
    args = parser.parse_args()
    if not 1 <= args.days <= 365: raise ValueError('days must be between 1 and 365')
    settings = get_settings()
    if settings.sam_data_source != 'mock': raise RuntimeError('Requires mock source')
    store = get_pipeline().store
    end = datetime(2026,9,11,tzinfo=timezone.utc)
    started = perf_counter()
    raw = enterprise_inventory(end, contractors=CONTRACTORS)
    raw.update(software_dimensions(raw))
    model = InventorySnapshot(captured_at=end,source='digimon-mock',**raw)
    fingerprint = hashlib.sha256(json.dumps({k:v for k,v in raw.items() if k != 'observations'},sort_keys=True).encode()).hexdigest()[:12]
    version = f'{VERSION}-{fingerprint}-{args.days}-{uuid4()}'
    dimensions = {}
    for entity in ('subsidiaries','sites','machines','users','products','installations','entitlements'):
        ref = store.delta.replace(f'silver/enterprise/{version}/{entity}', inventory_table(entity, raw[entity])).to_dict()
        store.put_parquet(f'bronze/enterprise/{version}/{entity}.parquet',raw[entity])
        dimensions[entity] = {**ref,'rows':len(raw[entity])}
    daily = []
    for offset in range(args.days):
        at = end-timedelta(days=args.days-1-offset)
        for row in raw['observations']:
            daily_observation(row, at)
        store.put_parquet(f'bronze/enterprise/{version}/daily/date={at.date()}/observations.parquet',raw['observations'])
        ref = store.delta.replace_day(f'silver/enterprise/{version}/daily', at.date(), inventory_table('observations', raw['observations'])).to_dict()
        daily.append({**ref,'observation_date':str(at.date()),'date':str(at.date()),'rows':len(raw['observations'])})
        if (offset+1)%30 == 0 or offset+1 == args.days:
            print(f'{offset+1}/{args.days} days persisted',flush=True)
    # Validate object existence and row counts independently of the generator.
    for item in daily:
        item['version'] = daily[-1]['version']
    for item in [*dimensions.values(),*daily]:
        count = read_table(store, item).num_rows
        if count != item['rows']: raise RuntimeError(f'Invalid row count: {item.get('path')}')
    manifest = {'version':version,'storage_format':'delta','source':'synthetic','employees':sum(u.employment_type=='employee' for u in model.users),
                'contractors':sum(u.employment_type=='contractor' for u in model.users),
                'machines':len(model.machines),'dimensions':dimensions,'daily':daily,
                'observations':sum(x['rows'] for x in daily),'days':args.days}
    manifest_key = f'gold/enterprise/{version}/manifest.json'
    store.put_json(manifest_key,manifest)
    # Read back the actual final partition before indexing it.
    raw['observations'] = read_table(store, daily[-1]).to_pylist()
    model = InventorySnapshot(captured_at=end,source='digimon-mock',**raw)
    run = publish_index(BusinessStore(settings.database_url),store.prefix,model,manifest_key)
    print({'run':run,'users':len(model.users),'machines':len(model.machines),
           'days':args.days,'observations':manifest['observations'],
           'seconds':round(perf_counter()-started,2)},flush=True)


if __name__ == '__main__': main()
