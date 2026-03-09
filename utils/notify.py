"""
utils/notify.py
Sends SMS or email alerts when great deals are found.
Phase 1: Twilio SMS (optional — works without it)
Phase 3: Add email via SendGrid or SMTP
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_sms_alert(
    deals,
    twilio_sid: str,
    twilio_token: str,
    from_number: str,
    to_number: str,
):
    """
    Send an SMS summary of great deals via Twilio.
    Silently skips if Twilio credentials are not configured.
    """
    if not all([twilio_sid, twilio_token, from_number, to_number]):
        logger.info("Twilio not configured — skipping SMS notification")
        return

    try:
        from twilio.rest import Client
    except ImportError:
        logger.warning("twilio not installed — run: pip install twilio")
        return

    great_deals = [d for d in deals if d.label == "great"]
    if not great_deals:
        return

    lines = ["🚗 AutoScout AI — Great Deals Found!\n"]
    for d in great_deals[:5]:  # limit to top 5
        l = d.listing
        vehicle = f"{l.year} {l.make} {l.model}".strip() or l.title[:40]
        lines.append(
            f"🔥 {vehicle}\n"
            f"   Ask: ${l.asking_price:,} | KBB: ${d.market_value.fair_value:,}\n"
            f"   Score: {d.score}/100 | Save ${d.savings_vs_kbb:,}\n"
            f"   {l.url}\n"
        )

    body = "\n".join(lines)

    try:
        client = Client(twilio_sid, twilio_token)
        message = client.messages.create(body=body[:1600], from_=from_number, to=to_number)
        logger.info(f"SMS alert sent: {message.sid}")
    except Exception as e:
        logger.error(f"SMS send failed: {e}")


def print_alert_summary(scored_listings, messages):
    """Print a quick summary to the terminal (always runs)."""
    great = [s for s in scored_listings if s.label == "great"]
    fair  = [s for s in scored_listings if s.label == "fair"]

    print("\n" + "═"*60)
    print(f"  AutoScout AI — Scan Complete")
    print("═"*60)
    print(f"  Total listings scored : {len(scored_listings)}")
    print(f"  🔥 Great deals        : {len(great)}")
    print(f"  ⚡ Fair deals         : {len(fair)}")
    print(f"  ✉  Messages drafted   : {len(messages)}")
    print("═"*60)

    if great:
        print("\n  TOP GREAT DEALS:")
        for s in great[:5]:
            l = s.listing
            vehicle = f"{l.year} {l.make} {l.model}".strip() or l.title[:50]
            print(f"\n  [{s.score:5.1f}] {vehicle}")
            print(f"         Ask ${l.asking_price:,}  |  KBB ${s.market_value.fair_value:,}  |  Save ${s.savings_vs_kbb:,}")
            print(f"         {l.url}")
    print()
