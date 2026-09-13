"""Coverage regressions must not replace a committed collection."""
from datetime import datetime, timezone
import pytest
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.collection.quality import CoveragePolicy, CoverageRejected, compare_coverage
from app.connectors.demo import snapshot


def test_coverage_checks_subsidiaries_even_when_total_is_unchanged():
    old = {'machines': 100, 'machines/subsidiary/A': 50, 'machines/subsidiary/B': 50}
    new = {'machines': 100, 'machines/subsidiary/A': 100}
    result = compare_coverage(old, new, CoveragePolicy())
    assert not result['accepted']
    assert result['decreases'] == [{'dimension': 'machines/subsidiary/B', 'previous': 50, 'received': 0}]


def test_retention_boundary_and_initial_baseline():
    assert compare_coverage({'machines': 100}, {'machines': 90}, CoveragePolicy())['accepted']
    assert not compare_coverage({'machines': 100}, {'machines': 89}, CoveragePolicy())['accepted']
    initial = compare_coverage({}, {'machines': 1}, CoveragePolicy())
    assert initial['accepted'] and not initial['baseline_available']


def test_missing_inventory_keeps_publication_and_records_rejection(context):
    pipeline, journal = context
    baseline = collect(CollectionRunner(pipeline, journal))
    raw = snapshot(datetime(2026, 1, 2, tzinfo=timezone.utc))
    del raw['inventory']
    with pytest.raises(CoverageRejected):
        CollectionRunner(pipeline, journal).run(raw, source='digimon-mock', scope='group',
                                               snapshot_id='missing-inventory', source_revision='1')
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group')['run_id'] == baseline['run_id']
    with journal.store.connect() as db:
        run = db.execute('SELECT * FROM collection_runs WHERE namespace=%s AND snapshot_id=%s',
                          (pipeline.store.prefix, 'missing-inventory')).fetchone()
    assert run['state'] == 'rejected' and run['error_code'] == 'COVERAGE_DECREASE'
    checkpoints = journal.checkpoints(run['id'])
    assert set(checkpoints) == {'bronze', 'validated'}
    assert not checkpoints['validated']['quality']['accepted']
    assert any(row['dimension'] == 'machines' for row in checkpoints['validated']['quality']['decreases'])


def test_explicit_floor_rejects_missing_dimension_without_baseline():
    policy = CoveragePolicy(minimum_counts={'machines/subsidiary/A': 50})
    report = compare_coverage({}, {'machines': 100}, policy)
    assert not report['accepted'] and not report['baseline_available']
    assert report['shortfalls'] == [{'dimension':'machines/subsidiary/A', 'minimum':50, 'received':0}]
    assert compare_coverage({}, {'machines/subsidiary/A':50}, policy)['accepted']


@pytest.mark.parametrize('value', [True, -1, 1.5, '10'])
def test_floor_requires_nonnegative_integer(value):
    with pytest.raises(ValueError):
        CoveragePolicy(minimum_counts={'machines':value})
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, collection_minimum_counts={'machines':value})


def test_unconfigured_floors_preserve_recovery_identity():
    assert CoveragePolicy().identity() == {'minimum_retained_fraction':0.9}


def test_first_load_below_floor_is_archived_but_never_published(context):
    pipeline, journal = context
    pipeline.collection_quality_policy = {'minimum_counts': {'machines': 121}}
    runner = CollectionRunner(pipeline, journal)
    with pytest.raises(CoverageRejected):
        collect(runner)
    steps = journal.checkpoints(runner.run_id)
    assert set(steps) == {'bronze', 'validated'}
    assert steps['validated']['quality']['shortfalls'] == [{'dimension':'machines', 'minimum':121, 'received':120}]
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None
