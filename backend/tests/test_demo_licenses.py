import pytest
from app.connectors.enterprise_software import demo_entitlements
from app.models.software_inventory import SoftwareEntitlement


def test_source_quantities_are_scoped_and_missing_is_not_zero():
    products = [dict(software_id='a',name='Microsoft 365 Apps'),
                dict(software_id='b',name='OpenSSH')]
    subsidiaries = [dict(subsidiary_id=f'ent-sub-{i:02}') for i in range(1,13)]
    rows = demo_entitlements(products, subsidiaries)
    assert len(rows) == 24
    assert len({r['entitlement_id'] for r in rows}) == 24
    assert all(SoftwareEntitlement.model_validate(r).synthetic for r in rows)
    paid = [r for r in rows if r['software_id']=='a']
    assert sum(r['quantity'] or 0 for r in paid) == 128000
    assert [r['subsidiary_id'] for r in paid if r['quantity'] is None] == []
    assert all(r['quantity'] is None and r['metric']=='unmetered' for r in rows if r['software_id']=='b')
    assert demo_entitlements(products, subsidiaries[:1]) == [r for r in rows if r['subsidiary_id']=='ent-sub-01']
    with pytest.raises(ValueError,match='model missing'):
        demo_entitlements([dict(software_id='unknown',name='Unknown')], subsidiaries)


def test_missing_reports_are_exceptional_and_localized():
    import json
    from pathlib import Path
    from app.connectors import enterprise_software
    rows = json.loads(Path(enterprise_software.__file__).with_name('demo_license_source.json').read_text())
    missing = [r for r in rows if r['metric'] != 'unmetered' and r['quantity'] is None]
    assert len(rows) == 360
    assert {(r['product'], r['subsidiary_id']) for r in missing} == {
        ('Maple', 'ent-sub-08'), ('ArcGIS Pro', 'ent-sub-08')}
    assert len({r['product'] for r in rows} - {r['product'] for r in missing}) == 28
