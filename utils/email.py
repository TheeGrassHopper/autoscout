"""
utils/email.py — Email sending helper.

Priority order:
  1. RESEND_API_KEY  → Resend HTTP API (recommended, free 100/day)
  2. SMTP_HOST       → plain SMTP relay (Gmail, etc.)
  3. neither set     → no-op with warning

FROM address note:
  Resend free tier with onboarding@resend.dev can ONLY send to the verified
  account owner's email address. For production, verify a custom domain at
  resend.com/domains and set FROM_EMAIL=noreply@yourdomain.com
"""

import logging
import os

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Send an email. Uses Resend if configured, falls back to SMTP.

    Args:
        to:      Recipient email address.
        subject: Email subject line.
        body:    Plain-text body (always required as fallback).
        html:    Optional HTML body — used only by Resend. If omitted, plain text is sent.
    """
    resend_key = os.getenv("RESEND_API_KEY", "")
    if resend_key:
        _send_via_resend(to, subject, body, resend_key, html=html)
    else:
        _send_via_smtp(to, subject, body)


def _send_via_resend(to: str, subject: str, body: str, api_key: str,
                     html: str | None = None) -> None:
    """Send via Resend HTTP API — no extra dependencies needed."""
    import json
    import urllib.request

    from_email = os.getenv("FROM_EMAIL", "AutoScout AI <onboarding@resend.dev>")
    payload: dict = {
        "from": from_email,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    data = json.dumps(payload).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
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
        err_str = str(e)
        if "403" in err_str or "Forbidden" in err_str:
            logger.error(
                "Resend 403 Forbidden for %s — the FROM address '%s' is restricted. "
                "With Resend's free tier, onboarding@resend.dev can only send to the "
                "account owner's verified email. Verify a custom domain at "
                "resend.com/domains and set FROM_EMAIL=noreply@yourdomain.com",
                to, from_email,
            )
        else:
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


# ── HTML Templates ─────────────────────────────────────────────────────────────

def password_reset_html(reset_link: str) -> str:
    """Return a clean HTML email for password reset."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset your AutoScout AI password</title>
</head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:520px;background-color:#1e293b;border-radius:12px;border:1px solid #334155;overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="padding:32px 40px 24px;border-bottom:1px solid #334155;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:#3b82f6;border-radius:8px;padding:6px 10px;margin-right:10px;">
                    <span style="color:#ffffff;font-size:14px;font-weight:700;letter-spacing:0.05em;">AS</span>
                  </td>
                  <td style="padding-left:10px;">
                    <span style="color:#f1f5f9;font-size:16px;font-weight:600;">AutoScout AI</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 40px;">
              <h1 style="margin:0 0 12px;color:#f1f5f9;font-size:22px;font-weight:700;">
                Reset your password
              </h1>
              <p style="margin:0 0 24px;color:#94a3b8;font-size:15px;line-height:1.6;">
                We received a request to reset the password for your AutoScout AI account.
                Click the button below to choose a new password.
              </p>
              <table cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
                <tr>
                  <td style="border-radius:8px;background:#3b82f6;">
                    <a href="{reset_link}"
                       style="display:inline-block;padding:13px 28px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:8px;">
                      Reset password
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;color:#64748b;font-size:13px;line-height:1.5;">
                This link expires in <strong style="color:#94a3b8;">1 hour</strong>.
                If you did not request a password reset, you can safely ignore this email —
                your password will not change.
              </p>
              <p style="margin:16px 0 0;color:#64748b;font-size:12px;">
                Or copy this URL into your browser:<br>
                <span style="color:#3b82f6;word-break:break-all;">{reset_link}</span>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px;border-top:1px solid #334155;">
              <p style="margin:0;color:#475569;font-size:12px;">
                AutoScout AI &mdash; automated car deal finder
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
