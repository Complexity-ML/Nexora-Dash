"""A worker must be ready for parallel script requests before serving browsers."""
from concurrent.futures import ThreadPoolExecutor
import re
from app.dash_ui.app import create_app


def test_startup_registers_scripts_without_business_or_lake_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Startup must not read business data or run the pipeline')
    monkeypatch.setattr('app.dash_ui.context.workspace.get_business_store', forbidden)
    monkeypatch.setattr('app.dash_ui.context.get_pipeline', forbidden)
    app = create_app(testing=True)
    # Registration must already be finished, before the first external request.
    assert app.registered_paths.get('dash')
    with app.server.test_client() as client:
        document = client.get('/').text
    paths = re.findall(r'<script[^>]+src="([^"]*_dash-component-suites[^"]+)"', document)
    assert len(paths) >= 5
    def fetch(path):
        with app.server.test_client() as client:
            response = client.get(path)
            return response.status_code, response.content_type
    with ThreadPoolExecutor(max_workers=8) as threads:
        responses = list(threads.map(fetch, paths * 2))
    assert all(code == 200 and 'javascript' in kind for code, kind in responses)
