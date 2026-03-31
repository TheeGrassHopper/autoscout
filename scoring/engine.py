"""
scoring/engine.py
Deal scoring algorithm tuned for car flipping (buy low from private sellers, resell retail).

Score Breakdown:
  Profit Margin (70%):  (Carvana retail - asking price) / Carvana retail
                        This is your actual gross margin on a flip.
  Demand Score  (20%):  How fast/easy is this vehicle to resell?
                        High-demand vehicles (Tacoma, F-150, Civic) score 100.
                        Niche/low-demand vehicles score lower.
  Mileage       (10%):  Signal only — lower mileage = easier sell.

Hard Gates (override score to 0 / poor):
  - Salvage or rebuilt title → excluded (unfinsanceable, hard to resell retail)
  - Gross profit < $2,500 → classified as poor regardless of margin %
    (small margin doesn't justify reconditioning cost + time)
  - No price or no market data → neutral score, flagged as unknown

Classification:
  75–100  = 🔥 GREAT DEAL  → strong flip candidate
  50–74   = ⚡ FAIR DEAL   → worth investigating
  0–49    = ❌ POOR        → skip
"""

import logging
import datetime
from dataclasses import dataclass, field
from typing import Optional
from scrapers.craigslist import RawListing
from pricing.kbb import PriceEstimate

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.date.today().year

# ── Vehicle Demand Tiers ──────────────────────────────────────────────────────
# Based on resale speed, financing availability, and buyer pool size.
# Score = how easy/fast this vehicle sells at retail.

DEMAND_TIERS: dict[str, int] = {
    # Tier 1 — 100: Fastest movers, highest retail demand, easiest to flip
    "tacoma": 100, "4runner": 100, "land cruiser": 100, "fj cruiser": 100,
    "f-150": 100, "f150": 100, "ranger": 100, "bronco": 100,
    "silverado": 100, "sierra": 100, "ram 1500": 100, "ram1500": 100,
    "wrangler": 100, "gladiator": 100,
    "civic": 95, "accord": 95, "cr-v": 95, "crv": 95, "pilot": 92,
    "camry": 92, "rav4": 95, "highlander": 90, "tundra": 95,
    "corolla": 88, "prius": 85,

    # Tier 2 — 75: Good demand, solid resale
    "outback": 80, "forester": 78, "crosstrek": 78, "impreza": 72,
    "cx-5": 80, "cx5": 80, "cx-9": 72, "mazda3": 70, "mazda6": 65,
    "explorer": 78, "escape": 72, "expedition": 82, "f-250": 85, "f250": 85,
    "mustang": 78, "edge": 70,
    "chevy colorado": 80, "colorado": 80, "canyon": 75,
    "traverse": 72, "equinox": 70, "tahoe": 85, "suburban": 85, "yukon": 85,
    "pathfinder": 70, "frontier": 78, "armada": 72, "murano": 65,
    "rogue": 75, "altima": 65, "sentra": 60,
    "tucson": 68, "santa fe": 70, "palisade": 75, "telluride": 90, "sorento": 72,
    "model 3": 82, "model y": 85,
    "grand cherokee": 78, "cherokee": 65, "compass": 58,

    # Tier 3 — 50: Average demand
    "passat": 55, "jetta": 58, "tiguan": 62, "atlas": 60,
    "malibu": 52, "impala": 48, "trax": 52, "trailblazer": 58,
    "charger": 65, "challenger": 68, "durango": 68, "journey": 42,
    "300": 52, "pacifica": 58,
    "sonata": 58, "elantra": 60, "kona": 58, "ioniq": 58,
    "legacy": 62, "wrx": 72, "brz": 68,
    "rx": 70, "nx": 68, "gx": 78, "lx": 82,
    "mdx": 72, "rdx": 65, "tlx": 60,
    "q5": 70, "q7": 68, "a4": 62, "a6": 58,
    "3 series": 68, "5 series": 62, "x3": 72, "x5": 75,
    "c-class": 62, "e-class": 60, "glc": 68, "gle": 70,
}

DEFAULT_DEMAND = 50  # fallback for unknown models


def _demand_score(make: str, model: str) -> int:
    """Look up the demand score for a make/model combo."""
    if not model:
        return DEFAULT_DEMAND
    key = model.lower().strip()
    score = DEMAND_TIERS.get(key, 0)
    if score:
        return score
    # Try partial match
    for k, v in DEMAND_TIERS.items():
        if k in key or key in k:
            return v
    return DEFAULT_DEMAND


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
    title_status: str = ""   # clean / salvage / rebuilt / lien / missing / unknown
    vin: str = ""
    seller_phone: str = ""
    location: str = ""
    posted_date: str = ""
    description: str = ""
    image_urls: list = field(default_factory=list)

    # Pricing
    asking_price: Optional[int] = None
    kbb_value: Optional[int] = None
    carvana_value: Optional[int] = None
    carmax_value: Optional[int] = None
    local_market_value: Optional[int] = None
    local_market_comp_urls: list = field(default_factory=list)
    blended_market_value: Optional[int] = None
    price_source_confidence: str = "low"
    savings_vs_kbb: Optional[int] = None
    savings_pct: Optional[float] = None

    # Flip-specific
    profit_estimate: Optional[int] = None       # carvana_retail - asking_price
    profit_margin_pct: Optional[float] = None   # profit / carvana_retail
    demand_score: int = 0                       # 0–100 how fast/easy to resell

    # Carvana cash offer (from sell-my-car automation — requires VIN)
    carvana_offer: Optional[int] = None         # what Carvana will pay YOU for the car
    carvana_offer_margin: Optional[float] = None  # (offer - asking) / asking; positive = guaranteed profit

    # Score
    total_score: int = 0
    price_score: int = 0
    mileage_score: int = 0
    age_score: int = 0
    deal_class: str = "unknown"

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

    def __init__(self, config: dict):
        self.config = config

    def score(
        self,
        listing: RawListing,
        price_estimate: Optional[PriceEstimate],
        carvana_price: Optional[int] = None,
        carmax_price: Optional[int] = None,
        local_market_price: Optional[int] = None,
        local_market_comp_urls: Optional[list] = None,
    ) -> ScoredListing:

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
            title_status=listing.title_status,
            vin=listing.vin,
            seller_phone=getattr(listing, "seller_phone", ""),
            location=listing.location,
            posted_date=listing.posted_date,
            description=listing.description,
            image_urls=listing.image_urls,
            asking_price=listing.price,
            carvana_value=carvana_price,
            carmax_value=carmax_price,
            local_market_value=local_market_price,
            local_market_comp_urls=local_market_comp_urls or [],
        )

        if price_estimate:
            scored.kbb_value = price_estimate.fair_market_value
            scored.price_source_confidence = price_estimate.confidence

        # ── Hard Gate 1: Title Status ─────────────────────────────────────────
        # Salvage/rebuilt = unfinsanceable by most buyers, kills your resale market
        bad_titles = {"salvage", "rebuilt", "missing"}
        if scored.title_status and scored.title_status.lower() in bad_titles:
            scored.deal_class = "poor"
            scored.total_score = 0
            logger.debug(f"Excluded (title={scored.title_status}): {listing.title[:50]}")
            return scored

        # ── Blended market value (for savings reference) ──────────────────────
        # Carvana 50% > local market 30% > KBB 20%
        prices, weights = [], []
        if carvana_price:
            prices.append(carvana_price); weights.append(0.50)
        if local_market_price:
            prices.append(local_market_price); weights.append(0.30)
        if scored.kbb_value:
            prices.append(scored.kbb_value); weights.append(0.20)

        if prices:
            total_weight = sum(weights)
            scored.blended_market_value = int(
                sum(p * w for p, w in zip(prices, weights)) / total_weight
            )

        reference = scored.blended_market_value or scored.kbb_value
        if scored.asking_price and reference:
            scored.savings_vs_kbb = reference - scored.asking_price
            scored.savings_pct = scored.savings_vs_kbb / reference

        # ── Flip profit estimate ──────────────────────────────────────────────
        # Use Carvana retail as the resale target (best proxy for what you can sell it for)
        resale_target = carvana_price or scored.blended_market_value or scored.kbb_value
        if resale_target and scored.asking_price:
            scored.profit_estimate = resale_target - scored.asking_price
            scored.profit_margin_pct = scored.profit_estimate / resale_target

        # ── Hard Gate 2: Minimum profit floor ────────────────────────────────
        min_profit = self.config.get("min_profit_dollars", 2500)
        if scored.profit_estimate is not None and scored.profit_estimate < min_profit:
            scored.deal_class = "poor"
            scored.total_score = max(0, int(
                (scored.profit_estimate / min_profit) * 40
            ))
            logger.debug(
                f"Below profit floor (${scored.profit_estimate:,} < ${min_profit:,}): {listing.title[:50]}"
            )
            return scored

        # ── Demand score ──────────────────────────────────────────────────────
        scored.demand_score = _demand_score(scored.make, scored.model)

        # ── Sub-scores ────────────────────────────────────────────────────────
        scored.price_score = self._score_profit_margin(scored)
        scored.mileage_score = self._score_mileage(scored)
        scored.age_score = scored.demand_score   # re-use age_score slot for demand

        # ── Weighted total ────────────────────────────────────────────────────
        # Profit margin 70%, demand 20%, mileage 10%
        pw = self.config.get("price_weight", 0.70)
        dw = self.config.get("demand_weight", 0.20)
        mw = self.config.get("mileage_weight", 0.10)

        scored.total_score = round(
            scored.price_score * pw
            + scored.demand_score * dw
            + scored.mileage_score * mw
        )
        scored.total_score = max(0, min(100, scored.total_score))

        # ── Classify ─────────────────────────────────────────────────────────
        great_min = self.config.get("great_deal_min_score", 75)
        fair_min = self.config.get("fair_deal_min_score", 50)

        if scored.total_score >= great_min:
            scored.deal_class = "great"
        elif scored.total_score >= fair_min:
            scored.deal_class = "fair"
        else:
            scored.deal_class = "poor"

        # ── Suggested offer (8% below asking by default) ──────────────────────
        if scored.asking_price:
            offer_pct = 1.0 - self.config.get("offer_pct_below_asking", 0.08)
            scored.suggested_offer = int(scored.asking_price * offer_pct)

        profit_str = f"${scored.profit_estimate:,}" if scored.profit_estimate else "n/a"
        margin_str = f"{scored.profit_margin_pct:.0%}" if scored.profit_margin_pct else "n/a"
        ask_str = f"${scored.asking_price:,}" if scored.asking_price else "no price"
        logger.debug(
            f"Scored: {listing.title[:40]} | "
            f"Ask {ask_str} | Profit {profit_str} ({margin_str}) | "
            f"Demand {scored.demand_score} | Score {scored.total_score} ({scored.deal_class})"
        )

        return scored

    # ── Sub-scorers ───────────────────────────────────────────────────────────

    def apply_carvana_offer(self, scored: ScoredListing, offer: int) -> ScoredListing:
        """
        Enrich a ScoredListing with a real Carvana cash offer and re-evaluate.

        Logic:
          offer >= asking            → guaranteed flip; override to "great", score 95+
          offer >= asking * 0.90     → strong deal; ensure at least "great"
          offer >= asking * 0.80     → decent margin; ensure at least "fair"
          offer <  asking * 0.70     → Carvana doesn't want it at this price; don't penalize
                                       (other sources may still show value)
        """
        scored.carvana_offer = offer
        if scored.asking_price:
            scored.carvana_offer_margin = (offer - scored.asking_price) / scored.asking_price

        margin = scored.carvana_offer_margin or 0.0

        if margin >= 0.0:
            # Guaranteed profit — Carvana will pay more than asking price
            scored.deal_class = "great"
            scored.total_score = max(scored.total_score, 95)
            logger.info(
                f"[CarvanaOffer] Guaranteed flip: offer ${offer:,} >= ask "
                f"${scored.asking_price:,} (+{margin:.0%}) → GREAT"
            )
        elif margin >= -0.10:
            # Within 10% — strong deal
            scored.deal_class = "great"
            scored.total_score = max(scored.total_score, 78)
            logger.info(
                f"[CarvanaOffer] Strong deal: offer ${offer:,} vs ask "
                f"${scored.asking_price:,} ({margin:.0%}) → GREAT"
            )
        elif margin >= -0.20:
            # Within 20% — fair deal
            if scored.deal_class == "poor":
                scored.deal_class = "fair"
                scored.total_score = max(scored.total_score, 55)
            logger.info(
                f"[CarvanaOffer] Decent margin: offer ${offer:,} vs ask "
                f"${scored.asking_price:,} ({margin:.0%}) → at least FAIR"
            )
        else:
            logger.info(
                f"[CarvanaOffer] Low offer: ${offer:,} vs ask ${scored.asking_price:,} "
                f"({margin:.0%}) — no upgrade"
            )

        return scored

    def _score_profit_margin(self, s: ScoredListing) -> int:
        """
        Score based on gross profit margin (as % of resale price).
        This is the primary driver — how much money do you make on this flip?

        30%+ margin → 100 (exceptional)
        20%+ margin → 90
        15%+ margin → 80
        10%+ margin → 65
         5%+ margin → 45
         0%+ margin → 25
        negative    → 0
        """
        if s.profit_margin_pct is None:
            return 50  # no data — neutral

        pct = s.profit_margin_pct

        if pct >= 0.30:   return 100
        elif pct >= 0.25: return 95
        elif pct >= 0.20: return 90
        elif pct >= 0.17: return 82
        elif pct >= 0.15: return 75
        elif pct >= 0.12: return 68
        elif pct >= 0.10: return 60
        elif pct >= 0.07: return 50
        elif pct >= 0.05: return 40
        elif pct >= 0.0:  return 25
        else:             return 0

    def _score_mileage(self, s: ScoredListing) -> int:
        """
        Mileage score — used as a secondary signal.
        High mileage = harder sell, more reconditioning risk.
        But don't over-penalize — a 100k Tacoma with great margin is still a good flip.
        """
        if not s.mileage:
            return 60  # unknown — slight discount

        m = s.mileage

        if m < 30000:   return 100
        elif m < 50000: return 90
        elif m < 75000: return 78
        elif m < 90000: return 65
        elif m < 110000: return 50
        elif m < 130000: return 35
        elif m < 150000: return 20
        else:            return 5


# ── Sorting & Formatting ─────────────────────────────────────────────────────

def sort_listings(listings: list[ScoredListing]) -> list[ScoredListing]:
    """Sort by profit estimate desc within each class."""
    order = {"great": 0, "fair": 1, "poor": 2, "unknown": 3}
    return sorted(
        listings,
        key=lambda x: (order.get(x.deal_class, 3), -(x.profit_estimate or 0))
    )


def print_summary(listings: list[ScoredListing]):
    great = [l for l in listings if l.deal_class == "great"]
    fair = [l for l in listings if l.deal_class == "fair"]
    poor = [l for l in listings if l.deal_class == "poor"]

    print("\n" + "═" * 70)
    print(f"  AutoScout — Flip Opportunity Scanner")
    print(f"  {len(listings)} listings  |  🔥 {len(great)} great  |  ⚡ {len(fair)} fair  |  ❌ {len(poor)} poor")
    print("═" * 70)

    for l in sort_listings(listings):
        if l.deal_class == "poor":
            continue

        icon = "🔥" if l.deal_class == "great" else "⚡"
        ask = f"${l.asking_price:,}" if l.asking_price else "no price"
        carvana = f"${l.carvana_value:,}" if l.carvana_value else "no Carvana"
        profit = f"${l.profit_estimate:,}" if l.profit_estimate else "?"
        margin = f"{l.profit_margin_pct:.0%}" if l.profit_margin_pct else "?"
        mi = f"{l.mileage:,} mi" if l.mileage else "? mi"

        print(f"\n{icon} [{l.total_score:>3}/100]  {l.title}")
        print(f"   Ask {ask}  |  Carvana {carvana}  |  Profit ~{profit} ({margin})")
        print(f"   {mi}  |  Title: {l.title_status or '?'}  |  Demand: {l.demand_score}/100")
        print(f"   {l.location}  |  {l.source}  |  {l.url}")

    print("\n" + "═" * 70 + "\n")
