"""Compute usage evidence from persisted daily observations of the active run."""
import json
from collections import defaultdict
import pyarrow as pa
from uuid import uuid4
from app.storage.table_reader import read_table
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.analytics.installation_usage import InstallationUsageAccumulator


def main():
    settings = get_settings()
    if settings.sam_data_source != 'mock':
        raise RuntimeError('This demo analysis command requires mock source')
    lake = get_pipeline().store
    store = BusinessStore(settings.database_url)
    with store.connect() as db:
        head = db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(lake.prefix,)).fetchone()
    manifest = json.loads(lake.get_bytes(head['manifest_key']))
    aggregate = InstallationUsageAccumulator()
    for i, partition in enumerate(manifest['daily'],1):
        rows = read_table(lake, partition, columns=['machine_id','license_pool_id','used']).to_pylist()
        aggregate.add_day(partition['date'], rows)
        if i%30 == 0: print(f'{i} days analyzed',flush=True)
    rows = aggregate.results()
    root = 'gold/enterprise/'+manifest['version']+'/'+str(uuid4())
    key = lake.delta.replace(root+'/installation_usage', pa.Table.from_pylist(rows)).to_dict()
    if read_table(lake, key).num_rows != len(rows):
        raise RuntimeError('Invalid persisted analysis')
    summary = defaultdict(lambda: {'installations_observed':0,'installations_active':0,'installations_without_usage':0,'installations_incomplete':0})
    for row in rows:
        item = summary[row['license_pool_id']]
        item['installations_observed'] += 1
        if row['active_days']:
            item['installations_active'] += 1
        elif row['complete_coverage']:
            item['installations_without_usage'] += 1
        if not row['complete_coverage']:
            item['installations_incomplete'] += 1
    report = {'period_start':manifest['daily'][0]['date'],'period_end':manifest['daily'][-1]['date'],
              'days':len(manifest['daily']), 'products':[{'license_pool_id':pool,**value} for pool,value in sorted(summary.items())],
              'detail_key':key}
    report_key = root+'/installation-usage.json'
    lake.put_json(report_key,report)
    manifest['installation_usage'] = {'key':report_key,'detail_key':key,'rows':len(rows)}
    manifest_key = root+'/manifest-with-usage.json'
    lake.put_json(manifest_key,manifest)
    with store.connect() as db:
        current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE',(lake.prefix,)).fetchone()
        if not current or current['run_id'] != head['id']:
            raise RuntimeError('Inventory changed during analysis; report was not activated')
        run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s FOR UPDATE', (head['id'],)).fetchone()
        if run['manifest_key'] != head['manifest_key']:
            raise RuntimeError('Analysis changed; report was not activated')
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s',(manifest_key,head['id']))
    print({'installations':len(rows),'days':report['days'],'products':len(summary),'activated':True},flush=True)


if __name__ == '__main__': main()
