"""
utils/db.py
SQLite/PostgreSQL database for tracking listings, scores, and sent messages.
Prevents duplicate messages and tracks pipeline history.
"""

import json
import logging
import os
from datetime import datetime

from utils.pg import IS_PG, column_exists, db_conn

logger = logging.getLogger(__name__)

# Column type helpers
_PK   = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
_REAL = "DOUBLE PRECISION"      if IS_PG else "REAL"


class Database:
    """Lightweight store for listing + messaging history."""

    def __init__(self, db_path: str = "output/autoscout.db"):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        return db_conn(self.db_path)

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id          TEXT PRIMARY KEY,
                    source              TEXT,
                    title               TEXT,
                    url                 TEXT,
                    asking_price        INTEGER,
                    kbb_value           INTEGER,
                    carvana_value       INTEGER,
                    local_market_value  INTEGER,
                    blended_market_value INTEGER,
                    profit_estimate     INTEGER,
                    profit_margin_pct   {_REAL},
                    demand_score        INTEGER,
                    savings             INTEGER,
                    total_score         INTEGER,
                    deal_class          TEXT,
                    make                TEXT,
                    model               TEXT,
                    year                INTEGER,
                    mileage             INTEGER,
                    location            TEXT,
                    vin                 TEXT,
                    title_status        TEXT,
                    posted_date         TEXT,
                    first_seen          TEXT,
                    last_seen           TEXT,
                    carvana_offer       INTEGER,
                    carvana_offer_margin {_REAL}
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS messages (
                    id              {_PK},
                    listing_id      TEXT,
                    message_text    TEXT,
                    drafted_at      TEXT,
                    sent_at         TEXT,
                    status          TEXT DEFAULT 'queued',
                    FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(total_score DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_class ON listings(deal_class)"
            )

        # Migrate existing DBs: add new columns if missing
        with self._connect() as conn:
            for col, defn in [
                ("carvana_value",        "INTEGER"),
                ("local_market_value",   "INTEGER"),
                ("blended_market_value", "INTEGER"),
                ("profit_estimate",      "INTEGER"),
                ("profit_margin_pct",    _REAL),
                ("demand_score",         "INTEGER"),
                ("vin",                  "TEXT"),
                ("title_status",         "TEXT"),
                ("posted_date",          "TEXT"),
                ("image_urls",           "TEXT"),
                ("carvana_offer",        "INTEGER"),
                ("carvana_offer_margin", _REAL),
            ]:
                if not column_exists(conn, "listings", col):
                    conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {defn}")

        logger.debug(f"Database ready: {self.db_path}")

    def upsert_listing(self, scored_listing):
        """Insert or update a scored listing."""
        now = datetime.now().isoformat()
        image_urls_json = json.dumps(getattr(scored_listing, "image_urls", None) or [])
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO listings
                    (listing_id, source, title, url, asking_price, kbb_value,
                     carvana_value, local_market_value, blended_market_value,
                     profit_estimate, profit_margin_pct, demand_score,
                     savings, total_score, deal_class, make, model, year, mileage,
                     location, vin, title_status, posted_date, image_urls,
                     carvana_offer, carvana_offer_margin, first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    kbb_value=excluded.kbb_value,
                    carvana_value=excluded.carvana_value,
                    local_market_value=excluded.local_market_value,
                    blended_market_value=excluded.blended_market_value,
                    profit_estimate=excluded.profit_estimate,
                    profit_margin_pct=excluded.profit_margin_pct,
                    demand_score=excluded.demand_score,
                    savings=excluded.savings,
                    total_score=excluded.total_score,
                    deal_class=excluded.deal_class,
                    image_urls=excluded.image_urls,
                    carvana_offer=excluded.carvana_offer,
                    carvana_offer_margin=excluded.carvana_offer_margin,
                    last_seen=excluded.last_seen
            """, (
                scored_listing.listing_id,
                scored_listing.source,
                scored_listing.title,
                scored_listing.url,
                scored_listing.asking_price,
                scored_listing.kbb_value,
                scored_listing.carvana_value,
                scored_listing.local_market_value,
                scored_listing.blended_market_value,
                scored_listing.profit_estimate,
                scored_listing.profit_margin_pct,
                scored_listing.demand_score,
                scored_listing.savings_vs_kbb,
                scored_listing.total_score,
                scored_listing.deal_class,
                scored_listing.make,
                scored_listing.model,
                scored_listing.year,
                scored_listing.mileage,
                scored_listing.location,
                scored_listing.vin or None,
                getattr(scored_listing, "title_status", None),
                scored_listing.posted_date,
                image_urls_json,
                scored_listing.carvana_offer,
                scored_listing.carvana_offer_margin,
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
            fair  = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='fair'").fetchone()[0]
            sent  = conn.execute("SELECT COUNT(*) FROM messages WHERE status='sent'").fetchone()[0]
        return {"total_listings": total, "great_deals": great, "fair_deals": fair, "messages_sent": sent}
