import asyncio
from app.services.pipeline import SamPipeline

class RealConnector: pass
class Store:
    def list_keys(self, prefix):
        raise AssertionError("real mode must not inspect or seed mock history")

def test_real_connector_never_bootstraps_mock_history():
    pipeline=SamPipeline(RealConnector(),Store(),None)
    asyncio.run(pipeline.bootstrap_mock_history())
