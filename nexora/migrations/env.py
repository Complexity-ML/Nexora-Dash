from alembic import context
from sqlalchemy import create_engine
from app.config import get_settings

url = get_settings().database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
