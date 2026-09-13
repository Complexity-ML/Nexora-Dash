"""Authorized BI reads independent of any web transport.

Use these services from a controlled export job or a BI integration adapter.
No public REST routes or browser-issued storage credentials are installed.
"""
from dataclasses import dataclass
from hashlib import sha256
from app.config import get_settings
from app.business.store import BusinessStore
from app.business.errors import BusinessError
from app.collection.journal import CollectionJournal
from app.bi.auth import reader_publication, authenticate_reader, BIUnauthorized


@dataclass(frozen=True)
class Export:
    snapshot_id: str
    content: bytes
    filename: str
    checksum: str


def current_publication(token=None):
    settings=get_settings()
    if not settings.bi_enabled: raise BusinessError(404,'BI access is disabled')
    if not token: raise BusinessError(401,'Invalid BI credentials')
    try:
        value=reader_publication(CollectionJournal(BusinessStore(settings.database_url)),namespace=settings.bi_namespace,token=token)
    except BIUnauthorized:
        raise BusinessError(401,'Invalid BI credentials') from None
    if value is None: raise BusinessError(404,'No BI publication')
    return value


def bi_lake(settings):
    from app.storage import S3ParquetStore
    return S3ParquetStore(settings.s3_endpoint_url,settings.s3_access_key,settings.s3_secret_key,settings.s3_bucket,settings.s3_region,settings.bi_namespace)


def read_snapshot(snapshot_id, token, table_name=None):
    from app.bi.catalog import publication
    from app.bi.download import snapshot_csv, publication_description, TableUnavailable
    from app.collection.maintenance_lock import protect_backup
    settings=get_settings()
    if not settings.bi_enabled: raise BusinessError(404,'BI access is disabled')
    if not token: raise BusinessError(401,'Invalid BI credentials')
    try:
        journal=CollectionJournal(BusinessStore(settings.database_url))
        identity=authenticate_reader(journal.store,namespace=settings.bi_namespace,token=token)
        with journal.store.connect() as db:
            protect_backup(db)
            current=publication(journal,namespace=settings.bi_namespace,audience=identity['audience'])
            if not current: raise BusinessError(404,'No BI publication')
            if current['snapshot_id']!=snapshot_id: raise BusinessError(409,'BI publication changed; reload the catalog')
            lake=bi_lake(settings)
            if table_name is None:
                return {'snapshot_id':snapshot_id,**publication_description(lake,current['artifact'],identity['audience'])}
            if table_name not in ('pool_usage','inventory_counts','license_entitlements'):
                raise BusinessError(404,'Unknown BI table')
            content=snapshot_csv(lake,current['artifact'],identity['audience'],table_name).encode()
    except BIUnauthorized:
        raise BusinessError(401,'Invalid BI credentials') from None
    except TableUnavailable:
        raise BusinessError(404,'Table absent from this BI publication') from None
    except BusinessError: raise
    except Exception:
        raise BusinessError(503,'BI data unavailable') from None
    return Export(snapshot_id,content,table_name+'.csv',sha256(content).hexdigest())
