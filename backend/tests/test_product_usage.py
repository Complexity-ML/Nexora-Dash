from datetime import date,timedelta
import pytest
import pyarrow as pa
from app.connectors.enterprise_product_usage import ProductUsageScenario
from app.analytics.product_usage import ProductUsageAccumulator


def scenario():
    machines=[{'machine_id':'host','asset_type':'server'}, {'machine_id':'vm','asset_type':'server','host_id':'host'}, {'machine_id':'pc','asset_type':'workstation'}]
    products=[{'software_id':'os','name':'System','category':'operating_system'}, {'software_id':'app','name':'Application','category':'application'}, {'software_id':'service','name':'Service','category':'service'}]
    installations=[{'installation_id':f'{m["machine_id"]}:{p["software_id"]}','machine_id':m['machine_id'],'software_id':p['software_id']} for m in machines for p in products]
    return ProductUsageScenario(machines,products,installations)


def test_product_observations_are_deterministic_and_bounded_by_machine_uptime():
    generator=scenario()
    day=date(2026,9,7)
    first=generator.table(day)
    assert first.equals(generator.table(day))
    assert not first.equals(generator.table(day+timedelta(days=1)))
    rows=first.to_pylist()
    uptime={r['machine_id']:r['duration_minutes'] for r in rows if r['measurement']=='system_uptime'}
    assert uptime['vm'] <= uptime['host']
    for r in rows:
        if r['observed']:
            assert 0 <= r['duration_minutes'] <= uptime[r['machine_id']] <= 1440
            assert r['used'] or r['duration_minutes']==0
        else:assert r['used'] is None and r['duration_minutes'] is None


def test_product_summary_keeps_missing_days_distinct_from_zero_activity():
    generator=scenario(); day=date(2026,9,7)
    first=generator.table(day)
    first=first.set_column(first.schema.get_field_index('used'),'used',pa.array([False]*first.num_rows,type=pa.bool_()))
    first=first.set_column(first.schema.get_field_index('duration_minutes'),'duration_minutes',pa.array([0]*first.num_rows,type=pa.int16()))
    accumulator=ProductUsageAccumulator(first)
    accumulator.add_day(day,first)
    last=first.set_column(first.schema.get_field_index('observation_date'),'observation_date',pa.array([day+timedelta(days=2)]*first.num_rows,type=pa.date32()))
    accumulator.add_day(day+timedelta(days=2),last)
    assert all(not r['complete_coverage'] and r['observed_days']==2 and r['period_days']==3 for r in accumulator.table().to_pylist())
    assert all(p['installations_without_usage']==0 for p in accumulator.summary())
    with pytest.raises(ValueError,match='Duplicate observation'):
        accumulator.add_day(day,first)
    reordered=first.take(pa.array(list(reversed(range(first.num_rows)))))
    with pytest.raises(ValueError,match='identity/order'):
        accumulator.add_day(day+timedelta(days=1),reordered)


def test_synthetic_missing_measurement_is_null_not_zero():
    generator=scenario()
    generator.installation_seeds[0]=997
    day=date(2026,9,7)
    while day.toordinal()%17:day+=timedelta(days=1)
    row=generator.table(day).to_pylist()[0]
    assert row['observed'] is False
    assert row['used'] is None and row['duration_minutes'] is None


def test_invalid_partition_does_not_partially_change_aggregate():
    day=date(2026,9,7);first=scenario().table(day)
    accumulator=ProductUsageAccumulator(first)
    values=first.column('duration_minutes').to_pylist();values[-1]=1500
    invalid=first.set_column(first.schema.get_field_index('duration_minutes'),'duration_minutes',pa.array(values,type=pa.int16()))
    with pytest.raises(ValueError,match='Invalid observed'):
        accumulator.add_day(day,invalid)
    assert accumulator.days==set()
    assert accumulator.observed==[0]*first.num_rows
    accumulator.add_day(day,first)
    assert all(r['observed_days']<=1 for r in accumulator.table().to_pylist())
