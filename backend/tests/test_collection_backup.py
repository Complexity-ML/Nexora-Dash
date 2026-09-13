from pathlib import Path
import shutil
from types import SimpleNamespace
import pyarrow as pa
from app.storage.delta_tables import DeltaTables
from app.collection.backup import delta_backup_files


def test_restore_pinned_versions_without_unreferenced_new_data(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    delta = DeltaTables(str(source))
    old = delta.replace('silver/machines', pa.table({'machine_id': ['old']}))
    current = delta.replace('silver/machines', pa.table({'machine_id': ['current']}))
    delta.open(current).create_checkpoint()
    later = delta.replace('silver/machines', pa.table({'machine_id': ['unpublished']}))
    delta.open(later).create_checkpoint()
    lake = SimpleNamespace(delta=delta, list_keys=lambda prefix: [str(p.relative_to(source))
        for p in (source/prefix).rglob('*') if p.is_file()])
    files = delta_backup_files(lake, [old.to_dict(), current.to_dict()])
    assert not any(key.endswith('_last_checkpoint') for key in files)
    assert not any(key.endswith('00000000000000000002.json') for key in files)
    destination = tmp_path/'restored'
    for key in files:
        target = destination/key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/key, target)
    # Remove the source entirely: reads must depend on the restored files alone.
    shutil.rmtree(source)
    restored = DeltaTables(str(destination))
    assert restored.read(old).to_pylist() == [{'machine_id': 'old'}]
    assert restored.read(current).to_pylist() == [{'machine_id': 'current'}]
    assert restored.latest('silver/machines').version == current.version
