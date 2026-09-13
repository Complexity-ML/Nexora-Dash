"""Read software dimensions from the same immutable run as inventory counts."""
from collections import defaultdict
from app.storage.table_reader import read_table


def enrich_software(rows, manifest, lake, all_catalog):
    dimensions = manifest.get('dimensions', {})
    if 'products' not in dimensions:
        return rows or []
    def read(name):
        item = dimensions.get(name)
        return read_table(lake, item).to_pylist() if item else []
    products = {p['software_id']:p for p in read('products')}
    by_name = defaultdict(list)
    for product in products.values():
        by_name[product['name']].append(product)
    subsidiaries = {s['subsidiary_id']:s for s in read('subsidiaries')}
    rights = defaultdict(list)
    # Current generated rights cover the enterprise. Do not imply that global rights
    # have been allocated to a workspace that only follows part of that enterprise.
    if all_catalog:
        for right in read('entitlements'):
            rights[right['software_id']].append({**right, 'subsidiary_name':subsidiaries.get(right.get('subsidiary_id'), {}).get('name')})
    result = []
    for row in products.values() if rows is None else rows:
        product = products.get(row.get('software_id'))
        if product is None and not row.get('software_id') and len(by_name[row['name']]) == 1:
            product = by_name[row['name']][0]
        if product is None:
            result.append(row)
            continue
        result.append({**row, **product, 'entitlements':rights[product['software_id']],
                       'entitlement_scope':'enterprise' if all_catalog else 'not_allocated'})
    return result


def snapshot_installations(snapshot):
    """Keep explicit product identity; names only identify legacy machine fields."""
    from hashlib import sha256
    products = {p.software_id:p.model_dump() for p in snapshot.products}
    named_ids = defaultdict(set)
    for product in snapshot.products:
        named_ids[product.name].add(product.software_id)
    installed = defaultdict(set)
    for item in snapshot.installations:
        installed[item.machine_id].add(item.software_id)
    for machine in snapshot.machines:
        for category, names in [('operating_system',[machine.operating_system]),
                                ('application',machine.applications),('service',machine.services)]:
            for name in names:
                if not name or name == 'Inventory agent':
                    continue
                candidates = named_ids[name]
                # Explicit installations already establish which same-named product is present.
                if installed[machine.machine_id] & candidates:
                    continue
                if len(candidates) == 1:
                    software_id = next(iter(candidates))
                else:
                    # An ambiguous legacy name must not be assigned to an arbitrary pool.
                    software_id = 'inventory-'+sha256(name.encode()).hexdigest()[:24]
                    products.setdefault(software_id, {'software_id':software_id,
                        'name':name,'category':category,'license_pool_id':None})
                installed[machine.machine_id].add(software_id)
    return products, installed


def snapshot_software(snapshot, pools):
    if snapshot is None:
        return []
    products, installed = snapshot_installations(snapshot)
    counts = defaultdict(int)
    for software_ids in installed.values():
        for software_id in software_ids:
            product = products[software_id]
            if pools is None or (product.get('license_pool_id') or software_id) in pools:
                counts[software_id] += 1
    subsidiaries = {s.subsidiary_id:s.name for s in snapshot.subsidiaries}
    return [{'machines':count,**products[software_id],
             'entitlements':[{**r.model_dump(), 'subsidiary_name':subsidiaries.get(r.subsidiary_id)} for r in snapshot.entitlements if pools is None and r.software_id == software_id],
             'entitlement_scope':'enterprise' if pools is None else 'not_allocated'}
            for software_id,count in sorted(counts.items(),key=lambda item:(-item[1],products[item[0]]['name'],item[0]))]
