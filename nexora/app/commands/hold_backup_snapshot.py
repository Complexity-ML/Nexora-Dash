"""Hold an exported PostgreSQL snapshot until the orchestrator closes stdin."""
import argparse
import json
import sys
from app.business.store import BusinessStore
from app.config import get_settings
from app.collection.retention import journal_roots
from app.collection.maintenance_lock import protect_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    with BusinessStore(get_settings().database_url).connect() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        protect_backup(db)
        snapshot = db.execute('SELECT pg_export_snapshot() AS snapshot').fetchone()['snapshot']
        print(json.dumps({'snapshot': snapshot, **journal_roots(db, args.namespace)}), flush=True)
        sys.stdin.readline()


if __name__ == '__main__':
    main()
