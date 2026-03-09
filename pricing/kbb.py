"""
pricing/kbb.py
Fetches KBB (Kelley Blue Book) market value estimates.

KBB does not offer a free public API. This module uses two strategies:
  1. KBB's internal price widget endpoint (reverse-engineered, may break)
  2. Scraping the KBB website for the "Fair Market Range" values

Both methods include respectful rate limiting and caching to avoid hammering.

NOTE: For production use, consider licensed data from:
  - Market Check API (marketcheck.com) — has KBB-sourced pricing
  - VinAudit API — VIN-based market value
  - DataOne Software — industry-grade pricing API
"""

import requests
import re
import time
import json
import logging
import hashlib
import os
from typing import Optional
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PriceEstimate:
    source: str
    make: str
    model: str
    year: int
    mileage: int
    trade_in_low: Optional[int] = None
    trade_in_high: Optional[int] = None
    private_party_low: Optional[int] = None
    private_party_high: Optional[int] = None
    retail_low: Optional[int] = None
    retail_high: Optional[int] = None
    fair_market_value: Optional[int] = None  # midpoint we use for scoring
    confidence: str = "low"   # low / medium / high

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class KBBPricer:
    """
    Fetches KBB market value for a given vehicle.

    Usage:
        pricer = KBBPricer()
        estimate = pricer.get_price(year=2019, make="Toyota", model="Tacoma", mileage=58000)
        print(estimate.fair_market_value)  # e.g. 34200
    """

    BASE_URL = "https://www.kbb.com"
    REQUEST_DELAY = 2.0

    # Simple file-based cache to avoid re-fetching the same vehicle
    CACHE_DIR = "output/.price_cache"

    def __init__(self):
        self.session = self._build_session()
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.kbb.com/",
        })
        return s

    # ── Public API ────────────────────────────────────────────────────────────

    def get_price(
        self,
        year: int,
        make: str,
        model: str,
        mileage: int,
        zip_code: str = "85001",
    ) -> Optional[PriceEstimate]:
        """
        Main method: returns a PriceEstimate or None if lookup fails.
        Checks cache first, then tries KBB.
        """
        cache_key = self._cache_key(year, make, model, mileage)
        cached = self._load_cache(cache_key)
        if cached:
            logger.debug(f"Cache hit: {year} {make} {model}")
            return PriceEstimate(**cached)

        estimate = self._fetch_kbb(year, make, model, mileage, zip_code)

        if estimate:
            self._save_cache(cache_key, estimate.to_dict())

        time.sleep(self.REQUEST_DELAY)
        return estimate

    # ── KBB Scraping ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=3, max=10))
    def _fetch_kbb(
        self, year: int, make: str, model: str, mileage: int, zip_code: str
    ) -> Optional[PriceEstimate]:
        """
        Scrape KBB for private-party fair market value.

        KBB URL structure:
          https://www.kbb.com/{make}/{model}/{year}/
          e.g. https://www.kbb.com/toyota/tacoma/2019/
        """
        make_slug = make.lower().replace(" ", "-")
        model_slug = model.lower().replace(" ", "-")
        url = f"{self.BASE_URL}/{make_slug}/{model_slug}/{year}/"

        logger.debug(f"KBB fetch: {url}")

        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 404:
                # Try alternate model slug
                logger.warning(f"KBB 404 for {url}, trying fallback estimate")
                return self._fallback_estimate(year, make, model, mileage)

            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            return self._parse_kbb_page(soup, year, make, model, mileage)

        except requests.RequestException as e:
            logger.error(f"KBB request failed: {e}")
            return self._fallback_estimate(year, make, model, mileage)

    def _parse_kbb_page(
        self, soup: BeautifulSoup, year: int, make: str, model: str, mileage: int
    ) -> Optional[PriceEstimate]:
        """Extract price data from a parsed KBB page."""

        # KBB renders prices in JSON-LD or in data attributes
        # Strategy 1: Look for JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                price = self._extract_price_from_jsonld(data)
                if price:
                    ppv = price
                    return PriceEstimate(
                        source="kbb",
                        make=make, model=model, year=year, mileage=mileage,
                        private_party_low=int(ppv * 0.92),
                        private_party_high=int(ppv * 1.08),
                        fair_market_value=ppv,
                        confidence="medium",
                    )
            except (json.JSONDecodeError, TypeError):
                continue

        # Strategy 2: Find price text patterns on the page
        page_text = soup.get_text()
        price_matches = re.findall(r'\$\s*([\d,]+)', page_text)
        prices = [int(p.replace(",", "")) for p in price_matches if 2000 < int(p.replace(",", "")) < 200000]

        if prices:
            # Use median of reasonable prices found
            prices.sort()
            mid = prices[len(prices) // 2]
            # Adjust for mileage vs KBB's default
            adjusted = self._adjust_for_mileage(mid, mileage)
            return PriceEstimate(
                source="kbb",
                make=make, model=model, year=year, mileage=mileage,
                private_party_low=int(adjusted * 0.90),
                private_party_high=int(adjusted * 1.10),
                fair_market_value=adjusted,
                confidence="low",
            )

        return self._fallback_estimate(year, make, model, mileage)

    def _extract_price_from_jsonld(self, data: dict) -> Optional[int]:
        """Try to find a price in JSON-LD structured data."""
        if isinstance(data, list):
            for item in data:
                result = self._extract_price_from_jsonld(item)
                if result:
                    return result
        if isinstance(data, dict):
            for key in ["price", "lowPrice", "highPrice", "offerPrice"]:
                if key in data:
                    try:
                        val = int(str(data[key]).replace(",", "").replace("$", ""))
                        if 2000 < val < 200000:
                            return val
                    except (ValueError, TypeError):
                        pass
            for val in data.values():
                if isinstance(val, (dict, list)):
                    result = self._extract_price_from_jsonld(val)
                    if result:
                        return result
        return None

    # ── Fallback: Depreciation Model ─────────────────────────────────────────

    # Average new MSRP by category (rough approximations)
    BASE_PRICES = {
        ("toyota", "tacoma"): 38000,
        ("toyota", "camry"): 27000,
        ("toyota", "rav4"): 31000,
        ("ford", "f-150"): 42000,
        ("ford", "f150"): 42000,
        ("ford", "mustang"): 35000,
        ("honda", "civic"): 24000,
        ("honda", "cr-v"): 30000,
        ("honda", "accord"): 29000,
        ("chevrolet", "silverado"): 40000,
        ("jeep", "wrangler"): 35000,
        ("jeep", "grand cherokee"): 38000,
        ("ram", "1500"): 41000,
        ("nissan", "altima"): 25000,
        ("bmw", "3 series"): 45000,
        ("default", "sedan"): 26000,
        ("default", "truck"): 38000,
        ("default", "suv"): 32000,
        ("default", "default"): 28000,
    }

    def _fallback_estimate(self, year: int, make: str, model: str, mileage: int) -> PriceEstimate:
        """
        Estimate market value using a depreciation model when KBB scraping fails.
        Vehicles depreciate ~15-20% in year 1, then ~10-15% per year after.
        """
        import datetime
        current_year = datetime.date.today().year
        age = current_year - year

        # Find base price
        key = (make.lower(), model.lower().split()[0])
        base_msrp = self.BASE_PRICES.get(key, self.BASE_PRICES[("default", "default")])

        # Depreciation curve
        if age == 0:
            retention = 0.80
        elif age == 1:
            retention = 0.68
        elif age == 2:
            retention = 0.60
        elif age == 3:
            retention = 0.53
        elif age <= 5:
            retention = 0.50 - (age - 3) * 0.05
        else:
            retention = max(0.20, 0.40 - (age - 5) * 0.04)

        base_value = int(base_msrp * retention)
        adjusted = self._adjust_for_mileage(base_value, mileage)

        return PriceEstimate(
            source="kbb_estimate",
            make=make, model=model, year=year, mileage=mileage,
            private_party_low=int(adjusted * 0.88),
            private_party_high=int(adjusted * 1.12),
            fair_market_value=adjusted,
            confidence="low",
        )

    def _adjust_for_mileage(self, base_value: int, mileage: int) -> int:
        """
        Adjust price for mileage vs average (12,000 miles/year).
        Each 10k miles over average reduces value by ~2–4%.
        """
        import datetime
        # Use a flat average baseline of 50k for simplicity
        avg_mileage = 50000
        delta_10k = (mileage - avg_mileage) / 10000
        adjustment = 1.0 - (delta_10k * 0.025)  # 2.5% per 10k miles
        adjustment = max(0.60, min(1.20, adjustment))   # Cap at ±40%
        return int(base_value * adjustment)

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_key(self, year, make, model, mileage) -> str:
        # Round mileage to nearest 5k for cache grouping
        mileage_bucket = round(mileage / 5000) * 5000
        raw = f"{year}-{make.lower()}-{model.lower()}-{mileage_bucket}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _load_cache(self, key: str) -> Optional[dict]:
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, key: str, data: dict):
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
