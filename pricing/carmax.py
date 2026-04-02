"""
pricing/carmax.py
Finds comparable listings on CarMax for a given vehicle.
Used as an additional market price data point alongside KBB and Carvana.

CarMax search URL structure:
  https://www.carmax.com/cars/{make}/{model}?year-min=X&year-max=X&miles-max=X
"""

import re
import time
import logging
from typing import Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CARMAX_SEARCH = "https://www.carmax.com/cars/{make}/{model}?{params}"


def get_carmax_price(
    make: str,
    model: str,
    year: int,
    mileage: int,
    year_range: int = 2,
    mileage_range: int = 20_000,
) -> Optional[int]:
    """
    Returns the median price of comparable CarMax listings.
    Returns None if unable to fetch.
    """
    make_slug = make.lower().replace(" ", "-")
    model_slug = model.lower().replace(" ", "-")

    params = urlencode({
        "year-min": year - year_range,
        "year-max": year + year_range,
        "miles-max": mileage + mileage_range,
    })
    url = CARMAX_SEARCH.format(make=make_slug, model=model_slug, params=params)

    try:
        time.sleep(1.0)
        resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code != 200:
            logger.debug(f"CarMax returned {resp.status_code} for {year} {make} {model}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        prices = []

        # CarMax embeds prices in text and data attributes
        price_pattern = re.compile(r"\$\s?([\d,]{4,6})(?!\d)")
        for el in soup.find_all(string=price_pattern):
            m = price_pattern.search(el)
            if m:
                p = int(m.group(1).replace(",", ""))
                if 3_000 < p < 200_000:
                    prices.append(p)

        # Also check data-qa and aria-label attributes
        for el in soup.find_all(attrs={"data-qa": True}):
            text = el.get_text()
            m = price_pattern.search(text)
            if m:
                p = int(m.group(1).replace(",", ""))
                if 3_000 < p < 200_000:
                    prices.append(p)

        if not prices:
            return None

        prices.sort()
        median_idx = len(prices) // 2
        result = prices[median_idx]
        logger.debug(f"CarMax median for {year} {make} {model}: ${result:,} ({len(prices)} listings)")
        return result

    except Exception as e:
        # Connection refused / network errors are common on Railway — log at debug only
        err_str = str(e).lower()
        if any(x in err_str for x in ("connection refused", "connection reset", "name or service not known")):
            logger.debug(f"CarMax unavailable for {year} {make} {model}: {e}")
        else:
            logger.warning(f"CarMax fetch error for {year} {make} {model}: {e}")
        return None
