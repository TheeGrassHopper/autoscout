"""
tests/conftest.py — Shared fixtures for the AutoScout test suite.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Minimal RawListing factory ────────────────────────────────────────────────

def make_raw_listing(**kwargs):
    """Return a RawListing with sensible defaults, overridable via kwargs."""
    from scrapers.craigslist import RawListing

    defaults = dict(
        source="craigslist",
        listing_id="test_001",
        url="https://phoenix.craigslist.org/test/001",
        title="2020 Toyota Tacoma TRD Sport 4x4",
        price=32000,
        location="Phoenix, AZ",
        posted_date="2024-01-01",
        description="Silver, FWD, no accidents, 60k miles, clean title",
        image_urls=[],
        year=2020,
        make="Toyota",
        model="Tacoma",
        mileage=60000,
        transmission="automatic",
        condition="good",
        title_status="clean",
        color="silver",
        vin=None,
    )
    defaults.update(kwargs)
    return RawListing(**defaults)


# ── In-memory SQLite DB fixture ───────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path):
    """Return a Database instance backed by a temporary file (auto-cleaned)."""
    from utils.db import Database

    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    yield db


# ── Scored listing factory ────────────────────────────────────────────────────

def make_scored_listing(**kwargs):
    """Return a ScoredListing with defaults suitable for most unit tests."""
    from scoring.engine import ScoredListing

    defaults = dict(
        source="craigslist",
        listing_id="test_001",
        url="https://example.com/test",
        title="2020 Toyota Tacoma TRD Sport 4x4",
        year=2020,
        make="Toyota",
        model="Tacoma",
        mileage=60000,
        asking_price=32000,
        kbb_value=36000,
        carvana_value=38000,
        blended_market_value=37000,
        profit_estimate=6000,
        profit_margin_pct=0.158,
        demand_score=85,
        total_score=72,
        deal_class="fair",
        title_status="clean",
        transmission="automatic",
        location="Phoenix, AZ",
        vin=None,
        posted_date="2024-01-01",
        description="",
        image_urls=[],
    )
    defaults.update(kwargs)
    return ScoredListing(**defaults)
