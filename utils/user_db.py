"""
utils/user_db.py — Per-user accounts, saved searches, and user-scoped favorites.

Separate from autoscout.db so user data survives database resets.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = "output/users.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserDB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    email           TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS saved_searches (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name       TEXT NOT NULL,
                    criteria   TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_results (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_id   INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
                    listing_id  TEXT NOT NULL,
                    result_data TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_favorites (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    listing_id   TEXT NOT NULL,
                    listing_data TEXT NOT NULL,
                    saved_at     TEXT NOT NULL,
                    UNIQUE(user_id, listing_id)
                );
            """)

    # ── Users ────────────────────────────────────────────────────────────────

    def create_user(self, email: str, hashed_password: str) -> dict:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?)",
                (email.lower().strip(), hashed_password, _now()),
            )
            row = conn.execute(
                "SELECT id, email, created_at FROM users WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── Saved Searches ───────────────────────────────────────────────────────

    def create_search(self, user_id: int, name: str, criteria: dict) -> dict:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO saved_searches (user_id, name, criteria, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, json.dumps(criteria), now, now),
            )
            return self._fetch_search(conn, cur.lastrowid)

    def get_searches(self, user_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [self._parse_search(row) for row in rows]

    def get_search(self, search_id: int) -> Optional[dict]:
        with self._conn() as conn:
            return self._fetch_search(conn, search_id)

    def delete_search(self, search_id: int, user_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
                (search_id, user_id),
            )
            return cur.rowcount > 0

    def delete_all_searches(self, user_id: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM saved_searches WHERE user_id = ?", (user_id,)
            )
            return cur.rowcount

    def _fetch_search(self, conn, search_id: int) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM saved_searches WHERE id = ?", (search_id,)
        ).fetchone()
        return self._parse_search(row) if row else None

    def _parse_search(self, row) -> dict:
        d = dict(row)
        d["criteria"] = json.loads(d["criteria"])
        return d

    # ── Search Results ───────────────────────────────────────────────────────

    def save_search_results(self, search_id: int, results: list[dict]):
        now = _now()
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO search_results (search_id, listing_id, result_data, created_at) VALUES (?, ?, ?, ?)",
                [(search_id, r.get("listing_id", ""), json.dumps(r), now) for r in results],
            )

    def get_search_results(self, search_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT result_data FROM search_results WHERE search_id = ? ORDER BY created_at DESC",
                (search_id,),
            ).fetchall()
            return [json.loads(row["result_data"]) for row in rows]

    # ── User Favorites ───────────────────────────────────────────────────────

    def add_favorite(self, user_id: int, listing_id: str, listing_data: dict) -> dict:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO user_favorites (user_id, listing_id, listing_data, saved_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, listing_id, json.dumps(listing_data), _now()),
            )
            row = conn.execute(
                "SELECT * FROM user_favorites WHERE user_id = ? AND listing_id = ?",
                (user_id, listing_id),
            ).fetchone()
            return {**json.loads(row["listing_data"]), "saved_at": row["saved_at"]}

    def get_favorites(self, user_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM user_favorites WHERE user_id = ? ORDER BY saved_at DESC",
                (user_id,),
            ).fetchall()
            return [{**json.loads(r["listing_data"]), "saved_at": r["saved_at"]} for r in rows]

    def remove_favorite(self, user_id: int, listing_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM user_favorites WHERE user_id = ? AND listing_id = ?",
                (user_id, listing_id),
            )
            return cur.rowcount > 0
