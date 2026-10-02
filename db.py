import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "futarszolgalat.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

@contextmanager
def kapcsolat():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
        ).fetchone()
        if has_tables is None:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close() 