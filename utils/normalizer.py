"""
utils/normalizer.py
Uses the Claude API to extract structured vehicle data from unstructured
listing titles and descriptions.

This solves the core problem: Craigslist listings are free-text and
people write things like:
  "2019 tacoma trd off road 4x4 crew cab - one owner clean title low miles"
  "MUST SELL ASAP - F150 XLT 5.0 V8 '21 - 42k miles hardly driven"

Claude normalizes all of these into consistent structured fields.
"""

import json
import logging

import anthropic
from typing import Optional

import anthropic

from scrapers.craigslist import RawListing

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a vehicle data extraction specialist.
Given a vehicle listing title and description, extract structured data.
Return ONLY valid JSON with these exact fields (use null for unknown values):
{
  "make": string or null,
  "model": string or null,
  "year": integer or null,
  "mileage": integer or null,
  "trim": string or null,
  "transmission": "automatic" | "manual" | null,
  "drivetrain": "4wd" | "awd" | "fwd" | "rwd" | null,
  "condition": "excellent" | "good" | "fair" | "poor" | null,
  "color": string or null,
  "vehicle_type": "car" | "truck" | "suv" | "van" | "other" | null,
  "title_status": "clean" | "salvage" | "rebuilt" | "lien" | null,
  "accident_history": boolean or null,
  "one_owner": boolean or null
}
No explanation. No markdown. Only the JSON object."""


def normalize_listing(listing: RawListing, api_key: str) -> RawListing:
    """
    Use Claude to fill in missing structured fields from title + description.
    Fields already populated on the listing are preserved.
    """
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping AI normalization")
        return listing

    prompt = f"""TITLE: {listing.title}
DESCRIPTION: {listing.description[:600]}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)

        # Fill in missing fields (don't overwrite what we already have)
        if not listing.make and data.get("make"):
            listing.make = data["make"]
        if not listing.model and data.get("model"):
            listing.model = data["model"]
        if not listing.year and data.get("year"):
            listing.year = data["year"]
        if not listing.mileage and data.get("mileage"):
            listing.mileage = data["mileage"]
        if not listing.transmission and data.get("transmission"):
            listing.transmission = data["transmission"]
        if not listing.condition and data.get("condition"):
            listing.condition = data["condition"]
        if not listing.color and data.get("color"):
            listing.color = data["color"]

        logger.debug(f"Normalized: {listing.title[:50]} → {listing.year} {listing.make} {listing.model}")

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.debug(f"Normalization parse error for '{listing.title[:40]}': {e}")
    except anthropic.AuthenticationError:
        logger.warning("ANTHROPIC_API_KEY is missing or invalid — skipping AI normalization. Add your key to .env to enable it.")
        raise  # re-raise so normalize_batch can stop trying
    except Exception as e:
        logger.debug(f"Claude normalization skipped for '{listing.title[:40]}': {e}")

    return listing


def normalize_batch(listings: list[RawListing], api_key: str, delay: float = 0.3) -> list[RawListing]:
    """Normalize a list of listings. Returns all listings (auth failures skip normalization gracefully)."""
    import time
    normalized = []
    api_disabled = False  # flip to True on first auth error so we stop spamming

    for i, listing in enumerate(listings):
        if not api_disabled:
            logger.info(f"Normalizing {i+1}/{len(listings)}: {listing.title[:60]}")
            try:
                listing = normalize_listing(listing, api_key)
                time.sleep(delay)
            except anthropic.AuthenticationError:
                api_disabled = True
                logger.warning("AI normalization disabled for this run — add ANTHROPIC_API_KEY to .env to enable")

        # Keep the listing even without normalization — regex parsing still runs
        if listing.make or listing.year:
            normalized.append(listing)
        else:
            logger.debug(f"  Dropping (no make/year parseable): {listing.title[:50]}")

    logger.info(f"Normalization complete: {len(normalized)}/{len(listings)} listings usable")
    return normalized
