"""
pricing/kbb_apify.py
Real KBB pricing via Apify's Kelley Blue Book scraper.

Uses the parseforge/kelley-blue-book-scraper Apify actor to fetch live KBB data.
Returns per-trim valuations; we take the median across trims for a given make/model/year.

Fields used:
  fppPrice              → KBB Fair Purchase Price (what buyers pay at dealers)
  fairMarketPriceAverage → KBB fair market average
  originalMSRP          → Original sticker price
  listPriceLow          → Lowest current listing price (trade-in proxy)
  listPriceHigh         → Highest current listing price

No VIN required — works with year + make + model only.
Uses your existing APIFY_API_TOKEN.

Pricing: free plan (up to 100 items/run, ~4-16 per vehicle) — no extra cost.
7-day disk cache per (make, model, year) so each vehicle is only fetched once/week.
"""

import json
import logging
import os
import statistics
import hashlib
import time
from typing import Optional
from pricing.kbb import PriceEstimate

logger = logging.getLogger(__name__)

_CACHE_DIR = "output/.price_cache"
_CACHE_TTL = 86400 * 7   # 7 days
_ACTOR_ID = "parseforge/kelley-blue-book-scraper"


def get_kbb_apify_price(
    make: str,
    model: str,
    year: int,
    mileage: int = 50000,
    apify_token: str = "",
) -> Optional[PriceEstimate]:
    """
    Fetch real KBB pricing via Apify for a make/model/year.

    Returns a PriceEstimate with:
      fair_market_value   = median fppPrice across all trims
      trade_in_low        = listPriceLow (lowest current asking — trade-in proxy)
      retail_high         = listPriceHigh (highest current asking)
      private_party_low   = fairMarketPriceLow (KBB fair market low)
      private_party_high  = fairMarketPriceHigh (KBB fair market high)
      confidence          = "high" (live KBB data)
      source              = "kbb_apify"

    Returns None if no token, missing fields, or API failure.
    """
    apify_token = apify_token or os.getenv("APIFY_API_TOKEN", "")
    if not apify_token:
        logger.debug("KBB/Apify: no APIFY_API_TOKEN — skipping")
        return None
    if not (make and model and year):
        logger.debug("KBB/Apify: missing make/model/year — skipping")
        return None

    # Normalize model to base name only (strip trim noise like "TRD", "SR5", "prerunner")
    # so "Tacoma TRD Off-Road" and "Tacoma SR5" both cache as "Tacoma"
    base_model = model.strip().split()[0]

    cache_key = _cache_key(make, base_model, year)
    cached = _load_cache(cache_key)
    if cached:
        logger.debug(f"KBB/Apify cache hit: {year} {make} {model}")
        return PriceEstimate(**cached)

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.warning("KBB/Apify: apify_client not installed — pip install apify-client")
        return None

    try:
        client = ApifyClient(apify_token)
        logger.info(f"KBB/Apify: fetching {year} {make} {base_model}…")

        run = client.actor(_ACTOR_ID).call(
            run_input={"vehicles": [{"year": year, "make": make, "model": base_model}]},
            timeout_secs=120,
        )

        if not run or run.get("status") != "SUCCEEDED":
            logger.warning(f"KBB/Apify: run failed for {year} {make} {base_model}: {run.get('status')}")
            return None

        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    except Exception as e:
        logger.warning(f"KBB/Apify: API error for {year} {make} {model}: {e}")
        return None

    if not items:
        logger.debug(f"KBB/Apify: no results for {year} {make} {model}")
        return None

    # Aggregate across all trims — median gives a fair middle-of-market value
    fpp_prices     = [i["fppPrice"]              for i in items if i.get("fppPrice")]
    fmv_avgs       = [i["fairMarketPriceAverage"] for i in items if i.get("fairMarketPriceAverage")]
    fmv_lows       = [i["fairMarketPriceLow"]     for i in items if i.get("fairMarketPriceLow")]
    fmv_highs      = [i["fairMarketPriceHigh"]    for i in items if i.get("fairMarketPriceHigh")]
    list_lows      = [i["listPriceLow"]           for i in items if i.get("listPriceLow")]
    list_highs     = [i["listPriceHigh"]          for i in items if i.get("listPriceHigh")]
    msrp_vals      = [i["originalMSRP"]           for i in items if i.get("originalMSRP")]

    if not fpp_prices and not fmv_avgs:
        logger.debug(f"KBB/Apify: no price fields for {year} {make} {model}")
        return None

    fair_market = int(statistics.median(fpp_prices or fmv_avgs))
    fmv_low     = int(statistics.median(fmv_lows))  if fmv_lows  else int(fair_market * 0.90)
    fmv_high    = int(statistics.median(fmv_highs)) if fmv_highs else int(fair_market * 1.10)
    list_low    = int(statistics.median(list_lows))  if list_lows  else fmv_low
    list_high   = int(statistics.median(list_highs)) if list_highs else fmv_high
    msrp        = int(statistics.median(msrp_vals))  if msrp_vals  else None

    # Adjust fair market for mileage vs the default KBB mileage assumption (~50k)
    fair_market = _adjust_for_mileage(fair_market, mileage)
    fmv_low     = _adjust_for_mileage(fmv_low, mileage)
    fmv_high    = _adjust_for_mileage(fmv_high, mileage)

    estimate = PriceEstimate(
        source="kbb_apify",
        make=make,
        model=model,
        year=year,
        mileage=mileage,
        trade_in_low=list_low,       # lowest current listing (trade-in proxy)
        retail_high=list_high,       # highest current listing
        private_party_low=fmv_low,   # KBB fair market low
        private_party_high=fmv_high, # KBB fair market high
        fair_market_value=fair_market,
        confidence="high",
    )
    if msrp:
        estimate.retail_high = msrp  # use MSRP as the ceiling reference

    _save_cache(cache_key, estimate.to_dict())
    logger.info(
        f"KBB/Apify: {year} {make} {model} → ${fair_market:,} "
        f"(range ${fmv_low:,}–${fmv_high:,}, {len(items)} trims)"
    )
    return estimate


def _adjust_for_mileage(base: int, mileage: int) -> int:
    """Adjust KBB price (based on ~50k average) for actual mileage."""
    avg_mileage = 50_000
    delta_10k = (mileage - avg_mileage) / 10_000
    factor = max(0.65, min(1.15, 1.0 - delta_10k * 0.025))
    return int(base * factor)


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(make: str, model: str, year: int) -> str:
    raw = f"kbb-apify-{year}-{make.lower()}-{model.lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache(key: str) -> Optional[dict]:
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > _CACHE_TTL:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(key: str, data: dict):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"KBB/Apify: cache write failed: {e}")
