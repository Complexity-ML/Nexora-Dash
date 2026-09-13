from types import SimpleNamespace
import json
from unittest.mock import Mock
from botocore.exceptions import ClientError
from app.services.pipeline import SamPipeline
from app.models.canonical import AnalyticsSummary

class Store:
    revision = 'initial'
    def __init__(self): self.objects = {}
    def usage_revision(self): return self.revision
    def get_bytes(self, key):
        if key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        return self.objects[key]
    def put_json(self, key, value): self.objects[key] = json.dumps(value).encode()

def test_cache_reuses_results_and_invalidates_data_settings_and_scope():
    store = Store()
    analytics = SimpleNamespace(threshold=.35, buffer_rate=.1)
    pipeline = SamPipeline(None, store, analytics)
    value = AnalyticsSummary(generated_at='2026-09-11T00:00:00Z',
        total_capacity=0, total_used=0, total_available=0, utilization_rate=0,
        pools_at_risk=0, pools_total=0, recovery_potential=0, trends=[], inactive=[], risks=[])
    pipeline._compute_analytics = Mock(return_value=value)
    assert pipeline.run_analytics() == value
    assert pipeline.run_analytics() == value
    assert pipeline._compute_analytics.call_count == 1
    # A new request/process still reads the stored result.
    another = SamPipeline(None, store, analytics)
    another._compute_analytics = Mock(side_effect=AssertionError('unexpected recompute'))
    assert another.run_analytics() == value
    for change in ('data', 'threshold', 'buffer', 'scope'):
        if change == 'data': store.revision = 'corrected'
        if change == 'threshold': analytics.threshold = .4
        if change == 'buffer': analytics.buffer_rate = .2
        pipeline.run_analytics([] if change == 'scope' else None)
    assert pipeline._compute_analytics.call_count == 5
    pipeline.run_analytics(['a', 'b'])
    pipeline.run_analytics(['b', 'a'])
    assert pipeline._compute_analytics.call_count == 6
