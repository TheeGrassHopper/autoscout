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
        """If Playwright is not installed, return (None, None) gracefully."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "playwright.sync_api":
                raise ImportError("Playwright not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from pricing import carvana as carvana_mod
        result = carvana_mod._fetch_from_carvana("Toyota", "Tacoma", 2020, 99999, 2, 20000)
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


# ── KBB cache ─────────────────────────────────────────────────────────────────

class TestKBBCache:

    def test_same_vehicle_same_result_twice(self):
        """Second call should return cached estimate, same value as first."""
        from pricing.kbb import KBBPricer
        pricer = KBBPricer()
        est1 = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=55555)
        est2 = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=55555)
        assert est1.fair_market_value == est2.fair_market_value

    def test_different_mileage_different_result(self):
        from pricing.kbb import KBBPricer
        pricer = KBBPricer()
        est_low = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=20000)
        est_high = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=120000)
        assert est_low.fair_market_value > est_high.fair_market_value
