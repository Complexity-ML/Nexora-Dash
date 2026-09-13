"""Exercise real HTTP business workflows in Docker against sam_business_test only."""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.business.store import BusinessStore


def main():
    source = urlsplit(os.environ['DATABASE_URL'])
    test_url = urlunsplit(source._replace(path='/sam_business_test'))
    env = {**os.environ, 'DATABASE_URL': test_url, 'DEMO_ACCOUNTS_ENABLED': 'false'}
    subprocess.run(['alembic', 'upgrade', 'head'], env=env, check=True)
    password = secrets.token_urlsafe(24)
    BusinessStore(test_url).seed_demo(password)
    server = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18001'],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url='http://127.0.0.1:18001', timeout=15) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Test HTTP server exited before startup')
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Test HTTP server did not become ready')
            def request(method, path, actor=None, expected=200, **body):
                headers = auth[actor] if actor else {}
                response = client.request(method, '/api/v1/business'+path, headers=headers, **({'json':body} if body else {}))
                assert response.status_code == expected, (method, path, response.status_code, response.text[:200])
                return response.json()
            auth = {}
            for role in ('admin', 'analyst', 'reader'):
                login = request('POST', '/login', email=role+'@sam.demo', password=password)
                auth[role] = {'Authorization':'Bearer '+login['token']}
            space = request('POST', '/workspaces', 'admin', 201, name='Validation HTTP '+str(uuid4()))
            base = '/workspaces/'+space['id']
            for role in ('analyst','reader'):
                request('PUT', base+'/members', 'admin', email=role+'@sam.demo', role=role)
            request('GET', base+'/cases', expected=401)
            request('PUT', base+'/costs/flex-cad', 'reader', 403, version=0, annual_unit_cents=12000)
            request('PUT', base+'/costs/flex-cad', 'analyst', version=0, annual_unit_cents=12000)
            case = request('POST', base+'/cases', 'analyst', 201, pool_id='flex-cad', title='Examen fictif HTTP', quantity=10, evidence='Validation du parcours')
            assert case['annual_unit_cents'] == 12000
            path = base+'/cases/'+case['id']
            request('PATCH', path, 'analyst', version=1, assignee_id='demo-analyst', quantity=10, annual_unit_cents=12000)
            request('POST', path+'/progress', 'analyst', version=2, status='in_progress', reason='Examen démarré')
            request('POST', path+'/comments', 'analyst', 201, text='Commentaire de validation')
            request('POST', path+'/progress', 'reader', 403, version=3, status='completed', reason='Clôture', outcome='no_action')
            request('POST', path+'/progress', 'analyst', version=3, status='completed', reason='Usage confirmé', outcome='recovered', actual_quantity=4)
            stored = request('GET', path, 'reader')
            assert stored['actual_quantity'] == 4 and stored['status'] == 'completed'
            assert len(stored['events']) == 5
            assert 'Terminé' in request('GET', path+'/export', 'reader')['content']
            other = request('POST', '/workspaces', 'admin', 201, name='Isolation HTTP '+str(uuid4()))
            request('GET', '/workspaces/'+other['id']+'/cases', 'reader', 404)
            request('POST', '/logout', 'reader')
            request('GET', '/me', 'reader', 401)
            print('HTTP workflow passed: persistence, costs, assignment, comments, result, export, isolation, reader restrictions, logout.')
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == '__main__':
    main()
