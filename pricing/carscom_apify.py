"""
pricing/carscom_apify.py
Cars.com market intel via Apify's benthepythondev/cars-com-scraper actor.

Runs when a VIN is available (triggered by "Get Carvana Cash Offer" button).
Returns comparable dealer listings for the same VIN/make+model+year with:
  - flip_score (0-100)
  - CARFAX flags (clean title, no accidents, 1 owner, service records)
  - deal_rating ("Great Deal" / "Good Deal" / "Fair Deal" / "High Price")
  - price_drop (price reduction from prior listing price)
  - comparable listings (up to 5 similar vehicles nearby)
  - exterior_color / transmission / drivetrain (for Carvana autofill)

Caches per VIN for 24 hours in output/.carscom_cache/
Pricing: $2.50/1K results (~$0.005 per lookup)
"""

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = "output/.carscom_cache"
_CACHE_TTL = 86400  # 24 hours
_ACTOR_ID = "benthepythondev/cars-com-scraper"


def _cache_path(vin: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{vin.upper()}.json")


def _load_cache(vin: str) -> Optional[dict]:
    path = _cache_path(vin)
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > _CACHE_TTL:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(vin: str, data: dict):
    try:
        with open(_cache_path(vin), "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def get_carscom_intel(
    vin: str,
    make: str = "",
    model: str = "",
    year: Optional[int] = None,
    mileage: Optional[int] = None,
    zip_code: str = "85288",
    apify_token: str = "",
) -> Optional[dict]:
    """
    Fetch Cars.com market intel for a VIN via Apify.

    Returns dict with:
      target        - the matching listing for this exact VIN (or None)
      comparables   - list of up to 5 similar listings (same make/model/year ±1)
      flip_score    - 0-100 flip score from Cars.com (target listing)
      deal_rating   - "Great Deal" / "Good Deal" / "Fair Deal" / "High Price"
      deal_savings  - dollars under/over market (from deal_badge_text)
      price_drop    - price reduction from prior listing price
      carfax        - {clean_title, no_accidents, one_owner, service_records}
      exterior_color- e.g. "Midnight Black" (for Carvana autofill)
      transmission  - e.g. "Automatic"
      drivetrain    - e.g. "4WD"
      avg_comp_price- average asking price of comparable listings
      comp_count    - number of comparable listings found
    """
    apify_token = apify_token or os.getenv("APIFY_API_TOKEN", "")
    if not apify_token:
        logger.debug("[CarscomApify] No APIFY_API_TOKEN — skipping")
        return None
    if not vin or len(vin.strip()) != 17:
        logger.debug("[CarscomApify] Invalid or missing VIN — skipping")
        return None

    vin = vin.strip().upper()
    cached = _load_cache(vin)
    if cached:
        logger.debug(f"[CarscomApify] Cache hit for VIN {vin}")
        return cached

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.warning("[CarscomApify] apify_client not installed — pip install apify-client")
        return None

    try:
        client = ApifyClient(apify_token)

        # Build search input — search by make/model/year to get comps,
        # then match exact VIN in results for the target listing
        run_input: dict = {
            "includeFlipScore": True,
            "includeDealerInfo": False,
            "includePhotos": False,
            "maxItems": 20,
        }

        # If we have make/model/year, search by those to get comps + hopefully find our VIN
        if make and model and year:
            run_input["searchParams"] = {
                "makes": [make],
                "models": [model.split()[0]],  # base model only
                "yearMin": year - 1,
                "yearMax": year + 1,
                "zip": zip_code,
                "radius": 500,
            }
            if mileage:
                run_input["searchParams"]["mileageMax"] = mileage + 30000
        else:
            # VIN-only search — less precise but still works
            run_input["searchParams"] = {
                "zip": zip_code,
                "radius": 500,
            }

        logger.info(f"[CarscomApify] Fetching Cars.com data for VIN={vin} ({year} {make} {model})…")

        run = client.actor(_ACTOR_ID).call(
            run_input=run_input,
            timeout_secs=120,
        )

        if not run or run.get("status") != "SUCCEEDED":
            logger.warning(f"[CarscomApify] Run failed: {run.get('status') if run else 'no run'}")
            return None

        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    except Exception as e:
        logger.warning(f"[CarscomApify] API error for VIN {vin}: {e}")
        return None

    if not items:
        logger.debug(f"[CarscomApify] No results for VIN {vin}")
        return None

    # Find the exact VIN match in results
    target = next((i for i in items if (i.get("vin") or "").upper() == vin), None)

    # All other results are comps
    comps = [i for i in items if (i.get("vin") or "").upper() != vin and i.get("price")]

    # Parse deal_savings from badge text e.g. "$1,270 under" → 1270, "$500 over" → -500
    def _parse_savings(badge: str) -> Optional[int]:
        if not badge:
            return None
        import re
        m = re.search(r'\$?([\d,]+)\s*(under|over)', badge, re.I)
        if not m:
            return None
        val = int(m.group(1).replace(",", ""))
        return val if "under" in m.group(2).lower() else -val

    src = target or {}
    flip_breakdown = src.get("flip_score_breakdown") or {}

    result = {
        "vin": vin,
        "target": {
            "url": src.get("url"),
            "title": src.get("title"),
            "price": src.get("price"),
            "mileage": src.get("mileage"),
            "year": src.get("year"),
            "make": src.get("make"),
            "model": src.get("model"),
            "trim": src.get("trim"),
            "dealer_name": src.get("dealer_name"),
        } if target else None,
        "flip_score": src.get("flip_score"),
        "flip_breakdown": {
            "deal_rating_score": flip_breakdown.get("deal_rating_score"),
            "price_score": flip_breakdown.get("price_score"),
            "carfax_score": flip_breakdown.get("carfax_score"),
            "resale_score": flip_breakdown.get("resale_score"),
        },
        "deal_rating": src.get("deal_rating"),
        "deal_savings": _parse_savings(src.get("deal_badge_text", "")),
        "price_drop": src.get("price_drop"),
        "carfax": {
            "clean_title": bool(src.get("carfax_clean_title")),
            "no_accidents": bool(src.get("carfax_no_accidents")),
            "one_owner": bool(src.get("carfax_1_owner")),
            "service_records": bool(src.get("carfax_service_records")),
        },
        "exterior_color": src.get("exterior_color"),
        "interior_color": src.get("interior_color"),
        "transmission": src.get("transmission"),
        "drivetrain": src.get("drivetrain"),
        "fuel_type": src.get("fuel_type"),
        "mpg_city": src.get("mpg_city"),
        "mpg_highway": src.get("mpg_highway"),
        "comparables": [
            {
                "title": c.get("title"),
                "price": c.get("price"),
                "mileage": c.get("mileage"),
                "year": c.get("year"),
                "trim": c.get("trim"),
                "deal_rating": c.get("deal_rating"),
                "flip_score": c.get("flip_score"),
                "url": c.get("url"),
            }
            for c in comps[:5]
        ],
        "avg_comp_price": (
            int(sum(c["price"] for c in comps) / len(comps)) if comps else None
        ),
        "comp_count": len(comps),
    }

    _save_cache(vin, result)
    logger.info(
        f"[CarscomApify] VIN={vin}: flip_score={result['flip_score']} "
        f"deal={result['deal_rating']} comps={result['comp_count']}"
    )
    return result
