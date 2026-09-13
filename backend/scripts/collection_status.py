"""Report missing published days and processing issues; never contact DIGIMON."""
import argparse
from datetime import date
import json
from app.dependencies import get_pipeline
from app.config import get_settings
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal
from app.collection.status import collection_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', type=date.fromisoformat, required=True)
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    parser.add_argument('--require-worker', action='store_true', help='Alert when no responsive recovery worker exists')
    parser.add_argument('--require-daily-worker', action='store_true', help='Alert when no responsive daily collector exists')
    parser.add_argument('--poll-timeout-seconds', type=int, default=3600, help='Attention threshold for unfinished attempts, not a cancellation deadline')
    args = parser.parse_args()
    settings = get_settings()
    pipeline = get_pipeline()
    result = collection_status(pipeline.store, CollectionJournal(BusinessStore(settings.database_url)),
        source='digimon-mock' if settings.sam_data_source == 'mock' else settings.collection_source,
        scope=settings.collection_scope, start=args.start, end=args.through, require_worker=args.require_worker, require_daily_worker=args.require_daily_worker, poll_timeout_seconds=args.poll_timeout_seconds)
    print(json.dumps(result))
    return 1 if result['needs_attention'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
