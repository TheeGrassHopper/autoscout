"""
scrapers/facebook.py
FB Marketplace scraping via Apify Actor.

Facebook Marketplace requires you to be logged in — the actor needs your
Facebook session cookies to access listings. Without cookies it gets blocked.

HOW TO GET YOUR FACEBOOK COOKIES:
  1. Install "EditThisCookie" or "Cookie-Editor" browser extension
  2. Log into facebook.com in your browser
  3. Click the extension → Export cookies as JSON
  4. Paste the JSON array into your .env file:
       FB_COOKIES='[{"name":"c_user","value":"..."},{"name":"xs","value":"..."},...]'
  5. The minimum cookies needed: c_user, xs, datr, fr, sb

The actor scrapes: Marketplace → Vehicles → Tempe AZ → 500mi radius
Private sellers only, clean title preferred, VIN extracted from descriptions.
"""

import logging
import re
from typing import Optional

from scrapers.craigslist import RawListing, _extract_vin

logger = logging.getLogger(__name__)

APIFY_ACTOR_ID = "apify/facebook-marketplace-scraper"

# FB Marketplace vehicles URL structure:
# /marketplace/{city}/vehicles/ with query params for price, radius, delivery method
FB_VEHICLES_URL = (
    "https://www.facebook.com/marketplace/tempe/vehicles/"
    "?minPrice={min_price}&maxPrice={max_price}"
    "&radius={radius}&deliveryMethod=local_pick_up"
    "&sortBy=creation_time_descend"
)


def scrape_facebook(
    location: str,
    keywords: list[str],
    min_price: int,
    max_price: int,
    max_mileage: int,
    radius_miles: int,
    apify_token: str,
    seen_ids: set[str],
    fb_cookies: Optional[list] = None,
) -> list[RawListing]:
    """
    Scrape FB Marketplace vehicles via Apify.
    Requires fb_cookies (list of cookie dicts) for authenticated access.
    """
    if not apify_token:
        logger.warning("APIFY_API_TOKEN not set — skipping FB Marketplace scrape")
        return []

    if not fb_cookies:
        logger.warning(
            "FB_COOKIES not set — Facebook Marketplace requires login cookies to scrape. "
            "See scrapers/facebook.py for instructions on how to export your cookies."
        )
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed. Run: pip install apify-client")
        return []

    client = ApifyClient(apify_token)
    listings = []

    # Build the vehicles search URL
    search_url = FB_VEHICLES_URL.format(
        min_price=min_price,
        max_price=max_price,
        radius=min(radius_miles, 500),  # FB max is 500mi
    )

    # If keywords given, add them to the search
    search_urls = []
    if keywords and any(keywords):
        for kw in keywords:
            if kw:
                kw_slug = kw.lower().replace(" ", "%20")
                search_urls.append({
                    "url": f"https://www.facebook.com/marketplace/tempe/vehicles/?query={kw_slug}"
                          f"&minPrice={min_price}&maxPrice={max_price}"
                          f"&radius={min(radius_miles, 500)}&deliveryMethod=local_pick_up"
                })
    else:
        search_urls.append({"url": search_url})

    run_input = {
        "startUrls": search_urls,
        "maxItems": 100,
        "cookies": fb_cookies,
    }

    logger.info(f"Triggering Apify FB Marketplace scrape — {len(search_urls)} URL(s), radius {radius_miles}mi")

    try:
        run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input, timeout_secs=300)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        logger.info(f"Apify returned {len(items)} FB items")

        for item in items:
            # Skip error items
            if item.get("error"):
                logger.debug(f"FB item error: {item.get('errorDescription')}")
                continue

            listing_id = str(item.get("id", "") or item.get("listing_id", ""))
            if not listing_id:
                continue

            fb_id = f"fb_{listing_id}"
            if fb_id in seen_ids:
                continue

            price = _parse_fb_price(item.get("price", ""))
            if not price:
                continue

            description = (item.get("description", "") or "")[:1200]
            mileage = _parse_fb_mileage(
                item.get("mileage", "") or item.get("condition", "") or description
            )

            if mileage and mileage > max_mileage:
                continue

            # Extract VIN from description
            vin = _extract_vin(description)

            # Detect title status
            title_status = _detect_title_status(
                item.get("title", ""), description
            )

            listing = RawListing(
                listing_id=fb_id,
                source="facebook",
                url=item.get("url") or f"https://www.facebook.com/marketplace/item/{listing_id}",
                title=(item.get("title", "") or "").strip(),
                price=price,
                location=item.get("location", location),
                posted_date=item.get("postedAt", "") or item.get("listed_at", ""),
                description=description,
                image_urls=item.get("images") or [],
                mileage=mileage,
                vin=vin,
                title_status=title_status,
            )

            # Parse make/model/year from title
            from scrapers.craigslist import CraigslistScraper
            dummy = CraigslistScraper.__new__(CraigslistScraper)
            dummy._parse_title_fields(listing, listing.title)

            listings.append(listing)
            seen_ids.add(fb_id)

    except Exception as e:
        logger.error(f"Apify FB scrape failed: {e}")

    logger.info(f"Facebook Marketplace: {len(listings)} new listings")
    return listings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_fb_price(price_str: str) -> Optional[int]:
    clean = re.sub(r"[^\d]", "", str(price_str))
    return int(clean) if clean else None


def _parse_fb_mileage(text: str) -> Optional[int]:
    # "Driven 45,000 miles" or "45k miles" or "45,000 mi"
    text = str(text)
    m = re.search(r"driven\s*([\d,]+)\s*k?\s*(miles?|mi)\b", text, re.IGNORECASE)
    if m:
        val = int(m.group(1).replace(",", ""))
        return val * 1000 if "k" in m.group(0).lower() else val
    m = re.search(r"([\d,]+)\s*k\s*(miles?|mi)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", "")) * 1000
    m = re.search(r"([\d,]+)\s*(miles?|mi)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _detect_title_status(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if re.search(r"\bsalvage\b", text):        return "salvage"
    if re.search(r"\brebuilt\b", text):        return "rebuilt"
    if re.search(r"\bclean\s*title\b", text):  return "clean"
    if re.search(r"\blien\b", text):           return "lien"
    if re.search(r"\bno\s*title\b|missing\s*title\b", text): return "missing"
    return "unknown"
