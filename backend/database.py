"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from backend.config import get_database_settings


def get_connection():
    """Create a new database connection."""
    settings = get_database_settings()
    return psycopg2.connect(settings.url)


@contextmanager
def get_db_cursor(dict_cursor: bool = True) -> Generator:
    """Context manager for database cursor."""
    conn = get_connection()
    cursor_factory = RealDictCursor if dict_cursor else None
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cursor:
            yield cursor
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_connection() -> bool:
    """Test database connection."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception:
        return False
