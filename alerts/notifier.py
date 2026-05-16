"""SMTP email notifications."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    if not settings.SMTP_USER or not settings.SMTP_PASS or not settings.ALERT_EMAIL:
        logger.info("SMTP not configured; would send: %s", subject)
        return False
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.ALERT_EMAIL
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error("send_email failed: %s", e)
        return False


def desktop_notify(title: str, message: str) -> None:
    try:
        import subprocess

        subprocess.run(
            ["osascript", "-e", f'display notification "{message[:200]}" with title "{title[:50]}"'],
            check=False,
            capture_output=True,
        )
    except Exception:
        logger.debug("desktop notify unavailable")
