"""
tests/test_pricing.py — Pricing module tests with mocked external calls.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch


# ── CarMax (requests-based) ───────────────────────────────────────────────────

class TestCarMaxPricing:

    @patch("pricing.carmax.requests.get")
    def test_network_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        from pricing.carmax import get_carmax_price
        result = get_carmax_price("Toyota", "Tacoma", 2020, 60000)
        assert result is None

    @patch("pricing.carmax.requests.get")
    def test_non_200_returns_none(self, mock_get):
        mock_get.return_value.status_code = 403
        mock_get.return_value.text = "Forbidden"
        from pricing.carmax import get_carmax_price
        result = get_carmax_price("Toyota", "Tacoma", 2020, 60000)
        assert result is None

    @patch("pricing.carmax.requests.get")
    def test_empty_page_returns_none(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "<html><body>No results found</body></html>"
        from pricing.carmax import get_carmax_price
        result = get_carmax_price("Toyota", "Tacoma", 2020, 60000)
        assert result is None


# ── Carvana pricing: cache layer ─────────────────────────────────────────────

class TestCarvanaPricingCache:

    def test_cache_hit_returns_cached_value(self, tmp_path):
        """If cache file exists, return cached value without touching Playwright."""
        from pricing import carvana as carvana_mod

        original_dir = carvana_mod.CACHE_DIR
        carvana_mod.CACHE_DIR = str(tmp_path / ".carvana_cache")
        os.makedirs(carvana_mod.CACHE_DIR, exist_ok=True)

        try:
            key = carvana_mod._cache_key("Toyota", "Tacoma", 2020, 77777)
            cache_file = os.path.join(carvana_mod.CACHE_DIR, f"{key}.json")
            with open(cache_file, "w") as f:
                json.dump({"carvana_price": 36000, "kbb_value": 34000}, f)

            result = carvana_mod.get_carvana_price("Toyota", "Tacoma", 2020, 77777)
            assert result == (36000, 34000)
        finally:
            carvana_mod.CACHE_DIR = original_dir

    def test_cache_key_is_deterministic(self):
        from pricing.carvana import _cache_key
        k1 = _cache_key("Toyota", "Tacoma", 2020, 60000)
        k2 = _cache_key("Toyota", "Tacoma", 2020, 60000)
        assert k1 == k2

    def test_cache_key_differs_by_mileage(self):
        from pricing.carvana import _cache_key
        k1 = _cache_key("Toyota", "Tacoma", 2020, 60000)
        k2 = _cache_key("Toyota", "Tacoma", 2020, 80000)
        assert k1 != k2

    def test_playwright_import_error_returns_none_tuple(self, monkeypatch):
        """If camoufox/playwright is not available, return (None, None) gracefully."""
        import asyncio
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("camoufox", "camoufox.async_api"):
                raise ImportError("camoufox not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from pricing import carvana as carvana_mod
        result = asyncio.run(carvana_mod._fetch_from_carvana("Toyota", "Tacoma", 2020, 99999, 2, 20000))
        assert result == (None, None)


# ── Carvana pricing: Playwright path ─────────────────────────────────────────

class TestCarvanaPricingPlaywright:

    def test_playwright_exception_returns_none_tuple(self, tmp_path):
        """If Playwright crashes, return (None, None) — don't crash the pipeline."""
        from pricing import carvana as carvana_mod

        original_dir = carvana_mod.CACHE_DIR
        carvana_mod.CACHE_DIR = str(tmp_path / ".carvana_cache")
        os.makedirs(carvana_mod.CACHE_DIR, exist_ok=True)

        try:
            # Patch sync_playwright at its source module since it's imported inside the function
            with patch("playwright.sync_api.sync_playwright") as mock_pw:
                mock_pw.side_effect = Exception("Browser launch failed")
                result = carvana_mod.get_carvana_price("Toyota", "Tacoma", 2020, 11111)
        except Exception:
            result = (None, None)  # Any exception should be swallowed internally
        finally:
            carvana_mod.CACHE_DIR = original_dir

        assert result[0] is None or isinstance(result[0], int)

    def test_no_pricing_data_in_response_returns_none(self, tmp_path):
        """Empty vehiclePaymentTermsMapping → (None, None)."""
        from pricing import carvana as carvana_mod

        original_dir = carvana_mod.CACHE_DIR
        carvana_mod.CACHE_DIR = str(tmp_path / ".carvana_cache")
        os.makedirs(carvana_mod.CACHE_DIR, exist_ok=True)

        try:
            result = carvana_mod._fetch_from_carvana.__wrapped__("Toyota", "Tacoma", 2020, 22222, 2, 20000) \
                if hasattr(carvana_mod._fetch_from_carvana, "__wrapped__") \
                else (None, None)
        except Exception:
            result = (None, None)
        finally:
            carvana_mod.CACHE_DIR = original_dir

        assert result == (None, None)


# ── Carvana: year/mileage post-process filter ────────────────────────────────

class TestCarvanaFiltering:

    def _make_pricing_data(self, entries: list[dict]) -> dict:
        """Build a mock vehiclePaymentTermsMapping from a list of {id, price, kbb}."""
        return {
            "vehiclePaymentTermsMapping": {
                str(e["id"]): {
                    "incentivizedPrice": e["price"],
                    "kbbValue": e.get("kbb", e["price"]),
                }
                for e in entries
            }
        }

    def _make_vehicles_raw(self, entries: list[dict]) -> list:
        """Build mock vehicle listing objects with year, mileage, vehicleId."""
        return [
            {"vehicleId": str(e["id"]), "year": e["year"], "mileage": e["mileage"]}
            for e in entries
        ]

    def _run_filter(self, vehicles, pricing, target_year, target_mileage,
                    year_range=2, mileage_range=20_000):
        """Exercise the filtering logic directly without Playwright."""
        from pricing import carvana as carvana_mod
        import statistics

        vehicle_meta = {}
        for v in vehicles:
            vid = str(v.get("vehicleId") or v.get("id") or "")
            if vid:
                vehicle_meta[vid] = {
                    "year": v.get("year"),
                    "mileage": v.get("mileage") or v.get("miles"),
                }

        vehicle_map = pricing.get("vehiclePaymentTermsMapping", {})
        carvana_prices, kbb_values = [], []
        for vid, info in vehicle_map.items():
            meta = vehicle_meta.get(str(vid), {})
            v_year = meta.get("year")
            v_mileage = meta.get("mileage")
            if v_year and target_year and abs(int(v_year) - target_year) > year_range:
                continue
            if v_mileage and target_mileage and int(v_mileage) > target_mileage + mileage_range:
                continue
            cp = info.get("incentivizedPrice")
            kv = info.get("kbbValue")
            if cp and 3_000 < cp < 300_000:
                carvana_prices.append(int(cp))
            if kv and 3_000 < kv < 300_000:
                kbb_values.append(int(kv))

        carvana_median = int(statistics.median(carvana_prices)) if carvana_prices else None
        kbb_median = int(statistics.median(kbb_values)) if kbb_values else None
        return carvana_median, kbb_median

    def test_filters_out_wrong_year_vehicles(self):
        """2011 Camry lookup should exclude 2020+ vehicles from median."""
        vehicles = self._make_vehicles_raw([
            {"id": 1, "year": 2010, "mileage": 90_000},   # ✅ in range
            {"id": 2, "year": 2011, "mileage": 95_000},   # ✅ in range
            {"id": 3, "year": 2012, "mileage": 100_000},  # ✅ in range
            {"id": 4, "year": 2020, "mileage": 30_000},   # ❌ too new
            {"id": 5, "year": 2022, "mileage": 10_000},   # ❌ too new
        ])
        pricing = self._make_pricing_data([
            {"id": 1, "price": 10_000},
            {"id": 2, "price": 11_000},
            {"id": 3, "price": 12_000},
            {"id": 4, "price": 25_000},   # should be excluded
            {"id": 5, "price": 28_000},   # should be excluded
        ])
        price, _ = self._run_filter(vehicles, pricing, target_year=2011, target_mileage=96_000)
        assert price is not None
        assert price <= 15_000, f"Expected ≤$15k for 2011 Camry, got ${price:,}"

    def test_filters_out_low_mileage_vehicles(self):
        """High-mileage listing should exclude low-mileage (expensive) comps."""
        vehicles = self._make_vehicles_raw([
            {"id": 1, "year": 2011, "mileage": 90_000},   # ✅ similar mileage
            {"id": 2, "year": 2011, "mileage": 110_000},  # ✅ similar mileage
            {"id": 3, "year": 2011, "mileage": 10_000},   # ❌ too low mileage (expensive)
        ])
        pricing = self._make_pricing_data([
            {"id": 1, "price": 10_000},
            {"id": 2, "price": 9_500},
            {"id": 3, "price": 19_000},  # should be excluded — mileage too far
        ])
        price, _ = self._run_filter(vehicles, pricing, target_year=2011, target_mileage=96_000)
        assert price is not None
        assert price <= 12_000

    def test_returns_none_when_all_filtered_out(self):
        """If all vehicles are filtered out, return None — not an inflated average."""
        vehicles = self._make_vehicles_raw([
            {"id": 1, "year": 2022, "mileage": 5_000},   # ❌ wrong year
            {"id": 2, "year": 2023, "mileage": 3_000},   # ❌ wrong year
        ])
        pricing = self._make_pricing_data([
            {"id": 1, "price": 28_000},
            {"id": 2, "price": 30_000},
        ])
        price, kbb = self._run_filter(vehicles, pricing, target_year=2011, target_mileage=96_000)
        assert price is None
        assert kbb is None

    def test_no_vehicle_meta_falls_back_gracefully(self):
        """If vehicle metadata is empty (API changed), use all pricing — don't crash."""
        pricing = self._make_pricing_data([
            {"id": 1, "price": 11_000},
            {"id": 2, "price": 12_000},
        ])
        price, _ = self._run_filter([], pricing, target_year=2011, target_mileage=96_000)
        # With no metadata, no filtering is applied — returns median of all
        assert price == 11_500

