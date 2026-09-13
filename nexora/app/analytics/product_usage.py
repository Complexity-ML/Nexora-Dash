"""Aggregate persisted product measurements; unknown days never imply inactivity."""
from collections import defaultdict
from datetime import date
import pyarrow as pa


class ProductUsageAccumulator:
    def __init__(self, identity: pa.Table):
        self.identity = identity.select(['installation_id','machine_id','software_id','measurement'])
        ids = self.identity.column('installation_id').to_pylist()
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate installation identifier')
        self.observed = [0]*len(ids)
        self.active = [0]*len(ids)
        self.last_used = [None]*len(ids)
        self.days = set()

    def add_day(self, day: date, table: pa.Table):
        if day in self.days:
            raise ValueError('Duplicate observation date')
        if not table.select(self.identity.column_names).equals(self.identity):
            raise ValueError('Installation identity/order differs from the generation')
        observed = table.column('observed').to_pylist()
        used = table.column('used').to_pylist()
        durations = table.column('duration_minutes').to_pylist()
        if any(d != day for d in table.column('observation_date').to_pylist()):
            raise ValueError('Partition date mismatch')
        for present,active,duration in zip(observed,used,durations):
            if not isinstance(present,bool):
                raise ValueError("Observation presence must be explicit")
            if not present:
                if active is not None or duration is not None:
                    raise ValueError('Absent observation contains usage values')
                continue
            if not isinstance(active,bool) or duration is None or not 0 <= duration <= 1440:
                raise ValueError('Invalid observed measurement')
            if not active and duration != 0:
                raise ValueError('Inactive measurement has duration')
        for i,(present,active) in enumerate(zip(observed,used)):
            if not present:
                continue
            self.observed[i] += 1
            self.active[i] += int(active)
            if active and (self.last_used[i] is None or day > self.last_used[i]):
                self.last_used[i] = day
        self.days.add(day)

    def table(self):
        if not self.days:
            raise ValueError('No observation days')
        expected = (max(self.days)-min(self.days)).days+1
        return self.identity.append_column('observed_days',pa.array(self.observed,type=pa.int32())) \
            .append_column('active_days',pa.array(self.active,type=pa.int32())) \
            .append_column('last_used_on',pa.array(self.last_used,type=pa.date32())) \
            .append_column('period_days',pa.array([expected]*len(self.observed),type=pa.int32())) \
            .append_column('complete_coverage',pa.array([n==expected for n in self.observed],type=pa.bool_()))

    def summary(self):
        result = defaultdict(lambda:dict(installations_observed=0,installations_active=0,installations_without_usage=0,installations_incomplete=0))
        for row in self.table().to_pylist():
            value=result[row['software_id']]
            value['installations_observed'] += 1
            value['installations_active'] += int(row['active_days']>0)
            value['installations_without_usage'] += int(row['active_days']==0 and row['complete_coverage'])
            value['installations_incomplete'] += int(not row['complete_coverage'])
        return [{'software_id':sid,**value} for sid,value in sorted(result.items())]
