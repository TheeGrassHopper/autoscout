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
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# ── Path setup (so we can import from the project root) ──────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.routers import auth as auth_router, users as users_router

from config import (FILTERS, LOCATION, MESSAGING, NOTIFICATIONS,
                    OUTPUT, PRICING_SOURCES, SCORING, SOURCES)

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

DB_PATH = OUTPUT.get("db_path", "output/autoscout.db")
FAV_DB_PATH = "output/favorites.db"

# ── Carvana offer job state ───────────────────────────────────────────────────
# listing_id -> {"status": "running"|"completed"|"error", "offer": str|None, ...}
_offer_jobs: dict = {}

# ── Pipeline state ────────────────────────────────────────────────────────────

_pipeline = {
    "running": False,
    "last_run": None,
    "last_count": 0,
    "logs": queue.Queue(maxsize=500),
}

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _rows(rows) -> list[dict]:
    return [dict(r) for r in rows]

def _db_exists() -> bool:
    return os.path.exists(DB_PATH)

def _fav_db():
    conn = sqlite3.connect(FAV_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_fav_schema():
    with _fav_db() as conn:
        conn.execute("""
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
                profit_margin_pct    REAL,
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
    if not _db_exists():
        return {"total_listings": 0, "great_deals": 0, "fair_deals": 0,
                "poor_deals": 0, "messages_queued": 0, "messages_approved": 0}

    with _db() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        great   = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='great'").fetchone()[0]
        fair    = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='fair'").fetchone()[0]
        poor    = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_class='poor'").fetchone()[0]
        queued  = conn.execute("SELECT COUNT(*) FROM messages WHERE status='queued'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM messages WHERE status='approved'").fetchone()[0]

    return {
        "total_listings": total,
        "great_deals": great,
        "fair_deals": fair,
        "poor_deals": poor,
        "messages_queued": queued,
        "messages_approved": approved,
    }


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
            INSERT OR REPLACE INTO favorites (
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
def start_carvana_offer(listing_id: str, background_tasks: BackgroundTasks, vin: Optional[str] = None):
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
    background_tasks.add_task(_run_carvana_offer_bg, listing_id, listing)
    return {"status": "started"}


@app.get("/api/deals/{listing_id}/carvana-offer")
def get_carvana_offer_status(listing_id: str):
    return _offer_jobs.get(listing_id, {"status": "not_started"})


def _run_carvana_offer_bg(listing_id: str, listing: dict):
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
    except Exception as e:
        _offer_jobs[listing_id].update({"status": "error", "error": str(e)})


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
def pipeline_status():
    return {
        "running": _pipeline["running"],
        "last_run": _pipeline["last_run"],
        "last_count": _pipeline["last_count"],
    }


@app.post("/api/pipeline/run")
def run_pipeline_endpoint(
    background_tasks: BackgroundTasks,
    query: str = "",
    dry_run: bool = True,
    zip_code: str = "",
    radius_miles: int = 0,
):
    if _pipeline["running"]:
        raise HTTPException(409, "Pipeline already running")
    background_tasks.add_task(
        _run_pipeline_bg,
        query=query, dry_run=dry_run,
        zip_code=zip_code, radius_miles=radius_miles,
    )
    return {"status": "started"}


def _run_pipeline_bg(query: str = "", dry_run: bool = True, zip_code: str = "", radius_miles: int = 0):
    _pipeline["running"] = True
    _pipeline["last_run"] = datetime.now().isoformat()

    handler = _QueueLogHandler(_pipeline["logs"])
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s — %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        from main import run_pipeline
        results = run_pipeline(query=query, dry_run=dry_run, zip_code=zip_code or None, radius_miles=radius_miles or None)
        _pipeline["last_count"] = len(results)
        _pipeline["logs"].put(f"✅ Pipeline complete — {len(results)} listings processed")
    except Exception as e:
        _pipeline["logs"].put(f"❌ Pipeline error: {e}")
        logging.exception("Pipeline background task failed")
    finally:
        root.removeHandler(handler)
        _pipeline["running"] = False


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except queue.Full:
            pass


@app.get("/api/pipeline/logs")
def stream_logs():
    """SSE endpoint — browser subscribes and receives live log lines."""
    def generate():
        while True:
            try:
                line = _pipeline["logs"].get(timeout=25)
                yield f"data: {json.dumps({'line': line})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'ping': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Database reset ────────────────────────────────────────────────────────────

@app.delete("/api/database")
def reset_database():
    if _pipeline["running"]:
        raise HTTPException(409, "Pipeline is running — stop it before clearing the database")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
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
