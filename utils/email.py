"""
utils/email.py — Shared SMTP email helper.
"""

import logging
import os

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP. No-ops if SMTP_HOST is not configured."""
    import smtplib
    from email.mime.text import MIMEText

    host  = os.getenv("SMTP_HOST", "")
    port  = int(os.getenv("SMTP_PORT", "587"))
    user  = os.getenv("SMTP_USER", "")
    pw    = os.getenv("SMTP_PASS", "")
    from_ = os.getenv("FROM_EMAIL", user)

    if not host or not user:
        logger.warning("SMTP not configured — skipping email to %s", to)
        return

    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"]    = from_
        msg["To"]      = to
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(from_, [to], msg.as_string())
        logger.info("Email sent to %s: %s", to, subject)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
