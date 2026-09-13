"""Bounded read-only aggregate benchmark of the active mock inventory index."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from time import perf_counter
from app.config import get_settings
from app.business.store import BusinessStore
from app.bi.inventory_snapshot import inventory_counts
from scripts.benchmark_local_reads import distribution


def benchmark(repeats, concurrency):
    settings=get_settings()
    if settings.sam_data_source != 'mock':
        raise ValueError('This benchmark is restricted to the mock inventory')
    store=BusinessStore(settings.database_url)
    with store.connect() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout='15s'")
        head=db.execute('''SELECT r.id FROM demo_generation d JOIN inventory_heads h ON h.namespace=d.prefix
            JOIN inventory_runs r ON r.id=h.run_id WHERE d.id=1''').fetchone()
        if head is None:
            raise ValueError('No active demo inventory index')
        selected=[r['subsidiary'] for r in db.execute("SELECT DISTINCT subsidiary FROM inventory_entities WHERE run_id=%s AND entity='sites' AND subsidiary IS NOT NULL",(head['id'],)).fetchall()]
        expected=db.execute("SELECT count(*) AS n FROM inventory_entities WHERE run_id=%s AND entity='machines' AND subsidiary=ANY(%s)",(head['id'],selected)).fetchone()['n']
    def read(_):
        started=perf_counter()
        with store.connect() as db:
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SET LOCAL statement_timeout='15s'")
            rows=inventory_counts(db,head['id'],selected)
        if sum(r['machines'] for r in rows) != expected:
            raise ValueError('Aggregate count differs from indexed machines')
        return (perf_counter()-started)*1000,len(rows)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results=list(pool.map(read,range(repeats)))
    return {'scope':'local_mock_index','concurrency':concurrency,'machines':expected,
            'subsidiaries':len(selected),'aggregate_rows':sorted({r[1] for r in results}),
            'timing':distribution([r[0] for r in results])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,choices=range(1,21),default=8,metavar='1..20')
    parser.add_argument('--concurrency',type=int,choices=range(1,9),default=4,metavar='1..8')
    args=parser.parse_args()
    try:
        print(json.dumps(benchmark(args.repeats,args.concurrency)))
    except Exception:
        print(json.dumps({'status':'failed','error_code':'BI_INVENTORY_BENCHMARK_FAILED'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
