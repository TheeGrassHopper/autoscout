"""
messaging/sender.py
Handles sending messages to sellers or exporting them for manual sending.

Phase 1: Export to CSV / print to screen for manual copy-paste.
Phase 2: FB Graph API / Playwright automation for auto-send.

IMPORTANT: Sending messages automatically requires care:
  - Respect platform ToS
  - Rate limit your sends
  - Only message each seller once
  - Always give sellers an easy out
"""

import logging
import csv
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageSender:
    """
    Manages message sending and tracking.

    Phase 1 behavior: Exports messages to a review CSV.
    Set auto_send=True only after full testing.
    """

    def __init__(self, db=None, auto_send: bool = False, output_dir: str = "output"):
        self.db = db
        self.auto_send = auto_send
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def process(self, scored_listing) -> bool:
        """
        Decide whether to send, queue for approval, or skip.
        Returns True if message was sent or queued.
        """
        if not scored_listing.message_draft:
            return False

        # Check if already contacted
        if self.db and self.db.was_contacted(scored_listing.listing_id):
            logger.info(f"Already contacted seller for {scored_listing.listing_id} — skipping")
            return False

        if self.auto_send and scored_listing.is_great_deal:
            return self._send(scored_listing)
        else:
            return self._queue_for_review(scored_listing)

    def _send(self, listing) -> bool:
        """
        Auto-send a message.
        Phase 1: Just logs it. Phase 2: Playwright automation.
        """
        logger.warning(
            f"AUTO-SEND not yet implemented — queuing for manual review instead. "
            f"({listing.title})"
        )
        return self._queue_for_review(listing)

    def _queue_for_review(self, listing) -> bool:
        """Write message to the approval queue CSV for manual sending."""
        queue_path = os.path.join(self.output_dir, "message_queue.csv")
        is_new = not os.path.exists(queue_path)

        with open(queue_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "queued_at", "deal_class", "score", "title",
                "asking_price", "kbb_value", "savings",
                "url", "message", "sent"
            ])
            if is_new:
                writer.writeheader()

            writer.writerow({
                "queued_at": datetime.now().isoformat(),
                "deal_class": listing.deal_class,
                "score": listing.total_score,
                "title": listing.title,
                "asking_price": listing.asking_price,
                "kbb_value": listing.kbb_value,
                "savings": listing.savings_vs_kbb,
                "url": listing.url,
                "message": listing.message_draft,
                "sent": "NO",
            })

        logger.info(f"Message queued for review: {listing.title[:50]}")

        # Also print to terminal for immediate visibility
        print(f"\n{'─'*60}")
        print(f"📋 MESSAGE READY TO SEND — {listing.title}")
        print(f"   URL: {listing.url}")
        print(f"   Score: {listing.total_score}/100 ({listing.deal_class.upper()})")
        print(f"   💬 Message:\n")
        print(f"   {listing.message_draft}")
        print(f"{'─'*60}")

        return True
