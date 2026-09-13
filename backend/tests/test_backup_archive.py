import json
import pytest
from app.collection.backup_archive import digest,seal_archive,verify_archive,MARKER


def fixture(root):
    for name in ('database.dump','snapshot.json','lake-object'):
        (root/name).write_bytes(name.encode())
    (root/'snapshot.json').write_text(json.dumps({'required_archive_members':['database.dump','snapshot.json','lake-object']}))
    return {name:digest(root/name) for name in ('database.dump','snapshot.json','lake-object')}


def test_sealed_archive_detects_later_corruption(tmp_path):
    files=fixture(tmp_path)
    seal_archive(tmp_path,files)
    assert verify_archive(tmp_path)['files'] == files
    with pytest.raises(FileExistsError):
        seal_archive(tmp_path,files)
    (tmp_path/'lake-object').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='checksum'):
        verify_archive(tmp_path)


def test_incomplete_copy_never_publishes_marker(tmp_path):
    files=fixture(tmp_path)
    (tmp_path/'lake-object').unlink()
    with pytest.raises(FileNotFoundError):
        seal_archive(tmp_path,files)
    assert not (tmp_path/MARKER).exists()


def test_archive_refuses_path_escape(tmp_path):
    files=fixture(tmp_path)
    files['../outside']='0'*64
    with pytest.raises(ValueError,match='member'):
        seal_archive(tmp_path,files)
    assert not (tmp_path/MARKER).exists()


def test_sync_failure_does_not_publish_completion(tmp_path, monkeypatch):
    from app.collection import backup_archive
    files = fixture(tmp_path)
    def failure(_):
        raise OSError('Storage synchronization failed')
    monkeypatch.setattr(backup_archive.os, 'fsync', failure)
    with pytest.raises(OSError):
        seal_archive(tmp_path, files)
    assert not (tmp_path/MARKER).exists()


def test_nested_members_and_directories_sync_before_marker(tmp_path, monkeypatch):
    from app.collection import backup_archive
    import os
    files = fixture(tmp_path)
    directory = tmp_path / 'restored' / 'table'
    directory.mkdir(parents=True)
    member = directory / 'data.parquet'
    member.write_bytes(b'test data')
    files['restored/table/data.parquet'] = digest(member)
    synced = set()
    original_sync, original_link = os.fsync, os.link
    def sync(fd):
        original_sync(fd)
        synced.add(os.fstat(fd).st_ino)
    def link(source, target):
        required = [tmp_path/key for key in files] + [tmp_path, directory.parent, directory]
        assert all(path.stat().st_ino in synced for path in required)
        original_link(source, target)
    monkeypatch.setattr(backup_archive.os, 'fsync', sync)
    monkeypatch.setattr(backup_archive.os, 'link', link)
    seal_archive(tmp_path, files)
    assert verify_archive(tmp_path)['files'] == files


def test_omitted_file_cannot_be_hidden_by_omitting_its_checksum(tmp_path):
    files = fixture(tmp_path)
    del files['lake-object']
    (tmp_path/'lake-object').unlink()
    with pytest.raises(ValueError, match='omits required'):
        seal_archive(tmp_path, files)
    assert not (tmp_path/MARKER).exists()
