"""
messaging/drafter.py
Uses the Claude API to draft personalized seller messages.

Phase 1: Template-based drafting (no API key required).
Phase 2: Claude API drafting for personalized, intelligent messages.
"""

import os
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class MessageDrafter:
    """
    Drafts seller messages for vehicle listings.

    Usage:
        drafter = MessageDrafter()
        msg = drafter.draft(scored_listing)
    """

    def __init__(self, use_claude: bool = False):
        """
        Args:
            use_claude: If True and ANTHROPIC_API_KEY is set, use Claude API
                        for personalized messages. Otherwise uses templates.
        """
        self.use_claude = use_claude and bool(os.getenv("ANTHROPIC_API_KEY"))
        if self.use_claude:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                logger.info("Claude API message drafting enabled")
            except ImportError:
                logger.warning("anthropic package not installed — falling back to templates")
                self.use_claude = False

    def draft(self, listing) -> str:
        """Draft a seller message for a scored listing."""
        if self.use_claude:
            try:
                return self._draft_with_claude(listing)
            except Exception as e:
                logger.error(f"Claude API error: {e} — falling back to template")

        return self._draft_from_template(listing)

    # ── Claude API Drafting ───────────────────────────────────────────────────

    def _draft_with_claude(self, listing) -> str:
        """Use Claude to write a personalized, context-aware message."""

        savings_str = ""
        if listing.savings_vs_kbb and listing.savings_vs_kbb > 0:
            savings_str = f"The asking price is ${listing.savings_vs_kbb:,} below KBB market value."
        elif listing.savings_vs_kbb and listing.savings_vs_kbb < 0:
            savings_str = f"The asking price is ${abs(listing.savings_vs_kbb):,} above KBB market value."

        ask_str     = f"${listing.asking_price:,}"   if listing.asking_price  else "unknown"
        kbb_str     = f"~${listing.kbb_value:,}"     if listing.kbb_value     else "unknown"
        mileage_str = f"{listing.mileage:,} miles"   if listing.mileage       else "unknown"
        offer_str   = f"${listing.suggested_offer:,}" if listing.suggested_offer else "flexible"

        prompt = f"""You are helping a car buyer send a message to a private seller on Craigslist or Facebook Marketplace.

Vehicle details:
- Vehicle: {listing.year} {listing.make} {listing.model}
- Asking price: {ask_str}
- KBB market value: {kbb_str}
- Mileage: {mileage_str}
- Suggested offer: {offer_str}
- Deal score: {listing.total_score}/100
- {savings_str}

Write a SHORT, friendly, conversational message (3–5 sentences max) to send to the seller.
The message should:
1. Express genuine interest in the vehicle
2. Ask if there's any flexibility on price (don't mention specific offer amount unless it's a great deal)
3. Mention you're a serious buyer who can move quickly
4. Sound like a real person — casual, not robotic
5. NOT mention KBB, market values, or research you've done (sounds pushy)

Return ONLY the message text, nothing else."""

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text.strip()

    # ── Template-Based Drafting ───────────────────────────────────────────────

    TEMPLATES = {
        "great": [
            "Hi! I saw your {vehicle} and I'm very interested — it looks like exactly what I've been searching for. I'm a serious buyer and can meet at your convenience with payment ready. Any flexibility on the price? I can move quickly. Thanks!",

            "Hey! Just came across your listing for the {vehicle} and I'd love to make this work. I'm ready to buy this week — cash or financing ready. Would you consider {offer}? Let me know, thanks!",

            "Hi there! I'm interested in your {vehicle}. I've been looking for one in this condition and yours stands out. I can meet quickly and payment is ready. Is the price negotiable at all? Looking forward to hearing from you!",
        ],
        "fair": [
            "Hi! I noticed your {vehicle} listing and I'm interested. Would you consider {offer}? I'm a serious buyer and can meet at your convenience. Let me know — thanks!",

            "Hello! Saw your {vehicle} for sale and it caught my attention. Any flexibility on the price? I'm ready to move quickly if we can agree on something. Thanks for your time!",
        ],
        "poor": [
            "Hi! I'm interested in your {vehicle}. Is there any flexibility on the price? Happy to come take a look if so. Thanks!",
        ],
    }

    def _draft_from_template(self, listing) -> str:
        """Fill a message template with listing data."""
        import random

        vehicle_str = f"{listing.year} {listing.make} {listing.model}".strip()
        if not vehicle_str.strip():
            vehicle_str = listing.title

        offer_str = f"${listing.suggested_offer:,}" if listing.suggested_offer else "a bit less"

        templates = self.TEMPLATES.get(listing.deal_class, self.TEMPLATES["fair"])
        template = random.choice(templates)

        msg = template.format(
            vehicle=vehicle_str,
            offer=offer_str,
            price=f"${listing.asking_price:,}" if listing.asking_price else "your price",
        )

        return msg
