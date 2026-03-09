"""
utils/db.py
SQLite database for tracking listings, scores, and sent messages.
Prevents duplicate messages and tracks pipeline history.
"""

import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    """Lightweight SQLite store for listing + messaging history."""

    def __init__(self, db_path: str = "output/autoscout.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id      TEXT PRIMARY KEY,
                    source          TEXT,
                    title           TEXT,
                    url             TEXT,
                    asking_price    INTEGER,
                    kbb_value       INTEGER,
                    savings         INTEGER,
                    total_score     INTEGER,
                    deal_class      TEXT,
                    make            TEXT,
                    model           TEXT,
                    year            INTEGER,
                    mileage         INTEGER,
                    location        TEXT,
                    first_seen      TEXT,
                    last_seen       TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id      TEXT,
                    message_text    TEXT,
                    drafted_at      TEXT,
                    sent_at         TEXT,
                    status          TEXT DEFAULT 'queued',
                    FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
                );

                CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(total_score DESC);
                CREATE INDEX IF NOT EXISTS idx_listings_class ON listings(deal_class);
            """)
        logger.debug(f"Database ready: {self.db_path}")

    def upsert_listing(self, scored_listing):
        """Insert or update a scored listing."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO listings
                    (listing_id, source, title, url, asking_price, kbb_value, savings,
                     total_score, deal_class, make, model, year, mileage, location,
                     first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    total_score=excluded.total_score,
                    deal_class=excluded.deal_class,
                    last_seen=excluded.last_seen
            """, (
                scored_listing.listing_id,
                scored_listing.source,
                scored_listing.title,
                scored_listing.url,
                scored_listing.asking_price,
                scored_listing.kbb_value,
                scored_listing.savings_vs_kbb,
                scored_listing.total_score,
                scored_listing.deal_class,
                scored_listing.make,
                scored_listing.model,
                scored_listing.year,
                scored_listing.mileage,
                scored_listing.location,
                now, now,
            ))

    def was_contacted(self, listing_id: str) -> bool:
        """Return True if we've already sent a message for this listing."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE listing_id=? AND status='sent' LIMIT 1",
                (listing_id,)
            ).fetchone()
        return row is not None

    def log_message(self, listing_id: str, message_text: str, status: str = "queued"):
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (listing_id, message_text, drafted_at, status) VALUES (?,?,?,?)",
                (listing_id, message_text, now, status)
            )

    def get_great_deals(self, limit: int = 20) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM listings WHERE deal_class='great' ORDER BY total_score DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            great = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='great'").fetchone()[0]
            fair = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='fair'").fetchone()[0]
            sent = conn.execute("SELECT COUNT(*) FROM messages WHERE status='sent'").fetchone()[0]
        return {"total_listings": total, "great_deals": great, "fair_deals": fair, "messages_sent": sent}
