from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from rpcms_ugpass.models import Base

ROOT = Path(__file__).resolve().parents[1]


def cfg(url):
    c = Config(str(ROOT / "alembic.ini"))
    c.set_main_option("script_location", str(ROOT / "migrations"))
    c.set_main_option("sqlalchemy.url", url)
    return c


def test_migrations_produce_exactly_the_model_schema(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    command.upgrade(cfg(url), "head")
    with create_engine(url).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata) == []
    command.downgrade(cfg(url), "base")
    with create_engine(url).connect() as conn:
        assert [t for t in Base.metadata.tables if create_engine(url).dialect.has_table(conn, t)] == []
