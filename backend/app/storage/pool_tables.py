"""Daily pool history in Delta, activated separately from legacy Parquet history."""
import json
from deltalake.exceptions import TableNotFoundError
import pyarrow as pa

MARKER = 'silver/delta-pools.json'
PATH = 'silver/pool_usage'


def enabled(store):
    if not hasattr(store, 'delta'):
        return False
    from botocore.exceptions import ClientError
    try:
        value = json.loads(store.get_bytes(MARKER))
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('NoSuchKey', '404'):
            raise
        return not store.list_keys('silver/usage/')
    if value.get('format') != 'delta' or value.get('path') != PATH:
        raise ValueError('Invalid pool storage marker')
    return True


def reference(store):
    try:
        return store.delta.latest(PATH)
    except TableNotFoundError:
        return None


def persist(store, day, rows):
    if not enabled(store):
        raise RuntimeError('Migrate existing pool history before collecting new Delta snapshots')
    return store.delta.replace_day(PATH, day, pa.Table.from_pylist(rows))
