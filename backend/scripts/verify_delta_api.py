"""Read-only API verification for the migrated local demonstration."""
import json
import os
import httpx
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.config import get_settings
from scripts.activate_delta import business_fingerprint


def main():
    with httpx.Client(base_url='http://backend:8000', timeout=180) as client:
        response = client.post('/api/v1/business/login', json={
            'email': 'admin@sam.demo', 'password': os.environ['SAM_DEMO_PASSWORD']})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()
        workspaces = get('/api/v1/business/me')['workspaces']
        assert workspaces
        results = []
        for workspace in workspaces:
            wid = workspace['id']
            root = f'/api/v1/business/workspaces/{wid}'
            products = get(root+'/inventory/software')
            inventory = get(root+'/inventory?entity=machines&limit=1')
            report = get(root+'/inventory/installation-usage')
            get(root+'/cases')
            get(root+'/costs')
            get(root+'/portfolio')
            summary = get('/api/v1/analytics/summary?workspace_id='+wid)
            assert inventory['available'] and report['available']
            if wid == 'demo':
                assert len(products) == 30
                assert inventory['counts']['machines'] == 138500
                rhel = next(p for p in products if p['name'] == 'Red Hat Enterprise Linux 9')
                evidence = get(root+'/inventory/installation-usage/machines?pool='+rhel['software_id'])
                assert evidence['available'] and evidence['total'] > 0
            results.append({'workspace':wid,'products':len(products),
                            'machines':inventory['counts']['machines'],'pools':summary['pools_total']})
        client.post('/api/v1/business/logout').raise_for_status()
    lake = get_pipeline().store
    audit = json.loads(lake.get_bytes('gold/migrations/activation.json'))
    with BusinessStore(get_settings().database_url).connect() as db:
        assert business_fingerprint(db) == audit['business_fingerprint']
    print(json.dumps({'verified': True, 'business_data_unchanged':True, 'workspaces':results}), flush=True)


if __name__ == '__main__':
    main()
