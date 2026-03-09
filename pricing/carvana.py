"""
pricing/carvana.py
Finds the cheapest comparable listing on Carvana for a given vehicle.
Used as an additional market price data point alongside KBB.
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
}

CARVANA_SEARCH = "https://www.carvana.com/cars/{make}-{model}?{params}"


def get_carvana_price(
    make: str,
    model: str,
    year: int,
    mileage: int,
    year_range: int = 2,
    mileage_range: int = 20_000,
) -> Optional[int]:
    """
    Returns the median price of comparable Carvana listings.
    Returns None if unable to fetch.
    """
    make_slug = make.lower().replace(" ", "-")
    model_slug = model.lower().replace(" ", "-")

    params = urlencode({
        "year-min": year - year_range,
        "year-max": year + year_range,
        "miles-min": max(0, mileage - mileage_range),
        "miles-max": mileage + mileage_range,
    })
    url = CARVANA_SEARCH.format(make=make_slug, model=model_slug, params=params)

    try:
        time.sleep(1.0)
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            logger.debug(f"Carvana returned {resp.status_code} for {year} {make} {model}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Carvana embeds prices in data attributes and text
        prices = []

        # Look for price patterns: "$24,590"
        price_pattern = re.compile(r"\$\s?([\d,]{4,6})(?!\d)")
        for el in soup.find_all(string=price_pattern):
            m = price_pattern.search(el)
            if m:
                p = int(m.group(1).replace(",", ""))
                if 3_000 < p < 200_000:
                    prices.append(p)

        if not prices:
            return None

        prices.sort()
        # Return median to avoid outliers
        median_idx = len(prices) // 2
        result = prices[median_idx]
        logger.debug(f"Carvana median for {year} {make} {model}: ${result:,} ({len(prices)} listings)")
        return result

    except Exception as e:
        logger.warning(f"Carvana fetch error for {year} {make} {model}: {e}")
        return None
