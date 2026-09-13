from types import SimpleNamespace
import pytest
from app.business.errors import BusinessError
from app.services.published_analytics import read_summary


def test_collection_reads_only_the_published_result():
    result=object()
    class Collection:
        def summary(self):return result
    class Pipeline:
        store=SimpleNamespace(collection=Collection())
        def run_analytics(self):raise AssertionError('UI started Spark')
        def sync(self):raise AssertionError('UI collected the source')
    assert read_summary(Pipeline()) is result


def test_missing_publication_does_not_generate_demo_data():
    class Pipeline:
        store=SimpleNamespace(collection=SimpleNamespace(summary=lambda:None))
        def run_analytics(self):raise AssertionError('UI started Spark')
        def bootstrap_mock_history(self):raise AssertionError('UI generated data')
    with pytest.raises(BusinessError) as error:read_summary(Pipeline())
    assert error.value.status_code==409
