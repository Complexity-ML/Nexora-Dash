"""Read manifest references through their storage protocol and pinned version."""
from io import BytesIO
import pyarrow.parquet as pq
from app.storage.delta_tables import DeltaReference


def read_table(lake, reference, *, columns=None, filters=None):
    if isinstance(reference, dict) and reference.get('format') == 'delta':
        ref = DeltaReference(path=reference['path'], version=reference['version'],
                             observation_date=reference.get('observation_date'))
        return lake.delta.read(ref, columns=columns, filters=filters)
    if isinstance(reference, dict) and reference.get('format') not in (None, 'parquet'):
        raise ValueError('Unsupported table format')
    key = reference['key'] if isinstance(reference, dict) else reference
    return pq.read_table(BytesIO(lake.get_bytes(key)), columns=columns, filters=filters)
