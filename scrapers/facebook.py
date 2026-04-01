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

ANTI-BLOCKING CONFIGURATION:
  - Proxy: set APIFY_PROXY_GROUPS=RESIDENTIAL in .env for best results
    (requires Apify paid plan; free plan uses datacenter proxies which FB blocks)
  - Concurrency is limited to 1 to appear human-like
  - Retries up to 2x with exponential backoff on BLOCKED errors

ENABLE/DISABLE:
  - Set FB_SCRAPER_ENABLED=false in .env to skip FB without changing config.py

The actor scrapes: Marketplace → Vehicles → configured city → radius
Private sellers only, clean title preferred, VIN extracted from descriptions.
"""

import asyncio
import logging
import re
import time
from typing import Optional

from scrapers.craigslist import RawListing, _extract_vin, _extract_phone, _extract_email

logger = logging.getLogger(__name__)

APIFY_ACTOR_ID = "curious_coder/facebook-marketplace"

# Max actor retries on BLOCKED/failure before giving up
_MAX_RUN_RETRIES = 2
_RETRY_DELAYS = [10, 20]  # seconds between retries (exponential-ish)

# FB Marketplace vehicles URL structure:
# /marketplace/{city}/vehicles/ with query params for price, radius, delivery method
FB_VEHICLES_URL = (
    "https://www.facebook.com/marketplace/{city}/vehicles/"
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
    Returns empty list on failure — pipeline continues with other sources.
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

    _check_cookie_expiry(fb_cookies)

    city_slug = location.lower().replace(" ", "").replace(",", "")
    query = keywords[0] if keywords else ""

    # ── Primary: camoufox stealth browser (bypasses FB bot detection) ─────────
    logger.info(f"FB Marketplace: trying camoufox scraper (query={query!r}, radius={radius_miles}mi)")
    from scrapers.facebook_camoufox import (
        scrape_fb_marketplace_async, _parse_price, _parse_year, _parse_mileage,
    )
    raw_items = asyncio.run(scrape_fb_marketplace_async(
        city_slug=city_slug,
        query=query,
        min_price=min_price,
        max_price=max_price,
        radius_miles=radius_miles,
        fb_cookies=fb_cookies,
        max_items=100,
    ))

    if raw_items:
        listings = _parse_camoufox_items(raw_items, location, max_mileage, seen_ids)
        logger.info(f"FB camoufox: {len(listings)} listings parsed")
        return listings

    # ── Fallback: Apify actor (may be blocked, but worth trying) ──────────────
    logger.warning("FB camoufox returned 0 items — falling back to Apify actor")
    if not apify_token:
        logger.warning("No APIFY_API_TOKEN — cannot fall back to Apify")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed. Run: pip install apify-client")
        return []

    client = ApifyClient(apify_token)
    search_urls = _build_search_urls(city_slug, keywords, min_price, max_price, radius_miles)
    run_input = _build_run_input(search_urls, fb_cookies)
    logger.info(f"Triggering Apify FB Marketplace scrape — {len(search_urls)} URL(s)")

    items = None
    last_error = None
    for attempt in range(1 + _MAX_RUN_RETRIES):
        if attempt > 0:
            delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            logger.warning(f"FB Apify retry {attempt}/{_MAX_RUN_RETRIES} — waiting {delay}s")
            time.sleep(delay)
        try:
            run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input, timeout_secs=360)
            run_status = run.get("status", "UNKNOWN")
            logger.info(f"Apify run status: {run_status} (id={run.get('id','?')}, attempt={attempt+1})")
            if run_status not in ("SUCCEEDED", "RUNNING"):
                last_error = f"status={run_status}"; continue
            candidate_items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.info(f"Apify returned {len(candidate_items)} FB items")
            if _all_blocked(candidate_items):
                last_error = "BLOCKED"; continue
            items = candidate_items
            break
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Apify FB call failed (attempt {attempt+1}): {e}")

    if items is None:
        logger.error(f"FB Marketplace: all methods failed. Last error: {last_error}")
        return []

    listings = _parse_items(items, location, max_mileage, seen_ids)
    logger.info(f"Facebook Marketplace: {len(listings)} listings (via Apify fallback)")
    return listings


# ── camoufox item parser ──────────────────────────────────────────────────────

def _parse_camoufox_items(
    raw_items: list,
    location: str,
    max_mileage: int,
    seen_ids: set[str],
) -> list[RawListing]:
    """Convert camoufox GraphQL items into RawListing objects."""
    from scrapers.facebook_camoufox import _parse_price, _parse_year, _parse_mileage
    from scrapers.craigslist import CraigslistScraper

    listings = []
    for item in raw_items:
        if item.get("is_pending"):
            continue

        lid = item.get("id", "")
        fb_id = f"fb_{lid}"
        if fb_id in seen_ids:
            continue

        price = _parse_price(item.get("price_str", ""))
        if not price:
            continue

        subtitle = item.get("subtitle", "")
        mileage  = _parse_mileage(subtitle)
        year     = _parse_year(subtitle)

        if mileage and mileage > max_mileage:
            continue

        title = (item.get("title", "") or "").strip()
        description = subtitle
        vin = _extract_vin(description)
        title_status = _detect_title_status(title, description)
        seller_phone = _extract_phone(description)
        seller_email = _extract_email(description)

        listing = RawListing(
            listing_id=fb_id,
            source="facebook",
            url=item.get("url", f"https://www.facebook.com/marketplace/item/{lid}/"),
            title=title,
            price=price,
            location=item.get("location", location),
            description=description,
            image_urls=[item["image_url"]] if item.get("image_url") else [],
            mileage=mileage,
            year=year,
            vin=vin,
            title_status=title_status,
            seller_phone=seller_phone,
            seller_email=seller_email,
        )

        # Try to fill make/model/year from title
        dummy = CraigslistScraper.__new__(CraigslistScraper)
        dummy._parse_title_fields(listing, listing.title)

        listings.append(listing)
        seen_ids.add(fb_id)

    return listings


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_search_urls(
    city_slug: str,
    keywords: list[str],
    min_price: int,
    max_price: int,
    radius_miles: int,
) -> list[dict]:
    """Build the list of FB Marketplace search URLs for the actor."""
    radius = min(radius_miles, 500)  # FB max is 500mi
    if keywords and any(keywords):
        urls = []
        for kw in keywords:
            if kw:
                kw_enc = kw.lower().replace(" ", "%20")
                urls.append({
                    "url": (
                        f"https://www.facebook.com/marketplace/{city_slug}/vehicles/"
                        f"?query={kw_enc}&minPrice={min_price}&maxPrice={max_price}"
                        f"&radius={radius}&deliveryMethod=local_pick_up"
                    )
                })
        if urls:
            return urls
    return [{
        "url": FB_VEHICLES_URL.format(
            city=city_slug,
            min_price=min_price,
            max_price=max_price,
            radius=radius,
        )
    }]


def _cookies_to_header_string(fb_cookies: list) -> str:
    """Convert JSON cookie array to 'name=value; name=value' header string for curious_coder actor."""
    if not fb_cookies:
        return ""
    if isinstance(fb_cookies, str):
        return fb_cookies  # already a header string
    parts = []
    for c in fb_cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if name and value:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _build_run_input(search_urls: list[dict], fb_cookies: list) -> dict:
    """
    Build input for curious_coder/facebook-marketplace actor.
    - urls: list of FB Marketplace search URLs
    - getListingDetails: True → returns vehicle-specific fields (VIN, make, model, year, mileage, etc.)
    - cookies: header-string format for authenticated access
    - proxy: US residential for best FB compatibility
    """
    # curious_coder uses "urls" (list of URL strings), not "startUrls" (list of dicts)
    url_strings = [u["url"] if isinstance(u, dict) else u for u in search_urls]
    run_input: dict = {
        "urls": url_strings,
        "getListingDetails": True,   # enables vehicle_make, vehicle_year, VIN, mileage, etc.
        "getAllListingPhotos": False, # skip extra photo fetches to save credits
        "strictFiltering": True,     # exclude off-location broad-match results
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyCountry": "US",
        },
    }
    if fb_cookies:
        run_input["cookies"] = _cookies_to_header_string(fb_cookies)
    return run_input


def _all_blocked(items: list) -> bool:
    """
    Return True if every item in the dataset is a BLOCKED error indicator.
    An empty dataset is NOT treated as blocked (could be zero listings).
    """
    if not items:
        return False
    blocked_count = sum(
        1 for item in items
        if _is_blocked_item(item)
    )
    # Treat as blocked if >80% of items are error/blocked signals
    return blocked_count > 0 and blocked_count / len(items) > 0.8


def _is_blocked_item(item: dict) -> bool:
    """Detect whether an item represents a BLOCKED / error response."""
    if item.get("error"):
        err = str(item.get("errorDescription", item.get("error", ""))).lower()
        return "block" in err or "captcha" in err or "login" in err or "403" in err
    # Some actor versions return a `status` field
    status = str(item.get("status", "")).lower()
    return status in ("blocked", "failed", "error")


def _parse_items(
    items: list,
    location: str,
    max_mileage: int,
    seen_ids: set[str],
) -> list[RawListing]:
    """
    Convert curious_coder/facebook-marketplace output items into RawListing objects.

    curious_coder returns structured vehicle fields when getListingDetails=True:
      vehicle_make_display_name, vehicle_model_display_name, vehicle_year,
      vehicle_odometer_data {value, unit}, vehicle_identification_number (VIN),
      vehicle_transmission_type, vehicle_fuel_type, vehicle_title_status,
      vehicle_seller_type (PRIVATE_SELLER vs dealer)
    """
    from scrapers.craigslist import CraigslistScraper

    listings = []
    for item in items:
        if item.get("error") or _is_blocked_item(item):
            logger.warning(f"FB item error: {item.get('errorDescription', item.get('error'))}")
            continue

        listing_id = str(item.get("id", "") or item.get("listing_id", ""))
        if not listing_id:
            continue

        fb_id = f"fb_{listing_id}"
        if fb_id in seen_ids:
            continue

        # ── Price ────────────────────────────────────────────────────────────
        price_obj = item.get("listing_price") or {}
        price = None
        if isinstance(price_obj, dict):
            price = _parse_fb_price(str(price_obj.get("amount") or price_obj.get("formatted_amount", "")))
        if not price:
            price = _parse_fb_price(str(item.get("price", "")))
        if not price:
            logger.debug(f"FB skip (no price): {item.get('marketplace_listing_title','')[:40]}")
            continue

        # ── Description ───────────────────────────────────────────────────────
        desc_obj = item.get("redacted_description") or {}
        description = (
            (desc_obj.get("text") if isinstance(desc_obj, dict) else "")
            or item.get("description", "")
            or ""
        )[:1200]

        # ── Mileage (structured first, then parse description) ────────────────
        odometer = item.get("vehicle_odometer_data") or {}
        mileage = None
        if isinstance(odometer, dict) and odometer.get("value"):
            val = int(odometer["value"])
            unit = (odometer.get("unit") or "").upper()
            mileage = val if "MI" in unit else int(val * 1.60934)  # km → miles
        if not mileage:
            mileage = _parse_fb_mileage(description)

        if mileage and mileage > max_mileage:
            continue

        # ── Private seller filter ─────────────────────────────────────────────
        seller_type = (item.get("vehicle_seller_type") or "").upper()
        if seller_type and seller_type not in ("PRIVATE_SELLER", "PRIVATE", ""):
            logger.debug(f"FB skip (dealer): {item.get('marketplace_listing_title','')[:40]}")
            continue

        # ── VIN ───────────────────────────────────────────────────────────────
        vin = item.get("vehicle_identification_number") or _extract_vin(description)

        # ── Title status ──────────────────────────────────────────────────────
        title_status_raw = (item.get("vehicle_title_status") or "").lower()
        if "clean" in title_status_raw:
            title_status = "clean"
        elif "salvage" in title_status_raw:
            title_status = "salvage"
        elif "rebuilt" in title_status_raw:
            title_status = "rebuilt"
        else:
            title_status = _detect_title_status(
                item.get("marketplace_listing_title", ""), description
            )

        # ── Location ──────────────────────────────────────────────────────────
        loc_obj = item.get("location") or {}
        geo = (loc_obj.get("reverse_geocode") or {}) if isinstance(loc_obj, dict) else {}
        listing_location = (
            ", ".join(filter(None, [geo.get("city"), geo.get("state")]))
            or item.get("location_text", "")
            or location
        )

        # ── Photos ───────────────────────────────────────────────────────────
        photo_url = item.get("primary_listing_photo_url", "")
        photos = item.get("listing_photos") or []
        if isinstance(photos, list):
            image_urls = [p.get("image", {}).get("uri", "") for p in photos if isinstance(p, dict)]
            image_urls = [u for u in image_urls if u]
        else:
            image_urls = [photo_url] if photo_url else []

        # ── Title ────────────────────────────────────────────────────────────
        title = (
            item.get("marketplace_listing_title")
            or item.get("custom_title")
            or ""
        ).strip()

        # ── Make / Model / Year — structured fields take priority ─────────────
        make  = (item.get("vehicle_make_display_name")  or "").strip().title()
        model = (item.get("vehicle_model_display_name") or "").strip().title()
        trim  = (item.get("vehicle_trim_display_name")  or "").strip()
        if trim:
            model = f"{model} {trim}".strip()
        year_val = item.get("vehicle_year")
        year = int(year_val) if year_val else None

        # ── Contact info ─────────────────────────────────────────────────────
        seller_phone = _extract_phone(description)
        seller_email = _extract_email(description)

        # ── Transmission / Fuel ───────────────────────────────────────────────
        transmission = (item.get("vehicle_transmission_type") or "").lower() or None
        fuel = (item.get("vehicle_fuel_type") or "").lower() or None

        # ── Posted date ───────────────────────────────────────────────────────
        creation_time = item.get("creation_time")
        posted_date = ""
        if creation_time:
            try:
                from datetime import datetime, timezone
                posted_date = datetime.fromtimestamp(int(creation_time), tz=timezone.utc).isoformat()
            except Exception:
                pass

        listing = RawListing(
            listing_id=fb_id,
            source="facebook",
            url=item.get("url") or f"https://www.facebook.com/marketplace/item/{listing_id}",
            title=title,
            price=price,
            location=listing_location,
            posted_date=posted_date,
            description=description,
            image_urls=image_urls,
            mileage=mileage,
            year=year,
            make=make,
            model=model,
            vin=vin,
            title_status=title_status,
            seller_phone=seller_phone,
            seller_email=seller_email,
        )

        # Store transmission/fuel if RawListing supports it
        if hasattr(listing, "transmission") and transmission:
            listing.transmission = transmission
        if hasattr(listing, "fuel") and fuel:
            listing.fuel = fuel

        # Fall back to title parsing only if make/model not populated
        if not make or not model:
            dummy = CraigslistScraper.__new__(CraigslistScraper)
            dummy._parse_title_fields(listing, listing.title)

        listings.append(listing)
        seen_ids.add(fb_id)

    return listings


def _check_cookie_expiry(cookies: list):
    """Warn in logs if any critical FB cookies are expiring soon or already expired."""
    now = time.time()
    critical = {"c_user", "xs", "datr", "fr", "sb"}
    for cookie in cookies:
        name = cookie.get("name", "")
        exp = cookie.get("expirationDate")
        if name not in critical or not exp:
            continue
        days_left = (exp - now) / 86400
        if days_left < 0:
            logger.error(
                f"FB cookie '{name}' has EXPIRED ({abs(days_left):.0f} days ago) — "
                "re-export your Facebook cookies and update FB_COOKIES in .env"
            )
        elif days_left < 7:
            logger.warning(
                f"FB cookie '{name}' expires in {days_left:.0f} day(s) — "
                "re-export soon to avoid scrape failures"
            )
        elif days_left < 21:
            logger.warning(
                f"FB cookie '{name}' expires in {days_left:.0f} days — plan to refresh"
            )


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
