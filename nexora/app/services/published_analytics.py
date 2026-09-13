"""Read published analytical results. UI reads never start Spark or collect DIGIMON."""
import json
from app.models.canonical import AnalyticsSummary
from app.storage.table_reader import read_table
from app.business.errors import BusinessError


def scoped_summary(value, pools):
    if pools is None:
        return value
    selected = set(pools)
    trends = [t for t in value.trends if t.license_pool_id in selected]
    risks = [r for r in value.risks if r.license_pool_id in selected]
    inactive = [i for i in value.inactive if i.license_pool_id in selected]
    capacity = sum(t.capacity for t in trends)
    used = sum(int(t.daily[-1]['used']) for t in trends if t.daily)
    return value.model_copy(update=dict(trends=trends, risks=risks, inactive=inactive,
        total_capacity=capacity, total_used=used, total_available=max(0, capacity-used),
        utilization_rate=used/capacity if capacity else 0, pools_total=len(trends),
        pools_at_risk=sum(r.level == 'high' for r in risks),
        recovery_potential=sum(i.recovery_potential for i in inactive)))


def read_summary(pipeline, pools=None):
    lake = pipeline.store
    if hasattr(lake, 'collection'):
        value = lake.collection.summary()
        if value is None:
            raise BusinessError(409, 'Les analyses ne sont pas encore publiées. Lancez le traitement du lac.')
    else:
        from deltalake.exceptions import TableNotFoundError
        from botocore.exceptions import ClientError
        try:
            if hasattr(lake, 'delta'):
                ref = lake.delta.latest('gold/analytics/latest')
                rows = lake.delta.read(ref).to_pylist()
            else:
                rows = read_table(lake, 'gold/analytics/latest.parquet').to_pylist()
        except (TableNotFoundError, FileNotFoundError):
            raise BusinessError(409, 'Les analyses ne sont pas encore publiées. Lancez le traitement du lac.') from None
        except ClientError as exc:
            if exc.response['Error']['Code'] not in ('NoSuchKey', '404'):
                raise
            raise BusinessError(409, 'Les analyses ne sont pas encore publiées. Lancez le traitement du lac.') from None
        if len(rows) != 1:
            raise BusinessError(503, 'Publication analytique invalide.')
        row = dict(rows[0])
        for key in ('trends', 'risks', 'inactive'):
            row[key] = json.loads(row.pop(key+'_json'))
        value = AnalyticsSummary.model_validate(row)
    return scoped_summary(value, pools)
