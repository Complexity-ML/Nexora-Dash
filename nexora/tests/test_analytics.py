from datetime import datetime, timedelta, timezone
from pyspark.sql import SparkSession
from app.analytics.spark_jobs import SparkAnalytics

def test_cached_reads_and_empty_history_do_not_start_spark(monkeypatch):
    def unexpected_start(*args, **kwargs):
        raise AssertionError('Reading cached data must not initialize Spark')
    monkeypatch.setattr(SparkSession.Builder, 'getOrCreate', unexpected_start)
    engine = SparkAnalytics('local[1]', .35, .1)
    assert engine.threshold == .35
    assert engine.compute([]).trends == []
    assert 'spark' not in engine.__dict__

def test_trend_underutilization_and_saturation():
    engine=SparkAnalytics("local[1]",.35,.1)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[]
    for day in range(100):
        for pool,name,cap,used in [("low","Unused",100,20),("growth","Growing",100,70+day//4)]:
            value=min(cap,used)
            rows.append({"license_pool_id":pool,"software_name":name,"timestamp":start+timedelta(days=day),
                         "capacity":cap,"used":value,"available":cap-value})
    result=engine.compute_frame(engine.spark.createDataFrame(rows))
    assert next(t for t in result.trends if t.license_pool_id=="low").p95_used == 20
    candidate=next(i for i in result.inactive if i.license_pool_id=="low")
    assert candidate.recovery_potential == 78 and candidate.confidence == "high"
    assert next(r for r in result.risks if r.license_pool_id=="growth").level == "high"

def test_zero_capacity_pool_does_not_break_risk_calculation():
    engine=SparkAnalytics("local[1]",.35,.1)
    result=engine.compute_frame(engine.spark.createDataFrame([{
        "license_pool_id":"zero","software_name":"Empty","timestamp":datetime(2026,1,1),
        "capacity":0,"used":0,"available":0}]))
    assert result.risks[0].level == "low"


def test_capacity_reduction_uses_current_stock_and_historical_rates():
    engine = SparkAnalytics("local[1]", .35, .1)
    start = datetime(2026, 1, 1)
    rows = [{"license_pool_id": "pool", "software_name": "Software",
             "timestamp": start + timedelta(days=day), "capacity": capacity,
             "used": 20, "available": capacity - 20}
            for day, capacity in enumerate([100] * 9 + [20])]
    result = engine.compute_frame(engine.spark.createDataFrame(rows))
    assert result.trends[0].capacity == 20
    assert result.trends[0].utilization_rate == .28
    assert result.risks[0].remaining_capacity == 0
    assert result.risks[0].level == "high"
    assert result.recovery_potential == 0
    assert result.trends[0].daily[0]["capacity"] == 100
    assert result.trends[0].daily[-1]["capacity"] == 20


def test_daily_capacity_belongs_to_peak_observation():
    engine = SparkAnalytics("local[1]", .35, .1)
    start = datetime(2026, 1, 1)
    rows = [{"license_pool_id": "pool", "software_name": "Software",
             "timestamp": start + timedelta(hours=hour), "capacity": capacity,
             "used": used, "available": capacity - used}
            for hour, capacity, used in [(0, 100, 50), (1, 200, 40)]]
    result = engine.compute_frame(engine.spark.createDataFrame(rows))
    assert result.trends[0].capacity == 200
    assert result.trends[0].utilization_rate == .35
    assert result.trends[0].daily == [{"date": "2026-01-01", "used": 50, "capacity": 100}]


def test_portfolio_filters_parquet_before_all_aggregations(tmp_path):
    engine=SparkAnalytics('local[1]',.35,.1)
    rows=[{'license_pool_id':pool,'software_name':pool,'timestamp':datetime(2026,1,1),
           'capacity':100,'used':used,'available':100-used} for pool,used in [('adobe',20),('other',90)]]
    path=str(tmp_path/'source.parquet')
    engine.spark.createDataFrame(rows).write.parquet(path)
    selected=engine.compute([path],['adobe'])
    assert selected.total_capacity==100 and selected.total_used==20
    assert selected.pools_total==1 and selected.pools_at_risk==0
    assert [t.license_pool_id for t in selected.trends]==['adobe']
    assert [t.license_pool_id for t in selected.inactive]==['adobe']
    empty=engine.compute([path],[])
    assert empty.total_capacity==0 and empty.trends==[] and empty.risks==[]
    assert engine.compute([path]).pools_total==2
