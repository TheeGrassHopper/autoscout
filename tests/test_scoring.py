"""
tests/test_scoring.py — DealScorer (scoring/engine.py) unit tests.

All pure logic — no external calls, no mocks needed.
"""

import pytest
from scoring.engine import DealScorer, ScoredListing, sort_listings
from pricing.kbb import PriceEstimate
from tests.conftest import make_raw_listing, make_scored_listing


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def scorer():
    return DealScorer(config={
        "great_deal_min_score": 75,
        "fair_deal_min_score": 50,
        "min_profit_dollars": 2500,
    })


def _price_est(fmv: int, source="kbb_estimate") -> PriceEstimate:
    return PriceEstimate(
        source=source,
        make="Toyota", model="Tacoma", year=2020, mileage=60000,
        fair_market_value=fmv,
        confidence="low",
    )


# ── Hard gate: salvage title → always poor, score 0 ──────────────────────────

def test_salvage_title_scores_zero(scorer):
    raw = make_raw_listing(title_status="salvage", price=15000)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result.deal_class == "poor"
    assert result.total_score == 0


def test_rebuilt_title_scores_zero(scorer):
    raw = make_raw_listing(title_status="rebuilt", price=20000)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result.deal_class == "poor"
    assert result.total_score == 0


def test_clean_title_is_not_title_gated(scorer):
    raw = make_raw_listing(title_status="clean", price=25000, mileage=50000)
    result = scorer.score(raw, price_estimate=_price_est(36000), carvana_price=40000)
    # A clean title with good margin should not be zero from the title gate
    assert not (result.deal_class == "poor" and result.total_score == 0 and result.profit_estimate > 2500)


# ── Hard gate: below minimum profit floor ────────────────────────────────────

def test_below_profit_floor_is_poor(scorer):
    # Ask $36k, Carvana $38k → profit $2k < $2.5k floor
    raw = make_raw_listing(price=36000)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result.deal_class == "poor"
    assert result.profit_estimate == 2000


def test_zero_profit_scores_zero(scorer):
    raw = make_raw_listing(price=40000)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result.profit_estimate < 0
    assert result.total_score == 0


# ── Deal classification thresholds ───────────────────────────────────────────

def test_great_deal_high_margin(scorer):
    # Ask $25k, Carvana $40k → 37.5% margin → great
    raw = make_raw_listing(price=25000, mileage=50000)
    result = scorer.score(raw, price_estimate=_price_est(38000), carvana_price=40000)
    assert result.deal_class == "great"
    assert result.total_score >= 75


def test_fair_deal_moderate_margin(scorer):
    # Ask $34k, Carvana $38k → 10.5% margin, some demand → fair range
    raw = make_raw_listing(price=34000, mileage=60000)
    result = scorer.score(raw, price_estimate=_price_est(36000), carvana_price=38000)
    assert result.deal_class in ("fair", "great")
    assert result.total_score >= 50


def test_poor_deal_no_margin(scorer):
    # Ask $37k, Carvana $38k → profit $1k < $2.5k floor
    raw = make_raw_listing(price=37000)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result.deal_class == "poor"


# ── Mileage scoring ───────────────────────────────────────────────────────────

def test_low_mileage_gets_higher_score_than_high_mileage(scorer):
    raw_low = make_raw_listing(price=25000, mileage=20000)
    raw_high = make_raw_listing(price=25000, mileage=120000)
    res_low = scorer.score(raw_low, price_estimate=_price_est(38000), carvana_price=40000)
    res_high = scorer.score(raw_high, price_estimate=_price_est(38000), carvana_price=40000)
    assert res_low.mileage_score > res_high.mileage_score


def test_very_high_mileage_scores_low(scorer):
    raw = make_raw_listing(price=25000, mileage=160000)
    result = scorer.score(raw, price_estimate=_price_est(38000), carvana_price=40000)
    assert result.mileage_score <= 10


# ── No pricing data edge cases ────────────────────────────────────────────────

def test_no_price_estimate_no_crash(scorer):
    raw = make_raw_listing(price=30000)
    result = scorer.score(raw, price_estimate=None, carvana_price=None)
    assert result is not None
    # With no pricing data, profit can't be calculated — expect poor or demand-only score
    assert isinstance(result.total_score, int)
    assert 0 <= result.total_score <= 100


def test_no_asking_price_no_crash(scorer):
    raw = make_raw_listing(price=None)
    result = scorer.score(raw, price_estimate=_price_est(35000), carvana_price=38000)
    assert result is not None


# ── Blended market value calculation ─────────────────────────────────────────

def test_blended_value_uses_all_sources(scorer):
    raw = make_raw_listing(price=30000, mileage=60000)
    result = scorer.score(
        raw,
        price_estimate=_price_est(34000),
        carvana_price=38000,
        carmax_price=36000,
    )
    assert result.blended_market_value is not None
    # Should be between KBB and Carvana values
    assert 34000 <= result.blended_market_value <= 38000


def test_blended_value_carvana_only(scorer):
    raw = make_raw_listing(price=30000, mileage=60000)
    result = scorer.score(raw, price_estimate=None, carvana_price=38000)
    assert result.blended_market_value == 38000


# ── Profit estimate ───────────────────────────────────────────────────────────

def test_profit_estimate_uses_carvana_as_resale(scorer):
    raw = make_raw_listing(price=30000, mileage=60000)
    result = scorer.score(raw, price_estimate=_price_est(36000), carvana_price=40000)
    assert result.profit_estimate == 10000
    assert abs(result.profit_margin_pct - 0.25) < 0.01


# ── sort_listings ─────────────────────────────────────────────────────────────

def test_sort_listings_great_before_fair_before_poor():
    great = make_scored_listing(deal_class="great", profit_estimate=8000, total_score=85)
    fair  = make_scored_listing(deal_class="fair",  profit_estimate=4000, total_score=62, listing_id="t2")
    poor  = make_scored_listing(deal_class="poor",  profit_estimate=0,    total_score=10, listing_id="t3")

    sorted_list = sort_listings([poor, great, fair])
    assert sorted_list[0].deal_class == "great"
    assert sorted_list[1].deal_class == "fair"
    assert sorted_list[2].deal_class == "poor"


def test_sort_within_class_by_profit_desc():
    a = make_scored_listing(deal_class="great", profit_estimate=10000, total_score=90)
    b = make_scored_listing(deal_class="great", profit_estimate=5000,  total_score=80, listing_id="t2")
    sorted_list = sort_listings([b, a])
    assert sorted_list[0].profit_estimate == 10000


# ── Score is always in 0-100 range ───────────────────────────────────────────

@pytest.mark.parametrize("price,carvana", [
    (1000, 40000),   # insanely cheap — great deal
    (45000, 40000),  # overpriced — negative profit
    (30000, 30000),  # break-even — below profit floor
    (0, 40000),      # free car (0 price handled gracefully)
])
def test_score_always_0_to_100(scorer, price, carvana):
    raw = make_raw_listing(price=price if price else None, mileage=60000)
    result = scorer.score(raw, price_estimate=_price_est(36000), carvana_price=carvana)
    assert 0 <= result.total_score <= 100


# ── ScoredListing properties ─────────────────────────────────────────────────

def test_is_great_deal_property():
    sl = make_scored_listing(deal_class="great")
    assert sl.is_great_deal is True
    assert sl.is_fair_deal is False


def test_is_fair_deal_property():
    sl = make_scored_listing(deal_class="fair")
    assert sl.is_fair_deal is True
    assert sl.is_great_deal is False


def test_is_poor_deal_properties():
    sl = make_scored_listing(deal_class="poor")
    assert sl.is_great_deal is False
    assert sl.is_fair_deal is False
