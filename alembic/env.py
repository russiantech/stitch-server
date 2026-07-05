# """
# alembic/env.py — Stitch migration environment.

# Pulls the DB URL from the same place your app does (so it's never out of
# sync with .env / settings), and imports every model module so autogenerate
# can see the full metadata, not just whatever happens to get imported first.
# """

# import sys
# from logging.config import fileConfig
# from pathlib import Path

# from alembic import context
# from sqlalchemy import engine_from_config, pool

# # Make sure `app` is importable regardless of where alembic is invoked from
# sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# # --- Import your app's Base and engine/settings -----------------------------
# from app.db.database import Base  # noqa: E402

# # --- Import every model module so they register on Base.metadata -----------
# # Add/remove to match what's actually in app/models/. If a module isn't
# # imported here, autogenerate will not see its tables and may try to DROP
# # them, thinking they were removed from the models.
# # import app.models.users            # noqa: F401,E402
# # import app.models.orders           # noqa: F401,E402
# # import app.models.pricing          # noqa: F401,E402
# # import app.models.tenant_billing    # noqa: F401,E402
# # import app.models.payments         # noqa: F401,E402

# # from app.models import *

# # Try to reuse the app's own settings object for the DB URL if available;
# # fall back to reading DATABASE_URL from the environment directly.
# try:
#     from app.core.config import get_app_config
#     DB_URL = get_app_config().database_config.sql_connection_string
# except Exception:
#     import os
#     DB_URL = os.environ.get("APP_DATABASE_URL")

# if not DB_URL:
#     raise RuntimeError(
#         "Could not resolve a database URL for Alembic. Set DATABASE_URL, "
#         "or adjust alembic/env.py to import it from your actual settings module."
#     )

# # psycopg2 URLs sometimes come as postgres:// — SQLAlchemy 2.x wants postgresql://
# if DB_URL.startswith("postgres://"):
#     DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# # Alembic Config object, provides access to values in alembic.ini
# config = context.config
# config.set_main_option("sqlalchemy.url", DB_URL)

# # Interpret the config file for Python logging
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

# # Metadata used for 'autogenerate' schema comparisons
# target_metadata = Base.metadata


# def run_migrations_offline() -> None:
#     """Generate SQL scripts without a live DB connection (e.g. for review/CI)."""
#     url = config.get_main_option("sqlalchemy.url")
#     context.configure(
#         url=url,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#         compare_type=True,
#         compare_server_default=True,
#     )
#     with context.begin_transaction():
#         context.run_migrations()


# def run_migrations_online() -> None:
#     """Run migrations against a live DB connection — the normal path."""
#     connectable = engine_from_config(
#         config.get_section(config.config_ini_section, {}),
#         prefix="sqlalchemy.",
#         poolclass=pool.NullPool,
#     )

#     with connectable.connect() as connection:
#         context.configure(
#             connection=connection,
#             target_metadata=target_metadata,
#             compare_type=True,          # catches column type changes, e.g. Integer -> UUID
#             compare_server_default=True,
#             render_as_batch=False,      # not needed on Postgres (only for SQLite)
#         )

#         with context.begin_transaction():
#             context.run_migrations()


# if context.is_offline_mode():
#     run_migrations_offline()
# else:
#     run_migrations_online()




# v2
"""
alembic/env.py — Stitch migration environment.
Auto-discovers all model modules so autogenerate never misses tables.
"""

import importlib
import pkgutil
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure `app` is importable regardless of where alembic is invoked from
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- Import your app's Base ---------------------------------------------------
from app.db.database import Base  # noqa: E402

# --- AUTO-DISCOVER all model modules -----------------------------------------
# This walks app/models/ and imports every .py file so they register on Base.
_MODELS_PACKAGE = "app.models"

def _import_all_models(package_name: str) -> None:
    """Import every submodule so SQLAlchemy sees all tables."""
    try:
        package = importlib.import_module(package_name)
    except ImportError:
        return

    for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if not is_pkg:
            try:
                importlib.import_module(module_name)
            except Exception as exc:
                print(f"[alembic] Warning: could not import {module_name}: {exc}")

_import_all_models(_MODELS_PACKAGE)

# --- DB URL resolution --------------------------------------------------------
try:
    from app.core.config import get_app_config
    DB_URL = get_app_config().database_config.sql_connection_string
except Exception:
    import os
    DB_URL = os.environ.get("APP_DATABASE_URL")

if not DB_URL:
    raise RuntimeError(
        "Could not resolve a database URL for Alembic. "
        "Set APP_DATABASE_URL or adjust alembic/env.py."
    )

if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# --- Alembic config -----------------------------------------------------------
config = context.config
config.set_main_option("sqlalchemy.url", DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

