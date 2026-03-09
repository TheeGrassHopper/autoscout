"""
utils/notifier.py
Sends SMS alerts when great deals are found.
Requires Twilio credentials in .env (optional).
"""

import os
import logging

logger = logging.getLogger(__name__)


class Notifier:
    """Send SMS notifications for great deals."""

    def __init__(self):
        self.enabled = all([
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN"),
            os.getenv("TWILIO_FROM_NUMBER"),
            os.getenv("TWILIO_TO_NUMBER"),
        ])
        if self.enabled:
            try:
                from twilio.rest import Client
                self.client = Client(
                    os.getenv("TWILIO_ACCOUNT_SID"),
                    os.getenv("TWILIO_AUTH_TOKEN")
                )
                logger.info("Twilio SMS notifications enabled")
            except ImportError:
                logger.warning("twilio package not installed — SMS disabled")
                self.enabled = False

    def alert_great_deal(self, listing):
        """Send an SMS alert for a great deal."""
        if not self.enabled:
            return

        savings = f"${listing.savings_vs_kbb:,} below KBB" if listing.savings_vs_kbb else ""
        msg = (
            f"🔥 AutoScout: GREAT DEAL FOUND!\n"
            f"{listing.title}\n"
            f"${listing.asking_price:,} asking {savings}\n"
            f"Score: {listing.total_score}/100\n"
            f"{listing.url}"
        )

        try:
            self.client.messages.create(
                body=msg,
                from_=os.getenv("TWILIO_FROM_NUMBER"),
                to=os.getenv("TWILIO_TO_NUMBER"),
            )
            logger.info(f"SMS alert sent for {listing.title[:40]}")
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
