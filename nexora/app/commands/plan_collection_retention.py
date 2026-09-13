"""Read retained journal references for the active lake namespace; no deletion."""
import json
from app.business.store import BusinessStore
from app.collection.journal import CollectionJournal
from app.collection.retention import journal_protection
from app.config import get_settings
from app.dependencies import get_pipeline


def main():
    settings = get_settings()
    report = journal_protection(get_pipeline().store, CollectionJournal(BusinessStore(settings.database_url)))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
