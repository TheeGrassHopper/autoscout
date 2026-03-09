"""
scoring/engine.py
Deal scoring algorithm. Takes a listing + price estimate and produces a 0–100 score.

Score Breakdown:
  Price Component (65%):  How far below market value is the asking price?
  Mileage Component (20%): Lower mileage = higher score.
  Age Component (15%):     Newer = higher score, but sweet spot is 3–6 years old.

Classification:
  75–100  = 🔥 GREAT DEAL  → trigger auto-message
  50–74   = ⚡ FAIR DEAL   → notify user
  0–49    = ❌ OVERPRICED  → skip
"""

import logging
import datetime
from dataclasses import dataclass, field
from typing import Optional
from scrapers.craigslist import RawListing
from pricing.kbb import PriceEstimate

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.date.today().year


@dataclass
class ScoredListing:
    """A fully scored vehicle listing ready for output/messaging."""

    # Raw listing data
    source: str = ""
    listing_id: str = ""
    url: str = ""
    title: str = ""
    year: Optional[int] = None
    make: str = ""
    model: str = ""
    mileage: Optional[int] = None
    transmission: str = ""
    location: str = ""
    posted_date: str = ""
    description: str = ""
    image_urls: list = field(default_factory=list)

    # Pricing
    asking_price: Optional[int] = None
    kbb_value: Optional[int] = None
    price_source_confidence: str = "low"
    savings_vs_kbb: Optional[int] = None
    savings_pct: Optional[float] = None

    # Score
    total_score: int = 0
    price_score: int = 0
    mileage_score: int = 0
    age_score: int = 0
    deal_class: str = "unknown"   # great / fair / poor / unknown

    # Messaging
    suggested_offer: Optional[int] = None
    message_draft: str = ""
    message_sent: bool = False

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["image_urls"] = "; ".join(d["image_urls"])
        return d

    @property
    def is_great_deal(self) -> bool:
        return self.deal_class == "great"

    @property
    def is_fair_deal(self) -> bool:
        return self.deal_class == "fair"


# ── Scoring Engine ────────────────────────────────────────────────────────────

class DealScorer:
    """
    Scores vehicle listings.

    Usage:
        scorer = DealScorer(config=SCORING)
        scored = scorer.score(listing, price_estimate)
    """

    def __init__(self, config: dict):
        self.config = config

    def score(
        self,
        listing: RawListing,
        price_estimate: Optional[PriceEstimate],
    ) -> ScoredListing:
        """Score a listing and return a ScoredListing."""

        scored = ScoredListing(
            source=listing.source,
            listing_id=listing.listing_id,
            url=listing.url,
            title=listing.title,
            year=listing.year,
            make=listing.make,
            model=listing.model,
            mileage=listing.mileage,
            transmission=listing.transmission,
            location=listing.location,
            posted_date=listing.posted_date,
            description=listing.description,
            image_urls=listing.image_urls,
            asking_price=listing.price,
        )

        if price_estimate:
            scored.kbb_value = price_estimate.fair_market_value
            scored.price_source_confidence = price_estimate.confidence

            if scored.asking_price and scored.kbb_value:
                scored.savings_vs_kbb = scored.kbb_value - scored.asking_price
                scored.savings_pct = scored.savings_vs_kbb / scored.kbb_value

        # Compute sub-scores
        scored.price_score = self._score_price(scored)
        scored.mileage_score = self._score_mileage(scored)
        scored.age_score = self._score_age(scored)

        # Weighted total
        pw = self.config.get("price_weight", 0.65)
        mw = self.config.get("mileage_weight", 0.20)
        aw = self.config.get("age_weight", 0.15)

        scored.total_score = round(
            scored.price_score * pw
            + scored.mileage_score * mw
            + scored.age_score * aw
        )
        scored.total_score = max(0, min(100, scored.total_score))

        # Classify
        great_min = self.config.get("great_deal_min_score", 75)
        fair_min = self.config.get("fair_deal_min_score", 50)

        if scored.total_score >= great_min:
            scored.deal_class = "great"
        elif scored.total_score >= fair_min:
            scored.deal_class = "fair"
        else:
            scored.deal_class = "poor"

        # Suggested offer
        if scored.asking_price:
            offer_pct = 1.0 - self.config.get("offer_pct_below_asking", 0.08)
            scored.suggested_offer = int(scored.asking_price * offer_pct)

        logger.debug(
            f"Scored: {listing.title[:40]} | "
            f"${scored.asking_price:,} vs KBB ${scored.kbb_value:,} | "
            f"Score {scored.total_score} ({scored.deal_class})"
        )

        return scored

    # ── Sub-scorers ───────────────────────────────────────────────────────────

    def _score_price(self, s: ScoredListing) -> int:
        """
        Price score 0–100.
        100 = asking price is 30%+ below KBB
        50  = asking price equals KBB
        0   = asking price is 20%+ above KBB
        """
        if not s.savings_pct:
            # No pricing data — neutral score
            return 50

        pct = s.savings_pct   # positive = below market, negative = above

        if pct >= 0.30:
            return 100
        elif pct >= 0.20:
            return 90
        elif pct >= 0.15:
            return 80
        elif pct >= 0.10:
            return 70
        elif pct >= 0.05:
            return 60
        elif pct >= 0.0:
            return 50
        elif pct >= -0.05:
            return 38
        elif pct >= -0.10:
            return 25
        elif pct >= -0.20:
            return 12
        else:
            return 0

    def _score_mileage(self, s: ScoredListing) -> int:
        """
        Mileage score 0–100.
        100 = under 20k miles
        70  = 40k–60k miles (sweet spot — depreciation hit done)
        0   = over 150k miles
        """
        if not s.mileage:
            return 50  # unknown mileage — neutral

        m = s.mileage

        if m < 20000:
            return 100
        elif m < 30000:
            return 92
        elif m < 40000:
            return 85
        elif m < 50000:
            return 78
        elif m < 60000:
            return 70
        elif m < 75000:
            return 60
        elif m < 90000:
            return 48
        elif m < 110000:
            return 35
        elif m < 130000:
            return 20
        elif m < 150000:
            return 10
        else:
            return 0

    def _score_age(self, s: ScoredListing) -> int:
        """
        Age score 0–100.
        Sweet spot: 3–6 year old vehicles (depreciation done, still reliable).
        """
        if not s.year:
            return 50

        age = CURRENT_YEAR - s.year

        if age == 0:
            return 70    # Brand new — high price, not a "deal"
        elif age == 1:
            return 80
        elif age == 2:
            return 90
        elif age <= 4:
            return 100   # Sweet spot
        elif age <= 6:
            return 88
        elif age <= 8:
            return 72
        elif age <= 10:
            return 55
        elif age <= 12:
            return 38
        elif age <= 15:
            return 22
        else:
            return 8


# ── Sorting & Formatting ─────────────────────────────────────────────────────

def sort_listings(listings: list[ScoredListing]) -> list[ScoredListing]:
    """Sort listings: great deals first, then by score desc."""
    order = {"great": 0, "fair": 1, "poor": 2, "unknown": 3}
    return sorted(listings, key=lambda x: (order.get(x.deal_class, 3), -x.total_score))


def print_summary(listings: list[ScoredListing]):
    """Pretty-print a deal summary to the terminal."""
    great = [l for l in listings if l.deal_class == "great"]
    fair = [l for l in listings if l.deal_class == "fair"]
    poor = [l for l in listings if l.deal_class == "poor"]

    print("\n" + "═" * 70)
    print(f"  AutoScout AI — Scan Results")
    print(f"  {len(listings)} listings scanned  |  "
          f"🔥 {len(great)} great  |  ⚡ {len(fair)} fair  |  ❌ {len(poor)} poor")
    print("═" * 70)

    for l in sort_listings(listings):
        if l.deal_class == "poor":
            continue  # Skip overpriced in terminal output

        icon = "🔥" if l.deal_class == "great" else "⚡"
        savings_str = ""
        if l.savings_vs_kbb is not None:
            if l.savings_vs_kbb > 0:
                savings_str = f"  ▼ ${l.savings_vs_kbb:,} below KBB"
            else:
                savings_str = f"  ▲ ${abs(l.savings_vs_kbb):,} above KBB"

        print(f"\n{icon} [{l.total_score:>3}/100]  {l.title}")
        print(f"   ${l.asking_price:,} asking"
              f"  |  KBB ~${l.kbb_value:,}"
              f"{savings_str}")
        print(f"   {l.mileage:,} mi  |  {l.location}  |  {l.source}")
        print(f"   {l.url}")

    print("\n" + "═" * 70 + "\n")
