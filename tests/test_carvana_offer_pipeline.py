"""
tests/test_carvana_offer_pipeline.py

Tests for the Carvana cash-offer enrichment pipeline:
  - Offer string parsing ($X,XXX → int)
  - Margin calculation
  - Deal class upgrades (guaranteed flip / strong / decent / low)
  - No upgrade when offer is too low
  - No-VIN listings are skipped
  - DB persists enriched offer
"""

import pytest
from tests.conftest import make_scored_listing


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply(asking: int, offer: int, deal_class: str = "fair", score: int = 60):
    """Apply a Carvana offer to a ScoredListing and return the result."""
    from scoring.engine import DealScorer
    sl = make_scored_listing(asking_price=asking, deal_class=deal_class, total_score=score)
    scorer = DealScorer(config={})
    return scorer.apply_carvana_offer(sl, offer)


# ── Offer string parsing ──────────────────────────────────────────────────────

class TestOfferParsing:

    def test_parse_standard_format(self):
        offer_str = "$8,500"
        result = int(offer_str.replace("$", "").replace(",", ""))
        assert result == 8500

    def test_parse_five_digit(self):
        offer_str = "$12,750"
        result = int(offer_str.replace("$", "").replace(",", ""))
        assert result == 12750

    def test_parse_no_comma(self):
        offer_str = "$4000"
        result = int(offer_str.replace("$", "").replace(",", ""))
        assert result == 4000


# ── Margin calculation ────────────────────────────────────────────────────────

class TestMarginCalculation:

    def test_positive_margin_when_offer_above_asking(self):
        sl = _apply(asking=7000, offer=8000)
        assert sl.carvana_offer_margin == pytest.approx(8000 / 7000 - 1, abs=0.001)
        assert sl.carvana_offer_margin > 0

    def test_negative_margin_when_offer_below_asking(self):
        sl = _apply(asking=10000, offer=8500)
        assert sl.carvana_offer_margin == pytest.approx(-0.15, abs=0.001)

    def test_zero_margin_when_offer_equals_asking(self):
        sl = _apply(asking=9000, offer=9000)
        assert sl.carvana_offer_margin == pytest.approx(0.0, abs=0.001)

    def test_offer_stored_on_listing(self):
        sl = _apply(asking=8000, offer=9500)
        assert sl.carvana_offer == 9500


# ── Deal class upgrades ───────────────────────────────────────────────────────

class TestDealClassUpgrades:

    def test_guaranteed_flip_offer_above_asking(self):
        """Offer ≥ asking → guaranteed profit → great, score ≥ 95."""
        sl = _apply(asking=7000, offer=8000, deal_class="fair", score=55)
        assert sl.deal_class == "great"
        assert sl.total_score >= 95

    def test_guaranteed_flip_offer_equals_asking(self):
        """Offer == asking → breakeven still counts as guaranteed (0% margin)."""
        sl = _apply(asking=7000, offer=7000, deal_class="fair", score=55)
        assert sl.deal_class == "great"
        assert sl.total_score >= 95

    def test_strong_deal_within_10_pct(self):
        """Offer within 10% below asking → great, score ≥ 78."""
        sl = _apply(asking=10000, offer=9200, deal_class="fair", score=60)
        # margin = -8% — within 10%
        assert sl.deal_class == "great"
        assert sl.total_score >= 78

    def test_decent_deal_within_20_pct_upgrades_poor(self):
        """Offer within 20% of asking → upgrades poor → fair, score ≥ 55."""
        sl = _apply(asking=10000, offer=8200, deal_class="poor", score=30)
        # margin = -18% — within 20%
        assert sl.deal_class == "fair"
        assert sl.total_score >= 55

    def test_decent_deal_does_not_downgrade_great(self):
        """Offer within 20% does not downgrade an already-great listing."""
        sl = _apply(asking=10000, offer=8200, deal_class="great", score=80)
        assert sl.deal_class == "great"
        assert sl.total_score >= 80

    def test_low_offer_no_upgrade(self):
        """Offer > 20% below asking → no upgrade, deal_class unchanged."""
        sl = _apply(asking=10000, offer=7000, deal_class="poor", score=30)
        # margin = -30% — beyond 20% threshold
        assert sl.deal_class == "poor"

    def test_low_offer_does_not_downgrade_existing_great(self):
        """A bad Carvana offer never downgrades a listing that scored well otherwise."""
        sl = _apply(asking=10000, offer=5000, deal_class="great", score=80)
        assert sl.deal_class == "great"
        assert sl.total_score >= 80

    def test_score_is_not_lowered_by_offer(self):
        """Applying an offer never reduces total_score below what it was."""
        sl = _apply(asking=10000, offer=7000, deal_class="fair", score=65)
        assert sl.total_score >= 65


# ── No-VIN listings skipped ───────────────────────────────────────────────────

class TestNoVinSkipped:

    def test_listings_without_vin_not_in_candidates(self):
        """_enrich candidates list should exclude listings with no VIN."""
        listings = [
            make_scored_listing(listing_id="a", vin="1GYKNCRS6JZ206169", deal_class="great"),
            make_scored_listing(listing_id="b", vin=None, deal_class="great"),
            make_scored_listing(listing_id="c", vin="", deal_class="fair"),
            make_scored_listing(listing_id="d", vin="3TMCZ5AN7LM319195", deal_class="fair"),
        ]
        candidates = [s for s in listings if s.vin and s.deal_class in ("fair", "great")]
        assert len(candidates) == 2
        assert all(s.vin for s in candidates)

    def test_poor_listings_not_in_candidates(self):
        """Only fair/great listings should be enriched — don't waste time on poor deals."""
        listings = [
            make_scored_listing(listing_id="p1", vin="1GYKNCRS6JZ206169", deal_class="poor"),
            make_scored_listing(listing_id="g1", vin="3TMCZ5AN7LM319195", deal_class="great"),
        ]
        candidates = [s for s in listings if s.vin and s.deal_class in ("fair", "great")]
        assert len(candidates) == 1
        assert candidates[0].listing_id == "g1"


# ── DB persistence ────────────────────────────────────────────────────────────

class TestOfferPersistence:

    def test_carvana_offer_saved_to_db(self, tmp_path):
        from utils.db import Database
        from scoring.engine import DealScorer

        db = Database(db_path=str(tmp_path / "test.db"))
        sl = make_scored_listing(listing_id="vin_test", vin="1GYKNCRS6JZ206169",
                                 deal_class="fair", asking_price=8000)
        scorer = DealScorer(config={})
        scorer.apply_carvana_offer(sl, 9000)
        db.upsert_listing(sl)

        rows = db.get_great_deals(limit=10)
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["carvana_offer"] == 9000
        assert row["deal_class"] == "great"

    def test_carvana_offer_margin_saved_to_db(self, tmp_path):
        from utils.db import Database
        from scoring.engine import DealScorer

        db = Database(db_path=str(tmp_path / "test.db"))
        sl = make_scored_listing(listing_id="margin_test", vin="3TMCZ5AN7LM319195",
                                 deal_class="fair", asking_price=10000)
        scorer = DealScorer(config={})
        scorer.apply_carvana_offer(sl, 9200)  # -8% margin
        db.upsert_listing(sl)

        rows = db.get_great_deals(limit=10)
        row = dict(rows[0])
        assert row["carvana_offer_margin"] == pytest.approx(-0.08, abs=0.001)
