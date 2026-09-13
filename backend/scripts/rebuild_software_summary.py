"""Rebuild software counts for the current inventory without changing its pointer."""
import json
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.business.inventory_service import inventory_head
from app.business.software_counts import rebuild_summary
from app.config import get_settings


def main():
    lake = get_pipeline().store
    with BusinessStore(get_settings().database_url).connect() as db:
        head = inventory_head(db, lake)
        if head is None:
            raise RuntimeError('No inventory index to summarize')
        rows = rebuild_summary(db, head['id'])
        print(json.dumps({'run_id':head['id'],'products':len(rows)}))


if __name__ == '__main__':
    main()
