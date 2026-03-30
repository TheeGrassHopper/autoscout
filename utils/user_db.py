"""
utils/user_db.py — Per-user accounts, saved searches, and user-scoped favorites.

Separate from autoscout.db so user data survives database resets.
"""

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from utils.pg import IS_PG, column_exists, db_conn


DB_PATH = "output/users.db"

# Column type helpers
_PK = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserDB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        with db_conn(self.path) as conn:
            if not IS_PG:
                conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS users (
                    id              {_PK},
                    email           TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    role            TEXT NOT NULL DEFAULT 'user',
                    notify_carvana  INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS saved_searches (
                    id         {_PK},
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name       TEXT NOT NULL,
                    criteria   TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS search_results (
                    id          {_PK},
                    search_id   INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
                    listing_id  TEXT NOT NULL,
                    result_data TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS user_favorites (
                    id           {_PK},
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    listing_id   TEXT NOT NULL,
                    listing_data TEXT NOT NULL,
                    saved_at     TEXT NOT NULL,
                    UNIQUE(user_id, listing_id)
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id         {_PK},
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token      TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    used       INTEGER NOT NULL DEFAULT 0
                )
            """)

        # Migrate existing DBs — add new columns if missing
        with self._conn() as conn:
            for col, defn in [
                ("role",           "TEXT    NOT NULL DEFAULT 'user'"),
                ("notify_carvana", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                if not column_exists(conn, "users", col):
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

    # ── Users ────────────────────────────────────────────────────────────────

    def _safe_user(self, row) -> dict:
        """Return user dict without hashed_password, with bool coercion."""
        d = dict(row)
        d.pop("hashed_password", None)
        d["notify_carvana"] = bool(d.get("notify_carvana", 0))
        return d

    def create_user(self, email: str, hashed_password: str) -> dict:
        admin_email = os.getenv("ADMIN_EMAIL", "").lower().strip()
        with self._conn() as conn:
            if IS_PG:
                cur = conn.execute(
                    "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?) RETURNING id",
                    (email.lower().strip(), hashed_password, _now()),
                )
                uid = conn.lastrowid
            else:
                cur = conn.execute(
                    "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?)",
                    (email.lower().strip(), hashed_password, _now()),
                )
                uid = cur.lastrowid
            # First user ever OR matches ADMIN_EMAIL env var → make admin
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if total == 1 or (admin_email and email.lower().strip() == admin_email):
                conn.execute("UPDATE users SET role='admin' WHERE id=?", (uid,))
            row = conn.execute(
                "SELECT id, email, role, notify_carvana, created_at FROM users WHERE id = ?", (uid,)
            ).fetchone()
            return self._safe_user(row)

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
            return dict(row) if row else None  # includes hashed_password (needed for auth)

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Returns safe profile (no password). Includes role for auth dependency."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, email, role, notify_carvana, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return self._safe_user(row) if row else None

    def update_user(self, user_id: int, email: Optional[str] = None,
                    notify_carvana: Optional[bool] = None) -> Optional[dict]:
        fields, params = [], []
        if email is not None:
            fields.append("email = ?")
            params.append(email.lower().strip())
        if notify_carvana is not None:
            fields.append("notify_carvana = ?")
            params.append(1 if notify_carvana else 0)
        if not fields:
            return self.get_user_by_id(user_id)
        params.append(user_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
            row = conn.execute(
                "SELECT id, email, role, notify_carvana, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return self._safe_user(row) if row else None

    def list_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, email, role, notify_carvana, created_at FROM users ORDER BY created_at"
            ).fetchall()
            return [self._safe_user(r) for r in rows]

    def set_user_role(self, user_id: int, role: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            return cur.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            return cur.rowcount > 0

    # ── Saved Searches ───────────────────────────────────────────────────────

    def create_search(self, user_id: int, name: str, criteria: dict) -> dict:
        now = _now()
        with self._conn() as conn:
            if IS_PG:
                conn.execute(
                    "INSERT INTO saved_searches (user_id, name, criteria, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (user_id, name, json.dumps(criteria), now, now),
                )
                search_id = conn.lastrowid
            else:
                cur = conn.execute(
                    "INSERT INTO saved_searches (user_id, name, criteria, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (user_id, name, json.dumps(criteria), now, now),
                )
                search_id = cur.lastrowid
            return self._fetch_search(conn, search_id)

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

    def update_search(self, search_id: int, user_id: int, name: str, criteria: dict) -> Optional[dict]:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE saved_searches SET name = ?, criteria = ?, updated_at = ?"
                " WHERE id = ? AND user_id = ?",
                (name, json.dumps(criteria), now, search_id, user_id),
            )
            if cur.rowcount == 0:
                return None
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
                """INSERT INTO user_favorites (user_id, listing_id, listing_data, saved_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (user_id, listing_id) DO UPDATE SET
                       listing_data=EXCLUDED.listing_data,
                       saved_at=EXCLUDED.saved_at""",
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

    # ── Password Reset ────────────────────────────────────────────────────────

    def create_reset_token(self, user_id: int) -> str:
        """Generate a secure single-use reset token valid for 1 hour."""
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
                (user_id, token, expires_at),
            )
        return token

    def get_reset_token(self, token: str) -> Optional[dict]:
        """Return token row if it exists, is unused, and has not expired."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM password_reset_tokens WHERE token = ? AND used = 0",
                (token,),
            ).fetchone()
            if not row:
                return None
            row = dict(row)
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                return None
            return row

    def consume_reset_token(self, token: str, new_hashed_password: str) -> bool:
        """Mark token used and update the user's password atomically."""
        row = self.get_reset_token(token)
        if not row:
            return False
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET hashed_password = ? WHERE id = ?",
                (new_hashed_password, row["user_id"]),
            )
            conn.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE token = ?",
                (token,),
            )
        return True
