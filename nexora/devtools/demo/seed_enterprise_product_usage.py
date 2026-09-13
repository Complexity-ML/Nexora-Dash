"""Extend the active mock lake with daily activity for installed non-pool products."""
from datetime import date
from hashlib import sha256
import json
from uuid import uuid4
import pyarrow as pa
from app.storage.table_reader import read_table
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.connectors.enterprise_product_usage import ProductUsageScenario, VERSION
from app.analytics.product_usage import ProductUsageAccumulator


def main():
    settings = get_settings()
    if settings.sam_data_source != 'mock':
        raise RuntimeError('Requires mock source')
    lake = get_pipeline().store
    business = BusinessStore(settings.database_url)
    with business.connect() as db:
        head = db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(lake.prefix,)).fetchone()
    if not head or not head['manifest_key'].startswith('gold/enterprise/'):
        raise RuntimeError('No enterprise inventory is active')
    manifest = json.loads(lake.get_bytes(head['manifest_key']))
    dimensions = {name:read_table(lake, manifest['dimensions'][name]).to_pylist()
                  for name in ('machines','products','installations')}
    days = sorted(date.fromisoformat(p['date']) for p in manifest['daily'])
    if len(set(days)) != len(days) or (days[-1]-days[0]).days+1 != len(days):
        raise ValueError('Demo generation requires one partition for every day')
    previous = manifest.get('installation_usage')
    if not previous:
        raise RuntimeError('Analyze the existing pool installations before extending the report')
    previous_report = json.loads(lake.get_bytes(previous['key']))
    if previous_report['days'] != len(days) or previous_report['period_start'] != str(days[0]) or previous_report['period_end'] != str(days[-1]):
        raise ValueError('Existing analysis has a different observation window')
    digest = sha256(json.dumps({'dimensions':manifest['dimensions'],'days':[str(d) for d in days]},sort_keys=True).encode()).hexdigest()[:16]
    version = f'{VERSION}-{digest}-{uuid4()}'
    scenario = ProductUsageScenario(**dimensions)
    if not scenario.rows:
        raise ValueError('No installed non-pool products')
    accumulator = ProductUsageAccumulator(scenario.table(days[0]))
    partitions = []
    for index, day in enumerate(days,1):
        key = f'silver/enterprise/{version}/date={day}/observations.parquet'
        table = scenario.table(day)
        lake.put_parquet(key.replace('silver/','bronze/',1),table)
        ref = lake.delta.replace_day(f'silver/enterprise/{version}/product_usage_daily', day, table).to_dict()
        ref['observation_date'] = str(day)
        table = read_table(lake, ref)
        accumulator.add_day(day,table)
        partitions.append({**ref,'date':str(day),'rows':table.num_rows})
        if index%10 == 0 or index == len(days):
            print(json.dumps({'days_verified':index,'days':len(days),'rows_per_day':table.num_rows}),flush=True)
    for partition in partitions:
        partition['version'] = partitions[-1]['version']
    details = accumulator.table()
    root = f'gold/enterprise/{version}/{uuid4()}'
    lake.delta.replace(root+'/product_usage', details)
    # Preserve historical application usage, explicitly keyed by its installed product.
    old = read_table(lake, previous.get('detail_key') or previous_report['detail_key']).to_pylist()
    products = {p['software_id']:p for p in dimensions['products']}
    pool_products = {p['license_pool_id']:p for p in products.values() if p.get('license_pool_id')}
    old = [{**r,'software_id':pool_products[r['license_pool_id']]['software_id'],'measurement':'application_execution',
            'last_used_on':date.fromisoformat(r['last_used_on']) if isinstance(r.get('last_used_on'),str) else r.get('last_used_on')}
           for r in old if r.get('license_pool_id') in pool_products]
    # Arrow promotes columns missing in either dataset to nullable values.
    combined = pa.concat_tables([pa.Table.from_pylist(old),details],promote_options='permissive')
    combined_key = lake.delta.replace(root+'/installation_usage', combined).to_dict()
    summaries = [{**p,'software_id':pool_products[p['license_pool_id']]['software_id'],'measurement':'application_execution'}
                 for p in previous_report['products'] if p.get('license_pool_id') in pool_products]
    kinds = {'operating_system':'system_uptime','application':'application_execution','service':'service_runtime'}
    summaries += [{**p,'license_pool_id':None,'measurement':kinds[products[p['software_id']]['category']]}
                  for p in accumulator.summary()]
    report = {'days':len(days),'period_start':str(days[0]),'period_end':str(days[-1]),
              'products':summaries,'detail_key':combined_key}
    report_key = root+'/installation-usage.json'
    lake.put_json(report_key,report)
    updated = {**manifest,'product_usage_daily':partitions,
               'product_usage_observations':sum(p['rows'] for p in partitions),
               'installation_usage':{'key':report_key,'detail_key':combined_key,'rows':combined.num_rows}}
    manifest_key = root+'/manifest.json'
    lake.put_json(manifest_key,updated)
    with business.connect() as db:
        current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE',(lake.prefix,)).fetchone()
        if not current or current['run_id'] != head['id']:
            raise RuntimeError('Inventory changed; generated data was not activated')
        current_run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s',(head['id'],)).fetchone()
        if current_run['manifest_key'] != head['manifest_key']:
            raise RuntimeError('Analysis changed; generated data was not activated')
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s',(manifest_key,head['id']))
    print(json.dumps({'activated':True,'days':len(days),'products':len(summaries),
                      'installations':combined.num_rows,'new_observations':updated['product_usage_observations']}),flush=True)


if __name__ == '__main__': main()
