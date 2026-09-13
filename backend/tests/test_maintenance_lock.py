import pytest
from test_cleanup_collection_guard import isolated, connection
from app.collection.maintenance_lock import protect_backup, protect_deletion


def test_parallel_backups_block_cleanup_until_last_reader_exits(isolated):
    with connection(*isolated) as first, connection(*isolated) as second:
        first.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        protect_backup(first)
        protect_backup(second)
        first.commit()
        with connection(*isolated) as cleanup:
            with pytest.raises(RuntimeError, match='deletion refused'):
                protect_deletion(cleanup)
        second.commit()
        with connection(*isolated) as cleanup:
            protect_deletion(cleanup)


def test_deletion_blocks_backup_and_other_deletion_and_rollback_releases(isolated):
    with connection(*isolated) as cleanup:
        protect_deletion(cleanup)
        with connection(*isolated) as backup:
            with pytest.raises(RuntimeError, match='retry backup'):
                protect_backup(backup)
        with connection(*isolated) as other:
            with pytest.raises(RuntimeError, match='deletion refused'):
                protect_deletion(other)
        cleanup.rollback()
        with connection(*isolated) as backup:
            protect_backup(backup)


def test_legacy_cleanup_uses_same_guard(isolated):
    from scripts.cleanup_migrated_demo import require_legacy_only
    with connection(*isolated) as backup:
        protect_backup(backup)
        with connection(*isolated) as cleanup:
            with pytest.raises(RuntimeError, match='deletion refused'):
                require_legacy_only(cleanup)
