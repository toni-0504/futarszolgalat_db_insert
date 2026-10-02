import sqlite3
from contextlib import contextmanager

@contextmanager
def kapcsolat():
    conn = sqlite3.connect("futarszolgalat.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close() 