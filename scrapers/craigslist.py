"""
scrapers/craigslist.py
Scrapes vehicle listings from Craigslist using RSS feeds and HTML parsing.

Craigslist RSS URL format:
  https://{city}.craigslist.org/search/{category}/rss?{params}

Categories:
  cta = cars+trucks (all)
  ctd = cars by dealer
  cto = cars by owner  ← best for deals
  trd = trucks by dealer
  tro = trucks by owner
"""

import feedparser
import requests
import time
import logging
import re
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class RawListing:
    """Raw listing data before AI normalization."""
    source: str = "craigslist"
    listing_id: str = ""
    url: str = ""
    title: str = ""
    price: Optional[int] = None
    location: str = ""
    posted_date: str = ""
    description: str = ""
    image_urls: list = field(default_factory=list)

    # Parsed fields (best-effort from title/description)
    year: Optional[int] = None
    make: str = ""
    model: str = ""
    mileage: Optional[int] = None
    transmission: str = ""
    condition: str = ""
    title_status: str = ""   # clean, salvage, rebuilt, etc.

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Craigslist RSS Scraper ────────────────────────────────────────────────────

class CraigslistScraper:
    """
    Scrapes Craigslist vehicle listings via RSS + detail page parsing.

    Usage:
        scraper = CraigslistScraper(city="phoenix", config=FILTERS)
        listings = scraper.scrape()
    """

    BASE_URL = "https://{city}.craigslist.org"

    # Craigslist vehicle RSS categories to search
    CATEGORIES = {
        "cars":   ["cto", "ctd"],   # cars by owner + dealer
        "trucks": ["tro", "trd"],   # trucks by owner + dealer
        "suvs":   ["cto", "ctd"],   # SUVs listed under cars/trucks
    }

    # Minimum delay between requests (seconds) — be respectful!
    REQUEST_DELAY = 1.5

    def __init__(self, city: str, config: dict, vehicle_types: list = None):
        self.city = city.lower()
        self.config = config
        self.vehicle_types = vehicle_types or ["cars", "trucks"]
        self.base = self.BASE_URL.format(city=self.city)
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })
        return s

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape(self, query: str = "") -> list[RawListing]:
        """
        Run the full scrape. Returns a list of RawListing objects.
        Deduplicates by listing ID.
        """
        seen_ids = set()
        all_listings = []

        categories = self._get_categories()
        logger.info(f"Scraping Craigslist {self.city} — {len(categories)} category feeds")

        for category in categories:
            rss_url = self._build_rss_url(category, query)
            listings = self._scrape_rss_feed(rss_url)

            for listing in listings:
                if listing.listing_id not in seen_ids:
                    seen_ids.add(listing.listing_id)
                    all_listings.append(listing)

            time.sleep(self.REQUEST_DELAY)

        logger.info(f"Collected {len(all_listings)} unique raw listings from Craigslist")

        # Filter by basic price/year before doing expensive detail fetches
        filtered = self._pre_filter(all_listings)
        logger.info(f"{len(filtered)} listings pass pre-filter (price/year range)")

        # Fetch detail pages for filtered listings to get mileage + images
        enriched = self._enrich_listings(filtered)

        return enriched

    # ── RSS Feed Parsing ──────────────────────────────────────────────────────

    def _build_rss_url(self, category: str, query: str = "") -> str:
        params = []
        if query:
            params.append(f"query={requests.utils.quote(query)}")
        if self.config.get("min_price"):
            params.append(f"min_price={self.config['min_price']}")
        if self.config.get("max_price"):
            params.append(f"max_price={self.config['max_price']}")
        if self.config.get("min_year"):
            params.append(f"min_auto_year={self.config['min_year']}")
        if self.config.get("max_year"):
            params.append(f"max_auto_year={self.config['max_year']}")

        # Owner-only listings tend to have better deals
        params.append("srchType=T")     # title search
        params.append("hasPic=1")       # listings with photos only

        query_str = "&".join(params)
        return f"{self.base}/search/{category}/rss?{query_str}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _scrape_rss_feed(self, url: str) -> list[RawListing]:
        """Parse a Craigslist RSS feed and return RawListings."""
        logger.debug(f"Fetching RSS: {url}")

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.error(f"RSS parse error: {e}")
            return []

        listings = []
        for entry in feed.entries:
            try:
                listing = self._parse_rss_entry(entry)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"Error parsing RSS entry: {e}")
                continue

        logger.debug(f"  → {len(listings)} listings from {url}")
        return listings

    def _parse_rss_entry(self, entry) -> Optional[RawListing]:
        """Extract a RawListing from a single RSS feed entry."""
        url = entry.get("link", "")
        if not url:
            return None

        # Extract listing ID from URL
        # Example: https://phoenix.craigslist.org/cto/d/tacoma/7654321234.html
        listing_id_match = re.search(r'/(\d{8,13})\.html', url)
        listing_id = listing_id_match.group(1) if listing_id_match else url

        title = entry.get("title", "").strip()
        price = self._parse_price(title)

        # Location is often in the title like "2019 Tacoma (Scottsdale)"
        location_match = re.search(r'\(([^)]+)\)', title)
        location = location_match.group(1) if location_match else ""

        # Clean title — remove price and location
        clean_title = re.sub(r'\$[\d,]+', '', title)
        clean_title = re.sub(r'\([^)]*\)', '', clean_title).strip()

        description = BeautifulSoup(
            entry.get("summary", ""), "lxml"
        ).get_text(separator=" ").strip()

        posted = entry.get("published", "")

        listing = RawListing(
            listing_id=listing_id,
            url=url,
            title=clean_title,
            price=price,
            location=location,
            posted_date=posted,
            description=description[:500],
        )

        # Best-effort parsing from title
        self._parse_title_fields(listing, clean_title)

        return listing

    # ── Detail Page Enrichment ────────────────────────────────────────────────

    def _enrich_listings(self, listings: list[RawListing]) -> list[RawListing]:
        """Fetch detail pages to extract mileage, images, and full description."""
        enriched = []
        total = len(listings)

        for i, listing in enumerate(listings, 1):
            logger.info(f"  Fetching detail {i}/{total}: {listing.title[:50]}")
            try:
                self._fetch_detail_page(listing)
            except Exception as e:
                logger.warning(f"  Detail fetch failed for {listing.listing_id}: {e}")

            enriched.append(listing)
            time.sleep(self.REQUEST_DELAY)

        return enriched

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    def _fetch_detail_page(self, listing: RawListing):
        """Fetch and parse a Craigslist listing detail page."""
        resp = self.session.get(listing.url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # ── Mileage ──
        # Look in the attributes table
        attrgroup = soup.find("div", class_="attrgroup")
        if attrgroup:
            for span in attrgroup.find_all("span"):
                text = span.get_text()
                miles_match = re.search(r'([\d,]+)\s*miles?', text, re.IGNORECASE)
                if miles_match and not listing.mileage:
                    listing.mileage = int(miles_match.group(1).replace(",", ""))

                # Transmission
                if re.search(r'\bautomatic\b', text, re.IGNORECASE):
                    listing.transmission = "automatic"
                elif re.search(r'\bmanual\b', text, re.IGNORECASE):
                    listing.transmission = "manual"

                # Title status
                title_match = re.search(
                    r'(clean|salvage|rebuilt|lien|missing)\s+title', text, re.IGNORECASE
                )
                if title_match:
                    listing.title_status = title_match.group(1).lower()

        # ── Mileage from description as fallback ──
        if not listing.mileage:
            body = soup.find("section", id="postingbody")
            if body:
                full_desc = body.get_text()
                listing.description = full_desc[:800]
                miles_match = re.search(r'([\d,]+)\s*(?:k\s*)?miles?', full_desc, re.IGNORECASE)
                if miles_match:
                    raw = miles_match.group(1).replace(",", "")
                    val = int(raw)
                    # Handle "90k miles"
                    if val < 1000 and "k" in miles_match.group(0).lower():
                        val *= 1000
                    listing.mileage = val

        # ── Images ──
        imgs = soup.find_all("img", class_=lambda c: c and "gallery" in c.lower())
        if not imgs:
            imgs = soup.select(".gallery-inner img, #thumbs img, img.thumb")
        listing.image_urls = [
            img.get("src", "") for img in imgs[:6] if img.get("src")
        ]

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_categories(self) -> list[str]:
        """Get unique Craigslist category codes based on configured vehicle types."""
        cats = set()
        for vtype in self.vehicle_types:
            for cat in self.CATEGORIES.get(vtype, ["cto"]):
                cats.add(cat)
        return list(cats)

    def _pre_filter(self, listings: list[RawListing]) -> list[RawListing]:
        """Quick filter before expensive detail page fetches."""
        filtered = []
        for l in listings:
            # Must have a price
            if not l.price:
                continue
            if l.price < self.config.get("min_price", 0):
                continue
            if l.price > self.config.get("max_price", 999999):
                continue
            # Year filter if parseable from title
            if l.year:
                if l.year < self.config.get("min_year", 1900):
                    continue
                if l.year > self.config.get("max_year", 2100):
                    continue
            # Skip salvage titles
            if self.config.get("exclude_salvage") and l.title_status == "salvage":
                continue
            filtered.append(l)
        return filtered

    def _parse_price(self, text: str) -> Optional[int]:
        """Extract a dollar price from text."""
        match = re.search(r'\$\s*([\d,]+)', text)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _parse_title_fields(self, listing: RawListing, title: str):
        """
        Best-effort extraction of year / make / model from listing title.
        Example: "2019 Toyota Tacoma TRD Off-Road 4x4"
        """
        # Year (4-digit, 2000–2030)
        year_match = re.search(r'\b(20[0-2]\d)\b', title)
        if year_match:
            listing.year = int(year_match.group(1))

        # Known makes (extend this list as needed)
        makes = [
            "Toyota", "Ford", "Chevrolet", "Chevy", "Honda", "Nissan", "RAM", "Ram",
            "Dodge", "Jeep", "GMC", "Subaru", "Hyundai", "Kia", "Mazda", "Volkswagen",
            "VW", "BMW", "Mercedes", "Audi", "Lexus", "Acura", "Infiniti", "Cadillac",
            "Buick", "Lincoln", "Volvo", "Tesla", "Mitsubishi", "Chrysler",
        ]
        for make in makes:
            if re.search(rf'\b{re.escape(make)}\b', title, re.IGNORECASE):
                listing.make = make.title()
                # Model = words after make until end / trim level
                make_pos = title.lower().find(make.lower())
                after_make = title[make_pos + len(make):].strip()
                model_match = re.match(r'([\w-]+(?:\s+[\w-]+)?)', after_make)
                if model_match:
                    listing.model = model_match.group(1).strip()
                break
