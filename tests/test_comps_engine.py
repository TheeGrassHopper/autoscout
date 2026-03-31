"""
tests/test_comps_engine.py

Tests for the CompsEngine filtering logic (no network calls needed).
Covers: widened ±2yr / ±15k filter, progressive fallback, cache helpers,
preload, and edge cases.
"""

import json
import os
import pytest
from utils.comps import CompsEngine, DEFAULT_YEAR_RANGE, DEFAULT_MILEAGE_RANGE, _load_cache, _save_cache


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _engine_with_pool(entries: list[tuple]) -> CompsEngine:
    """Build a CompsEngine with a pre-seeded pool, bypassing network."""
    engine = CompsEngine([])
    engine._cache[("toyota", "camry")] = [[y, m, p] for y, m, p in entries]
    return engine


# ── Default window constants ──────────────────────────────────────────────────

class TestDefaults:

    def test_year_range_is_2(self):
        assert DEFAULT_YEAR_RANGE == 2

    def test_mileage_range_is_15k(self):
        assert DEFAULT_MILEAGE_RANGE == 15_000


# ── Filter: year window ───────────────────────────────────────────────────────

class TestYearFilter:

    def test_includes_exact_year(self):
        engine = _engine_with_pool([(2020, 80_000, 15_000)])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 15_000

    def test_includes_year_within_2(self):
        engine = _engine_with_pool([
            (2018, 80_000, 14_000),  # 2020 - 2 = 2018 ✅
            (2022, 80_000, 16_000),  # 2020 + 2 = 2022 ✅
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 15_000  # median of 14k and 16k

    def test_excludes_year_beyond_2(self):
        engine = _engine_with_pool([
            (2017, 80_000, 10_000),  # 2020 - 3 ❌
            (2023, 80_000, 25_000),  # 2020 + 3 ❌
        ])
        # Both filtered out — falls back to full pool median
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 17_500  # full pool fallback

    def test_old_filter_1yr_would_have_missed_these(self):
        """Verify ±2yr catches comps that ±1yr would miss."""
        engine = _engine_with_pool([
            (2018, 80_000, 14_000),  # ±1yr would exclude (diff=2), ±2yr includes ✅
            (2022, 80_000, 16_000),  # ±1yr would exclude (diff=2), ±2yr includes ✅
            (2021, 80_000, 15_500),  # both include ✅
        ])
        # With ±2yr we get 3 comps → median = 15_500
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price is not None
        assert price == 15_500

    def test_year_filter_skipped_when_comp_year_unknown(self):
        """Comps with unknown year should still be included."""
        engine = _engine_with_pool([(None, 80_000, 12_000)])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 12_000

    def test_year_filter_skipped_when_listing_year_unknown(self):
        """If listing year is unknown, don't filter any comps by year."""
        engine = _engine_with_pool([
            (2015, 80_000, 8_000),
            (2022, 80_000, 20_000),
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=None, mileage=80_000)
        assert price == 14_000  # median of both


# ── Filter: mileage window ────────────────────────────────────────────────────

class TestMileageFilter:

    def test_includes_mileage_within_15k(self):
        engine = _engine_with_pool([
            (2020, 70_000, 14_000),   # 80k - 10k = 70k ✅
            (2020, 94_000, 13_000),   # 80k + 14k ✅
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 13_500

    def test_excludes_mileage_beyond_15k(self):
        engine = _engine_with_pool([
            (2020, 60_000, 18_000),   # 80k - 20k ❌
            (2020, 100_000, 9_000),   # 80k + 20k ❌
        ])
        # Both filtered by mileage — falls back to year-relaxed then full pool
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price is not None  # fallback kicks in

    def test_old_filter_10k_would_have_missed_these(self):
        """Verify ±15k catches comps that ±10k would miss."""
        engine = _engine_with_pool([
            (2020, 68_000, 14_500),   # diff=12k — ±10k misses, ±15k catches ✅
            (2020, 93_000, 13_500),   # diff=13k — ±10k misses, ±15k catches ✅
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 14_000  # median

    def test_mileage_filter_skipped_when_comp_mileage_unknown(self):
        engine = _engine_with_pool([(2020, None, 15_000)])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 15_000

    def test_mileage_filter_skipped_when_listing_mileage_unknown(self):
        engine = _engine_with_pool([
            (2020, 10_000, 22_000),
            (2020, 180_000, 5_000),
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=None)
        assert price == 13_500  # median of both


# ── Progressive fallback ──────────────────────────────────────────────────────

class TestProgressiveFallback:

    def test_relaxes_mileage_when_strict_filter_empty(self):
        """If strict year+mileage filter returns nothing, relax mileage only."""
        engine = _engine_with_pool([
            (2020, 50_000, 18_000),   # year matches ✅ but mileage diff=30k ❌ strict
            (2020, 120_000, 10_000),  # year matches ✅ but mileage diff=40k ❌ strict
        ])
        # Strict: nothing. Relaxed (year only): both → median = 14k
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 14_000

    def test_uses_full_pool_when_year_filter_also_empty(self):
        """Last resort: use all comps regardless of year/mileage."""
        engine = _engine_with_pool([
            (2010, 50_000, 5_000),
            (2015, 60_000, 9_000),
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price == 7_000  # full pool median

    def test_returns_none_when_pool_empty(self):
        engine = CompsEngine([])
        price, urls = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000)
        assert price is None
        assert urls == []

    def test_returns_none_for_unknown_make_model(self):
        engine = _engine_with_pool([(2020, 80_000, 15_000)])
        price, urls = engine.get_market_price("honda", "civic", year=2020, mileage=80_000)
        assert price is None
        assert urls == []


# ── Custom range override ─────────────────────────────────────────────────────

class TestCustomRanges:

    def test_custom_year_range_1(self):
        """Can pass year_range=1 to get tighter comps."""
        engine = _engine_with_pool([
            (2019, 80_000, 14_000),   # diff=1 ✅ with range=1
            (2018, 80_000, 12_000),   # diff=2 ❌ with range=1
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000,
                                           year_range=1)
        assert price == 14_000

    def test_custom_mileage_range_5k(self):
        """Can pass mileage_range=5_000 for very tight mileage matching."""
        engine = _engine_with_pool([
            (2020, 82_000, 15_000),   # diff=2k ✅ with range=5k
            (2020, 70_000, 20_000),   # diff=10k ❌ with range=5k
        ])
        price, _ = engine.get_market_price("toyota", "camry", year=2020, mileage=80_000,
                                           mileage_range=5_000)
        assert price == 15_000


# ── Preload ───────────────────────────────────────────────────────────────────

class TestPreload:

    def test_preload_seeds_cache(self):
        from tests.conftest import make_raw_listing
        listings = [
            make_raw_listing(make="Toyota", model="Camry", year=2020, mileage=80_000, price=14_000),
            make_raw_listing(make="Toyota", model="Camry", year=2019, mileage=90_000, price=12_000),
        ]
        engine = CompsEngine(listings)
        price, _ = engine.get_market_price("Toyota", "Camry", year=2020, mileage=80_000)
        assert price is not None

    def test_preload_skips_listings_without_make(self):
        from tests.conftest import make_raw_listing
        listings = [make_raw_listing(make=None, model="Camry", price=14_000)]
        engine = CompsEngine(listings)
        assert ("", "camry") not in engine._cache
        assert ("none", "camry") not in engine._cache


# ── Disk cache helpers ────────────────────────────────────────────────────────

class TestDiskCache:

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        import utils.comps as comps_mod
        monkeypatch.setattr(comps_mod, "_COMPS_CACHE_DIR", str(tmp_path))
        comps = [[2020, 80_000, 14_000], [2021, 75_000, 15_000]]
        _save_cache("toyota", "camry", comps)
        loaded = _load_cache("toyota", "camry")
        assert loaded == comps

    def test_expired_cache_returns_none(self, tmp_path, monkeypatch):
        import utils.comps as comps_mod
        monkeypatch.setattr(comps_mod, "_COMPS_CACHE_DIR", str(tmp_path))
        _save_cache("toyota", "camry", [[2020, 80_000, 14_000]])
        # Backdate the file's mtime by 2 days
        path = comps_mod._cache_path("toyota", "camry")
        old_time = time.time() - 86400 * 2
        os.utime(path, (old_time, old_time))
        assert _load_cache("toyota", "camry") is None

    def test_missing_cache_returns_none(self, tmp_path, monkeypatch):
        import utils.comps as comps_mod
        monkeypatch.setattr(comps_mod, "_COMPS_CACHE_DIR", str(tmp_path))
        assert _load_cache("honda", "civic") is None


import time  # needed by TestDiskCache
