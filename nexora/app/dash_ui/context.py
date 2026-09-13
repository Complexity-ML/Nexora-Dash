from dataclasses import dataclass
from flask import session, current_app
from app.business import workspace_service as workspace
from app.business import portfolio_service as portfolio
from app.business.errors import BusinessError
from app.dependencies import get_pipeline
from app.services.published_analytics import read_summary


@dataclass
class Context:
    user: dict
    store: object
    workspace: dict
    spaces: list
    pipeline: object = None

    @property
    def wid(self):
        return self.workspace['id']

    @property
    def writable(self):
        return self.workspace['role'] in ('admin', 'analyst')

    def lake(self):
        if self.pipeline is None:
            self.pipeline = get_pipeline()
        return self.pipeline

    def pools(self):
        return portfolio.selected_pools(self.wid, self.user, self.store)

    def summary(self):
        return read_summary(self.lake(), self.pools())

    def call(self, function, *args, lake=False, **kwargs):
        if lake:
            kwargs['pipeline'] = self.lake()
        return function(*args, user=self.user, store=self.store, **kwargs)


def business_store():
    return current_app.config.get('NEXORA_BUSINESS_STORE') or workspace.get_business_store()


def authenticated_user():
    store = business_store()
    user = store.user_for_token(session.get('token', ''))
    if not user:
        session.clear()
        raise BusinessError(401, 'Connectez-vous à votre espace.')
    return user,store


def current_context(wid=None):
    user,store=authenticated_user()
    spaces = workspace.me(user=user, store=store)['workspaces']
    selected = wid or session.get('workspace')
    if selected is None and spaces:
        selected = spaces[0]['id']
    active = next((w for w in spaces if w['id'] == selected), None)
    if not active:
        raise BusinessError(404, 'Cet espace n’est plus accessible. Choisissez un autre espace.')
    return Context(user, store, active, spaces)
