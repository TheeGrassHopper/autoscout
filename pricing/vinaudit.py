"""
pricing/vinaudit.py
VinAudit Market Value API — VIN-based vehicle pricing.

VinAudit provides real transaction-based market values using VIN + mileage.
No guessing, no depreciation models — actual market data.

API: https://marketvalue.vinaudit.com/getmarketvalue.php
  Required: key, vin, mileage
  Optional: period (days of data, default 90)
  Returns:  { success, count, mean, prices: [low, average, high] }

Pricing: 500 free calls, then ~$0.01/call
Sign up:  https://vinaudit.com/register

Set VINAUDIT_API_KEY in .env to enable.
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
_CACHE_TTL = 86400 * 7   # 7 days — market values don't change that fast
_API_URL = "https://marketvalue.vinaudit.com/getmarketvalue.php"


def get_vinaudit_price(
    vin: str,
    mileage: int,
    make: str = "",
    model: str = "",
    year: int = 0,
    period: int = 90,
    api_key: str = "",
) -> Optional[PriceEstimate]:
    """
    Fetch market value from VinAudit for a specific VIN + mileage.

    Returns a PriceEstimate with:
      - fair_market_value = mean transaction price
      - trade_in_low / retail_high = price range
      - confidence = "high" when count >= 5, "medium" when 1-4, "low" when 0
      - source = "vinaudit"

    Returns None if no API key, VIN is blank, or the API call fails.
    """
    api_key = api_key or os.getenv("VINAUDIT_API_KEY", "")
    if not api_key:
        logger.debug("VinAudit: no API key — skipping")
        return None
    if not vin or not vin.strip():
        logger.debug("VinAudit: no VIN — skipping")
        return None

    vin = vin.strip().upper()

    # Check cache
    cache_key = _cache_key(vin, mileage)
    cached = _load_cache(cache_key)
    if cached:
        logger.debug(f"VinAudit cache hit: {vin}")
        return PriceEstimate(**cached)

    try:
        resp = requests.get(
            _API_URL,
            params={"key": api_key, "vin": vin, "mileage": mileage, "period": period},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"VinAudit: API error for {vin}: {e}")
        return None

    if not data.get("success"):
        logger.debug(f"VinAudit: no data for {vin} (success=false, count={data.get('count', 0)})")
        return None

    count = data.get("count", 0)
    mean = data.get("mean")
    prices = data.get("prices", [])   # [low, average, high]

    if not mean or mean <= 0:
        logger.debug(f"VinAudit: zero mean for {vin}")
        return None

    low  = int(prices[0]) if len(prices) > 0 and prices[0] else int(mean * 0.88)
    high = int(prices[2]) if len(prices) > 2 and prices[2] else int(mean * 1.12)
    confidence = "high" if count >= 5 else "medium" if count >= 1 else "low"

    estimate = PriceEstimate(
        source="vinaudit",
        make=make,
        model=model,
        year=year or 0,
        mileage=mileage,
        trade_in_low=low,
        retail_high=high,
        fair_market_value=int(mean),
        confidence=confidence,
    )

    _save_cache(cache_key, estimate.to_dict())
    logger.info(
        f"VinAudit: {vin} → ${int(mean):,} (count={count}, confidence={confidence})"
    )
    return estimate


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(vin: str, mileage: int) -> str:
    mileage_bucket = round(mileage / 5000) * 5000
    raw = f"vinaudit-{vin}-{mileage_bucket}"
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
        logger.warning(f"VinAudit: cache write failed: {e}")
