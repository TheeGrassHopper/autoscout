"""
scripts/test_db_backends.py

Smoke-tests the Database and UserDB layers against both backends.

Usage:
    # SQLite (local)
    python scripts/test_db_backends.py

    # Postgres (production URL)
    DATABASE_URL=postgresql://... python scripts/test_db_backends.py
"""

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
_errors = []


def check(label: str, expr: bool):
    if expr:
        print(f"  {PASS}  {label}")
    else:
        msg = f"FAILED: {label}"
        _errors.append(msg)
        print(f"  {FAIL}  {label}")


def section(title: str):
    print(f"\n── {title} {'─' * max(0, 50 - len(title))}")


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_scored_listing(**kwargs):
    from scoring.engine import ScoredListing
    defaults = dict(
        source="craigslist", listing_id="smoke_001",
        url="https://example.com/test",
        title="2020 Toyota Tacoma TRD",
        year=2020, make="Toyota", model="Tacoma", mileage=60000,
        asking_price=32000, kbb_value=36000, carvana_value=38000,
        blended_market_value=37000, profit_estimate=6000,
        profit_margin_pct=0.158, demand_score=85, total_score=72,
        deal_class="fair", title_status="clean", transmission="automatic",
        location="Phoenix, AZ", vin=None, posted_date="2024-01-01",
        description="", image_urls=[],
    )
    defaults.update(kwargs)
    return ScoredListing(**defaults)


# ── listings DB tests ─────────────────────────────────────────────────────────

def test_listings_db(tmp_path):
    from utils.db import Database

    db = Database(db_path=str(tmp_path / "test.db"))

    section("Database — schema")
    stats = db.stats()
    check("stats() returns expected keys",
          all(k in stats for k in ["total_listings", "great_deals", "fair_deals", "messages_sent"]))

    section("Database — upsert + stats")
    sl = _make_scored_listing(listing_id="l1", deal_class="great", total_score=90)
    db.upsert_listing(sl)
    stats = db.stats()
    check("total_listings == 1 after insert", stats["total_listings"] == 1)
    check("great_deals == 1", stats["great_deals"] == 1)

    # Upsert same ID updates in-place
    sl2 = _make_scored_listing(listing_id="l1", deal_class="fair", total_score=55)
    db.upsert_listing(sl2)
    stats = db.stats()
    check("upsert keeps total at 1", stats["total_listings"] == 1)
    check("deal_class updated to fair", stats["great_deals"] == 0)

    section("Database — get_great_deals")
    for i in range(3):
        db.upsert_listing(_make_scored_listing(listing_id=f"g{i}", deal_class="great", total_score=80))
    great = db.get_great_deals(limit=2)
    check("get_great_deals respects limit", len(great) == 2)

    section("Database — messages")
    db.upsert_listing(_make_scored_listing(listing_id="msg1"))
    check("was_contacted False before message", not db.was_contacted("msg1"))
    db.log_message("msg1", "Hello!", status="queued")
    check("was_contacted False for queued", not db.was_contacted("msg1"))
    db.log_message("msg1", "Hello!", status="sent")
    check("was_contacted True after sent", db.was_contacted("msg1"))
    check("messages_sent in stats", db.stats()["messages_sent"] == 1)


# ── user DB tests ─────────────────────────────────────────────────────────────

def test_user_db(tmp_path):
    from utils.user_db import UserDB
    import bcrypt

    db = UserDB(path=str(tmp_path / "users.db"))
    pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()

    section("UserDB — create user")
    user = db.create_user("test@example.com", pw_hash)
    check("user has id", bool(user.get("id")))
    check("email stored correctly", user["email"] == "test@example.com")
    check("first user is admin", user["role"] == "admin")
    check("no password in safe user", "hashed_password" not in user)

    section("UserDB — get user")
    fetched = db.get_user_by_email("test@example.com")
    check("get_user_by_email returns row", fetched is not None)
    check("hashed_password present for auth", "hashed_password" in fetched)

    by_id = db.get_user_by_id(user["id"])
    check("get_user_by_id works", by_id is not None)
    check("no password in get_user_by_id", "hashed_password" not in by_id)

    section("UserDB — update user")
    updated = db.update_user(user["id"], notify_carvana=True)
    check("notify_carvana updated to True", updated["notify_carvana"] is True)

    section("UserDB — second user is not admin")
    pw2 = bcrypt.hashpw(b"pass2", bcrypt.gensalt()).decode()
    user2 = db.create_user("user2@example.com", pw2)
    check("second user role is user", user2["role"] == "user")

    section("UserDB — saved searches")
    search = db.create_search(user["id"], "Tacoma hunt", {"make": "Toyota", "model": "Tacoma"})
    check("search created with id", bool(search.get("id")))
    searches = db.get_searches(user["id"])
    check("get_searches returns 1 result", len(searches) == 1)
    check("criteria is dict", isinstance(searches[0]["criteria"], dict))
    deleted = db.delete_search(search["id"], user["id"])
    check("search deleted", deleted)
    check("searches empty after delete", len(db.get_searches(user["id"])) == 0)

    section("UserDB — favorites")
    listing_data = {"listing_id": "fav1", "title": "Test Car", "asking_price": 30000}
    db.add_favorite(user["id"], "fav1", listing_data)
    favs = db.get_favorites(user["id"])
    check("favorite saved", len(favs) == 1)
    check("listing_data round-tripped", favs[0]["title"] == "Test Car")
    # Upsert same favorite
    db.add_favorite(user["id"], "fav1", {**listing_data, "asking_price": 28000})
    check("upsert favorite keeps count at 1", len(db.get_favorites(user["id"])) == 1)
    removed = db.remove_favorite(user["id"], "fav1")
    check("favorite removed", removed)
    check("favorites empty", len(db.get_favorites(user["id"])) == 0)

    section("UserDB — password reset")
    token = db.create_reset_token(user["id"])
    check("token is non-empty string", bool(token))
    row = db.get_reset_token(token)
    check("get_reset_token returns row", row is not None)
    new_hash = bcrypt.hashpw(b"newpass", bcrypt.gensalt()).decode()
    ok = db.consume_reset_token(token, new_hash)
    check("consume_reset_token returns True", ok)
    check("token unusable after consume", db.get_reset_token(token) is None)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from utils.pg import IS_PG

    backend = "PostgreSQL" if IS_PG else "SQLite"
    print(f"\n{'='*55}")
    print(f"  DB Backend Smoke Test — {backend}")
    print(f"{'='*55}")

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        tmp_path = Path(tmp)
        try:
            test_listings_db(tmp_path / "listings")
        except Exception:
            _errors.append("listings DB crashed")
            traceback.print_exc()
        try:
            test_user_db(tmp_path / "users")
        except Exception:
            _errors.append("user DB crashed")
            traceback.print_exc()

    print(f"\n{'='*55}")
    if _errors:
        print(f"  {FAIL}  {len(_errors)} failure(s):")
        for e in _errors:
            print(f"       • {e}")
        sys.exit(1)
    else:
        print(f"  {PASS}  All checks passed ({backend})")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
