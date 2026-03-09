"""
scoring/deal_scorer.py
Scores each listing from 0–100 based on price vs market, mileage, and year.

Formula:
    price_score  = (market_price - asking_price) / market_price * 100
    mileage_deduction = (mileage / 10_000) * penalty_per_10k
    year_bonus   = (year - min_year) * bonus_per_year  (capped at 10)
    raw_score    = price_score - mileage_deduction + year_bonus
    final_score  = clamp(raw_score, 0, 100)
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

from scrapers.craigslist import RawListing
from pricing.kbb import MarketValue

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.date.today().year


@dataclass
class ScoredListing:
    listing: RawListing
    market_value: MarketValue

    # Comparison prices
    carvana_price: Optional[int] = None
    carmax_price: Optional[int] = None

    # Computed fields
    score: float = 0.0
    label: str = ""                     # "great" | "fair" | "skip"
    savings_vs_kbb: int = 0             # dollars saved vs KBB fair value
    pct_below_kbb: float = 0.0          # percentage below KBB

    # Score breakdown (for transparency)
    price_component: float = 0.0
    mileage_deduction: float = 0.0
    year_bonus: float = 0.0


def score_listing(
    listing: RawListing,
    market_value: MarketValue,
    carvana_price: Optional[int] = None,
    carmax_price: Optional[int] = None,
    great_deal_threshold: float = 15.0,
    fair_deal_threshold: float = 5.0,
    mileage_penalty_per_10k: float = 3.0,
    year_bonus_per_year: float = 1.0,
    min_year: int = 2017,
) -> ScoredListing:
    """Score a listing and return a ScoredListing."""

    result = ScoredListing(listing=listing, market_value=market_value,
                           carvana_price=carvana_price, carmax_price=carmax_price)

    asking = listing.asking_price
    market = market_value.fair_value

    if not asking or not market or market == 0:
        result.label = "skip"
        return result

    # ── Price component ──────────────────────────────────────────────────────
    pct_below = (market - asking) / market * 100
    result.pct_below_kbb = round(pct_below, 1)
    result.savings_vs_kbb = market - asking
    result.price_component = pct_below  # can be negative (overpriced)

    # ── Mileage deduction ────────────────────────────────────────────────────
    mileage = listing.mileage or 0
    mileage_deduction = (mileage / 10_000) * mileage_penalty_per_10k
    result.mileage_deduction = round(mileage_deduction, 1)

    # ── Year bonus ───────────────────────────────────────────────────────────
    year = listing.year or min_year
    year_bonus = min((year - min_year) * year_bonus_per_year, 10.0)
    result.year_bonus = round(year_bonus, 1)

    # ── Final score ──────────────────────────────────────────────────────────
    raw = pct_below - mileage_deduction + year_bonus
    result.score = round(max(0.0, min(100.0, raw)), 1)

    # ── Label ────────────────────────────────────────────────────────────────
    if pct_below >= great_deal_threshold and result.score >= 70:
        result.label = "great"
    elif pct_below >= fair_deal_threshold and result.score >= 40:
        result.label = "fair"
    else:
        result.label = "skip"

    return result


def score_all(
    listings: list[RawListing],
    market_values: dict[str, MarketValue],
    carvana_prices: dict[str, Optional[int]] = None,
    carmax_prices: dict[str, Optional[int]] = None,
    **score_kwargs,
) -> list[ScoredListing]:
    """Score a batch of listings and return sorted by score descending."""
    carvana_prices = carvana_prices or {}
    carmax_prices = carmax_prices or {}
    results = []

    for listing in listings:
        mv = market_values.get(listing.id)
        if not mv:
            logger.warning(f"No market value for {listing.id} — skipping score")
            continue
        scored = score_listing(
            listing=listing,
            market_value=mv,
            carvana_price=carvana_prices.get(listing.id),
            carmax_price=carmax_prices.get(listing.id),
            **score_kwargs,
        )
        results.append(scored)
        logger.debug(
            f"Scored: {listing.title[:50]} | "
            f"Ask ${listing.asking_price:,} | KBB ${mv.fair_value:,} | "
            f"{listing.pct_below_kbb if hasattr(listing,'pct_below_kbb') else scored.pct_below_kbb:.1f}% below | "
            f"Score {scored.score}"
        )

    results.sort(key=lambda x: x.score, reverse=True)
    return results
