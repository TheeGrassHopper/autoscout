"""
utils/comps.py
Market comps engine — builds a comparable price database for each vehicle.

For each unique (make, model) found in the pipeline:
  - Pre-loads ALL listings already scraped (Craigslist + Facebook from main run)
  - Additionally scrapes Craigslist NATIONALLY (no city subdomain) for deeper coverage
  - Facebook is already at 500mi max — main-run data is reused as FB comps

When scoring a specific listing, filters the comp pool to:
  - Year ± 1  (e.g., 2021/2022/2023 for a 2022 vehicle)
  - Mileage ± 10,000 miles

Returns the median asking price of matching comps.
"""

import logging
import re
import statistics
import time
from typing import Optional
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

CL_NATIONAL_BASE = "https://www.craigslist.org"
MAX_COMPS_PER_VEHICLE = 80   # cap per vehicle to keep scrape fast


class CompsEngine:
    """
    Holds a comp price pool per (make, model).
    Each entry: (year: int|None, mileage: int|None, price: int)
    """

    def __init__(self, raw_listings: list):
        # Cache: (make.lower(), model.lower()) -> [(year, mileage, price), ...]
        self._cache: dict[tuple, list] = {}
        self._preload(raw_listings)

    def _preload(self, raw_listings: list):
        """Seed comp cache from listings already scraped in the main run."""
        count = 0
        for l in raw_listings:
            if l.make and l.model and l.price:
                key = (l.make.lower(), l.model.lower())
                if key not in self._cache:
                    self._cache[key] = []
                self._cache[key].append((l.year, l.mileage, l.price))
                count += 1
        logger.info(f"Comps: pre-loaded {count} listings from main scrape into comp cache")

    def fetch_all_comps(self, unique_vehicles: set[tuple], max_seconds: int = 60):
        """
        Open ONE Playwright browser and scrape national Craigslist for
        every unique (make, model) pair. Stops after max_seconds total to
        avoid blocking the pipeline indefinitely.
        """
        if not unique_vehicles:
            return

        logger.info(f"Comps: fetching national CL comps for {len(unique_vehicles)} vehicle type(s) (max {max_seconds}s)…")
        deadline = time.time() + max_seconds

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            for make, model in unique_vehicles:
                if time.time() > deadline:
                    logger.info(f"Comps: time limit reached — skipping remaining vehicles")
                    break
                try:
                    comps = self._scrape_cl_national(context, make, model)
                    key = (make.lower(), model.lower())
                    if key not in self._cache:
                        self._cache[key] = []
                    self._cache[key].extend(comps)
                    logger.info(
                        f"Comps: {make} {model} — {len(comps)} national CL comps "
                        f"({len(self._cache[key])} total in pool)"
                    )
                except Exception as e:
                    logger.warning(f"Comps: failed for {make} {model}: {e}")
            browser.close()

    def get_market_price(
        self,
        make: str,
        model: str,
        year: Optional[int],
        mileage: Optional[int],
    ) -> Optional[int]:
        """
        Return median comp price filtered to year ±1 and mileage ±10k.
        Falls back to all comps for the make/model if nothing passes filters.
        """
        key = (make.lower(), model.lower())
        pool = self._cache.get(key, [])
        if not pool:
            return None

        filtered = []
        for (comp_year, comp_mileage, price) in pool:
            # Year gate: skip only if BOTH years are known and differ by more than 1
            if year and comp_year and abs(comp_year - year) > 1:
                continue
            # Mileage gate: skip only if BOTH are known and differ by more than 10k
            if mileage and comp_mileage and abs(comp_mileage - mileage) > 10_000:
                continue
            filtered.append(price)

        if len(filtered) >= 2:
            return int(statistics.median(filtered))
        if len(filtered) == 1:
            return filtered[0]

        # Fallback: relaxed — use all comps for this make/model
        all_prices = [p for (_, _, p) in pool]
        if len(all_prices) >= 2:
            logger.debug(f"Comps: no year/mileage matches for {make} {model} — using full pool median")
            return int(statistics.median(all_prices))
        return None

    # ── Internal scrapers ──────────────────────────────────────────────────────

    def _scrape_cl_national(self, context, make: str, model: str) -> list:
        """
        Scrape the national Craigslist search (no city subdomain) for a
        make/model. Card-only — does NOT visit detail pages (fast).
        Returns list of (year, mileage, price) tuples.
        """
        results = []
        params = {
            "query": f"{make} {model}",
            "auto_title": "clean",
            "hasPic": "1",
        }
        url = f"{CL_NATIONAL_BASE}/search/cto?{urlencode(params)}"

        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            try:
                page.wait_for_selector("[data-pid]", timeout=8_000)
            except PWTimeout:
                logger.debug(f"Comps: no CL national results for {make} {model}")
                return results

            cards = page.locator("[data-pid]")
            total = min(cards.count(), MAX_COMPS_PER_VEHICLE)

            for i in range(total):
                try:
                    card = cards.nth(i)

                    price_el = card.locator(".price, .priceinfo")
                    if not price_el.count():
                        continue
                    price = _parse_price(price_el.first.inner_text())
                    if not price or price < 500:
                        continue

                    title = ""
                    label = card.locator(".label")
                    if label.count():
                        title = label.first.inner_text().strip()
                    year = _parse_year(title)

                    mileage = None
                    meta = card.locator(".meta")
                    if meta.count():
                        mileage = _parse_mileage(meta.first.inner_text())

                    results.append((year, mileage, price))
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"Comps: CL national page error for {make} {model}: {e}")
        finally:
            page.close()

        return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_price(text: str) -> Optional[int]:
    m = re.search(r"\$\s*([\d,]+)", text)
    return int(m.group(1).replace(",", "")) if m else None


def _parse_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20[0-2]\d|19[89]\d)\b", text)
    return int(m.group(1)) if m else None


def _parse_mileage(text: str) -> Optional[int]:
    m = re.search(r"([\d,]+)\s*(k)?\s*mi\b", text, re.IGNORECASE)
    if not m:
        return None
    val = int(m.group(1).replace(",", ""))
    return val * 1000 if m.group(2) else val
