"""Publish the small reference demo into a new, empty mock installation."""
import json
from app.config import get_settings
from app.business import demo_service, workspace_service
from app.dependencies import get_pipeline


def initialize():
    demo_service.check_mode()
    settings=get_settings()
    if not settings.demo_accounts_enabled:
        raise RuntimeError('Enable demo accounts before initializing the mock lake')
    if settings.collection_enabled:
        raise RuntimeError('Initialize before activating journaled collection')
    store=workspace_service.get_business_store()
    previous=demo_service.generation(store)
    if previous['version'] != 0:
        raise RuntimeError('A demo generation already exists; no data changed')
    objects=get_pipeline().store
    if objects.list_keys(''):
        raise RuntimeError('The active lake is not empty; no data changed')
    with store.connect() as db:
        user=db.execute("SELECT id,email,name FROM users WHERE id='demo-admin'").fetchone()
    if not user:
        raise RuntimeError('The demo administrator is unavailable')
    workspace_service.source_operator(user,store)
    # Existing staging and version checks publish only after reference validation.
    # No old generation or business data is deleted by this operation.
    return demo_service.reset(demo_service.Reset(version=previous['version'],confirmation='REINITIALISER LA DEMO'),user,store)


def main():
    print('Preparing the reference demo in a new generation...',flush=True)
    print(json.dumps(initialize()),flush=True)


if __name__=='__main__':main()
