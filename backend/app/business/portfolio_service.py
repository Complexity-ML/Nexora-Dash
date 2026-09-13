from app.services.published_analytics import read_summary
from app.business.errors import BusinessError
import json
from pydantic import Field
from app.business.workspace_service import Input, current_user, get_business_store, member
from app.dependencies import get_pipeline


def read_portfolio(db, wid):
    row = db.execute('SELECT all_catalog,pool_ids,version FROM workspace_portfolios WHERE workspace_id=%s',(wid,)).fetchone()
    # Preserve the full catalog for pre-existing spaces. New spaces explicitly start empty.
    return dict(row) if row else {'all_catalog':True,'pool_ids':[],'version':0}

def selected_pools(workspace_id: str | None = None, user=None, store=None):
    if workspace_id is None:
        return None  # The authenticated source catalog is intentionally available to every SAM.
    with store.connect() as db:
        member(db,workspace_id,user)
        selected=read_portfolio(db,workspace_id)
    return None if selected['all_catalog'] else selected['pool_ids']

def catalog_items(pipeline, store):
    # Keep historical pool IDs stable; standalone inventory products use their software ID.
    try:
        trends = read_summary(pipeline).trends
    except BusinessError as exc:
        if exc.status_code != 409:
            raise
        trends = []
    items = {t.license_pool_id: {'pool_id':t.license_pool_id,'name':t.software_name,'capacity':t.capacity}
             for t in trends}
    if not hasattr(getattr(pipeline, 'store', None), 'prefix'):
        return list(items.values())
    with store.connect() as db:
        head = db.execute('SELECT r.manifest_key FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s', (pipeline.store.prefix,)).fetchone()
    if head and head['manifest_key'].startswith('gold/enterprise/'):
        from app.storage.table_reader import read_table
        manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
        dimension = manifest.get('dimensions', {}).get('products')
        if dimension:
            for product in read_table(pipeline.store, dimension).to_pylist():
                key = product.get('license_pool_id') or product['software_id']
                items.setdefault(key, {'pool_id':key, 'name':product['name'], 'capacity':None})
    if not head:
        from app.business.inventory_service import latest_inventory
        from app.business.software_estate import snapshot_software
        for product in snapshot_software(latest_inventory(pipeline.store), None):
            key = product.get('license_pool_id') or product['software_id']
            items.setdefault(key, {'pool_id':key,'name':product['name'],'capacity':None})
    return sorted(items.values(), key=lambda item:item['name'].casefold())


def catalog(user=None, pipeline=None, store=None):
    return catalog_items(pipeline, store)

def portfolio(wid: str,user=None,store=None):
    with store.connect() as db:
        role=member(db,wid,user)
        return {**read_portfolio(db,wid),'can_edit':role=='admin'}

class PortfolioUpdate(Input):
    all_catalog: bool
    pool_ids: list[str] = Field(max_length=10000)
    version: int = Field(ge=0)

def update_portfolio(wid: str,body:PortfolioUpdate,user=None,store=None,pipeline=None):
    with store.connect() as db:
        member(db,wid,user,admin=True)
    ids=sorted(set(body.pool_ids))
    if body.all_catalog and ids:
        raise BusinessError(422,'Le catalogue complet ne doit pas contenir une sélection partielle.')
    if not body.all_catalog:
        available={item['pool_id'] for item in catalog_items(pipeline, store)}
        if not set(ids)<=available:
            raise BusinessError(422,'Un logiciel sélectionné ne figure plus dans le catalogue disponible. Rechargez-le.')
    with store.connect() as db:
        member(db,wid,user,admin=True)
        previous=read_portfolio(db,wid)
        if previous['version']!=body.version:
            raise BusinessError(409,'Périmètre modifié par un autre membre. Rechargez-le.')
        value={'all_catalog':body.all_catalog,'pool_ids':ids,'version':body.version+1}
        db.execute('INSERT INTO workspace_portfolios VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id) DO UPDATE SET all_catalog=EXCLUDED.all_catalog,pool_ids=EXCLUDED.pool_ids,version=EXCLUDED.version',(wid,body.all_catalog,json.dumps(ids),value['version']))
        store.event(db,wid,None,user['id'],'portfolio.updated',{'before':previous,'after':value})
    return {**value,'can_edit':True}
