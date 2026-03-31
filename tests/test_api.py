"""
tests/test_api.py — FastAPI endpoint tests using TestClient.

External dependencies (pipeline, DB) are patched so tests run offline.
"""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── DB helpers for seeding ────────────────────────────────────────────────────

def _seed_listings(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT,
            asking_price INTEGER, kbb_value INTEGER, carvana_value INTEGER,
            carmax_value INTEGER, local_market_value INTEGER,
            blended_market_value INTEGER, profit_estimate INTEGER,
            profit_margin_pct REAL, demand_score INTEGER, savings INTEGER,
            total_score INTEGER, deal_class TEXT, make TEXT, model TEXT,
            year INTEGER, mileage INTEGER, location TEXT, vin TEXT,
            title_status TEXT, posted_date TEXT, first_seen TEXT, last_seen TEXT,
            description TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT, message_text TEXT,
            drafted_at TEXT, sent_at TEXT, status TEXT DEFAULT 'queued'
        )
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("id_great", "craigslist", "2020 Tacoma TRD", "http://x.com/1",
             30000, 36000, 40000, None, None, 38000, 10000, 0.25, 90, 8000,
             85, "great", "Toyota", "Tacoma", 2020, 60000, "Phoenix,AZ", None, "clean",
             "2024-01-01", "2024-01-01", "2024-01-01", "desc1"),
            ("id_fair", "craigslist", "2019 F-150 XLT", "http://x.com/2",
             34000, 36000, 38000, None, None, 37000, 4000, 0.105, 70, 3000,
             62, "fair", "Ford", "F-150", 2019, 80000, "Phoenix,AZ", None, "clean",
             "2024-01-01", "2024-01-01", "2024-01-01", "desc2"),
        ]
    )
    conn.commit()
    conn.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._stats_cache["data"] = None
    app_module._stats_cache["expires"] = 0.0
    app_module._ensure_fav_schema()
    return TestClient(app_module.app)


@pytest.fixture()
def seeded_client(tmp_path, monkeypatch):
    import api.app as app_module
    db_path = str(tmp_path / "test.db")
    fav_path = str(tmp_path / "fav.db")
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(app_module, "DB_PATH", db_path)
    monkeypatch.setattr(app_module, "FAV_DB_PATH", fav_path)
    app_module._stats_cache["data"] = None
    app_module._stats_cache["expires"] = 0.0
    _seed_listings(db_path)
    app_module._ensure_fav_schema()
    return TestClient(app_module.app)


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ── /api/stats ────────────────────────────────────────────────────────────────

def test_stats_empty_db(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_listings"] == 0
    assert data["great_deals"] == 0


def test_stats_with_data(seeded_client):
    res = seeded_client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_listings"] == 2
    assert data["great_deals"] == 1
    assert data["fair_deals"] == 1


# ── /api/deals ────────────────────────────────────────────────────────────────

def test_deals_empty_db_returns_empty_list(client):
    res = client.get("/api/deals")
    assert res.status_code == 200
    assert res.json() == []


def test_deals_returns_all(seeded_client):
    res = seeded_client.get("/api/deals")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_deals_filter_by_class(seeded_client):
    res = seeded_client.get("/api/deals?deal_class=great")
    assert res.status_code == 200
    deals = res.json()
    assert len(deals) == 1
    assert deals[0]["deal_class"] == "great"


def test_deals_filter_by_source(seeded_client):
    res = seeded_client.get("/api/deals?source=craigslist")
    assert res.status_code == 200
    assert all(d["source"] == "craigslist" for d in res.json())


def test_deals_limit_param(seeded_client):
    res = seeded_client.get("/api/deals?limit=1")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_deals_ordered_by_score_desc(seeded_client):
    res = seeded_client.get("/api/deals")
    deals = res.json()
    scores = [d["total_score"] for d in deals]
    assert scores == sorted(scores, reverse=True)


# ── /api/deals/{listing_id} ───────────────────────────────────────────────────
# NOTE: get_deal() returns the listing dict directly with "messages" key embedded

def test_get_single_deal_found(seeded_client):
    res = seeded_client.get("/api/deals/id_great")
    assert res.status_code == 200
    data = res.json()
    # The route returns the listing dict with messages embedded
    assert data["listing_id"] == "id_great"
    assert "messages" in data


def test_get_single_deal_not_found(seeded_client):
    res = seeded_client.get("/api/deals/nonexistent_id")
    assert res.status_code == 404


# ── /api/pipeline/status ──────────────────────────────────────────────────────

def test_pipeline_status_initial_state(client):
    import api.app as app_module
    # Fresh slot for anon user
    app_module._pipelines.pop("anon", None)
    res = client.get("/api/pipeline/status")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is False
    assert data["last_run"] is None


# ── /api/pipeline/run ─────────────────────────────────────────────────────────

def test_pipeline_run_returns_started(client):
    import api.app as app_module
    app_module._pipelines.pop("anon", None)
    with patch("api.app._run_pipeline_bg"):
        res = client.post("/api/pipeline/run?query=tacoma&dry_run=true")
    assert res.status_code == 200
    assert res.json()["status"] == "started"
    # Reset state
    app_module._pipelines.pop("anon", None)


def test_pipeline_run_rejects_concurrent(client):
    import api.app as app_module
    slot = app_module._get_pipeline("anon")
    slot["running"] = True
    try:
        res = client.post("/api/pipeline/run")
        assert res.status_code == 409
    finally:
        slot["running"] = False


def test_pipeline_users_run_concurrently(client):
    """Two different users can run pipelines simultaneously."""
    import api.app as app_module
    from api.routers.auth import make_token

    app_module._pipelines.pop("1", None)
    app_module._pipelines.pop("2", None)

    token1 = make_token(1, "user1@test.com")
    token2 = make_token(2, "user2@test.com")
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    with patch("api.app._run_pipeline_bg"):
        r1 = client.post("/api/pipeline/run?query=tacoma&dry_run=true", headers=headers1)
    assert r1.status_code == 200, r1.json()

    # User 2 should NOT be blocked by user 1's running pipeline
    with patch("api.app._run_pipeline_bg"):
        r2 = client.post("/api/pipeline/run?query=camry&dry_run=true", headers=headers2)
    assert r2.status_code == 200, r2.json()

    # Each user sees only their own status
    s1 = client.get("/api/pipeline/status", headers=headers1).json()
    s2 = client.get("/api/pipeline/status", headers=headers2).json()
    assert s1["running"] is True
    assert s2["running"] is True

    # Cleanup
    app_module._pipelines.pop("1", None)
    app_module._pipelines.pop("2", None)


def test_pipeline_stop_only_affects_own_slot(client):
    """Stopping one user's pipeline doesn't touch another user's."""
    import api.app as app_module
    from api.routers.auth import make_token

    token1 = make_token(1, "user1@test.com")
    token2 = make_token(2, "user2@test.com")
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    slot1 = app_module._get_pipeline("1")
    slot2 = app_module._get_pipeline("2")
    slot1["running"] = True
    slot2["running"] = True

    try:
        r = client.post("/api/pipeline/stop", headers=headers1)
        assert r.status_code == 200
        assert slot1["stop_requested"] is True
        assert slot2["stop_requested"] is False
    finally:
        slot1["running"] = False
        slot1["stop_requested"] = False
        slot2["running"] = False


# ── /api/favorites ────────────────────────────────────────────────────────────

def test_favorites_empty(client):
    res = client.get("/api/favorites")
    assert res.status_code == 200
    assert res.json() == []


def test_save_and_retrieve_favorite(seeded_client):
    res = seeded_client.post("/api/favorites/id_great")
    assert res.status_code == 200

    fav_res = seeded_client.get("/api/favorites")
    assert fav_res.status_code == 200
    favs = fav_res.json()
    assert len(favs) == 1
    assert favs[0]["listing_id"] == "id_great"


def test_favorite_not_found_listing(seeded_client):
    res = seeded_client.post("/api/favorites/nonexistent")
    assert res.status_code == 404


def test_remove_favorite(seeded_client):
    seeded_client.post("/api/favorites/id_great")
    del_res = seeded_client.delete("/api/favorites/id_great")
    assert del_res.status_code == 200

    fav_res = seeded_client.get("/api/favorites")
    assert fav_res.json() == []


# ── /api/messages/queue ───────────────────────────────────────────────────────

def test_messages_queue_empty(seeded_client):
    res = seeded_client.get("/api/messages/queue")
    assert res.status_code == 200
    assert res.json() == []


def test_messages_queue_shows_queued(seeded_client):
    import api.app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.execute(
        "INSERT INTO messages (listing_id, message_text, drafted_at, status) VALUES (?,?,?,?)",
        ("id_great", "Hey, interested in your Tacoma?", "2024-01-01", "queued")
    )
    conn.commit()
    conn.close()

    res = seeded_client.get("/api/messages/queue")
    assert res.status_code == 200
    msgs = res.json()
    assert len(msgs) == 1
    assert msgs[0]["message_text"] == "Hey, interested in your Tacoma?"


# ── /api/messages/{id}/approve & skip ────────────────────────────────────────

def test_approve_message(seeded_client):
    import api.app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.execute(
        "INSERT INTO messages (id, listing_id, message_text, drafted_at, status) VALUES (?,?,?,?,?)",
        (42, "id_great", "Hey!", "2024-01-01", "queued")
    )
    conn.commit()
    conn.close()

    res = seeded_client.post("/api/messages/42/approve")
    assert res.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    status = conn.execute("SELECT status FROM messages WHERE id=42").fetchone()[0]
    conn.close()
    assert status == "approved"


def test_skip_message(seeded_client):
    import api.app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.execute(
        "INSERT INTO messages (id, listing_id, message_text, drafted_at, status) VALUES (?,?,?,?,?)",
        (99, "id_fair", "Hey!", "2024-01-01", "queued")
    )
    conn.commit()
    conn.close()

    res = seeded_client.post("/api/messages/99/skip")
    assert res.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    status = conn.execute("SELECT status FROM messages WHERE id=99").fetchone()[0]
    conn.close()
    assert status == "skipped"


# NOTE: approve/skip on nonexistent ID returns 200 (UPDATE with no rows is not an error in SQLite)
# This is the current API behavior — the test verifies it doesn't crash.
def test_approve_nonexistent_message_does_not_crash(seeded_client):
    res = seeded_client.post("/api/messages/9999/approve")
    assert res.status_code in (200, 404)


# ── /api/config ───────────────────────────────────────────────────────────────

def test_config_endpoint(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "location" in data
    assert "filters" in data
    assert "scoring" in data


# ── /api/database DELETE ─────────────────────────────────────────────────────

def test_delete_database_clears_data(seeded_client):
    res = seeded_client.delete("/api/database")
    assert res.status_code == 200

    res2 = seeded_client.get("/api/stats")
    assert res2.json()["total_listings"] == 0


def test_delete_database_blocked_while_running(client):
    import api.app as app_module
    slot = app_module._get_pipeline("anon")
    slot["running"] = True
    try:
        res = client.delete("/api/database")
        assert res.status_code == 409
    finally:
        slot["running"] = False


# ── API key middleware ────────────────────────────────────────────────────────

def test_api_key_required_when_configured(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "secret123")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._ensure_fav_schema()

    c = TestClient(app_module.app)
    res = c.get("/api/stats")
    assert res.status_code == 401


def test_api_key_accepted_via_header(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "secret123")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._ensure_fav_schema()

    c = TestClient(app_module.app)
    res = c.get("/api/stats", headers={"X-API-Key": "secret123"})
    assert res.status_code == 200


def test_api_key_accepted_via_query_param(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "secret123")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._ensure_fav_schema()

    c = TestClient(app_module.app)
    res = c.get("/api/stats?api_key=secret123")
    assert res.status_code == 200


def test_health_bypasses_api_key(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "secret123")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._ensure_fav_schema()

    c = TestClient(app_module.app)
    res = c.get("/health")
    assert res.status_code == 200


# ── CarMax offer endpoints ────────────────────────────────────────────────────

def test_carmax_offer_status_not_started(seeded_client):
    res = seeded_client.get("/api/deals/id_great/carmax-offer")
    assert res.status_code == 200
    assert res.json()["status"] == "not_started"


def test_carmax_offer_start_no_vin(seeded_client):
    """Listing with no VIN should 400."""
    res = seeded_client.post("/api/deals/id_great/carmax-offer")
    assert res.status_code == 400
    assert "VIN" in res.json()["detail"]


def test_carmax_offer_start_with_vin(seeded_client, monkeypatch):
    """POST with explicit VIN queues a job and returns started."""
    import api.app as app_module
    app_module._carmax_jobs.pop("id_great", None)

    with patch("api.app._run_carmax_offer_bg"):
        res = seeded_client.post("/api/deals/id_great/carmax-offer?vin=1HGBH41JXMN109186")
    assert res.status_code == 200
    assert res.json()["status"] == "started"

    status = seeded_client.get("/api/deals/id_great/carmax-offer").json()
    assert status["status"] == "running"

    app_module._carmax_jobs.pop("id_great", None)


def test_carmax_offer_completed_state(seeded_client):
    """Manually setting a completed job is returned correctly."""
    import api.app as app_module
    app_module._carmax_jobs["id_great"] = {
        "status": "completed",
        "offer": "$6,000–$9,500",
        "offer_low": 6000,
        "offer_high": 9500,
        "error": None,
        "steps": ["Navigated to CarMax", "Entered VIN", "Got offer"],
    }
    res = seeded_client.get("/api/deals/id_great/carmax-offer")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["offer_low"] == 6000
    assert data["offer_high"] == 9500

    app_module._carmax_jobs.pop("id_great", None)
