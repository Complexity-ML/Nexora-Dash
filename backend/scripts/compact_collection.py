"""Inspect or compact a published usage day; no VACUUM and no legacy activation."""
import argparse
from datetime import date
import json
from app.config import get_settings
from app.dependencies import get_pipeline
from app.collection.reader import PublishedCollection
from app.collection.compaction import compact_usage_day
from app.collection.journal import Conflict
from app.storage.delta_tables import DeltaReference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day', type=date.fromisoformat, required=True)
    parser.add_argument('--target-mib', type=int, default=128, choices=range(1, 1025), metavar='1..1024')
    parser.add_argument('--apply', action='store_true', help='Compact, validate and publish; default only inspects')
    args = parser.parse_args()
    if not get_settings().collection_enabled:
        raise RuntimeError('Journaled collection must be activated before maintenance')
    try:
        pipeline = get_pipeline()
        lake, journal = pipeline.store, pipeline.collection_journal
        source, scope = pipeline.collection_source, pipeline.collection_scope
        day = args.day.isoformat()
        if args.apply:
            report = compact_usage_day(lake, journal, source=source, scope=scope, day=day,
                                       target_size=args.target_mib * 1048576)
        else:
            reader = PublishedCollection(lake, journal, source, scope)
            if not reader.manifest or day not in reader.manifest['daily']:
                raise ValueError('No published usage for this day')
            reference = DeltaReference(**reader.manifest['daily'][day]['usage'])
            report = {'status':'preview', 'manifest_key':reader.manifest_key,
                      'reference':reference.to_dict(), 'table_files':len(lake.delta.open(reference).file_uris()),
                      'latest_version':lake.delta.latest(reference.path).version,
                      'target_mib':args.target_mib}
        print(json.dumps({'day':day, 'source':source, 'scope':scope, 'apply':args.apply, **report}))
        return 0
    except Conflict:
        print(json.dumps({'status':'conflict', 'error_code':'COMPACTION_PUBLICATION_CHANGED'}))
        return 1
    except Exception:
        # Source/storage failures may contain private paths or credentials.
        print(json.dumps({'status':'failed', 'error_code':'COMPACTION_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
