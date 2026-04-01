"""
utils/db.py
SQLite/PostgreSQL database for tracking listings, scores, and sent messages.
Prevents duplicate messages and tracks pipeline history.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

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
                    carvana_offer_margin {_REAL},
                    local_market_comp_urls TEXT,
                    seller_phone        TEXT,
                    seller_email        TEXT,
                    suggested_offer     INTEGER,
                    cylinders           TEXT,
                    fuel                TEXT,
                    body_type           TEXT,
                    transmission        TEXT
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
                ("carvana_offer",           "INTEGER"),
                ("carvana_offer_margin",    _REAL),
                ("local_market_comp_urls",  "TEXT"),
                ("seller_phone",            "TEXT"),
                ("seller_email",            "TEXT"),
                ("suggested_offer",         "INTEGER"),
                ("cylinders",               "TEXT"),
                ("fuel",                    "TEXT"),
                ("body_type",               "TEXT"),
                ("transmission",            "TEXT"),
            ]:
                if not column_exists(conn, "listings", col):
                    conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {defn}")

        # Pricing cache table — survives scrape runs, keyed by vehicle+source
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pricing_cache (
                    cache_key   TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    value       INTEGER,
                    kbb_value   INTEGER,
                    cached_at   TEXT NOT NULL,
                    expires_at  TEXT NOT NULL,
                    PRIMARY KEY (cache_key, source)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pricing_cache_expires ON pricing_cache(expires_at)"
            )

        logger.debug(f"Database ready: {self.db_path}")

    def upsert_listing(self, scored_listing):
        """Insert or update a scored listing."""
        now = datetime.now().isoformat()
        image_urls_json = json.dumps(getattr(scored_listing, "image_urls", None) or [])
        comp_urls_json = json.dumps(getattr(scored_listing, "local_market_comp_urls", None) or [])
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO listings
                    (listing_id, source, title, url, asking_price, kbb_value,
                     carvana_value, local_market_value, blended_market_value,
                     profit_estimate, profit_margin_pct, demand_score,
                     savings, total_score, deal_class, make, model, year, mileage,
                     location, vin, title_status, posted_date, image_urls,
                     carvana_offer, carvana_offer_margin, local_market_comp_urls,
                     seller_phone, seller_email, suggested_offer,
                     cylinders, fuel, body_type, transmission,
                     first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    kbb_value=excluded.kbb_value,
                    carvana_value=excluded.carvana_value,
                    local_market_value=excluded.local_market_value,
                    local_market_comp_urls=excluded.local_market_comp_urls,
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
                    seller_phone=excluded.seller_phone,
                    seller_email=excluded.seller_email,
                    suggested_offer=excluded.suggested_offer,
                    cylinders=excluded.cylinders,
                    fuel=excluded.fuel,
                    body_type=excluded.body_type,
                    transmission=excluded.transmission,
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
                comp_urls_json,
                getattr(scored_listing, "seller_phone", "") or None,
                getattr(scored_listing, "seller_email", "") or None,
                getattr(scored_listing, "suggested_offer", None),
                getattr(scored_listing, "cylinders", "") or None,
                getattr(scored_listing, "fuel", "") or None,
                getattr(scored_listing, "body_type", "") or None,
                getattr(scored_listing, "transmission", "") or None,
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

    # ── Pricing Cache ─────────────────────────────────────────────────────────

    _MILEAGE_BUCKET = 10_000   # round mileage to nearest 10k for cache key
    _CACHE_TTL_DAYS = 7

    @staticmethod
    def _price_cache_key(make: str, model: str, year: int, mileage: int) -> str:
        """Stable cache key: lower-cased make+model+year + mileage bucket."""
        import hashlib
        bucket = round(mileage / Database._MILEAGE_BUCKET) * Database._MILEAGE_BUCKET
        raw = f"{make.lower()}|{model.lower()}|{year}|{bucket}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def get_price_cache(self, make: str, model: str, year: int, mileage: int,
                        source: str) -> Optional[tuple]:
        """Return (value, kbb_value) from cache if still valid, else None."""
        key = self._price_cache_key(make, model, year, mileage)
        now = datetime.now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, kbb_value FROM pricing_cache "
                "WHERE cache_key=? AND source=? AND expires_at > ?",
                (key, source, now),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def set_price_cache(self, make: str, model: str, year: int, mileage: int,
                        source: str, value: Optional[int], kbb_value: Optional[int] = None):
        """Upsert a pricing result into the cache with a 7-day TTL."""
        from datetime import timedelta
        key = self._price_cache_key(make, model, year, mileage)
        now = datetime.now()
        expires = (now + timedelta(days=self._CACHE_TTL_DAYS)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO pricing_cache (cache_key, source, value, kbb_value, cached_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key, source) DO UPDATE SET
                       value=excluded.value, kbb_value=excluded.kbb_value,
                       cached_at=excluded.cached_at, expires_at=excluded.expires_at""",
                (key, source, value, kbb_value, now.isoformat(), expires),
            )

    def purge_stale_listings(self, max_age_days: int = 7) -> int:
        """
        Delete listings whose posted_date is older than max_age_days.
        Listings with no posted_date are kept (can't determine age).
        Returns number of rows deleted.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM listings "
                "WHERE posted_date IS NOT NULL AND posted_date != '' AND posted_date < ?",
                (cutoff,),
            )
        count = cur.rowcount
        if count:
            logger.info(f"Purged {count} stale listings older than {max_age_days} days")
        return count

    def get_all_listing_ids(self) -> set[str]:
        """Return all listing_ids currently in the DB (for TICKET-006 skip logic)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT listing_id FROM listings").fetchall()
        return {r[0] for r in rows}

    def purge_expired_price_cache(self):
        """Delete expired cache rows — call occasionally to keep DB size down."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM pricing_cache WHERE expires_at <= ?",
                (datetime.now().isoformat(),),
            )
        logger.debug(f"Purged {cur.rowcount} expired pricing cache rows")
