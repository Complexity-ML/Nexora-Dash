from app.analytics import SparkAnalytics
from app.config import get_settings
from app.connectors.digimon import HttpDigimonConnector, MockDigimonConnector
from app.services.pipeline import SamPipeline
from app.storage import S3ParquetStore


def get_pipeline() -> SamPipeline:
    s=get_settings()
    from app.business.analysis_preferences import read_settings
    from app.business.store import BusinessStore
    business_store = BusinessStore(s.database_url)
    values = read_settings(business_store)
    with business_store.connect() as db:
        generation = db.execute('SELECT prefix FROM demo_generation WHERE id=1').fetchone()
    prefix = generation['prefix'] if s.sam_data_source == 'mock' and generation else ''

    connector=(MockDigimonConnector() if s.sam_data_source == "mock" else
               HttpDigimonConnector(s.digimon_base_url,s.digimon_timeout))
    store=S3ParquetStore(s.s3_endpoint_url,s.s3_access_key,s.s3_secret_key,s.s3_bucket,s.s3_region,prefix)
    pipeline = SamPipeline(connector,store,SparkAnalytics(s.spark_master,values["threshold"],values["buffer"]))
    if s.collection_enabled:
        from app.collection.journal import CollectionJournal
        from app.collection.reader import PublishedCollection
        pipeline.collection_quality_policy = {'minimum_retained_fraction': s.collection_minimum_retained_fraction,
                                              'minimum_counts': s.collection_minimum_counts}
        pipeline.collection_journal = CollectionJournal(business_store)
        pipeline.collection_source = 'digimon-mock' if s.sam_data_source == 'mock' else s.collection_source
        pipeline.collection_scope = s.collection_scope
        store.collection = PublishedCollection(store,pipeline.collection_journal,pipeline.collection_source,pipeline.collection_scope)
        if store.collection.manifest is None:
            from app.storage import pool_tables
            from app.business.errors import BusinessError
            with business_store.connect() as db:
                indexed = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s',(prefix,)).fetchone()
            if indexed or pool_tables.reference(store) is not None or store.list_keys('silver/usage/'):
                raise BusinessError(503,'Importer et valider l’historique existant avant d’activer la collecte avec reprise.')
    return pipeline
