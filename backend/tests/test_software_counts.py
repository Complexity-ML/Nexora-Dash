from datetime import datetime, timezone
from types import SimpleNamespace
from test_collection_runner import context
from app.models.inventory import InventorySnapshot
from app.business.inventory_index import publish_index
from app.business.software_counts import compute_counts, read_counts


def test_cached_counts_preserve_product_identity_scope_and_version(context):
    pipeline, journal = context
    snapshot = InventorySnapshot.model_validate({'captured_at':datetime.now(timezone.utc),'source':'test',
        'machines':[{'machine_id':'m1','name':'m1','kind':'physical','operating_system':''},
                    {'machine_id':'m2','name':'m2','kind':'physical','operating_system':''}],
        'products':[{'software_id':'a','name':'Same','category':'application','license_pool_id':'pool-a'},
                    {'software_id':'b','name':'Same','category':'application','license_pool_id':'pool-b'}],
        'installations':[{'installation_id':'i1','software_id':'a','machine_id':'m1'},
                         {'installation_id':'i2','software_id':'b','machine_id':'m2'}]})
    first = publish_index(journal.store, pipeline.store.prefix, snapshot, 'gold/first.json')
    snapshot.installations.append(type(snapshot.installations[0])(installation_id='i3',software_id='a',machine_id='m2'))
    second = publish_index(journal.store, pipeline.store.prefix, snapshot, 'gold/second.json')
    with journal.store.connect() as db:
        assert read_counts(db, first, ['pool-a'])[0]['machines'] == 1
        assert read_counts(db, second, ['pool-a'])[0]['machines'] == 2
        assert read_counts(db, second, ['pool-b'])[0]['software_id'] == 'b'
        assert read_counts(db, second, []) == []
        def execute(query, params):
            assert 'WITH machines' not in query
            return db.execute(query, params)
        assert len(read_counts(SimpleNamespace(execute=execute), second)) == 2
        expected = compute_counts(db, second)
        assert read_counts(db, second) == expected
        db.execute('DELETE FROM inventory_software_summaries WHERE run_id=%s', (second,))
        assert read_counts(db, second) == expected
