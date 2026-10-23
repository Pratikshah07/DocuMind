"""Migrations apply cleanly and match the ORM models.

Runs against a throwaway SQLite file. The same checks against PostgreSQL are
run with the Alembic CLI (see backend/README.md).
"""

from argparse import Namespace
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.db.session import build_engine
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.cmd_opts = Namespace(x=[f"url={url}"])
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config = alembic_config(url)
    engine = build_engine(url)

    command.upgrade(config, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
