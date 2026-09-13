"""Opt-in check against the configured MinIO, isolated from active generations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os
from uuid import uuid4
import pyarrow as pa
import pytest
from app.config import get_settings
from app.storage.delta_tables import s3_delta_tables


@pytest.mark.skipif(os.environ.get('TEST_DELTA_MINIO') != '1', reason='requires local MinIO')
def test_conditional_concurrent_commits_and_reopen():
    settings = get_settings()
    prefix = 'delta-validation/' + str(uuid4()) + '/'
    tables = s3_delta_tables(settings, prefix)
    initial = tables.replace_day('silver/events', date(2026, 1, 1), pa.table({'count': [1]}))
    def write(day):
        return tables.replace_day('silver/events', date(2026, 1, day), pa.table({'count': [day]}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        commits = list(pool.map(write, [2, 3]))
    reopened = s3_delta_tables(settings, prefix)
    assert sorted(reopened.read(reopened.latest('silver/events'))['count'].to_pylist()) == [1, 2, 3]
    assert reopened.read(initial)['count'].to_pylist() == [1]
    assert len({c.version for c in commits}) == 2
