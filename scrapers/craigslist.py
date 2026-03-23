"""
scrapers/craigslist.py
Scrapes Craigslist vehicle listings using Playwright (headless Chromium).

Craigslist migrated to a fully JS-rendered SPA in 2024 — the old RSS feeds
now return empty HTML shells. Playwright renders the page fully before
we extract listings.

Selectors confirmed against live phoenix.craigslist.org (2025):
  [data-pid]           — each listing card
  .label               — listing title
  .price / .priceinfo  — asking price
  .meta                — mileage + location + date text
  .result-location     — neighborhood
  .result-posted-date  — listing age
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# VIN pattern: 17 chars, no I/O/Q, must contain both letters and digits
_VIN_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')

def _extract_vin(text: str) -> str:
    """Extract a valid-looking VIN from free text. Returns first match or empty string."""
    if not text:
        return ""
    for m in _VIN_RE.finditer(text.upper()):
        candidate = m.group(1)
        # Must have at least one letter and one digit (filters out all-digit sequences)
        if re.search(r'[A-HJ-NPR-Z]', candidate) and re.search(r'[0-9]', candidate):
            return candidate
    return ""


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class RawListing:
    source: str = "craigslist"
    listing_id: str = ""
    url: str = ""
    title: str = ""
    price: Optional[int] = None
    location: str = ""
    posted_date: str = ""
    description: str = ""
    image_urls: list = field(default_factory=list)
    year: Optional[int] = None
    make: str = ""
    model: str = ""
    mileage: Optional[int] = None
    transmission: str = ""
    condition: str = ""
    title_status: str = ""
    color: str = ""
    vin: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Scraper ───────────────────────────────────────────────────────────────────

class CraigslistScraper:
    BASE = "https://{city}.craigslist.org"
    CATEGORIES = ["cto"]   # by-owner only

    def __init__(self, city: str, config: dict, vehicle_types: list = None):
        self.city = city.lower()
        self.config = config
        self.base = self.BASE.format(city=self.city)

    def scrape(self, query: str = "") -> list[RawListing]:
        all_listings: list[RawListing] = []
        seen_ids: set = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            for cat in self.CATEGORIES:
                url = self._build_url(cat, query)
                logger.info(f"Scraping Craigslist [{cat}]: {url}")
                try:
                    listings = self._scrape_page(context, url)
                    for l in listings:
                        if l.listing_id not in seen_ids:
                            seen_ids.add(l.listing_id)
                            all_listings.append(l)
                    logger.info(f"  {cat}: {len(listings)} listings found")
                except Exception as e:
                    logger.error(f"Craigslist [{cat}] failed: {e}")

            # Fetch detail pages to extract description + VIN
            logger.info(f"Fetching listing details for VIN/description extraction...")
            for listing in all_listings:
                if listing.url:
                    try:
                        self._fetch_detail(context, listing)
                    except Exception as e:
                        logger.debug(f"Detail fetch failed for {listing.listing_id}: {e}")

            browser.close()

        logger.info(f"Craigslist raw total: {len(all_listings)}")
        filtered = self._filter(all_listings)
        logger.info(f"Craigslist after filters: {len(filtered)}")
        return filtered

    def _scrape_page(self, context, url: str) -> list[RawListing]:
        page = context.new_page()
        results = []
        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
            try:
                page.wait_for_selector("[data-pid]", timeout=15_000)
            except PWTimeout:
                logger.warning(f"No listings rendered at {url}")
                return []

            cards = page.locator("[data-pid]")
            total = cards.count()
            logger.info(f"  {total} cards on page")

            for i in range(total):
                try:
                    listing = self._parse_card(cards.nth(i))
                    if listing:
                        results.append(listing)
                except Exception as e:
                    logger.debug(f"Card {i} parse error: {e}")
        finally:
            page.close()
        return results

    def _parse_card(self, card) -> Optional[RawListing]:
        pid = card.get_attribute("data-pid") or ""
        if not pid:
            return None

        link = card.locator("a.main").first
        url = link.get_attribute("href") if link.count() else ""
        if not url:
            return None

        title = ""
        label = card.locator(".label")
        if label.count():
            title = label.first.inner_text().strip()

        price = None
        price_el = card.locator(".price, .priceinfo")
        if price_el.count():
            price = self._parse_price(price_el.first.inner_text())

        mileage, location, posted_date = None, "", ""
        meta = card.locator(".meta")
        if meta.count():
            meta_text = meta.first.inner_text()
            mi = re.search(r"([\d,]+)\s*(k)?\s*mi\b", meta_text, re.IGNORECASE)
            if mi:
                val = int(mi.group(1).replace(",", ""))
                if mi.group(2):
                    val *= 1000
                mileage = val

        # Posted date — dedicated span inside .meta
        date_el = card.locator(".result-posted-date")
        if date_el.count():
            posted_date = date_el.first.inner_text().strip()

        loc_el = card.locator(".result-location")
        if loc_el.count():
            location = loc_el.first.inner_text().strip()

        images = [
            img.get_attribute("src")
            for img in card.locator("img").all()
            if img.get_attribute("src") and "craigslist.org" in (img.get_attribute("src") or "")
        ]

        listing = RawListing(
            listing_id=pid, url=url, title=title, price=price,
            mileage=mileage, location=location, posted_date=posted_date,
            image_urls=images[:6],
        )
        self._parse_title_fields(listing, title)
        self._parse_title_status(listing)
        return listing

    def _build_url(self, category: str, query: str = "") -> str:
        params: dict = {"hasPic": "1"}
        if query:
            params["query"] = query
        if self.config.get("min_price"):
            params["min_price"] = self.config["min_price"]
        if self.config.get("max_price"):
            params["max_price"] = self.config["max_price"]
        if self.config.get("min_year"):
            params["min_auto_year"] = self.config["min_year"]
        if self.config.get("max_year"):
            params["max_auto_year"] = self.config["max_year"]
        if self.config.get("max_mileage"):
            params["auto_miles_max"] = self.config["max_mileage"]
        if self.config.get("search_radius_miles"):
            params["search_distance"] = self.config["search_radius_miles"]
        if self.config.get("zip_code"):
            params["postal"] = self.config["zip_code"]
        # Always filter for clean title only
        params["auto_title"] = "clean"
        return f"{self.base}/search/{category}?{urlencode(params)}"

    def _filter(self, listings: list[RawListing]) -> list[RawListing]:
        out = []
        for l in listings:
            if not l.price:
                continue
            if l.price < self.config.get("min_price", 0):
                continue
            if l.price > self.config.get("max_price", 999_999):
                continue
            if l.year:
                if l.year < self.config.get("min_year", 1900):
                    continue
                if l.year > self.config.get("max_year", 2100):
                    continue
            if l.mileage and l.mileage > self.config.get("max_mileage", 999_999):
                continue
            if self.config.get("exclude_salvage") and l.title_status == "salvage":
                continue
            out.append(l)
        return out

    def _fetch_detail(self, context, listing: RawListing):
        """Visit the individual listing page to extract full description and VIN."""
        page = context.new_page()
        try:
            page.goto(listing.url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(1500)

            # Full description
            desc_el = page.locator("#postingbody, .posting-description, section.postingbody")
            if desc_el.count():
                listing.description = desc_el.first.inner_text().strip()[:1200]

            # Attribute table (title status, condition, etc.)
            for row in page.locator(".attrgroup span, p.attrgroup span").all():
                text = row.inner_text().strip().lower()
                if "title status" in text:
                    val = text.replace("title status:", "").strip()
                    if val:
                        listing.title_status = val
                elif "condition" in text:
                    listing.condition = text.replace("condition:", "").strip()

            # Re-run title status detection now that we have full description
            self._parse_title_status(listing)

            # Extract VIN from description
            vin = _extract_vin(listing.description)
            if vin:
                listing.vin = vin
                logger.debug(f"  VIN found: {vin} — {listing.title[:40]}")

        finally:
            page.close()

    def _parse_price(self, text: str) -> Optional[int]:
        m = re.search(r"\$\s*([\d,]+)", text)
        return int(m.group(1).replace(",", "")) if m else None

    def _parse_title_status(self, listing: RawListing):
        """Detect title status from the listing title and description."""
        text = f"{listing.title} {listing.description}".lower()
        if re.search(r"\bsalvage\b", text):
            listing.title_status = "salvage"
        elif re.search(r"\brebuilt\b", text):
            listing.title_status = "rebuilt"
        elif re.search(r"\bclean\s*title\b", text):
            listing.title_status = "clean"
        elif re.search(r"\blien\b", text):
            listing.title_status = "lien"
        elif re.search(r"\bmissing\s*title\b|no\s*title\b", text):
            listing.title_status = "missing"
        else:
            listing.title_status = "unknown"

    def _parse_title_fields(self, listing: RawListing, title: str):
        if not title:
            return
        m = re.search(r"\b(20[0-2]\d|19[89]\d)\b", title)
        if m:
            listing.year = int(m.group(1))

        MAKES = [
            "Chevrolet", "Volkswagen", "Mercedes-Benz", "Mercedes",
            "Toyota", "Nissan", "Subaru", "Hyundai", "Mazda", "Honda",
            "Mitsubishi", "Chrysler", "Cadillac", "Infiniti", "Lincoln",
            "Dodge", "Chevy", "Buick", "Acura", "Lexus", "Tesla",
            "Jeep", "Ford", "GMC", "RAM", "Ram", "BMW", "Audi",
            "Volvo", "Kia", "VW",
        ]
        for make in MAKES:
            if re.search(rf"\b{re.escape(make)}\b", title, re.IGNORECASE):
                listing.make = make.title()
                pos = title.lower().find(make.lower())
                after = title[pos + len(make):].strip()
                m2 = re.match(r"([\w-]+(?:\s+[\w-]+)?)", after)
                if m2:
                    listing.model = m2.group(1).strip()
                break
