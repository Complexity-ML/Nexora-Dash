import pytest
from app.business.exploration import aggregate, records, completeness
from app.business.errors import BusinessError
from app.business.inventory_index import publish_index
from app.business import workspace_service as business
from test_business import business as business_fixture
from app.models.inventory import InventorySnapshot
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import uuid4


@pytest.fixture
def exploration_context(business_fixture):
    client,headers,base,store=business_fixture
    user=store.user_for_token(headers['admin']['Authorization'].split()[1])
    wid=base.split('/')[-1]
    # Small, realistic deterministic inventory from the same generator as collection tests.
    from app.connectors.demo import snapshot
    at=datetime(2026,1,1,tzinfo=timezone.utc)
    raw=snapshot(at)
    model=InventorySnapshot(captured_at=at,source='digimon-mock',**raw['inventory'])
    namespace='explore-'+str(uuid4())
    publish_index(store,namespace,model,'silver/test')
    with store.connect() as db: db.execute('UPDATE workspace_portfolios SET all_catalog=true WHERE workspace_id=%s',(wid,))
    return wid,user,store,SimpleNamespace(store=SimpleNamespace(prefix=namespace)),model


def test_cross_dimension_totals_and_drilldown(exploration_context):
    wid,user,store,pipeline,model=exploration_context
    result=aggregate(wid,dimension='country',split='kind',user=user,store=store,pipeline=pipeline)
    assert result['records']==len(model.machines)
    assert sum(r['records'] for r in result['rows'])==len(model.machines)
    row=result['rows'][0]
    drilled=records(wid,filters={'country':row['key0'],'kind':row['key1']},user=user,store=store,pipeline=pipeline)
    assert drilled['total']==row['records']
    assert drilled['run_id']==result['run_id']


def test_exploration_enforces_workspace_and_uses_bound_filters(exploration_context):
    wid,user,store,pipeline,model=exploration_context
    with pytest.raises(BusinessError): aggregate(wid,dimension='country; DROP TABLE users',user=user,store=store,pipeline=pipeline)
    assert records(wid,filters={'country':"' OR 1=1 --"},user=user,store=store,pipeline=pipeline)['total']==0
    with pytest.raises(BusinessError): aggregate(wid,user={'id':'outsider'},store=store,pipeline=pipeline)
    with store.connect() as db: db.execute("UPDATE workspace_portfolios SET all_catalog=false,pool_ids='[]' WHERE workspace_id=%s",(wid,))
    assert aggregate(wid,user=user,store=store,pipeline=pipeline)['records']==0


def test_missing_dimensions_are_not_zero_or_discarded(exploration_context):
    wid,user,store,pipeline,model=exploration_context
    result=completeness(wid,entity='users',user=user,store=store,pipeline=pipeline)
    assert result['total']==len(model.users)
    assert all(0<=field['missing']<=result['total'] for field in result['fields'])
    # Never sum absent numeric values as if the source supplied zero.
    with store.connect() as db: db.execute("UPDATE inventory_entities SET data=data-'cpu_cores' WHERE run_id=(SELECT run_id FROM inventory_heads WHERE namespace=%s) AND entity='machines'",(pipeline.store.prefix,))
    result=aggregate(wid,measure='cpu_cores',user=user,store=store,pipeline=pipeline)
    assert result['value'] is None
