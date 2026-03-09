"""
scrapers/facebook.py
FB Marketplace scraping via Apify Actor (Phase 2).

FB actively blocks direct scraping, so we use Apify's pre-built
"Facebook Marketplace Scraper" actor which handles sessions and anti-bot.

Setup:
  1. Create a free account at https://apify.com
  2. Find the actor: apify/facebook-marketplace-scraper
  3. Set APIFY_API_TOKEN in your .env file
  4. Enable this scraper in config.py
"""

import logging
from typing import Optional

from scrapers.craigslist import RawListing

logger = logging.getLogger(__name__)

# Apify actor ID for FB Marketplace scraping
APIFY_ACTOR_ID = "apify/facebook-marketplace-scraper"


def scrape_facebook(
    location: str,
    keywords: list[str],
    min_price: int,
    max_price: int,
    max_mileage: int,
    radius_miles: int,
    apify_token: str,
    seen_ids: set[str],
) -> list[RawListing]:
    """
    Trigger Apify actor to scrape FB Marketplace and return RawListings.
    Requires: pip install apify-client
    """
    if not apify_token:
        logger.warning("APIFY_API_TOKEN not set — skipping FB Marketplace scrape")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed. Run: pip install apify-client")
        return []

    client = ApifyClient(apify_token)
    listings = []

    for keyword in keywords:
        logger.info(f"Triggering Apify FB scrape for: {keyword}")

        run_input = {
            "searchQuery": keyword,
            "location": location,
            "maxItems": 40,
            "minPrice": min_price,
            "maxPrice": max_price,
            "radiusMiles": radius_miles,
        }

        try:
            run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input)
            items = client.dataset(run["defaultDatasetId"]).iterate_items()

            for item in items:
                listing_id = str(item.get("id", ""))
                if listing_id in seen_ids:
                    continue

                price = _parse_fb_price(item.get("price", ""))
                mileage = _parse_fb_mileage(item.get("mileage", "") or item.get("description", ""))

                if mileage and mileage > max_mileage:
                    continue

                listing = RawListing(
                    listing_id=f"fb_{listing_id}",
                    source="facebook",
                    url=item.get("url", f"https://www.facebook.com/marketplace/item/{listing_id}"),
                    title=item.get("title", "").strip(),
                    price=price,
                    location=item.get("location", location),
                    posted_date=item.get("postedAt", ""),
                    description=item.get("description", "")[:800],
                    image_urls=item.get("images") or [],
                    mileage=mileage,
                )
                listings.append(listing)

        except Exception as e:
            logger.error(f"Apify FB scrape failed for '{keyword}': {e}")

    logger.info(f"FB Marketplace scrape complete: {len(listings)} new listings")
    return listings


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_fb_price(price_str: str) -> Optional[int]:
    import re
    clean = re.sub(r"[^\d]", "", str(price_str))
    return int(clean) if clean else None

def _parse_fb_mileage(text: str) -> Optional[int]:
    import re
    match = re.search(r"([\d,]+)\s*(miles?|mi)", str(text), re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return None
