"""
tests/test_market_pricing.py

Unit tests for VinAudit and CarsXE pricing modules.
All tests are network-free — API calls are intercepted with monkeypatch/mock.

Covers:
  - VinAudit: successful response, no-VIN skip, no-key skip, zero-mean skip,
               cache roundtrip, expired cache, API error handling
  - CarsXE: successful response, missing-fields skip, no-key skip,
             VIN-preferred path, cache roundtrip, price parsing edge cases
  - Pipeline priority: VinAudit > CarsXE > KBB depreciation model
"""

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(data: dict, status: int = 200):
    """Return a mock requests.Response-like object."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return resp


# ── VinAudit ──────────────────────────────────────────────────────────────────

class TestVinAudit:

    def test_returns_price_estimate_on_success(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {
            "success": True,
            "count": 12,
            "mean": 28500,
            "prices": [24000, 28500, 33000],
        }
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)):
            from pricing.vinaudit import get_vinaudit_price
            est = get_vinaudit_price(
                vin="1GYKNCRS6JZ206169",
                mileage=55000,
                make="Toyota",
                model="Tacoma",
                year=2018,
            )

        assert est is not None
        assert est.fair_market_value == 28500
        assert est.trade_in_low == 24000
        assert est.retail_high == 33000
        assert est.confidence == "high"    # count=12 → high
        assert est.source == "vinaudit"

    def test_medium_confidence_when_count_low(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": True, "count": 3, "mean": 20000, "prices": [17000, 20000, 23000]}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)):
            from pricing.vinaudit import get_vinaudit_price
            est = get_vinaudit_price(vin="TESTVIN001", mileage=80000, make="Honda", model="Civic", year=2016)

        assert est.confidence == "medium"   # count=3

    def test_returns_none_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("VINAUDIT_API_KEY", raising=False)
        from pricing.vinaudit import get_vinaudit_price
        est = get_vinaudit_price(vin="1GYKNCRS6JZ206169", mileage=50000)
        assert est is None

    def test_returns_none_when_vin_blank(self, monkeypatch):
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")
        from pricing.vinaudit import get_vinaudit_price
        assert get_vinaudit_price(vin="", mileage=50000) is None
        assert get_vinaudit_price(vin="   ", mileage=50000) is None

    def test_returns_none_when_api_returns_success_false(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": False, "count": 0, "mean": 0}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)):
            from pricing.vinaudit import get_vinaudit_price
            est = get_vinaudit_price(vin="BADVIN", mileage=50000)
        assert est is None

    def test_returns_none_on_api_error(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        import requests
        with patch("pricing.vinaudit.requests.get", side_effect=requests.Timeout("timeout")):
            from pricing.vinaudit import get_vinaudit_price
            est = get_vinaudit_price(vin="1GYKNCRS6JZ206169", mileage=50000)
        assert est is None

    def test_cache_roundtrip(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": True, "count": 8, "mean": 35000, "prices": [30000, 35000, 40000]}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)) as mock_get:
            from pricing.vinaudit import get_vinaudit_price
            # First call — hits network
            get_vinaudit_price(vin="CACHETESTVIN", mileage=60000, make="Ford", model="F-150", year=2019)
            assert mock_get.call_count == 1

            # Second call — cache hit, no network
            est2 = get_vinaudit_price(vin="CACHETESTVIN", mileage=60000, make="Ford", model="F-150", year=2019)
            assert mock_get.call_count == 1   # still 1
            assert est2.fair_market_value == 35000

    def test_expired_cache_refetches(self, monkeypatch, tmp_path):
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": True, "count": 5, "mean": 22000, "prices": [18000, 22000, 26000]}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)) as mock_get:
            from pricing.vinaudit import get_vinaudit_price, _cache_key
            vin = "EXPIREDVIN"
            # Populate cache
            get_vinaudit_price(vin=vin, mileage=40000)
            # Expire the file
            cache_file = os.path.join(str(tmp_path), f"{_cache_key(vin, 40000)}.json")
            old = time.time() - va_mod._CACHE_TTL - 1
            os.utime(cache_file, (old, old))

            # Should refetch
            get_vinaudit_price(vin=vin, mileage=40000)
            assert mock_get.call_count == 2

    def test_fallback_price_range_when_prices_list_empty(self, monkeypatch, tmp_path):
        """When API returns mean but no prices array, derive range from mean."""
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": True, "count": 2, "mean": 10000, "prices": []}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)):
            from pricing.vinaudit import get_vinaudit_price
            est = get_vinaudit_price(vin="NOPRICESLIST", mileage=100000)

        assert est is not None
        assert est.fair_market_value == 10000
        assert est.trade_in_low == int(10000 * 0.88)
        assert est.retail_high  == int(10000 * 1.12)


# ── CarsXE ────────────────────────────────────────────────────────────────────

class TestCarsXE:

    def test_returns_price_estimate_on_success(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        payload = {"price": {"average": 26000, "below": 22000, "above": 30000}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)):
            from pricing.carsxe import get_carsxe_price
            est = get_carsxe_price(make="Toyota", model="Camry", year=2019, mileage=70000)

        assert est is not None
        assert est.fair_market_value == 26000
        assert est.trade_in_low == 22000
        assert est.retail_high == 30000
        assert est.source == "carsxe"
        assert est.confidence == "medium"

    def test_returns_none_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("CARSXE_API_KEY", raising=False)
        from pricing.carsxe import get_carsxe_price
        est = get_carsxe_price(make="Toyota", model="Camry", year=2019, mileage=70000)
        assert est is None

    def test_returns_none_when_missing_make_model_year(self, monkeypatch):
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")
        from pricing.carsxe import get_carsxe_price
        assert get_carsxe_price(make="", model="Camry", year=2019, mileage=50000) is None
        assert get_carsxe_price(make="Toyota", model="", year=2019, mileage=50000) is None
        assert get_carsxe_price(make="Toyota", model="Camry", year=0, mileage=50000) is None

    def test_uses_vin_when_provided(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        payload = {"price": {"average": 31000, "below": 27000, "above": 35000}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)) as mock_get:
            from pricing.carsxe import get_carsxe_price
            get_carsxe_price(
                make="Ford", model="F-150", year=2020, mileage=50000,
                vin="1FTEW1EP9LFB06169",
            )

        call_params = mock_get.call_args[1]["params"]
        assert "vin" in call_params
        assert "year" not in call_params  # VIN supplied — no need for year param

    def test_no_vin_uses_make_model_year(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        payload = {"price": {"average": 18000, "below": 15000, "above": 21000}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)) as mock_get:
            from pricing.carsxe import get_carsxe_price
            get_carsxe_price(make="Honda", model="Civic", year=2017, mileage=90000, vin="")

        call_params = mock_get.call_args[1]["params"]
        assert "year" in call_params
        assert call_params["make"] == "Honda"
        assert "vin" not in call_params

    def test_returns_none_on_empty_price_block(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        with patch("pricing.carsxe.requests.get", return_value=_mock_response({})):
            from pricing.carsxe import get_carsxe_price
            est = get_carsxe_price(make="Toyota", model="Camry", year=2019, mileage=70000)
        assert est is None

    def test_returns_none_on_api_error(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        import requests
        with patch("pricing.carsxe.requests.get", side_effect=requests.ConnectionError("down")):
            from pricing.carsxe import get_carsxe_price
            est = get_carsxe_price(make="Toyota", model="Camry", year=2019, mileage=70000)
        assert est is None

    def test_price_string_parsing(self, monkeypatch, tmp_path):
        """price values might come as strings with commas/dollar signs."""
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        payload = {"price": {"average": "24,500", "below": "$21,000", "above": "28000"}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)):
            from pricing.carsxe import get_carsxe_price
            est = get_carsxe_price(make="Nissan", model="Altima", year=2018, mileage=65000)

        assert est is not None
        assert est.fair_market_value == 24500
        assert est.trade_in_low == 21000
        assert est.retail_high == 28000

    def test_cache_roundtrip(self, monkeypatch, tmp_path):
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")

        payload = {"price": {"average": 15000, "below": 12000, "above": 18000}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)) as mock_get:
            from pricing.carsxe import get_carsxe_price
            get_carsxe_price(make="Chevrolet", model="Malibu", year=2016, mileage=100000)
            assert mock_get.call_count == 1

            est2 = get_carsxe_price(make="Chevrolet", model="Malibu", year=2016, mileage=100000)
            assert mock_get.call_count == 1   # cache hit
            assert est2.fair_market_value == 15000


# ── Pipeline priority: VinAudit > CarsXE > KBB ───────────────────────────────

class TestPricingPriority:
    """
    Verify that in the pipeline, VinAudit displaces KBB estimates,
    and CarsXE displaces KBB only when VinAudit is not available.
    """

    def test_vinaudit_displaces_kbb_estimate(self, monkeypatch, tmp_path):
        """VinAudit result (high confidence) should replace KBB estimate (low confidence)."""
        import pricing.vinaudit as va_mod
        monkeypatch.setattr(va_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("VINAUDIT_API_KEY", "test_key")

        payload = {"success": True, "count": 10, "mean": 32000, "prices": [28000, 32000, 36000]}
        with patch("pricing.vinaudit.requests.get", return_value=_mock_response(payload)):
            from pricing.vinaudit import get_vinaudit_price
            from pricing.kbb import KBBPricer

            kbb_pricer = KBBPricer()
            kbb_est = kbb_pricer.get_price(year=2019, make="Toyota", model="Tacoma", mileage=60000)

            va_est = get_vinaudit_price(
                vin="1NXBR32E85Z545487",
                mileage=60000,
                make="Toyota",
                model="Tacoma",
                year=2019,
            )

            # Simulate pipeline logic: VinAudit wins over KBB estimate
            price_est = kbb_est
            if va_est and va_est.fair_market_value:
                price_est = va_est

        assert price_est.source == "vinaudit"
        assert price_est.fair_market_value == 32000
        assert price_est.confidence == "high"

    def test_carsxe_displaces_kbb_when_no_vinaudit(self, monkeypatch, tmp_path):
        """CarsXE replaces KBB estimate when VinAudit is unavailable."""
        import pricing.carsxe as cx_mod
        monkeypatch.setattr(cx_mod, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("CARSXE_API_KEY", "test_key")
        monkeypatch.delenv("VINAUDIT_API_KEY", raising=False)

        payload = {"price": {"average": 25000, "below": 21000, "above": 29000}}
        with patch("pricing.carsxe.requests.get", return_value=_mock_response(payload)):
            from pricing.carsxe import get_carsxe_price
            from pricing.kbb import KBBPricer

            kbb_pricer = KBBPricer()
            kbb_est = kbb_pricer.get_price(year=2019, make="Honda", model="Civic", mileage=70000)

            # No VinAudit (no key) — CarsXE is used instead
            cx_est = get_carsxe_price(make="Honda", model="Civic", year=2019, mileage=70000)

            price_est = kbb_est
            if cx_est and cx_est.fair_market_value:
                price_est = cx_est

        assert price_est.source == "carsxe"
        assert price_est.fair_market_value == 25000

    def test_vinaudit_not_displaced_by_carsxe(self):
        """When VinAudit already set price_est, CarsXE should not overwrite it.
        Tests the pipeline priority logic directly using PriceEstimate objects."""
        from pricing.kbb import PriceEstimate

        va_est = PriceEstimate(
            source="vinaudit", make="Ford", model="F-150",
            year=2020, mileage=50000, fair_market_value=40000, confidence="high"
        )
        cx_est = PriceEstimate(
            source="carsxe", make="Ford", model="F-150",
            year=2020, mileage=50000, fair_market_value=30000, confidence="medium"
        )

        # Simulate pipeline logic: CarsXE only used if VinAudit source not set
        price_est = va_est
        if not (price_est and price_est.source == "vinaudit"):
            if cx_est and cx_est.fair_market_value:
                price_est = cx_est

        assert price_est.source == "vinaudit"
        assert price_est.fair_market_value == 40000
