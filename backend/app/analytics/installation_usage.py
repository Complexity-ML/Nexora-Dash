"""Aggregate observed machine/software usage without inferring concurrent licenses."""
from collections import defaultdict


class InstallationUsageAccumulator:
    def __init__(self):
        self._days = set()
        self._records = {}

    def add_day(self, day, observations):
        if day in self._days:
            raise ValueError('Duplicate observation day')
        self._days.add(day)
        # Several people may share a machine: one installation is active if any
        # of its observed users used the software on this day.
        daily = defaultdict(bool)
        for row in observations:
            key = (row['machine_id'], row['license_pool_id'])
            daily[key] = daily[key] or row['used']
        for key, used in daily.items():
            state = self._records.setdefault(key, {'observed_days':0,'active_days':0,'last_used_on':None})
            state['observed_days'] += 1
            state['active_days'] += int(used)
            if used and (state['last_used_on'] is None or day > state['last_used_on']):
                state['last_used_on'] = day

    def results(self):
        return [{'machine_id':machine, 'license_pool_id':pool, **state,
                 'period_days':len(self._days),
                 'complete_coverage':state['observed_days'] == len(self._days)}
                for (machine,pool),state in sorted(self._records.items())]
