"""
scrapers/facebook_camoufox.py
Facebook Marketplace vehicle scraper using camoufox (stealth Firefox browser).

Strategy:
  - Inject FB session cookies into camoufox browser context
  - Navigate to the FB Marketplace vehicles search URL
  - Parse SSR HTML: FB embeds GraphQL response data directly in the page HTML
    (Comet SSR framework — listings are in the initial HTML, not in post-load API calls)
  - Also intercept /api/graphql responses for pagination (strip "for (;;);" prefix)
  - Scroll down to trigger pagination and collect more listings
  - Parse vehicle details (year, mileage) from subtitle text fields

Response path (both SSR HTML and live GraphQL):
  data.marketplace_search.feed_units.edges[n].node
  → __typename == "MarketplaceFeedListingStoryObject"
  → .listing (id, title, price, location, subtitles)
"""

import asyncio
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_SCROLL_PAUSES = 4       # how many times to scroll for more listings
_SCROLL_DELAY_MS = 2500  # ms between scrolls
_PAGE_TIMEOUT = 30_000   # ms


async def scrape_fb_marketplace_async(
    city_slug: str,
    query: str,
    min_price: int,
    max_price: int,
    radius_miles: int,
    fb_cookies: list,
    max_items: int = 100,
) -> list[dict]:
    """
    Core async scraper. Returns raw item dicts with keys:
      id, title, price_str, location, subtitle, image_url, is_pending
    """
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        logger.error("camoufox not installed — cannot scrape FB Marketplace")
        return []

    radius_km = min(int(radius_miles * 1.609), 500)
    url = (
        f"https://www.facebook.com/marketplace/{city_slug}/vehicles/"
        f"?query={query}&minPrice={min_price}&maxPrice={max_price}"
        f"&radius={radius_km}&deliveryMethod=local_pick_up"
        f"&sortBy=creation_time_descend"
    )
    logger.info(f"FB camoufox: loading {url}")

    collected: list[dict] = []
    seen_ids: set[str] = set()

    async def on_response(response):
        """Intercept GraphQL responses (pagination after initial scroll)."""
        if "api/graphql" not in response.url:
            return
        try:
            text = await response.text()
            # FB prefixes JSON responses with "for (;;);" to prevent hijacking
            if text.startswith("for (;;);"):
                text = text[9:]
            body = json.loads(text)
        except Exception:
            return
        _process_graphql_body(body, collected, seen_ids, max_items)

    playwright_cookies = _convert_cookies(fb_cookies)

    try:
        async with AsyncCamoufox(headless=True, geoip=True) as browser:
            context = await browser.new_context()
            if playwright_cookies:
                await context.add_cookies(playwright_cookies)

            page = await context.new_page()
            page.on("response", on_response)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT)
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"FB camoufox: page load issue: {e}")

            # Parse SSR HTML for initial listings (FB embeds data in page HTML)
            html = await page.content()
            before = len(collected)
            _parse_html_listings(html, collected, seen_ids, max_items)
            logger.debug(f"FB camoufox: initial HTML parse → {len(collected) - before} listings")

            # Scroll to trigger pagination
            for i in range(_SCROLL_PAUSES):
                if len(collected) >= max_items:
                    break
                try:
                    await page.evaluate(
                        "document.body && window.scrollBy(0, document.body.scrollHeight)"
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(_SCROLL_DELAY_MS)

                # Re-parse HTML after scroll (new listings may be added to DOM)
                html = await page.content()
                before = len(collected)
                _parse_html_listings(html, collected, seen_ids, max_items)
                logger.debug(
                    f"FB camoufox: scroll {i+1}/{_SCROLL_PAUSES}, "
                    f"{len(collected)} total ({len(collected) - before} new)"
                )

    except Exception as e:
        logger.warning(f"FB camoufox: browser error: {e}")

    logger.info(f"FB camoufox: collected {len(collected)} raw listings")
    return collected


# ── GraphQL body parser ───────────────────────────────────────────────────────

def _process_graphql_body(body: dict, collected: list, seen_ids: set, max_items: int):
    """Process a parsed GraphQL response body to extract marketplace listings."""
    edges = (
        body.get("data", {})
            .get("marketplace_search", {})
            .get("feed_units", {})
            .get("edges", [])
    )
    for edge in edges:
        if len(collected) >= max_items:
            return
        node = edge.get("node", {})
        if node.get("__typename") != "MarketplaceFeedListingStoryObject":
            continue
        _extract_listing(node.get("listing", {}), collected, seen_ids)


# ── HTML SSR parser ───────────────────────────────────────────────────────────

def _parse_html_listings(html: str, collected: list, seen_ids: set, max_items: int):
    """
    Extract listings from FB Marketplace SSR HTML.

    FB (Comet framework) embeds the initial GraphQL response directly in page HTML.
    Strategy 1: Find and parse the marketplace_search JSON blob (full GraphQL structure).
    Strategy 2: Regex field extraction from raw HTML (fallback).
    """
    if len(collected) >= max_items:
        return

    # Strategy 1: extract the marketplace_search JSON object
    for m in re.finditer(r'"marketplace_search"\s*:\s*\{', html):
        ms_start = m.end() - 1  # opening {
        obj_str = _extract_balanced_json(html, ms_start, max_length=500_000)
        if not obj_str:
            continue
        try:
            ms_data = json.loads(obj_str)
            edges = ms_data.get("feed_units", {}).get("edges", [])
            for edge in edges:
                if len(collected) >= max_items:
                    return
                node = edge.get("node", {})
                if node.get("__typename") != "MarketplaceFeedListingStoryObject":
                    continue
                _extract_listing(node.get("listing", {}), collected, seen_ids)
            if collected:
                return  # successfully parsed — skip strategy 2
        except Exception as e:
            logger.debug(f"FB HTML strategy 1 failed: {e}")

    # Strategy 2: regex extraction (handles relay-store format where fields may be split)
    _parse_listings_regex(html, collected, seen_ids, max_items)


def _extract_listing(listing: dict, collected: list, seen_ids: set):
    """Append a single listing dict from a parsed GraphQL listing node."""
    lid = listing.get("id")
    if not lid or lid in seen_ids:
        return
    seen_ids.add(lid)

    price_info = listing.get("listing_price", {})
    price_str = (
        price_info.get("formatted_amount")
        or price_info.get("amount", "")
    )

    # Subtitles — FB returns vehicle details as text lines
    # e.g. [{"subtitle": {"text": "2018 · 135,000 mi"}}, ...]
    # Some SSR versions use {"subtitle": "2018 · 135,000 mi"} directly
    subtitles = []
    for sub in listing.get("custom_sub_titles_with_rendering_flags", []):
        if not isinstance(sub, dict):
            continue
        sub_val = sub.get("subtitle", {})
        t = sub_val.get("text", "") if isinstance(sub_val, dict) else str(sub_val or "")
        if t:
            subtitles.append(t)
    if not subtitles:
        sub_text = listing.get("listing_seller_description", {}).get("text", "")
        if sub_text:
            subtitles.append(sub_text)

    image_url = (
        listing.get("primary_listing_photo", {})
               .get("image", {})
               .get("uri", "")
    )

    location_text = (
        listing.get("location_text", {}).get("text", "")
        or listing.get("location", {})
                 .get("reverse_geocode", {})
                 .get("city_page", {})
                 .get("display_name", "")
    )

    collected.append({
        "id":         lid,
        "title":      listing.get("marketplace_listing_title", ""),
        "price_str":  price_str,
        "location":   location_text,
        "subtitle":   " · ".join(subtitles),
        "image_url":  image_url,
        "is_pending": listing.get("is_pending", False),
        "url":        f"https://www.facebook.com/marketplace/item/{lid}/",
    })


def _parse_listings_regex(html: str, collected: list, seen_ids: set, max_items: int):
    """
    Fallback regex parser for when JSON extraction fails.
    Finds marketplace_listing_title occurrences and extracts nearby fields.
    """
    for m in re.finditer(r'"marketplace_listing_title"\s*:\s*"([^"]*)"', html):
        if len(collected) >= max_items:
            break

        title = _decode_json_str(m.group(1))
        title_pos = m.start()

        # Search window: 3000 chars before and after the title field
        win_start = max(0, title_pos - 3000)
        win_end = min(len(html), title_pos + 3000)
        window = html[win_start:win_end]
        local_pos = title_pos - win_start

        # Find the nearest numeric listing ID before the title
        # FB listing IDs are 10–16 digit numbers
        lid = None
        id_matches = list(re.finditer(r'"id"\s*:\s*"(\d{10,16})"', window[:local_pos + 100]))
        if id_matches:
            lid = id_matches[-1].group(1)  # take closest before title

        if not lid or lid in seen_ids:
            continue

        # Price
        price_str = ""
        p = re.search(r'"formatted_amount"\s*:\s*"([^"]*)"', window)
        if p:
            price_str = _decode_json_str(p.group(1))

        # Subtitles (handles both string and {"text":"..."} object formats)
        subtitles = []
        for sub_m in re.finditer(
            r'"subtitle"\s*:\s*(?:"([^"]*)"|{[^}]*?"text"\s*:\s*"([^"]*)")',
            window
        ):
            text = sub_m.group(1) or sub_m.group(2) or ""
            if text:
                subtitles.append(_decode_json_str(text))

        # Location
        location_text = ""
        loc_m = re.search(r'"location_text"\s*:\s*{[^}]*?"text"\s*:\s*"([^"]*)"', window)
        if loc_m:
            location_text = _decode_json_str(loc_m.group(1))

        # Image URL (scontent CDN)
        image_url = ""
        img_m = re.search(r'"uri"\s*:\s*"(https:(?:\\\/|\/)[^"]*scontent[^"]*)"', window)
        if img_m:
            image_url = img_m.group(1).replace("\\/", "/")

        is_pending = bool(re.search(r'"is_pending"\s*:\s*true', window))

        seen_ids.add(lid)
        collected.append({
            "id":         lid,
            "title":      title,
            "price_str":  price_str,
            "location":   location_text,
            "subtitle":   " · ".join(subtitles),
            "image_url":  image_url,
            "is_pending": is_pending,
            "url":        f"https://www.facebook.com/marketplace/item/{lid}/",
        })


# ── Shared helpers ────────────────────────────────────────────────────────────

def _decode_json_str(s: str) -> str:
    """Properly decode a raw JSON string value (unicode escapes, etc.)."""
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s


def _extract_balanced_json(text: str, start: int, max_length: int = 100_000) -> Optional[str]:
    """
    Extract a complete JSON object/array from `text` starting at `start`.
    Uses balanced brace matching with correct string literal handling.
    """
    if start >= len(text) or text[start] not in ('{', '['):
        return None

    opener = text[start]
    closer = '}' if opener == '{' else ']'
    depth = 0
    in_string = False
    i = start
    end = min(start + max_length, len(text))

    while i < end:
        c = text[i]
        if in_string:
            if c == '\\':
                i += 2  # skip escaped char
                continue
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1

    return None


def _convert_cookies(fb_cookies: list) -> list:
    """Convert FB cookie export format to Playwright format."""
    out = []
    for c in fb_cookies:
        if not c.get("name") or not c.get("value"):
            continue
        cookie = {
            "name":   c["name"],
            "value":  c["value"],
            "domain": c.get("domain", ".facebook.com"),
            "path":   c.get("path", "/"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp:
            cookie["expires"] = int(exp)
        out.append(cookie)
    return out


def _parse_year(subtitle: str) -> Optional[int]:
    """Extract 4-digit year from subtitle like '2018 · 135,000 mi'."""
    m = re.search(r'\b(19[89]\d|20[012]\d)\b', subtitle)
    return int(m.group(1)) if m else None


def _parse_mileage(subtitle: str) -> Optional[int]:
    """Extract mileage from subtitle like '2018 · 135,000 mi' or '45K mi'."""
    m = re.search(r'([\d,]+)\s*[Kk]\s*(?:mi|miles)', subtitle)
    if m:
        return int(m.group(1).replace(",", "")) * 1000
    m = re.search(r'([\d,]+)\s*(?:mi|miles)', subtitle)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _parse_price(price_str: str) -> Optional[int]:
    """Convert '$28,500' or '28500' to int."""
    clean = re.sub(r"[^\d]", "", str(price_str))
    return int(clean) if clean else None
