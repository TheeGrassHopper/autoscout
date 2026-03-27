"""
utils/comps.py
Market comps engine — builds a comparable price database for each vehicle.

For each unique (make, model) found in the pipeline:
  - Pre-loads ALL listings already scraped (Craigslist + Facebook from main run)
  - Additionally scrapes Craigslist NATIONALLY (no city subdomain) for deeper coverage
  - Facebook is already at 500mi max — main-run data is reused as FB comps

When scoring a specific listing, filters the comp pool to:
  - Year ± DEFAULT_YEAR_RANGE    (default ±2, e.g. 2020 → 2018–2022 comps)
  - Mileage ± DEFAULT_MILEAGE_RANGE  (default ±15k miles)

Performance:
  - 24h disk cache per (make, model) — repeat runs skip the network entirely
  - Parallel Playwright workers (_PARALLEL_WORKERS) for first-run fetches

Returns the median asking price of matching comps.
"""

import json
import logging
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

CL_NATIONAL_BASE = "https://www.craigslist.org"
MAX_COMPS_PER_VEHICLE = 80   # cap per vehicle to keep scrape fast
_COMPS_CACHE_DIR = "output/.comps_cache"
_COMPS_CACHE_TTL = 86400      # 24 hours
_PARALLEL_WORKERS = 4         # concurrent Playwright browser instances

# Filter windows applied when scoring a specific listing against the comp pool.
# Wider = more comps (better median), less precise to the exact spec.
DEFAULT_YEAR_RANGE    = 2        # ±2 years   (was ±1)
DEFAULT_MILEAGE_RANGE = 15_000   # ±15k miles (was ±10k)


# ── Disk cache helpers ────────────────────────────────────────────────────────

def _cache_path(make: str, model: str) -> str:
    os.makedirs(_COMPS_CACHE_DIR, exist_ok=True)
    key = f"{make.lower()}_{model.lower()}".replace(" ", "_").replace("/", "-")
    return os.path.join(_COMPS_CACHE_DIR, f"{key}.json")


def _load_cache(make: str, model: str) -> Optional[list]:
    path = _cache_path(make, model)
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > _COMPS_CACHE_TTL:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(make: str, model: str, comps: list):
    try:
        with open(_cache_path(make, model), "w") as f:
            json.dump(comps, f)
    except Exception:
        pass


# ── Engine ────────────────────────────────────────────────────────────────────

class CompsEngine:
    """
    Holds a comp price pool per (make, model).
    Each entry: [year: int|None, mileage: int|None, price: int]
    """

    def __init__(self, raw_listings: list):
        # Pool: (make.lower(), model.lower()) -> [[year, mileage, price], ...]
        self._cache: dict[tuple, list] = {}
        self._preload(raw_listings)

    def _preload(self, raw_listings: list):
        """Seed comp pool from listings already scraped in the main run."""
        count = 0
        for l in raw_listings:
            if l.make and l.model and l.price:
                key = (l.make.lower(), l.model.lower())
                if key not in self._cache:
                    self._cache[key] = []
                self._cache[key].append([l.year, l.mileage, l.price])
                count += 1
        logger.info(f"Comps: pre-loaded {count} listings from main scrape into comp pool")

    def fetch_all_comps(self, unique_vehicles: set[tuple], max_seconds: int = 600):
        """
        Fetch national Craigslist comps for all unique (make, model) pairs.

        - Hits a 24h disk cache first — skips network entirely for cached vehicles.
        - Remaining vehicles fetched in parallel (_PARALLEL_WORKERS at a time).
        - Hard time cap via max_seconds.
        """
        if not unique_vehicles:
            return

        # Split into cache hits vs needs network fetch
        needs_fetch = []
        cache_hits = 0
        for make, model in unique_vehicles:
            cached = _load_cache(make, model)
            if cached is not None:
                key = (make.lower(), model.lower())
                if key not in self._cache:
                    self._cache[key] = []
                self._cache[key].extend(cached)
                cache_hits += 1
            else:
                needs_fetch.append((make, model))

        if cache_hits:
            logger.info(
                f"Comps: {cache_hits}/{len(unique_vehicles)} vehicle type(s) loaded from 24h cache"
            )

        if not needs_fetch:
            return

        logger.info(
            f"Comps: fetching {len(needs_fetch)} vehicle type(s) from national CL "
            f"({_PARALLEL_WORKERS} parallel workers, max {max_seconds}s)…"
        )
        deadline = time.time() + max_seconds

        def fetch_one(make_model):
            make, model = make_model
            if time.time() > deadline:
                return make, model, []
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        )
                    )
                    comps = _scrape_cl_national(context, make, model)
                    browser.close()
                return make, model, comps
            except Exception as e:
                logger.warning(f"Comps: fetch failed for {make} {model}: {e}")
                return make, model, []

        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
            futures = {pool.submit(fetch_one, pair): pair for pair in needs_fetch}
            for future in as_completed(futures):
                make, model, comps = future.result()
                key = (make.lower(), model.lower())
                if key not in self._cache:
                    self._cache[key] = []
                self._cache[key].extend(comps)
                _save_cache(make, model, comps)
                logger.info(
                    f"Comps: {make} {model} — {len(comps)} national CL comps "
                    f"({len(self._cache[key])} total in pool)"
                )

    def get_market_price(
        self,
        make: str,
        model: str,
        year: Optional[int],
        mileage: Optional[int],
        year_range: int = DEFAULT_YEAR_RANGE,
        mileage_range: int = DEFAULT_MILEAGE_RANGE,
    ) -> Optional[int]:
        """
        Return median comp price filtered to year ±year_range and mileage ±mileage_range.
        Falls back progressively if not enough comps pass the strict filter.
        """
        key = (make.lower(), model.lower())
        pool = self._cache.get(key, [])
        if not pool:
            return None

        filtered = []
        for entry in pool:
            comp_year, comp_mileage, price = entry[0], entry[1], entry[2]
            # Year gate: only apply when both are known
            if year and comp_year and abs(comp_year - year) > year_range:
                continue
            # Mileage gate: only apply when both are known
            if mileage and comp_mileage and abs(comp_mileage - mileage) > mileage_range:
                continue
            filtered.append(price)

        if len(filtered) >= 2:
            return int(statistics.median(filtered))
        if len(filtered) == 1:
            return filtered[0]

        # Fallback: relax mileage gate only
        relaxed = []
        for entry in pool:
            comp_year, comp_mileage, price = entry[0], entry[1], entry[2]
            if year and comp_year and abs(comp_year - year) > year_range:
                continue
            relaxed.append(price)

        if len(relaxed) >= 2:
            logger.debug(
                f"Comps: relaxed mileage filter for {make} {model} "
                f"— {len(relaxed)} year-matched comps"
            )
            return int(statistics.median(relaxed))

        # Last resort: all comps for make/model regardless of year/mileage
        all_prices = [e[2] for e in pool]
        if len(all_prices) >= 2:
            logger.debug(
                f"Comps: no year/mileage matches for {make} {model} — using full pool median"
            )
            return int(statistics.median(all_prices))

        return None


# ── Internal scraper ──────────────────────────────────────────────────────────

def _scrape_cl_national(context, make: str, model: str) -> list:
    """
    Scrape the national Craigslist search (no city subdomain) for a make/model.
    Card-only — does NOT visit detail pages (fast).
    Returns list of [year, mileage, price] entries.
    """
    results = []
    params = {"query": f"{make} {model}", "auto_title": "clean", "hasPic": "1"}
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
                results.append([year, mileage, price])
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
