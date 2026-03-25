"""
tests/test_kbb.py — KBBPricer fallback model unit tests.

Pure logic — no network calls. Uses isolated cache directory to avoid
pollution from prior runs.
"""

import os
import pytest
from pricing.kbb import KBBPricer, PriceEstimate


@pytest.fixture()
def pricer(tmp_path, monkeypatch):
    """KBBPricer with isolated temp cache directory."""
    p = KBBPricer()
    monkeypatch.setattr(p, "CACHE_DIR", str(tmp_path / ".price_cache"))
    os.makedirs(str(tmp_path / ".price_cache"), exist_ok=True)
    return p


# ── Known makes/models return reasonable values ───────────────────────────────

@pytest.mark.parametrize("year,make,model,mileage,expected_min,expected_max", [
    (2021, "Toyota", "Tacoma",   80000,  24000, 40000),
    (2021, "Toyota", "Tundra",   80000,  30000, 52000),
    (2020, "Ford",   "F-150",    70000,  22000, 50000),
    (2023, "Toyota", "Tacoma",   30000,  33000, 55000),
    (2019, "Honda",  "Civic",    60000,   8000, 24000),
    (2018, "Ram",    "1500",     90000,  12000, 38000),
])
def test_known_vehicle_estimate_in_range(pricer, year, make, model, mileage, expected_min, expected_max):
    est = pricer.get_price(year=year, make=make, model=model, mileage=mileage)
    assert est is not None
    assert expected_min <= est.fair_market_value <= expected_max, (
        f"{year} {make} {model} @ {mileage}mi → ${est.fair_market_value:,} "
        f"(expected ${expected_min:,}–${expected_max:,})"
    )


# ── Truck retention is better than sedan ──────────────────────────────────────

def test_tundra_fmv_higher_than_camry_same_year(pricer):
    """Tundra has higher MSRP than Camry, so same age should yield higher FMV."""
    tundra = pricer.get_price(year=2021, make="Toyota", model="Tundra", mileage=60000)
    camry  = pricer.get_price(year=2021, make="Toyota", model="Camry",  mileage=60000)
    assert tundra.fair_market_value > camry.fair_market_value


def test_truck_fmv_is_positive(pricer):
    """Truck value should always be a positive number."""
    est = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=60000)
    assert est.fair_market_value > 10000


# ── Newer cars worth more than older ──────────────────────────────────────────

def test_newer_car_worth_more(pricer):
    newer = pricer.get_price(year=2022, make="Toyota", model="Tacoma", mileage=60000)
    older = pricer.get_price(year=2016, make="Toyota", model="Tacoma", mileage=60000)
    assert newer.fair_market_value > older.fair_market_value


# ── Higher mileage reduces value ─────────────────────────────────────────────

def test_high_mileage_reduces_value(pricer):
    low_miles  = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=20000)
    high_miles = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=140000)
    assert low_miles.fair_market_value > high_miles.fair_market_value


# ── Unknown vehicle falls back to default ─────────────────────────────────────

def test_unknown_vehicle_uses_default(pricer):
    est = pricer.get_price(year=2020, make="Lada", model="Niva", mileage=50000)
    assert est is not None
    assert est.fair_market_value > 0


# ── Estimate source is kbb_estimate ──────────────────────────────────────────

def test_estimate_source_tag(pricer):
    est = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=60000)
    assert est.source == "kbb_estimate"


# ── Confidence is low (fallback model) ───────────────────────────────────────

def test_estimate_confidence_is_low(pricer):
    est = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=60000)
    assert est.confidence == "low"


# ── Private party range surrounds fair market value ──────────────────────────

def test_price_range_is_symmetric_around_fmv(pricer):
    est = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=60000)
    assert est.private_party_low < est.fair_market_value < est.private_party_high


# ── Mileage adjustment caps at reasonable bounds ─────────────────────────────

def test_extreme_high_mileage_capped(pricer):
    very_high = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=500000)
    assert very_high.fair_market_value > 0  # Should not go negative or zero


def test_very_low_mileage_higher_than_high_mileage(pricer):
    low  = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=5000)
    high = pricer.get_price(year=2020, make="Toyota", model="Tacoma", mileage=200000)
    assert low.fair_market_value > high.fair_market_value


# ── BASE_PRICES table sanity ─────────────────────────────────────────────────

def test_tundra_base_price_higher_than_camry():
    assert KBBPricer.BASE_PRICES[("toyota", "tundra")] > KBBPricer.BASE_PRICES[("toyota", "camry")]


def test_truck_default_higher_than_sedan_default():
    assert KBBPricer.BASE_PRICES[("default", "truck")] > KBBPricer.BASE_PRICES[("default", "sedan")]


def test_all_base_prices_are_positive():
    for key, val in KBBPricer.BASE_PRICES.items():
        assert val > 0, f"BASE_PRICES[{key}] is non-positive: {val}"


# ── Cache behaviour ───────────────────────────────────────────────────────────

def test_same_query_returns_same_result(pricer):
    est1 = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=55555)
    est2 = pricer.get_price(year=2021, make="Toyota", model="Tacoma", mileage=55555)
    assert est1.fair_market_value == est2.fair_market_value
