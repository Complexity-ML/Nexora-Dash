"""The license screen must not enumerate enterprise machine installations."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
import pyarrow as pa
import pytest
import app.business.inventory_service as api


@pytest.mark.parametrize('all_catalog', [True, False])
def test_license_only_request_reads_dimensions_and_preserves_scope(monkeypatch, all_catalog):
    selected = {'all_catalog':all_catalog,'pool_ids':['rhel']}
    checked = []
    monkeypatch.setattr(api,'member',lambda db,wid,user:checked.append((wid,user['id'])))
    monkeypatch.setattr(api,'read_portfolio',lambda db,wid:selected)
    class Store:
        @contextmanager
        def connect(self): yield self
        def execute(self, sql, params):
            assert 'inventory_entities' not in sql
            assert 'inventory_heads' in sql
            return SimpleNamespace(fetchone=lambda:{'run_id':'run','manifest_key':'gold/enterprise/test'})
    values = {
        'products':[{'software_id':'rhel','name':'RHEL'}, {'software_id':'office','name':'Office'}],
        'subsidiaries':[{'subsidiary_id':'sae','name':'SAE'}],
        'entitlements':[{'software_id':'rhel','quantity':10,'metric':'device','subsidiary_id':'sae'}],
    }
    reads=[]
    def read(lake, reference):
        reads.append(reference['key'])
        return pa.Table.from_pylist(values[reference['key']])
    monkeypatch.setattr('app.business.software_estate.read_table',read)
    manifest={'dimensions':{k:{'key':k} for k in values}}
    lake=SimpleNamespace(prefix='demo',get_bytes=lambda key:json.dumps(manifest).encode())
    result=api.inventory_software('workspace',include_installations=False,user={'id':'reader'},store=Store(),pipeline=SimpleNamespace(store=lake))
    assert checked == [('workspace','reader')]
    assert len(result) == (2 if all_catalog else 1)
    assert all('machines' not in row for row in result)
    assert result[0]['entitlements'] == ([{**values['entitlements'][0],'subsidiary_name':'SAE'}] if all_catalog else [])
    assert set(reads) <= {'products','subsidiaries','entitlements'}
