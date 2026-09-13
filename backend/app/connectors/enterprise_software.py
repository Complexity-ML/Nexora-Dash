"""Stable synthetic software dimensions derived from actual generated machines.

Entitlement metrics and quantities below are demo assumptions, not vendor rules.
"""
import hashlib
import json
from pathlib import Path
from app.connectors.demo import CATALOG


def software_dimensions(inventory):
    names = {}
    for machine in inventory['machines']:
        names[machine['operating_system']] = 'operating_system'
        for name in machine['applications']:
            names.setdefault(name, 'application')
        for name in machine['services']:
            names.setdefault(name, 'service')
    pools = {name: pool for pool, name, *_ in CATALOG}
    identifier = lambda name: 'sw-' + hashlib.sha256(name.encode()).hexdigest()[:16]
    products = [{'software_id': identifier(name), 'name': name, 'category': category,
                 'license_pool_id': pools.get(name)} for name, category in sorted(names.items())]
    installations = []
    for machine in inventory['machines']:
        for name in sorted({machine['operating_system'], *machine['applications'], *machine['services']}):
            software_id = identifier(name)
            installations.append({'installation_id':f"{machine['machine_id']}:{software_id}",
                                  'machine_id':machine['machine_id'], 'software_id':software_id})
    entitlements = demo_entitlements(products, inventory['subsidiaries'])
    return {'products':products, 'installations':installations, 'entitlements':entitlements}


def demo_entitlements(products, subsidiaries):
    """Map fixed mock-source records; quantities never depend on installations."""
    fixture = json.loads(Path(__file__).with_name('demo_license_source.json').read_text())
    by_name = {p['name']: p['software_id'] for p in products}
    allowed = {s['subsidiary_id'] for s in subsidiaries}
    known = {r['product'] for r in fixture}
    if set(by_name) - known:
        raise ValueError('Demo license model missing for unknown product')
    return [{'entitlement_id': 'source-'+by_name[r['product']]+'-'+r['subsidiary_id'],
             'software_id': by_name[r['product']], 'subsidiary_id':r['subsidiary_id'],
             'metric':r['metric'], 'quantity':r['quantity'], 'synthetic':True}
            for r in fixture if r['product'] in by_name and r['subsidiary_id'] in allowed]
