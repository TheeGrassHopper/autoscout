"""
pricing/carvana.py
Fetches real-market pricing from Carvana's internal API.

Strategy:
  Load the Carvana SRP (search results page) with Playwright, then intercept
  the `merch/search/api/v2/pricing` response that fires automatically.
  That endpoint returns both `kbbValue` and `incentivizedPrice` for every
  comparable vehicle shown — no scraping of HTML needed.

Returns:
  (carvana_price, kbb_value) tuple — both are medians across comparable listings.
"""

import logging
import statistics
import hashlib
import json
import os
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

CACHE_DIR = "output/.carvana_cache"


def get_carvana_price(
    make: str,
    model: str,
    year: int,
    mileage: int,
    year_range: int = 2,
    mileage_range: int = 20_000,
) -> tuple[Optional[int], Optional[int]]:
    """
    Returns (carvana_price, kbb_value) — medians across comparable Carvana listings.
    Both may be None if Carvana has no comparable inventory.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = _cache_key(make, model, year, mileage)
    cached = _load_cache(cache_key)
    if cached is not None:
        logger.debug(f"Carvana cache hit: {year} {make} {model}")
        return cached.get("carvana_price"), cached.get("kbb_value")

    result = _fetch_from_carvana(make, model, year, mileage, year_range, mileage_range)
    _save_cache(cache_key, {"carvana_price": result[0], "kbb_value": result[1]})
    return result


def _fetch_from_carvana(
    make: str,
    model: str,
    year: int,
    mileage: int,
    year_range: int,
    mileage_range: int,
) -> tuple[Optional[int], Optional[int]]:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("Playwright not installed; skipping Carvana pricing")
        return None, None

    make_slug = make.lower().replace(" ", "-")
    model_slug = model.lower().split()[0].replace(" ", "-")  # base model only

    params = urlencode({
        "year-min": year - year_range,
        "year-max": year + year_range,
        "miles-max": mileage + mileage_range,
    })
    url = f"https://www.carvana.com/cars/{make_slug}-{model_slug}?{params}"
    logger.debug(f"Carvana search: {url}")

    pricing_data: dict = {}
    vehicles_raw: list = []

    def on_response(response):
        if "search/api/v2/pricing" in response.url:
            try:
                pricing_data.update(response.json())
            except Exception:
                pass
        elif "search/api/v2" in response.url and "pricing" not in response.url:
            # Vehicle listings endpoint — contains year, mileage, vehicleId
            try:
                data = response.json()
                if isinstance(data, dict):
                    for key in ("vehicles", "results", "data", "items"):
                        if isinstance(data.get(key), list):
                            vehicles_raw.extend(data[key])
                            break
            except Exception:
                pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Wait up to 10s for the pricing API call to fire
                page.wait_for_timeout(8_000)
            except PWTimeout:
                logger.debug(f"Carvana page timeout for {year} {make} {model}")
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"Carvana Playwright error for {year} {make} {model}: {e}")
        return None, None

    # Build vehicle metadata map: vehicle_id -> {year, mileage}
    vehicle_meta: dict = {}
    for v in vehicles_raw:
        vid = str(v.get("vehicleId") or v.get("id") or "")
        if vid:
            vehicle_meta[vid] = {
                "year":    v.get("year"),
                "mileage": v.get("mileage") or v.get("miles"),
            }

    # pricing_data is keyed by vehiclePaymentTermsMapping → vehicle_id → {...}
    vehicle_map = pricing_data.get("vehiclePaymentTermsMapping", {})
    if not vehicle_map:
        logger.debug(f"Carvana: no pricing data returned for {year} {make} {model}")
        return None, None

    carvana_prices = []
    kbb_values = []
    skipped = 0
    for vid, info in vehicle_map.items():
        # Post-process filter: apply year ±range and mileage ≤ listing+range
        # Only filter if we have vehicle metadata (graceful fallback if API changes)
        if vehicle_meta:
            meta = vehicle_meta.get(str(vid), {})
            v_year    = meta.get("year")
            v_mileage = meta.get("mileage")
            if v_year and year and abs(int(v_year) - year) > year_range:
                skipped += 1
                continue
            if v_mileage and mileage and int(v_mileage) > mileage + mileage_range:
                skipped += 1
                continue

        cp = info.get("incentivizedPrice")
        kv = info.get("kbbValue")
        if cp and 3_000 < cp < 300_000:
            carvana_prices.append(int(cp))
        if kv and 3_000 < kv < 300_000:
            kbb_values.append(int(kv))

    # If filtering removed everything, return None rather than an inflated average
    if not carvana_prices:
        logger.debug(
            f"Carvana {year} {make} {model}: no comparables after year/mileage filter "
            f"(skipped {skipped}/{len(vehicle_map)})"
        )
        return None, None

    carvana_median = int(statistics.median(carvana_prices)) if carvana_prices else None
    kbb_median = int(statistics.median(kbb_values)) if kbb_values else None

    logger.info(
        f"Carvana {year} {make} {model}: "
        f"carvana=${carvana_median:,} kbb=${kbb_median:,} "
        f"({len(carvana_prices)} filtered comps, {skipped} skipped)"
    )
    return carvana_median, kbb_median


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_key(make, model, year, mileage) -> str:
    mileage_bucket = round(mileage / 10_000) * 10_000
    base_model = model.lower().split()[0]
    raw = f"{year}-{make.lower()}-{base_model}-{mileage_bucket}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache(key: str) -> Optional[dict]:
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_cache(key: str, data: dict):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Carvana cache write failed: {e}")
