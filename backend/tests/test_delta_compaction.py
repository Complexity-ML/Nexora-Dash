import pyarrow as pa
import pytest
from deltalake import write_deltalake
from app.storage.delta_tables import DeltaTables


def test_compaction_preserves_pinned_versions_and_repeating_is_noop(tmp_path):
    lake = DeltaTables(str(tmp_path))
    path = 'silver/usage'
    first = lake.replace(path, pa.table({'id':[1], 'used':[10]}))
    for i in range(2, 6):
        write_deltalake(lake.uri(path), pa.table({'id':[i], 'used':[i*10]}), mode='append')
    before = lake.latest(path)
    old_files = set(lake.open(before).file_uris())
    candidate, metrics = lake.compact(before)
    assert metrics['numFilesRemoved'] > 1
    assert len(lake.open(candidate).file_uris()) < len(old_files)
    assert lake.read(first).to_pylist() == [{'id':1,'used':10}]
    assert lake.read(before).sort_by('id').equals(lake.read(candidate).sort_by('id'))
    from pathlib import Path
    assert all(Path(filename).exists() for filename in old_files)
    again, repeat = lake.compact(candidate)
    assert again == candidate and repeat['numFilesAdded'] == 0
    with pytest.raises(ValueError, match='current table version'):
        lake.compact(before)
