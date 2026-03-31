"""
api/app.py — AutoScout AI REST API

Run with:
    uvicorn api.app:app --reload --port 8000

Endpoints:
    GET  /api/stats               → dashboard numbers
    GET  /api/deals               → all scored listings
    GET  /api/deals/{id}          → single listing + messages
    GET  /api/messages/queue      → pending messages to approve
    POST /api/messages/{id}/approve
    POST /api/messages/{id}/skip
    GET  /api/pipeline/status
    POST /api/pipeline/run
    GET  /api/pipeline/logs       → SSE log stream
    GET  /api/config
"""

import json
import logging
import os
import queue
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# ── Path setup (so we can import from the project root) ──────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routers import auth as auth_router, users as users_router, admin as admin_router

from config import (FILTERS, LOCATION, MESSAGING, NOTIFICATIONS,
                    OUTPUT, PRICING_SOURCES, SCORING, SOURCES)
from utils.pg import IS_PG, db_conn as _db_conn

# ── Logging setup (configure before any routes run) ───────────────────────────
os.makedirs("output", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("output/autoscout.log", encoding="utf-8"),
    ],
    force=True,  # override any root handler set earlier
)
logger = logging.getLogger("autoscout.api")
logger.info("AutoScout API starting up")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="AutoScout AI", version="1.0")

# ── CORS ─────────────────────────────────────────────────────────────────────
_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Railway frontend origin set via env
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Key auth (optional — set AUTOSCOUT_API_KEY env var to enable) ─────────
_API_KEY = os.getenv("AUTOSCOUT_API_KEY", "")

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if _API_KEY:
        path = request.url.path
        if request.method == "OPTIONS" or path == "/health" or path.startswith("/auth"):
            return await call_next(request)
        # Accept key from header OR query param (EventSource can't set headers)
        key = (
            request.headers.get("X-API-Key", "")
            or request.query_params.get("api_key", "")
        )
        if key != _API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s — %s",
        request.method, request.url.path, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


@app.get("/health")
def health():
    return {"status": "ok"}

# ── User portal routers ───────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(admin_router.router)

DB_PATH = OUTPUT.get("db_path", "output/autoscout.db")
FAV_DB_PATH = "output/favorites.db"

# ── Carvana offer job state ───────────────────────────────────────────────────
# listing_id -> {"status": "running"|"completed"|"error", "offer": str|None, ...}
_offer_jobs: dict = {}

# ── Stats cache (avoid hammering DB on every 3s poll) ────────────────────────
_stats_cache: dict = {"data": None, "expires": 0.0}

# ── Pipeline state (per-user) ─────────────────────────────────────────────────
# Keyed by user_key (str user_id from JWT, or "anon").
# Each slot is independent — multiple users can run simultaneously.

_pipelines: dict[str, dict] = {}
_pipelines_lock = threading.Lock()


def _make_pipeline_slot() -> dict:
    return {
        "running": False,
        "last_run": None,
        "last_count": 0,
        "logs": queue.Queue(maxsize=500),
        "start_time": None,
        "stop_requested": False,
    }


def _get_pipeline_key(request: Request) -> str:
    """Extract user_id from Bearer token, fall back to 'anon'."""
    from api.routers.auth import decode_token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        payload = decode_token(auth[7:])
        if payload and payload.get("sub"):
            return str(payload["sub"])
    return "anon"


def _get_pipeline(key: str) -> dict:
    with _pipelines_lock:
        if key not in _pipelines:
            _pipelines[key] = _make_pipeline_slot()
        return _pipelines[key]

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    """Return a context manager that yields a unified DB connection for the main DB."""
    return _db_conn(DB_PATH)

def _rows(rows) -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        import json as _json
        if "image_urls" in d:
            d["image_urls"] = _json.loads(d["image_urls"] or "[]")
        if "local_market_comp_urls" in d:
            d["local_market_comp_urls"] = _json.loads(d["local_market_comp_urls"] or "[]")
        out.append(d)
    return out


from utils.email import send_email as _send_email

def _db_exists() -> bool:
    """Return True if the listings table exists in the main DB."""
    if IS_PG:
        try:
            with _db_conn(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name='listings'",
                    (),
                ).fetchone()
                return bool(row and row[0])
        except Exception:
            return False
    else:
        if not os.path.exists(DB_PATH):
            return False
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'"
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            return False

def _fav_db():
    """Return a context manager that yields a unified DB connection for the favorites DB."""
    return _db_conn(FAV_DB_PATH)

_REAL = "DOUBLE PRECISION" if IS_PG else "REAL"

def _ensure_fav_schema():
    with _fav_db() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS favorites (
                listing_id           TEXT PRIMARY KEY,
                source               TEXT,
                title                TEXT,
                url                  TEXT,
                asking_price         INTEGER,
                kbb_value            INTEGER,
                carvana_value        INTEGER,
                carmax_value         INTEGER,
                local_market_value   INTEGER,
                blended_market_value INTEGER,
                profit_estimate      INTEGER,
                profit_margin_pct    {_REAL},
                demand_score         INTEGER,
                savings              INTEGER,
                total_score          INTEGER,
                deal_class           TEXT,
                make                 TEXT,
                model                TEXT,
                year                 INTEGER,
                mileage              INTEGER,
                location             TEXT,
                vin                  TEXT,
                title_status         TEXT,
                posted_date          TEXT,
                first_seen           TEXT,
                last_seen            TEXT,
                saved_at             TEXT NOT NULL
            )
        """)

_ensure_fav_schema()


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    import time
    now = time.monotonic()
    if _stats_cache["data"] and now < _stats_cache["expires"]:
        return _stats_cache["data"]

    if not _db_exists():
        result = {"total_listings": 0, "great_deals": 0, "fair_deals": 0,
                  "poor_deals": 0, "messages_queued": 0, "messages_approved": 0}
    else:
        with _db() as conn:
            total    = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            great    = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='great'").fetchone()[0]
            fair     = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='fair'").fetchone()[0]
            poor     = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='poor'").fetchone()[0]
            queued   = conn.execute("SELECT COUNT(*) FROM messages WHERE status='queued'").fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM messages WHERE status='approved'").fetchone()[0]
        result = {
            "total_listings": total, "great_deals": great, "fair_deals": fair,
            "poor_deals": poor, "messages_queued": queued, "messages_approved": approved,
        }

    _stats_cache["data"] = result
    _stats_cache["expires"] = now + 15.0  # cache for 15 seconds
    return result


# ── Deals ─────────────────────────────────────────────────────────────────────

@app.get("/api/deals")
def get_deals(
    deal_class: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 200,
):
    if not _db_exists():
        return []

    sql = "SELECT * FROM listings"
    conditions, params = [], []

    if deal_class:
        conditions.append("deal_class = ?")
        params.append(deal_class)
    if source:
        conditions.append("source = ?")
        params.append(source)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY total_score DESC LIMIT ?"
    params.append(limit)

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows(rows)


@app.get("/api/deals/{listing_id}")
def get_deal(listing_id: str):
    if not _db_exists():
        raise HTTPException(404, "No database yet")

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM listings WHERE listing_id=?", (listing_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Listing not found")

        msgs = conn.execute(
            "SELECT * FROM messages WHERE listing_id=? ORDER BY drafted_at DESC",
            (listing_id,)
        ).fetchall()

    deal = dict(row)
    deal["image_urls"] = json.loads(deal.get("image_urls") or "[]")
    deal["local_market_comp_urls"] = json.loads(deal.get("local_market_comp_urls") or "[]")
    deal["messages"] = _rows(msgs)
    return deal


# ── Favorites ─────────────────────────────────────────────────────────────────

@app.get("/api/favorites")
def get_favorites():
    _ensure_fav_schema()
    with _fav_db() as conn:
        rows = conn.execute("SELECT * FROM favorites ORDER BY saved_at DESC").fetchall()
    return _rows(rows)


@app.post("/api/favorites/{listing_id}")
def save_favorite(listing_id: str):
    if not _db_exists():
        raise HTTPException(404, "Main database not found")
    with _db() as conn:
        row = conn.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")

    data = dict(row)
    data["saved_at"] = datetime.now().isoformat()
    data.setdefault("carmax_value", None)

    _ensure_fav_schema()
    with _fav_db() as conn:
        conn.execute("""
            INSERT INTO favorites (
                listing_id, source, title, url, asking_price, kbb_value,
                carvana_value, carmax_value, local_market_value, blended_market_value,
                profit_estimate, profit_margin_pct, demand_score, savings,
                total_score, deal_class, make, model, year, mileage, location,
                vin, title_status, posted_date, first_seen, last_seen, saved_at
            ) VALUES (
                :listing_id, :source, :title, :url, :asking_price, :kbb_value,
                :carvana_value, :carmax_value, :local_market_value, :blended_market_value,
                :profit_estimate, :profit_margin_pct, :demand_score, :savings,
                :total_score, :deal_class, :make, :model, :year, :mileage, :location,
                :vin, :title_status, :posted_date, :first_seen, :last_seen, :saved_at
            )
            ON CONFLICT(listing_id) DO UPDATE SET
                source=EXCLUDED.source, title=EXCLUDED.title, url=EXCLUDED.url,
                asking_price=EXCLUDED.asking_price, kbb_value=EXCLUDED.kbb_value,
                carvana_value=EXCLUDED.carvana_value, carmax_value=EXCLUDED.carmax_value,
                local_market_value=EXCLUDED.local_market_value,
                blended_market_value=EXCLUDED.blended_market_value,
                profit_estimate=EXCLUDED.profit_estimate,
                profit_margin_pct=EXCLUDED.profit_margin_pct,
                demand_score=EXCLUDED.demand_score, savings=EXCLUDED.savings,
                total_score=EXCLUDED.total_score, deal_class=EXCLUDED.deal_class,
                make=EXCLUDED.make, model=EXCLUDED.model, year=EXCLUDED.year,
                mileage=EXCLUDED.mileage, location=EXCLUDED.location,
                vin=EXCLUDED.vin, title_status=EXCLUDED.title_status,
                posted_date=EXCLUDED.posted_date, first_seen=EXCLUDED.first_seen,
                last_seen=EXCLUDED.last_seen, saved_at=EXCLUDED.saved_at
        """, data)
    return {"status": "saved", "listing_id": listing_id}


@app.delete("/api/favorites/{listing_id}")
def remove_favorite(listing_id: str):
    _ensure_fav_schema()
    with _fav_db() as conn:
        conn.execute("DELETE FROM favorites WHERE listing_id=?", (listing_id,))
    return {"status": "removed", "listing_id": listing_id}


# ── Carvana Offer Automation ──────────────────────────────────────────────────

@app.post("/api/deals/{listing_id}/carvana-offer")
def start_carvana_offer(listing_id: str, background_tasks: BackgroundTasks,
                        vin: Optional[str] = None, user_id: Optional[int] = None):
    """Kick off the Playwright Carvana sell automation. Accepts optional ?vin= override."""
    listing = None
    if _db_exists():
        with _db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, title FROM listings WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        _ensure_fav_schema()
        with _fav_db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, title FROM favorites WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        # Listing may not be in DB yet (e.g. called from favorites-only); create minimal record
        listing = {"listing_id": listing_id, "vin": None, "mileage": 50000, "title": "", "description": ""}
    # Manual VIN overrides stored VIN
    if vin:
        listing["vin"] = vin
    if not listing.get("vin"):
        raise HTTPException(400, "No VIN available — paste a VIN in the field and try again")

    _offer_jobs[listing_id] = {"status": "running", "offer": None, "error": None, "steps": []}
    background_tasks.add_task(_run_carvana_offer_bg, listing_id, listing, user_id)
    return {"status": "started"}


@app.get("/api/deals/{listing_id}/carvana-offer")
def get_carvana_offer_status(listing_id: str):
    return _offer_jobs.get(listing_id, {"status": "not_started"})


def _run_carvana_offer_bg(listing_id: str, listing: dict, user_id: Optional[int] = None):
    import asyncio as _aio
    from utils.carvana_sell import run_carvana_offer
    try:
        result = _aio.run(run_carvana_offer(
            vin=listing["vin"],
            mileage=int(listing.get("mileage") or 50000),
            title=listing.get("title", ""),
            description=listing.get("description", "") or "",
        ))
        _offer_jobs[listing_id].update(result)
        # Email notification
        if user_id and result.get("status") in ("completed", "error"):
            try:
                from utils.user_db import UserDB as _UserDB
                u = _UserDB().get_user_by_id(user_id)
                if u and u.get("notify_carvana"):
                    offer = result.get("offer") or "Not available"
                    subject = f"Carvana offer ready: {listing.get('title', listing_id)}"
                    body = (
                        f"Your Carvana cash offer result:\n\n"
                        f"Vehicle: {listing.get('title', listing_id)}\n"
                        f"Offer: {offer}\n"
                        f"Status: {result.get('status')}\n"
                        f"{'Error: ' + result['error'] if result.get('error') else ''}\n"
                    )
                    _send_email(u["email"], subject, body)
            except Exception as email_err:
                logger.warning("Carvana email notification failed: %s", email_err)
    except Exception as e:
        _offer_jobs[listing_id].update({"status": "error", "error": str(e)})


# ── Cars.com Market Intel ─────────────────────────────────────────────────────

_carscom_jobs: dict = {}  # listing_id → result dict

@app.get("/api/deals/{listing_id}/carscom-intel")
def get_carscom_intel_status(listing_id: str):
    """Return cached or in-progress Cars.com intel for a listing."""
    return _carscom_jobs.get(listing_id, {"status": "not_started", "data": None})


@app.post("/api/deals/{listing_id}/carscom-intel")
def start_carscom_intel(listing_id: str, background_tasks: BackgroundTasks):
    """Kick off a Cars.com Apify lookup for the listing's VIN in the background."""
    listing = None
    if _db_exists():
        with _db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, make, model, year FROM listings WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        _ensure_fav_schema()
        with _fav_db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, make, model, year FROM favorites WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        listing = {"listing_id": listing_id, "vin": None, "mileage": None, "make": "", "model": "", "year": None}

    if not listing.get("vin"):
        return {"status": "no_vin", "data": None}

    _carscom_jobs[listing_id] = {"status": "running", "data": None}
    background_tasks.add_task(_run_carscom_bg, listing_id, listing)
    return {"status": "started"}


def _run_carscom_bg(listing_id: str, listing: dict):
    from pricing.carscom_apify import get_carscom_intel
    try:
        data = get_carscom_intel(
            vin=listing.get("vin", ""),
            make=listing.get("make", ""),
            model=listing.get("model", ""),
            year=listing.get("year"),
            mileage=listing.get("mileage"),
        )
        _carscom_jobs[listing_id] = {"status": "completed", "data": data}
    except Exception as e:
        _carscom_jobs[listing_id] = {"status": "error", "data": None, "error": str(e)}
        logger.warning(f"[CarscomIntel] Failed for {listing_id}: {e}")


# ── CarMax Offer ──────────────────────────────────────────────────────────────

_carmax_jobs: dict = {}  # listing_id → result dict


@app.post("/api/deals/{listing_id}/carmax-offer")
def start_carmax_offer(listing_id: str, background_tasks: BackgroundTasks,
                       vin: Optional[str] = None):
    listing = None
    if _db_exists():
        with _db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, title FROM listings WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        _ensure_fav_schema()
        with _fav_db() as conn:
            row = conn.execute(
                "SELECT listing_id, vin, mileage, title FROM favorites WHERE listing_id=?",
                (listing_id,)
            ).fetchone()
            if row:
                listing = dict(row)
    if not listing:
        listing = {"listing_id": listing_id, "vin": None, "mileage": 50000, "title": ""}
    if vin:
        listing["vin"] = vin
    if not listing.get("vin"):
        raise HTTPException(400, "No VIN available")

    _carmax_jobs[listing_id] = {"status": "running", "offer": None, "offer_low": None, "offer_high": None, "error": None, "steps": []}
    background_tasks.add_task(_run_carmax_offer_bg, listing_id, listing)
    return {"status": "started"}


@app.get("/api/deals/{listing_id}/carmax-offer")
def get_carmax_offer_status(listing_id: str):
    return _carmax_jobs.get(listing_id, {"status": "not_started", "offer": None, "offer_low": None, "offer_high": None})


def _run_carmax_offer_bg(listing_id: str, listing: dict):
    import asyncio as _aio
    from utils.carmax_sell import run_carmax_offer
    from utils.vin_decode import decode_vin
    try:
        vin_data = decode_vin(listing["vin"]) if listing.get("vin") else {}
        result = _aio.run(run_carmax_offer(
            vin=listing["vin"],
            mileage=int(listing.get("mileage") or 50000),
            trim=vin_data.get("trim"),
        ))
        _carmax_jobs[listing_id].update(result)
    except Exception as e:
        _carmax_jobs[listing_id].update({"status": "error", "error": str(e)})
        logger.warning(f"[CarmaxOffer] Failed for {listing_id}: {e}")


# ── Messages ──────────────────────────────────────────────────────────────────

@app.get("/api/messages/queue")
def get_message_queue():
    if not _db_exists():
        return []

    with _db() as conn:
        rows = conn.execute("""
            SELECT m.id, m.listing_id, m.message_text, m.drafted_at, m.status,
                   l.title, l.url, l.asking_price, l.kbb_value, l.savings,
                   l.total_score, l.deal_class, l.make, l.model, l.year, l.mileage, l.location
            FROM messages m
            JOIN listings l ON m.listing_id = l.listing_id
            WHERE m.status = 'queued'
            ORDER BY l.total_score DESC
        """).fetchall()

    return _rows(rows)


@app.post("/api/messages/{message_id}/approve")
def approve_message(message_id: int):
    if not _db_exists():
        raise HTTPException(404, "No database yet")
    with _db() as conn:
        conn.execute(
            "UPDATE messages SET status='approved', sent_at=? WHERE id=?",
            (datetime.now().isoformat(), message_id),
        )
    return {"status": "approved"}


@app.post("/api/messages/{message_id}/skip")
def skip_message(message_id: int):
    if not _db_exists():
        raise HTTPException(404, "No database yet")
    with _db() as conn:
        conn.execute("UPDATE messages SET status='skipped' WHERE id=?", (message_id,))
    return {"status": "skipped"}


# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.get("/api/pipeline/status")
def pipeline_status(request: Request):
    p = _get_pipeline(_get_pipeline_key(request))
    elapsed = None
    if p["running"] and p["start_time"]:
        elapsed = int((datetime.now() - datetime.fromisoformat(p["start_time"])).total_seconds())
    return {
        "running": p["running"],
        "last_run": p["last_run"],
        "last_count": p["last_count"],
        "start_time": p["start_time"],
        "elapsed_seconds": elapsed,
        "stop_requested": p["stop_requested"],
    }


@app.post("/api/pipeline/stop")
def stop_pipeline(request: Request):
    p = _get_pipeline(_get_pipeline_key(request))
    if not p["running"]:
        raise HTTPException(409, "Pipeline is not running")
    p["stop_requested"] = True
    return {"status": "stop_requested"}


@app.post("/api/pipeline/run")
def run_pipeline_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    query: str = "",
    dry_run: bool = True,
    zip_code: str = "",
    radius_miles: int = 0,
    include_facebook: bool = True,
    min_year: int = 0,
    max_year: int = 0,
    max_price: int = 0,
    max_mileage: int = 0,
):
    key = _get_pipeline_key(request)
    p = _get_pipeline(key)
    if p["running"]:
        raise HTTPException(409, "Your pipeline is already running")
    # Set running=True immediately to prevent race condition
    p["running"] = True
    p["last_run"] = datetime.now().isoformat()
    p["start_time"] = datetime.now().isoformat()
    p["stop_requested"] = False
    background_tasks.add_task(
        _run_pipeline_bg,
        pipeline_key=key,
        query=query, dry_run=dry_run,
        zip_code=zip_code, radius_miles=radius_miles,
        include_facebook=include_facebook,
        min_year=min_year, max_year=max_year,
        max_price=max_price, max_mileage=max_mileage,
    )
    return {"status": "started"}


def _run_pipeline_bg(pipeline_key: str, query: str = "", dry_run: bool = True,
                     zip_code: str = "", radius_miles: int = 0,
                     include_facebook: bool = True, min_year: int = 0, max_year: int = 0,
                     max_price: int = 0, max_mileage: int = 0):
    p = _get_pipeline(pipeline_key)
    handler = _QueueLogHandler(p["logs"])
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s — %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        import asyncio
        from main import run_pipeline
        results = asyncio.run(run_pipeline(
            query=query, dry_run=dry_run,
            zip_code=zip_code or None, radius_miles=radius_miles or None,
            stop_check=lambda: p["stop_requested"],
            include_facebook=include_facebook,
            min_year=min_year or None, max_year=max_year or None,
            max_price=max_price or None, max_mileage=max_mileage or None,
        ))
        p["last_count"] = len(results)
        msg = f"⛔ Pipeline stopped — {len(results)} listings processed" if p["stop_requested"] \
              else f"✅ Pipeline complete — {len(results)} listings processed"
        p["logs"].put(msg)
    except Exception as e:
        p["logs"].put(f"❌ Pipeline error: {e}")
        logging.exception("Pipeline background task failed")
    finally:
        root.removeHandler(handler)
        p["running"] = False
        p["start_time"] = None
        p["stop_requested"] = False


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except queue.Full:
            pass


@app.post("/api/pipeline/prefetch")
def prefetch_comps(background_tasks: BackgroundTasks, request: Request):
    """
    K: Pre-warm the comps cache for all vehicles currently in the DB.
    Designed to be called by a scheduler (Railway cron, external cron, etc.)
    so the first real pipeline run finds all comps already cached.

    Safe to call while a pipeline is running — it only writes to the comps
    cache, which is read-only during scoring.
    """
    _verify_api_key(request)

    def _run_prefetch():
        try:
            import asyncio
            from utils.db import Database
            from utils.comps import CompsEngine

            db = Database(db_path=DB_PATH)
            rows = db.get_great_deals(limit=500) or []
            # Also pull fair + poor
            with db._connect() as conn:
                all_rows = conn.execute(
                    "SELECT make, model FROM listings WHERE make IS NOT NULL AND model IS NOT NULL"
                ).fetchall()

            unique = {(r["make"], r["model"]) for r in all_rows if r["make"] and r["model"]}
            if not unique:
                logger.info("Prefetch: no vehicles in DB yet — nothing to warm")
                return

            logger.info(f"Prefetch: warming comps cache for {len(unique)} vehicle type(s)…")
            engine = CompsEngine([])
            engine.fetch_all_comps(unique, max_seconds=300)
            logger.info("Prefetch: comps cache warm-up complete")
        except Exception as e:
            logger.error(f"Prefetch failed: {e}")

    background_tasks.add_task(_run_prefetch)
    return {"status": "prefetch_started"}


@app.get("/api/pipeline/logs")
def stream_logs(request: Request, token: str = ""):
    """SSE endpoint — browser subscribes and receives live log lines for their pipeline.
    Pass ?token=<jwt> since EventSource cannot set Authorization headers.
    Falls back to Bearer token in header → anon.
    """
    if token:
        from api.routers.auth import decode_token
        payload = decode_token(token)
        key = str(payload["sub"]) if payload and payload.get("sub") else "anon"
    else:
        key = _get_pipeline_key(request)
    p = _get_pipeline(key)

    def generate():
        while True:
            try:
                line = p["logs"].get(timeout=25)
                yield f"data: {json.dumps({'line': line})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'ping': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Database reset ────────────────────────────────────────────────────────────

@app.delete("/api/database")
def reset_database(request: Request):
    from api.routers.auth import decode_token
    from utils.user_db import UserDB as _UserDB

    # Require authentication
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    payload = decode_token(auth[7:])
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = _UserDB().get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required to clear the database")

    # Check no pipeline is running for any user
    with _pipelines_lock:
        running_users = [k for k, p in _pipelines.items() if p["running"]]
    if running_users:
        raise HTTPException(409, "Pipeline is running — stop it before clearing the database")

    if IS_PG:
        with _db_conn(DB_PATH) as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM listings")
            conn.execute("DELETE FROM pricing_cache")
    elif os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    _stats_cache["data"] = None
    _stats_cache["expires"] = 0.0
    return {"status": "cleared"}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    return {
        "location": LOCATION,
        "filters": FILTERS,
        "sources": SOURCES,
        "pricing_sources": PRICING_SOURCES,
        "scoring": SCORING,
        "messaging": MESSAGING,
    }
