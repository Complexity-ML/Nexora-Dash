from datetime import datetime, timezone
import pytest
from app.connectors.demo import snapshot
from app.connectors.demo_inventory import inventory
from app.models.inventory import map_inventory_payload


def payload():
    at = datetime(2026,9,11,tzinfo=timezone.utc)
    return {**snapshot(at), 'inventory': inventory(at)}


def test_inventory_demo_links_and_determinism():
    raw = payload()
    assert raw == payload()
    model = map_inventory_payload(raw)
    assert len(model.machines) == 120 and len(model.users) == 60
    assert len(model.observations) == 240
    assert sum(m.kind == 'virtual' for m in model.machines) == 40
    assert any('Red Hat' in m.operating_system for m in model.machines)
    assert map_inventory_payload({'capturedAt': raw['capturedAt']}) is None


@pytest.mark.parametrize('field,value', [('machine_id','missing'), ('user_id','missing'), ('license_pool_id','missing')])
def test_inventory_rejects_broken_relationships(field,value):
    raw = payload()
    raw['inventory']['observations'][0][field] = value
    with pytest.raises(ValueError): map_inventory_payload(raw)


def test_inventory_rejects_duplicate_entities_and_observations():
    for collection in ('sites','machines','users','observations'):
        raw = payload()
        raw['inventory'][collection].append(raw['inventory'][collection][0])
        with pytest.raises(ValueError): map_inventory_payload(raw)


def test_unknown_site_is_rejected():
    raw = payload()
    raw['inventory']['machines'][0]['site_id'] = 'unknown'
    with pytest.raises(ValueError, match='Unknown site'): map_inventory_payload(raw)


def test_inventory_view_scopes_all_relationships_and_paginates():
    from app.business.inventory_service import inventory_view
    model = map_inventory_payload(payload())
    empty = inventory_view(model, [], 'machines', '', 0, 25)
    assert empty['rows'] == [] and empty['counts'] == {'machines':0,'users':0,'sites':0}
    page = inventory_view(model, ['flex-cad'], 'machines', '', 0, 5)
    assert len(page['rows']) == 5 and page['total'] > 5
    assert all(row['software'] == ['flex-cad'] for row in page['rows'])
    assert inventory_view(model,None,'machines','Red Hat',0,100)['total'] == 40
    assert inventory_view(model,None,'sites','Toulouse',0,25)['total'] == 1
    assert not inventory_view(None,None,'users','',0,25)['available']


def test_inventory_roundtrip_parquet(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.models.inventory import InventorySnapshot
    value = map_inventory_payload(payload())
    target = tmp_path/'inventory.parquet'
    pq.write_table(pa.Table.from_pylist([value.model_dump(mode='json')]),target)
    assert InventorySnapshot.model_validate(pq.read_table(target).to_pylist()[0]) == value


def test_subsidiaries_and_geographic_filters():
    from app.business.inventory_service import inventory_view
    model = map_inventory_payload(payload())
    assert len(model.subsidiaries) == 2
    assert {s.country for s in model.sites} == {'France', 'Canada'}
    alpha = inventory_view(model,None,'machines','',0,100,subsidiary='demo-subsidiary-1')
    assert alpha['total'] == 38
    assert all(r['subsidiary'] == 'Filiale démo Alpha' for r in alpha['rows'])
    canada = inventory_view(model,None,'users','',0,100,country='Canada')
    assert canada['total'] == 20
    assert all(r['region'] == 'Québec' for r in canada['rows'])
    assert inventory_view(model,None,'sites','',0,25,country='Canada',region='Occitanie')['total'] == 0
    raw = payload()
    raw['inventory']['sites'][0]['subsidiary_id'] = 'missing'
    with pytest.raises(ValueError,match='Unknown subsidiary'):
        map_inventory_payload(raw)


def test_vm_location_matches_host_and_empty_inventory_roundtrips():
    import pyarrow as pa
    import pyarrow.parquet as pq
    from io import BytesIO
    from app.models.inventory import InventorySnapshot
    model = map_inventory_payload(payload())
    machines = {m.machine_id:m for m in model.machines}
    assert all(m.site_id == machines[m.host_id].site_id for m in model.machines if m.host_id)
    empty = InventorySnapshot(captured_at=model.captured_at,source='digimon')
    output = BytesIO()
    pq.write_table(pa.Table.from_pylist([empty.model_dump(mode='json')]),output)
    assert InventorySnapshot.model_validate(pq.read_table(BytesIO(output.getvalue())).to_pylist()[0]) == empty


def test_persistence_reuses_key_and_latest_read_uses_only_latest_day():
    from io import BytesIO
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.services.pipeline import SamPipeline
    from app.business.inventory_service import latest_inventory
    class Storage:
        def __init__(self): self.objects = {}; self.reads = []
        def put_parquet(self,key,rows):
            output = BytesIO()
            pq.write_table(pa.Table.from_pylist(rows),output)
            self.objects[key] = output.getvalue()
        def list_keys(self,prefix): return [k for k in self.objects if k.startswith(prefix)]
        def get_bytes(self,key): self.reads.append(key); return self.objects[key]
    storage = Storage()
    pipeline = SamPipeline(None,storage,None)
    pipeline.persist_snapshot(snapshot(datetime(2026,9,10,tzinfo=timezone.utc)),'fixed')
    pipeline.persist_snapshot(payload(),'fixed')
    pipeline.persist_snapshot(payload(),'fixed')
    assert len(storage.list_keys('silver/inventory/')) == 2
    assert len(storage.list_keys('silver/usage/')) == 2
    assert latest_inventory(storage) == map_inventory_payload(payload())
    assert len(storage.reads) == 1 and '2026-09-11' in storage.reads[0]


def test_host_cycles_rejected():
    raw = payload()
    raw['inventory']['machines'][0]['host_id'] = 'demo-machine-002'
    raw['inventory']['machines'][1]['host_id'] = 'demo-machine-001'
    with pytest.raises(ValueError,match='Cyclic host'):
        map_inventory_payload(raw)


def test_enterprise_scenario_has_server_roles_and_coherent_links():
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.models.inventory import InventorySnapshot
    at = datetime(2026,9,11,tzinfo=timezone.utc)
    value = enterprise_inventory(at,employees=1100,workstations=1000,physical_servers=20,virtual_servers=200)
    model = InventorySnapshot(captured_at=at,source='digimon-mock',**value)
    assert len(model.users) == 1100 and len(model.machines) == 1220
    assert len(model.sites) == 180 and len(model.subsidiaries) == 12
    assert any('IIS' in m.services and 'Windows Server' in m.operating_system for m in model.machines)
    assert any('Red Hat' in m.operating_system for m in model.machines)
    hosts = {m.machine_id:m for m in model.machines}
    assert all(hosts[m.host_id].site_id == m.site_id for m in model.machines if m.host_id)
    assert value == enterprise_inventory(at,employees=1100,workstations=1000,physical_servers=20,virtual_servers=200)


def test_execution_telemetry_preserves_unknown_and_zero():
    from datetime import datetime, timezone
    from app.connectors.enterprise_inventory import daily_observation
    from app.models.inventory import SoftwareObservation
    import pytest
    row = dict(machine_id='m', user_id='ent-user-000005', license_pool_id='p', used=False)
    daily_observation(row, datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert SoftwareObservation(**row).execution_minutes is None
    row['user_id'] = 'ent-user-000001'
    daily_observation(row, datetime(2026, 9, 12, tzinfo=timezone.utc))
    assert not row['used'] and row['execution_minutes'] == 0
    with pytest.raises(ValueError):
        SoftwareObservation(**{**row, 'execution_minutes': 15})
    with pytest.raises(ValueError):
        SoftwareObservation(**{**row, 'used': True, 'execution_minutes': 1441})


def test_enterprise_subsidiaries_have_distinct_sizes_and_consistent_locations():
    from datetime import datetime, timezone
    from collections import Counter
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.models.inventory import InventorySnapshot
    data = enterprise_inventory(datetime(2026,9,11,tzinfo=timezone.utc), employees=1100,workstations=1000,physical_servers=100,virtual_servers=200)
    model = InventorySnapshot(captured_at=datetime(2026,9,11,tzinfo=timezone.utc),source='digimon-mock',**data)
    sites = {s.site_id:s.subsidiary_id for s in model.sites}
    counts = Counter(sites[u.site_id] for u in model.users)
    assert counts['ent-sub-01'] > counts['ent-sub-12'] * 5
    machines = {m.machine_id:m for m in model.machines}
    users = {u.user_id:u for u in model.users}
    assert all(m.site_id == machines[m.host_id].site_id for m in model.machines if m.host_id)
    assert all(machines[o.machine_id].site_id == users[o.user_id].site_id for o in model.observations)


def test_enterprise_workstations_install_the_observed_products():
    from datetime import datetime, timezone
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.connectors.demo import CATALOG
    data = enterprise_inventory(datetime(2026,9,11,tzinfo=timezone.utc),employees=220,workstations=200,physical_servers=10,virtual_servers=20)
    machines = {m['machine_id']:m for m in data['machines']}
    names = {c[0]:c[1] for c in CATALOG}
    assert {'desktop','laptop','server','virtual'} == {m['form_factor'] for m in machines.values()}
    for observation in data['observations']:
        assert names[observation['license_pool_id']] in machines[observation['machine_id']]['applications']
    windows = [m for m in machines.values() if m['asset_type']=='workstation' and m['operating_system'].startswith('Windows')]
    assert all('Microsoft 365 Apps' in m['applications'] for m in windows)
    assert all(len(m['applications']) >= 6 for m in windows)


def test_enterprise_site_counts_differ_by_subsidiary():
    from datetime import datetime, timezone
    from collections import Counter
    from app.connectors.enterprise_inventory import enterprise_inventory, SITE_COUNTS
    data = enterprise_inventory(datetime(2026,9,11,tzinfo=timezone.utc),employees=220,workstations=200,physical_servers=10,virtual_servers=20)
    counts = Counter(s['subsidiary_id'] for s in data['sites'])
    assert [counts[f'ent-sub-{i:02}'] for i in range(1,13)] == SITE_COUNTS
    assert sum(counts.values()) == 180
    assert counts['ent-sub-01'] == 34 and counts['ent-sub-12'] == 3


def test_contractors_are_additional_people_with_valid_assignments():
    from datetime import datetime, timezone
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.models.inventory import InventorySnapshot
    at = datetime(2026,9,11,tzinfo=timezone.utc)
    data = enterprise_inventory(at,employees=1100,workstations=1000,physical_servers=20,virtual_servers=200,contractors=165)
    model = InventorySnapshot(captured_at=at,source='digimon-mock',**data)
    assert sum(u.employment_type=='employee' for u in model.users) == 1100
    assert sum(u.employment_type=='contractor' for u in model.users) == 165
    assert len(model.observations) == 2530
    assert all(u.display_name.startswith('Prestataire') for u in model.users if u.employment_type=='contractor')


def test_each_contractor_has_a_dedicated_laptop_and_software():
    from datetime import datetime, timezone
    from app.connectors.enterprise_inventory import enterprise_inventory
    data = enterprise_inventory(datetime(2026,9,11,tzinfo=timezone.utc),employees=110,workstations=100,physical_servers=2,virtual_servers=20,contractors=16)
    machines = {m['machine_id']:m for m in data['machines']}
    assigned = set()
    for user in data['users']:
        if user['employment_type'] != 'contractor': continue
        usage = [o for o in data['observations'] if o['user_id']==user['user_id']]
        assert len(usage)==2
        pc = machines[usage[0]['machine_id']]
        assert pc['form_factor']=='laptop'
        assert pc['machine_id'] not in assigned
        assigned.add(pc['machine_id'])
        assert user['site_id']==pc['site_id'] and 'Microsoft 365 Apps' in pc['applications']
    assert len(assigned)==16 and len(machines)==138


def test_enterprise_software_dimensions_are_linked_and_rights_are_explicit():
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.connectors.enterprise_software import software_dimensions
    from app.models.inventory import InventorySnapshot
    at = datetime(2026, 9, 11, tzinfo=timezone.utc)
    raw = enterprise_inventory(at, employees=30, workstations=20, physical_servers=2, virtual_servers=6, contractors=4)
    raw.update(software_dimensions(raw))
    model = InventorySnapshot(captured_at=at, source='digimon-mock', **raw)
    names = {p.software_id:p.name for p in model.products}
    assert 'Red Hat Enterprise Linux 9' in names.values()
    assert 'Microsoft 365 Apps' in names.values()
    assert len({(i.machine_id,i.software_id) for i in model.installations}) == len(model.installations)
    assert {i.machine_id for i in model.installations} == {m.machine_id for m in model.machines}
    assert all(e.synthetic for e in model.entitlements)
    assert {e.software_id for e in model.entitlements} == {p.software_id for p in model.products}
    assert {e.metric for e in model.entitlements} == {'device', 'named_user', 'concurrent', 'unmetered'}
    assert software_dimensions(raw) == software_dimensions(raw)
    raw['installations'][0]['machine_id'] = 'missing'
    with pytest.raises(ValueError, match='Unknown machine in installation'):
        InventorySnapshot(captured_at=at, source='digimon-mock', **raw)


def test_entitlement_validation_rejects_unknown_products_and_unmetered_quantity():
    from app.models.inventory import InventorySnapshot
    from app.models.software_inventory import SoftwareEntitlement
    with pytest.raises(ValueError, match='Unmetered'):
        SoftwareEntitlement(entitlement_id='e', software_id='s', metric='unmetered', quantity=1)
    with pytest.raises(ValueError, match='Unknown software product'):
        InventorySnapshot(captured_at=datetime.now(timezone.utc),source='test',
                          entitlements=[{'entitlement_id':'e','software_id':'missing','metric':'device','quantity':1}])


def test_software_entitlements_are_not_allocated_to_partial_workspace():
    import pyarrow as pa
    import pyarrow.parquet as pq
    from io import BytesIO
    from types import SimpleNamespace
    from app.business.software_estate import enrich_software
    data = {}
    for key, rows in {
        'products':[{'software_id':'rhel','name':'RHEL','category':'operating_system'}],
        'entitlements':[{'entitlement_id':'e','software_id':'rhel','metric':'device','quantity':10,'synthetic':True}],
    }.items():
        output = BytesIO()
        pq.write_table(pa.Table.from_pylist(rows), output)
        data[key] = output.getvalue()
    manifest = {'dimensions':{key:{'key':key} for key in data}}
    lake = SimpleNamespace(get_bytes=lambda key:data[key])
    rows = [{'name':'RHEL','machines':8}]
    full = enrich_software(rows,manifest,lake,True)
    assert full[0]['entitlements'][0]['quantity'] == 10
    partial = enrich_software(rows,manifest,lake,False)
    assert partial[0]['machines'] == 8
    assert partial[0]['entitlements'] == []
    assert partial[0]['entitlement_scope'] == 'not_allocated'


def test_license_manager_requires_explicit_source_metadata():
    from app.connectors.digimon import map_digimon_payload
    raw = snapshot(datetime(2026,9,11,tzinfo=timezone.utc))
    mapped = map_digimon_payload(raw)
    assert sum(row.license_manager == 'flexnet' for row in mapped.stock) == 9
    assert next(row for row in mapped.stock if row.license_pool_id == 'flex-adobe').license_manager == 'other'
    for pool in raw['pools']:
        pool.pop('licenseManager')
    assert all(row.license_manager is None for row in map_digimon_payload(raw).stock)


def test_usage_requires_matching_installation_when_catalog_is_supplied():
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.connectors.enterprise_software import software_dimensions
    from app.models.inventory import InventorySnapshot
    at = datetime(2026,9,11,tzinfo=timezone.utc)
    raw = enterprise_inventory(at,employees=12,workstations=10,physical_servers=1,virtual_servers=1)
    raw.update(software_dimensions(raw))
    InventorySnapshot(captured_at=at,source='digimon-mock',**raw)
    observed = raw['observations'][0]
    product = next(p for p in raw['products'] if p['license_pool_id'] == observed['license_pool_id'])
    raw['installations'] = [i for i in raw['installations'] if (i['machine_id'],i['software_id']) != (observed['machine_id'],product['software_id'])]
    with pytest.raises(ValueError,match='matching software installation'):
        InventorySnapshot(captured_at=at,source='digimon-mock',**raw)


def test_standalone_system_portfolio_indexes_machines_users_and_sites():
    from app.connectors.enterprise_inventory import enterprise_inventory
    from app.connectors.enterprise_software import software_dimensions
    from app.models.inventory import InventorySnapshot
    from app.business.inventory_index import entity_rows
    from app.business.inventory_service import inventory_view
    at = datetime(2026, 9, 11, tzinfo=timezone.utc)
    raw = enterprise_inventory(at, employees=30, workstations=20, physical_servers=2, virtual_servers=6, contractors=4)
    raw.update(software_dimensions(raw))
    model = InventorySnapshot(captured_at=at, source='digimon-mock', **raw)
    rhel = next(p.software_id for p in model.products if p.name == 'Red Hat Enterprise Linux 9')
    expected = {i.machine_id for i in model.installations if i.software_id == rhel}
    rows = list(entity_rows(model))
    assert {r[1] for r in rows if r[0]=='machines' and rhel in r[10]} == expected
    expected_users = {o.user_id for o in model.observations if o.machine_id in expected and o.user_id}
    assert {r[1] for r in rows if r[0]=='users' and rhel in r[10]} == expected_users
    expected_sites = {m.site_id for m in model.machines if m.machine_id in expected}
    expected_sites.update(u.site_id for u in model.users if u.user_id in expected_users)
    assert {r[1] for r in rows if r[0]=='sites' and rhel in r[10]} == expected_sites
    view = inventory_view(model, [rhel], 'machines', '', 0, 100)
    assert {m['machine_id'] for m in view['rows']} == expected
    assert inventory_view(model, [], 'machines', '', 0, 100)['total'] == 0
