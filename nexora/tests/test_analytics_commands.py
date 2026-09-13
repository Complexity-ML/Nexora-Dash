import pytest
@pytest.mark.parametrize('endpoint_name', ['stock', 'live'])
def test_published_stock_io_does_not_block_event_loop(endpoint_name):
    import asyncio
    from threading import Event
    from types import SimpleNamespace
    from app.services import analytics_commands as routes
    entered, release = Event(), Event()
    def read_snapshot():
        entered.set()
        assert release.wait(5), 'Event loop blocked during storage read'
        return SimpleNamespace(stock=[], usage=[])
    pipeline = SimpleNamespace(store=SimpleNamespace(collection=SimpleNamespace(latest_snapshot=read_snapshot)))
    async def check():
        task = asyncio.create_task(getattr(routes, endpoint_name)(pool_ids=None, pipeline=pipeline))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            release.set()
            assert await task == []
        finally:
            release.set()
    asyncio.run(check())
