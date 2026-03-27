"""
tests/test_db.py — Database (utils/db.py) unit tests using a temp SQLite file.
"""

import pytest
from utils.db import Database
from tests.conftest import make_scored_listing


@pytest.fixture()
def db(tmp_path):
    return Database(db_path=str(tmp_path / "test.db"))


# ── Schema is created on init ─────────────────────────────────────────────────

def test_tables_created_on_init(db):
    # Verify tables exist by running queries against them (works for both SQLite + Postgres)
    stats = db.stats()
    assert "total_listings" in stats
    assert "messages_sent" in stats


# ── upsert_listing ────────────────────────────────────────────────────────────

def test_upsert_inserts_new_listing(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    stats = db.stats()
    assert stats["total_listings"] == 1


def test_upsert_updates_existing_listing(db):
    sl = make_scored_listing(total_score=50, deal_class="fair")
    db.upsert_listing(sl)

    sl_updated = make_scored_listing(total_score=85, deal_class="great")
    db.upsert_listing(sl_updated)

    stats = db.stats()
    assert stats["total_listings"] == 1
    assert stats["great_deals"] == 1


def test_upsert_multiple_listings(db):
    for i in range(5):
        sl = make_scored_listing(listing_id=f"id_{i}", deal_class="fair")
        db.upsert_listing(sl)
    assert db.stats()["total_listings"] == 5


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_counts_by_class(db):
    db.upsert_listing(make_scored_listing(listing_id="g1", deal_class="great", total_score=80))
    db.upsert_listing(make_scored_listing(listing_id="f1", deal_class="fair",  total_score=60))
    db.upsert_listing(make_scored_listing(listing_id="f2", deal_class="fair",  total_score=55))
    db.upsert_listing(make_scored_listing(listing_id="p1", deal_class="poor",  total_score=10))

    stats = db.stats()
    assert stats["total_listings"] == 4
    assert stats["great_deals"] == 1
    assert stats["fair_deals"] == 2


def test_stats_empty_db(db):
    stats = db.stats()
    assert stats["total_listings"] == 0
    assert stats["great_deals"] == 0


# ── get_great_deals ───────────────────────────────────────────────────────────

def test_get_great_deals_returns_only_great(db):
    db.upsert_listing(make_scored_listing(listing_id="g1", deal_class="great", total_score=90))
    db.upsert_listing(make_scored_listing(listing_id="f1", deal_class="fair",  total_score=60))
    db.upsert_listing(make_scored_listing(listing_id="p1", deal_class="poor",  total_score=10))

    great = db.get_great_deals()
    # Returns sqlite Row objects — check count
    assert len(great) == 1


def test_get_great_deals_respects_limit(db):
    for i in range(10):
        db.upsert_listing(make_scored_listing(listing_id=f"g{i}", deal_class="great", total_score=80))
    assert len(db.get_great_deals(limit=3)) == 3


# ── was_contacted ─────────────────────────────────────────────────────────────
# NOTE: was_contacted() returns True only when status='sent' (not 'approved')

def test_was_contacted_false_before_message(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    assert db.was_contacted("test_001") is False


def test_was_contacted_true_after_sent_message(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    db.log_message("test_001", "Hey, interested in your Tacoma?", status="sent")
    assert db.was_contacted("test_001") is True


def test_was_contacted_false_for_queued_message(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    db.log_message("test_001", "Message in queue", status="queued")
    assert db.was_contacted("test_001") is False


def test_was_contacted_false_for_approved_not_sent(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    db.log_message("test_001", "Approved but not sent yet", status="approved")
    assert db.was_contacted("test_001") is False


# ── log_message ───────────────────────────────────────────────────────────────

def test_log_message_persisted(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    db.log_message("test_001", "Hey there!", status="queued")
    # Verify via the was_contacted helper (queued ≠ sent)
    assert db.was_contacted("test_001") is False
    # Re-log as sent and confirm it shows up
    db.log_message("test_001", "Hey there!", status="sent")
    assert db.was_contacted("test_001") is True


def test_log_message_default_status_is_queued(db):
    sl = make_scored_listing()
    db.upsert_listing(sl)
    db.log_message("test_001", "Test message")
    # Default status is 'queued' so was_contacted should be False
    assert db.was_contacted("test_001") is False


# ── Isolation between test runs ───────────────────────────────────────────────

def test_separate_db_instances_are_independent(tmp_path):
    db_a = Database(db_path=str(tmp_path / "a.db"))
    db_b = Database(db_path=str(tmp_path / "b.db"))

    db_a.upsert_listing(make_scored_listing(listing_id="only_in_a"))
    assert db_a.stats()["total_listings"] == 1
    assert db_b.stats()["total_listings"] == 0
