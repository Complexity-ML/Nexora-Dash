"""Bounded benchmark of direct Python reads in the configured mock environment."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from math import ceil
from statistics import median
from time import perf_counter
from app.config import get_settings
from app.business import workspace_service as business, inventory_service as inventory
from app.dash_ui.context import Context


def distribution(values):
    ordered = sorted(values)
    return {'samples': len(values), 'median_ms': round(median(ordered), 1),
            'p95_ms': round(ordered[ceil(.95*len(ordered))-1], 1), 'max_ms': round(max(ordered), 1)} if values else {'samples': 0}



def benchmark(workspace,repeats,concurrency,mixed=False):
    settings=get_settings()
    if settings.sam_data_source!='mock':
        raise ValueError('This benchmark is restricted to mock data')
    if not 1<=repeats<=20 or not 1<=concurrency<=8:
        raise ValueError('Use at most 20 repetitions and 8 concurrent reads')
    store=business.get_business_store()
    auth=business.login(business.Login(email='admin@sam.demo',password=settings.sam_demo_password),store)
    try:
        spaces=business.me(auth['user'],store)['workspaces']
        active=next((w for w in spaces if w['id']==workspace),None)
        if not active:raise ValueError('Workspace is not accessible')
        def read(name):
            ctx=Context(auth['user'],store,active,spaces)
            started=perf_counter()
            try:
                if name=='machines':value=ctx.call(inventory.inventory,workspace,lake=True,entity='machines',limit=25)
                elif name=='software':value=ctx.call(inventory.inventory_software,workspace,lake=True)
                else:value=ctx.call(inventory.installation_usage,workspace,lake=True)
                return {'ms':(perf_counter()-started)*1000,'ok':True,'bytes':len(json.dumps(value,default=str))}
            except Exception:
                return {'ms':(perf_counter()-started)*1000,'ok':False,'bytes':0}
        names=['machines','software','installation_usage']
        firsts={name:read(name) for name in names}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            if mixed:
                tasks=names*repeats
                results=list(pool.map(read,tasks))
                samples={n:[v for k,v in zip(tasks,results) if k==n] for n in names}
            else:samples={n:list(pool.map(read,[n]*repeats)) for n in names}
        return {'transport':'direct Python','concurrency':concurrency,'repeats':repeats,
            'reads':{n:{'first_ms':round(firsts[n]['ms'],1),'first_ok':firsts[n]['ok'],
                'bytes':firsts[n]['bytes'],**distribution([v['ms'] for v in samples[n] if v['ok']]),
                'failures':sum(not v['ok'] for v in samples[n])} for n in names}}
    finally:business.logout(auth['token'],auth['user'],store)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--repeats',type=int,default=4)
    parser.add_argument('--concurrency',type=int,default=2)
    parser.add_argument('--mixed',action='store_true')
    args=parser.parse_args()
    result=benchmark(args.workspace,args.repeats,args.concurrency,args.mixed)
    print(json.dumps(result))
    return int(any(v['failures'] or not v['first_ok'] for v in result['reads'].values()))

if __name__=='__main__':raise SystemExit(main())
