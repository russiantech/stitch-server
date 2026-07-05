"""
app/db/database.py — Lazy singleton DB engine for Stitch.
Follows the exact pattern from the Intellect reference.
"""
import json
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from sqlalchemy.pool import QueuePool

from app.core.config import get_app_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_session_maker = None

def _json_serializer(obj):
    return json.dumps(obj, default=str)

def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    config = get_app_config()
    db_url = config.database_config.sql_connection_string
    if not db_url:
        raise ValueError("APP_SQL_CONNECTION_STRING is not set in .env")

    _engine = create_engine(
        db_url,
        json_serializer=_json_serializer,
        poolclass=QueuePool,
        pool_size=config.database_config.pool_size,
        max_overflow=config.database_config.max_overflow,
        pool_recycle=config.database_config.pool_recycle,
        pool_timeout=config.database_config.pool_timeout,
        echo=config.database_config.echo,
        pool_pre_ping=True,
        future=True,
        # connect_args={"connect_timeout": 5},
        connect_args={"connect_timeout": 10} if "postgresql" in db_url else {},
    )

    @event.listens_for(_engine, "connect")
    def set_timezone(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET TIME ZONE 'Africa/Lagos'")
        cursor.close()

    logger.info("Database engine initialised.")
    return _engine


def get_session_maker() -> sessionmaker:
    global _session_maker
    if _session_maker is None:
        _session_maker = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_maker


def get_db():
    """FastAPI dependency — yields a DB session, rolls back on error."""
    db: Session = get_session_maker()()
    try:
        yield db
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Database error: %s", exc)
        raise
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables created/verified.")


def close_db():
    global _engine, _session_maker
    if _engine:
        _engine.dispose()
        logger.info("Database connection pool closed.")
        _engine = None
        _session_maker = None


def db_ping() -> str:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"

