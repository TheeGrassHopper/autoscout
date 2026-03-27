"""
utils/pg.py — Unified DB connection helper.

When DATABASE_URL is set → use psycopg2 (PostgreSQL).
When DATABASE_URL is not set → use sqlite3 as before (local dev / tests).

Usage:
    from utils.pg import db_conn, IS_PG, column_exists

    with db_conn("output/autoscout.db") as conn:
        conn.execute("SELECT * FROM listings WHERE id = ?", (1,))
        row = conn.fetchone()
"""

import os
import re
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")
IS_PG = bool(DATABASE_URL)


# ── Postgres adapter ──────────────────────────────────────────────────────────

class _PGAdapter:
    """
    Wraps a psycopg2 cursor so it behaves like sqlite3's connection/cursor combo.

    Key differences handled:
    - `?` placeholders are converted to `%s`
    - `.lastrowid` is extracted from `RETURNING id` queries automatically
    - `.execute()` returns self (like sqlite3's connection.execute())
    - Named dict params (`:name` style used in app.py's favorites INSERT) are
      converted to %(name)s style for psycopg2.
    """

    def __init__(self, pg_conn):
        self._conn = pg_conn
        import psycopg2.extras
        self._cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._lastrowid = None
        self._rowcount = 0

    # ── Placeholder conversion ────────────────────────────────────────────────

    @staticmethod
    def _adapt_sql(sql: str, params):
        """
        Convert sqlite3-style SQL to psycopg2-style:
          - `?` positional → `%s`
          - `:name` named   → %(name)s  (with dict params)
        Also ensures `AUTOINCREMENT` is stripped (not valid in PG).
        """
        sql = sql.replace("AUTOINCREMENT", "")
        sql = sql.replace("INTEGER PRIMARY KEY", "BIGSERIAL PRIMARY KEY")

        if isinstance(params, dict):
            # Named-style: :foo → %(foo)s
            sql = re.sub(r":(\w+)", r"%(\1)s", sql)
        else:
            # Positional-style: ? → %s
            sql = sql.replace("?", "%s")

        return sql

    # ── sqlite3-like interface ─────────────────────────────────────────────────

    def execute(self, sql: str, params=()):
        adapted = self._adapt_sql(sql, params)
        # Detect RETURNING id so we can capture lastrowid
        returning = "returning id" in adapted.lower()
        self._cur.execute(adapted, params or None)
        self._rowcount = self._cur.rowcount
        if returning:
            row = self._cur.fetchone()
            self._lastrowid = row["id"] if row else None
        return self

    def executemany(self, sql: str, params_seq):
        adapted = self._adapt_sql(sql, ())
        self._cur.executemany(adapted, params_seq)
        self._rowcount = self._cur.rowcount
        return self

    def executescript(self, script: str):
        """Execute a multi-statement script (splits on ';')."""
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._cur.execute(stmt)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        # RealDictCursor already returns a dict-like; wrap as plain dict
        return dict(row)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._rowcount

    def __getitem__(self, key):
        """Allow row[0] access (used in stats() for COUNT(*) results)."""
        raise TypeError("Use fetchone()/fetchall() then index the returned dict/list")


# ── Row wrapper for PG fetchone results supporting both [0] and ["col"] ──────

class _PGRow(dict):
    """Dict subclass that also supports integer index access for COUNT(*) etc."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


# ── Patch adapter fetchone/fetchall to return _PGRow ─────────────────────────

_orig_fetchone = _PGAdapter.fetchone
_orig_fetchall = _PGAdapter.fetchall


def _fetchone_pg(self):
    row = _orig_fetchone(self)
    return _PGRow(row) if row is not None else None


def _fetchall_pg(self):
    rows = _orig_fetchall(self)
    return [_PGRow(r) for r in rows]


_PGAdapter.fetchone = _fetchone_pg
_PGAdapter.fetchall = _fetchall_pg


# ── SQLite Row wrapper (supports both key and index access already) ───────────

# sqlite3.Row supports both column-name and integer index access natively.


# ── Context manager ───────────────────────────────────────────────────────────

@contextmanager
def db_conn(sqlite_path: str = ""):
    """
    Yield a unified connection object.

    If DATABASE_URL is set, yields a _PGAdapter wrapping a psycopg2 connection.
    Otherwise yields a sqlite3 connection with row_factory=sqlite3.Row.

    The caller uses it as a plain context manager:
        with db_conn("output/autoscout.db") as conn:
            conn.execute(...)
    """
    if IS_PG:
        import psycopg2
        pg_conn = psycopg2.connect(DATABASE_URL)
        adapter = _PGAdapter(pg_conn)
        try:
            yield adapter
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()
            raise
        finally:
            pg_conn.close()
    else:
        # Ensure parent dir exists for sqlite path
        if sqlite_path:
            os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
        conn = sqlite3.connect(sqlite_path or ":memory:")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ── Schema helper ─────────────────────────────────────────────────────────────

def column_exists(conn, table: str, col: str) -> bool:
    """Return True if `col` exists in `table`. Works for both SQLite and Postgres."""
    if IS_PG:
        row = conn.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=? AND column_name=?",
            (table, col),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM pragma_table_info(?) WHERE name=?",
            (table, col),
        ).fetchone()
    count = row[0] if row else 0
    return bool(count)
