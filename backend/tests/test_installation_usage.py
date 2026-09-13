import pytest
from app.analytics.installation_usage import InstallationUsageAccumulator


def observation(machine, user, used):
    return {'machine_id':machine,'user_id':user,'license_pool_id':'app','used':used}


def test_shared_workstation_is_not_counted_twice_or_marked_inactive():
    aggregate = InstallationUsageAccumulator()
    aggregate.add_day('2026-09-01',[observation('pc','alice',False),observation('pc','bob',True)])
    aggregate.add_day('2026-09-02',[observation('pc','alice',False),observation('pc','bob',False)])
    row, = aggregate.results()
    assert row['observed_days'] == 2 and row['active_days'] == 1
    assert row['last_used_on'] == '2026-09-01' and row['complete_coverage']


def test_missing_installation_day_is_not_zero_usage():
    aggregate = InstallationUsageAccumulator()
    aggregate.add_day('2026-09-01',[observation('pc','alice',False)])
    aggregate.add_day('2026-09-02',[])
    row, = aggregate.results()
    assert row['observed_days'] == 1 and not row['complete_coverage']
    assert row['last_used_on'] is None
    with pytest.raises(ValueError,match='Duplicate'):
        aggregate.add_day('2026-09-02',[])
