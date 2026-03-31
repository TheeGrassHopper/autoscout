"""
utils/email.py — Email sending helper.

Priority order:
  1. RESEND_API_KEY  → Resend HTTP API (recommended, free 100/day)
  2. SMTP_HOST       → plain SMTP relay (Gmail, etc.)
  3. neither set     → no-op with warning
"""

import logging
import os

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Uses Resend if configured, falls back to SMTP."""
    resend_key = os.getenv("RESEND_API_KEY", "")
    if resend_key:
        _send_via_resend(to, subject, body, resend_key)
    else:
        _send_via_smtp(to, subject, body)


def _send_via_resend(to: str, subject: str, body: str, api_key: str) -> None:
    """Send via Resend HTTP API — no extra dependencies needed."""
    import json
    import urllib.request

    from_email = os.getenv("FROM_EMAIL", "AutoScout AI <onboarding@resend.dev>")
    payload = json.dumps({
        "from": from_email,
        "to": [to],
        "subject": subject,
        "text": body,
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Email sent via Resend to %s: %s (status %s)", to, subject, resp.status)
    except Exception as e:
        logger.error("Resend failed for %s: %s", to, e)


def _send_via_smtp(to: str, subject: str, body: str) -> None:
    """Send via SMTP relay (Gmail app password, etc.)."""
    import smtplib
    from email.mime.text import MIMEText

    host  = os.getenv("SMTP_HOST", "")
    port  = int(os.getenv("SMTP_PORT", "587"))
    user  = os.getenv("SMTP_USER", "")
    pw    = os.getenv("SMTP_PASS", "")
    from_ = os.getenv("FROM_EMAIL", user)

    if not host or not user:
        logger.warning("No email provider configured (RESEND_API_KEY or SMTP_HOST) — skipping email to %s", to)
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
        logger.info("Email sent via SMTP to %s: %s", to, subject)
    except Exception as e:
        logger.error("SMTP failed for %s: %s", to, e)
