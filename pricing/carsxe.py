"""
pricing/carsxe.py
CarsXE Market Value API — make/model/year/mileage pricing (no VIN needed).

CarsXE aggregates used-car transaction data to produce market valuations.
Works without a VIN — useful for listings that don't include one.

API: https://api.carsxe.com/valuation
  Required: key, vin  OR  key + year + make + model
  Optional: mileage, state
  Returns:  { price: { average, below, above } }

Pricing: 100 free calls, then ~$0.01–$0.05/call
Sign up:  https://api.carsxe.com

Set CARSXE_API_KEY in .env to enable.
"""

import logging
import os
import time
import json
import hashlib
import requests
from typing import Optional
from pricing.kbb import PriceEstimate

logger = logging.getLogger(__name__)

_CACHE_DIR = "output/.price_cache"
_CACHE_TTL = 86400 * 7   # 7 days
_API_URL = "https://api.carsxe.com/valuation"


def get_carsxe_price(
    make: str,
    model: str,
    year: int,
    mileage: int,
    vin: str = "",
    state: str = "",
    api_key: str = "",
) -> Optional[PriceEstimate]:
    """
    Fetch market value from CarsXE.

    Prefers VIN lookup when available (more accurate), falls back to
    make/model/year/mileage when VIN is absent.

    Returns a PriceEstimate with:
      - fair_market_value = average transaction price
      - trade_in_low = below-average price
      - retail_high = above-average price
      - confidence = "medium" always (CarsXE doesn't expose comp count)
      - source = "carsxe"

    Returns None if no API key, missing required fields, or API failure.
    """
    api_key = api_key or os.getenv("CARSXE_API_KEY", "")
    if not api_key:
        logger.debug("CarsXE: no API key — skipping")
        return None
    if not (make and model and year):
        logger.debug("CarsXE: missing make/model/year — skipping")
        return None

    vin = (vin or "").strip().upper()

    # Cache key — prefer VIN-based key for accuracy
    cache_key = _cache_key(vin=vin, make=make, model=model, year=year, mileage=mileage)
    cached = _load_cache(cache_key)
    if cached:
        logger.debug(f"CarsXE cache hit: {year} {make} {model}")
        return PriceEstimate(**cached)

    params: dict = {"key": api_key, "mileage": mileage}
    if vin:
        params["vin"] = vin
    else:
        params.update({"year": year, "make": make, "model": model})
    if state:
        params["state"] = state

    try:
        resp = requests.get(_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"CarsXE: API error for {year} {make} {model}: {e}")
        return None

    price_block = data.get("price") or data.get("data", {}).get("price")
    if not price_block:
        logger.debug(f"CarsXE: no price block for {year} {make} {model}: {data}")
        return None

    avg   = _to_int(price_block.get("average") or price_block.get("avg"))
    below = _to_int(price_block.get("below"))
    above = _to_int(price_block.get("above"))

    if not avg or avg <= 0:
        logger.debug(f"CarsXE: zero average for {year} {make} {model}")
        return None

    low  = below or int(avg * 0.88)
    high = above or int(avg * 1.12)

    estimate = PriceEstimate(
        source="carsxe",
        make=make,
        model=model,
        year=year,
        mileage=mileage,
        trade_in_low=low,
        retail_high=high,
        fair_market_value=avg,
        confidence="medium",
    )

    _save_cache(cache_key, estimate.to_dict())
    logger.info(f"CarsXE: {year} {make} {model} @ {mileage:,}mi → ${avg:,}")
    return estimate


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").replace("$", "")))
    except (ValueError, TypeError):
        return None


def _cache_key(vin: str, make: str, model: str, year: int, mileage: int) -> str:
    mileage_bucket = round(mileage / 5000) * 5000
    if vin:
        raw = f"carsxe-vin-{vin}-{mileage_bucket}"
    else:
        raw = f"carsxe-{year}-{make.lower()}-{model.lower()}-{mileage_bucket}"
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
        logger.warning(f"CarsXE: cache write failed: {e}")
