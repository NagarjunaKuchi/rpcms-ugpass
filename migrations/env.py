import os

from alembic import context
from sqlalchemy import create_engine

from rpcms_ugpass.config import Settings
from rpcms_ugpass.models import Base

target_metadata = Base.metadata


def _url() -> str:
    # Only the database URL is needed, so migrations do not require the service's secrets to be set.
    return (context.config.get_main_option("sqlalchemy.url") or os.environ.get("RPCMS_UGPASS_DATABASE_URL")
            or Settings.model_fields["database_url"].default)


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
