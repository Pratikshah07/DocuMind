from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.db.session import build_engine
from app.models import Base

config = context.config
# Programmatic callers (tests) pass configure_logger=False to keep the app's logging setup intact.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Allow `alembic -x url=...` for one-off runs; default to the app's DATABASE_URL.
settings = get_settings()
url = context.get_x_argument(as_dictionary=True).get("url") or settings.database_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Same engine setup as the app: connect timeout, SQLite foreign keys.
    connectable = build_engine(url, connect_timeout=settings.database_connect_timeout)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
