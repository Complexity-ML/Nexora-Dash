"""PySpark is the MVP analytics engine; local[*] is only its demo deployment mode."""
from datetime import datetime, timedelta, timezone
import math
from functools import cached_property

from pyspark.sql import SparkSession, Window, functions as F

from app.models.canonical import AnalyticsSummary, InactiveCandidate, SaturationRisk, Trend


class SparkAnalytics:
    def __init__(self, master: str, underutilization_threshold: float, buffer_rate: float):
        self.master = master
        self.threshold, self.buffer_rate = underutilization_threshold, buffer_rate

    @cached_property
    def spark(self):
        # Catalog and cached Gold reads do not need a JVM or a Spark session.
        return (SparkSession.builder.master(self.master).appName("sam-analytics")
                .config("spark.ui.enabled", "false").getOrCreate())

    def compute(self, silver_paths: list[str], pool_ids: list[str] | None = None) -> AnalyticsSummary:
        if not silver_paths:
            return AnalyticsSummary(generated_at=datetime.now(timezone.utc), total_capacity=0,
                total_used=0, total_available=0, utilization_rate=0, pools_at_risk=0,
                pools_total=0, recovery_potential=0, trends=[], inactive=[], risks=[])
        return self.prepare_frame(self.spark.read.parquet(*silver_paths), pool_ids)

    def compute_table(self, table, pool_ids=None):
        # delta-rs resolves the pinned transaction before handing this bounded
        # pool-capacity table to Spark. Inventory is processed separately.
        if not table.num_rows:
            return self.compute([], pool_ids)
        return self.prepare_frame(self.spark.createDataFrame(table), pool_ids)

    def prepare_frame(self, frame, pool_ids=None):
        df = frame.withColumn("timestamp", F.to_timestamp("timestamp"))
        if pool_ids is not None:
            df = df.filter(F.col("license_pool_id").isin(pool_ids))
        return self.compute_frame(df)

    def compute_frame(self, df) -> AnalyticsSummary:
        ordered = Window.partitionBy("license_pool_id").orderBy("timestamp")
        indexed = df.withColumn("row", F.row_number().over(ordered))
        stats = (indexed.groupBy("license_pool_id", "software_name")
            .agg(F.min("timestamp").alias("start"), F.max("timestamp").alias("end"),
                 F.avg("used").alias("avg"), F.max("used").alias("maximum"),
                 F.percentile_approx("used", .95).alias("p95"), F.avg(F.when(F.col("capacity") > 0, F.col("used") / F.col("capacity")).otherwise(0)).alias("utilization"),
                 F.countDistinct(F.to_date("timestamp")).alias("days"),
                 F.max(F.when(F.col("row") == 1, F.col("used"))).alias("first_used"),
                 F.max(F.struct("timestamp", "used", "capacity")).alias("latest")))
        daily_rows = (df.groupBy("license_pool_id", F.to_date("timestamp").alias("day"))
                      .agg(F.max(F.struct("used", "timestamp", "capacity")).alias("peak")).orderBy("day").collect())
        daily = {}
        for r in daily_rows: daily.setdefault(r.license_pool_id, []).append({"date": str(r.day), "used": r.peak.used, "capacity": r.peak.capacity})
        trends, inactive, risks = [], [], []
        for r in stats.collect():
            capacity = r.latest.capacity
            utilization = r.utilization
            elapsed = max(1, (r.end-r.start).days)
            growth = (r.latest.used-r.first_used)/elapsed
            remaining = max(0, capacity-r.latest.used)
            saturation = r.end + timedelta(days=remaining/growth) if growth > 0 else None
            current_rate = r.latest.used / capacity if capacity else 0
            level = "high" if current_rate >= .9 or (saturation and saturation <= r.end+timedelta(days=30)) else "medium" if current_rate >= .75 else "low"
            trends.append(Trend(license_pool_id=r.license_pool_id, software_name=r.software_name,
                period_start=r.start, period_end=r.end, average_used=round(r.avg,2), maximum_used=r.maximum,
                p95_used=float(r.p95), capacity=capacity, utilization_rate=round(utilization,4),
                previous_period_change=round((r.latest.used-r.first_used)/r.first_used,4) if r.first_used else None,
                daily=daily.get(r.license_pool_id, [])))
            if utilization < self.threshold:
                potential=max(0, math.floor(capacity-r.maximum-r.maximum*self.buffer_rate))
                confidence="high" if r.days >= 90 else "medium" if r.days >= 30 else "low"
                inactive.append(InactiveCandidate(license_pool_id=r.license_pool_id, software_name=r.software_name,
                    utilization_rate=round(utilization,4), observed_days=r.days, recovery_potential=potential,
                    confidence=confidence, reason=f"Utilisation moyenne sous le seuil configurable de {self.threshold * 100:g}%; examen humain requis.",
                    period_start=r.start, period_end=r.end))
            risks.append(SaturationRisk(license_pool_id=r.license_pool_id, software_name=r.software_name,
                level=level, growth_per_day=round(growth,2), remaining_capacity=remaining,
                estimated_saturation_date=saturation, reason="Projection linéaire déterministe fondée sur le premier et le dernier relevé."))
        latest_at=df.agg(F.max("timestamp")).first()[0]
        latest=df.filter(F.col("timestamp")==latest_at)
        totals=latest.agg(F.sum("capacity"),F.sum("used"),F.sum("available")).first()
        return AnalyticsSummary(generated_at=datetime.now(timezone.utc), total_capacity=totals[0] or 0,
            total_used=totals[1] or 0,total_available=totals[2] or 0,
            utilization_rate=round((totals[1] or 0)/(totals[0] or 1),4),
            pools_at_risk=sum(x.level=="high" for x in risks), pools_total=len(risks),
            recovery_potential=sum(x.recovery_potential for x in inactive), trends=trends,inactive=inactive,risks=risks)
