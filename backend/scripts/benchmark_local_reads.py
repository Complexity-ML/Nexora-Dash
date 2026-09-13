"""Bounded read benchmark of the local demo; no production-network claim."""
import argparse
import asyncio
import json
from math import ceil
from statistics import median
from time import perf_counter
from urllib.parse import urlsplit, quote
import httpx
from app.config import get_settings


def distribution(values):
    ordered = sorted(values)
    return {'samples': len(values), 'median_ms': round(median(ordered), 1),
            'p95_ms': round(ordered[ceil(.95*len(ordered))-1], 1), 'max_ms': round(max(ordered), 1)} if values else {'samples': 0}


async def benchmark(base, workspace, repeats, concurrency, mixed=False):
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', 'backend') or parsed.username or parsed.password:
        raise ValueError('This command is restricted to the local demonstration')
    if not 1 <= repeats <= 20 or not 1 <= concurrency <= 8:
        raise ValueError('Use at most 20 reads per route and concurrency at most 8')
    settings = get_settings()
    async with httpx.AsyncClient(base_url=base, timeout=30, follow_redirects=False) as client:
        response = await client.post('/api/v1/business/login', json={'email':'admin@sam.demo','password':settings.sam_demo_password})
        if response.status_code != 200:
            raise RuntimeError('Local demo authentication failed')
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        prefix = '/api/v1/business/workspaces/' + quote(workspace, safe='')
        routes = {'machines': prefix+'/inventory?entity=machines&limit=25',
                  'software': prefix+'/inventory/software',
                  'installation_usage': prefix+'/inventory/installation-usage'}
        semaphore = asyncio.Semaphore(concurrency)
        async def read(path):
            async with semaphore:
                started = perf_counter()
                try:
                    result = await client.get(path)
                    return {'ms': (perf_counter()-started)*1000, 'status':result.status_code, 'bytes':len(result.content)}
                except httpx.HTTPError:
                    return {'ms': (perf_counter()-started)*1000, 'status':'transport_error', 'bytes':0}
        try:
            report = {'concurrency':concurrency,'repeats':repeats,'mode':'mixed' if mixed else 'per_route','routes':{}}
            firsts, samples = {}, {}
            if mixed:
                for name, path in routes.items():
                    firsts[name] = await read(path)
                async def named_read(name, path):
                    return name, await read(path)
                burst = await asyncio.gather(*(named_read(name, path)
                    for _ in range(repeats) for name, path in routes.items()))
                for name in routes:
                    samples[name] = [value for route, value in burst if route == name]
            for name, path in routes.items():
                first = firsts[name] if mixed else await read(path)
                values = samples[name] if mixed else await asyncio.gather(*(read(path) for _ in range(repeats)))
                ok = [v for v in values if v['status']==200]
                report['routes'][name] = {'first_observed_ms':round(first['ms'],1),
                    'first_status':first['status'], 'body_bytes':first['bytes'],
                    **distribution([v['ms'] for v in ok]), 'failures':len(values)-len(ok)}
            return report
        finally:
            await client.post('/api/v1/business/logout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://backend:8000')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--repeats', type=int, default=8)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--mixed', action='store_true', help='Interleave all routes within the concurrency limit')
    args = parser.parse_args()
    result = asyncio.run(benchmark(args.base, args.workspace, args.repeats, args.concurrency, args.mixed))
    print(json.dumps(result), flush=True)
    return 1 if any(v['failures'] or v['first_status'] != 200 for v in result['routes'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
