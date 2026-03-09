"""
messaging/message_composer.py
Uses Claude to draft personalized, natural-sounding messages to sellers.
Each message is unique and tailored to the specific vehicle and deal.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)


@dataclass
class DraftMessage:
    listing_id: str
    vehicle: str
    asking_price: int
    offer_price: int
    message_body: str
    source: str          # "craigslist" | "facebook"
    listing_url: str
    score: float


SYSTEM_PROMPT = """You are helping someone buy a used vehicle at a fair price.
Write a SHORT, friendly, natural message to the seller (3–5 sentences max).
- Sound like a real person, not a bot
- Be genuinely interested but not desperate
- Optionally mention an offer price if provided
- Don't use generic openers like "I hope this message finds you well"
- Don't mention KBB, market research, or pricing tools
- End with a simple call to action
Return ONLY the message text. No subject line. No explanation."""


TONES = {
    "casual": "Write in a casual, friendly tone like texting a friend.",
    "formal": "Write in a polite, professional tone.",
    "urgent": "Convey that you're ready to buy today and can move fast.",
    "lowball": "You're interested but trying to negotiate down. Be friendly but firm on price.",
}


def compose_message(
    vehicle: str,
    asking_price: int,
    market_price: int,
    mileage: int,
    year: int,
    tone: str = "casual",
    api_key: str = "",
    include_offer: bool = True,
) -> str:
    """Draft a seller message using Claude. Falls back to template if API unavailable."""

    offer_price = _suggest_offer(asking_price, market_price)
    offer_str = f"${offer_price:,}" if include_offer else ""

    if not api_key:
        return _template_message(vehicle, asking_price, offer_str, tone)

    tone_instruction = TONES.get(tone, TONES["casual"])

    prompt = f"""Vehicle: {vehicle}
Seller's asking price: ${asking_price:,}
{"My offer: " + offer_str if offer_str else ""}
Mileage: {mileage:,} miles
Year: {year}
Tone instruction: {tone_instruction}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except Exception as e:
        logger.error(f"Claude message composition failed: {e}")
        return _template_message(vehicle, asking_price, offer_str, tone)


def compose_batch(scored_listings, api_key: str, tone: str = "casual", min_score: float = 80.0) -> list[DraftMessage]:
    """Compose messages for all listings at or above the score threshold."""
    import time
    drafts = []

    eligible = [s for s in scored_listings if s.score >= min_score]
    logger.info(f"Composing messages for {len(eligible)} listings (score ≥ {min_score})")

    for scored in eligible:
        listing = scored.listing
        vehicle = f"{listing.year} {listing.make} {listing.model}".strip()
        if not vehicle.strip():
            vehicle = listing.title

        body = compose_message(
            vehicle=vehicle,
            asking_price=listing.asking_price or 0,
            market_price=scored.market_value.fair_value,
            mileage=listing.mileage or 0,
            year=listing.year or 2020,
            tone=tone,
            api_key=api_key,
        )

        draft = DraftMessage(
            listing_id=listing.id,
            vehicle=vehicle,
            asking_price=listing.asking_price or 0,
            offer_price=_suggest_offer(listing.asking_price or 0, scored.market_value.fair_value),
            message_body=body,
            source=listing.source,
            listing_url=listing.url,
            score=scored.score,
        )
        drafts.append(draft)
        logger.info(f"  Drafted message for: {vehicle} (score {scored.score})")
        time.sleep(0.5)  # avoid rate limiting

    return drafts


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _suggest_offer(asking: int, market: int) -> int:
    """Suggest a reasonable offer: midpoint between asking and 10% below asking."""
    if not asking:
        return 0
    floor = int(asking * 0.88)   # don't go below 12% under asking
    target = int(asking * 0.94)  # suggest ~6% under asking
    return max(floor, target)


def _template_message(vehicle: str, asking_price: int, offer_str: str, tone: str) -> str:
    templates = {
        "casual": (
            f"Hey! Just saw your {vehicle} listing and I'm interested. "
            f"{'Would you take ' + offer_str + '? ' if offer_str else ''}"
            f"I'm a serious buyer and can meet up quickly. Let me know!"
        ),
        "formal": (
            f"Hello, I came across your listing for the {vehicle} and would like to express my interest. "
            f"{'I would like to propose an offer of ' + offer_str + '. ' if offer_str else ''}"
            f"I am a qualified buyer and can accommodate your schedule. Please let me know if you are interested."
        ),
        "urgent": (
            f"Hi! I want your {vehicle} — I'm shopping today and have {offer_str or 'cash'} ready. "
            f"Can we meet today or tomorrow? Let me know ASAP!"
        ),
        "lowball": (
            f"Hi! Love the {vehicle}. Best I can do is {offer_str or 'a lower offer'} — "
            f"cash, fast close, no hassle. Interested?"
        ),
    }
    return templates.get(tone, templates["casual"])
