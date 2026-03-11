"""
WhatsApp messaging module via Twilio.
Handles sending analysis text back to a WhatsApp number,
splitting long messages into chunks to stay within WhatsApp's 4096-char limit.

Setup (.env):
    TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN=your_auth_token
    TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
    WHATSAPP_TO=whatsapp:+91XXXXXXXXXX   (used only by CLI --notify flow)
"""

import os
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class NotificationResult:
    success: bool
    message_sid: Optional[str] = None
    error: Optional[str] = None


def _get_twilio_client():
    """Return a configured Twilio client or raise ImportError/ValueError."""
    try:
        from twilio.rest import Client  # type: ignore
    except ImportError:
        raise ImportError("twilio not installed. Run: pip3 install twilio")

    sid   = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
    return Client(sid, token)


def _normalise_number(number: str) -> str:
    """Ensure the number has the whatsapp: prefix."""
    if not number.startswith("whatsapp:"):
        return f"whatsapp:{number}"
    return number


def split_message_chunks(text: str, max_length: int = 3500) -> list[str]:
    """
    Split a long message into chunks ≤ max_length chars,
    breaking at newlines to preserve formatting.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_length and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)

    if current:
        chunks.append("".join(current))

    return chunks


def send_text_to_whatsapp(
    to_number: str,
    text: str,
    from_number: Optional[str] = None,
    chunk_delay: float = 1.0
) -> NotificationResult:
    """
    Send analysis text to a WhatsApp number.
    Long messages are automatically split into multiple messages.

    Args:
        to_number:    Destination WhatsApp number (e.g. "+919876543210" or "whatsapp:+91...")
        text:         Full analysis text to send
        from_number:  Twilio sandbox/business number (defaults to TWILIO_WHATSAPP_FROM env var)
        chunk_delay:  Seconds to wait between chunks (avoid Twilio rate limits)

    Returns:
        NotificationResult of the first message; errors in later chunks are logged but not fatal.
    """
    try:
        client = _get_twilio_client()
    except (ImportError, ValueError) as e:
        return NotificationResult(success=False, error=str(e))

    from_num = _normalise_number(
        from_number or os.environ.get("TWILIO_WHATSAPP_FROM", "+14155238886")
    )
    to_num = _normalise_number(to_number)

    chunks = split_message_chunks(text)
    first_sid = None

    for i, chunk in enumerate(chunks):
        try:
            msg = client.messages.create(body=chunk, from_=from_num, to=to_num)
            if i == 0:
                first_sid = msg.sid
            if i < len(chunks) - 1:
                time.sleep(chunk_delay)
        except Exception as e:
            return NotificationResult(
                success=(first_sid is not None),
                message_sid=first_sid,
                error=f"Chunk {i+1}/{len(chunks)} failed: {e}"
            )

    return NotificationResult(success=True, message_sid=first_sid)


def send_whatsapp_notification(analysis: dict) -> NotificationResult:
    """
    Legacy helper kept for compatibility — sends plain text analysis.
    `analysis` dict must contain a "text" key with the full analysis string,
    and optionally "to_number" (falls back to WHATSAPP_TO env var).
    """
    to_number = analysis.get("to_number") or os.environ.get("WHATSAPP_TO")
    if not to_number:
        return NotificationResult(
            success=False,
            error="No to_number provided and WHATSAPP_TO not set in .env"
        )
    text = analysis.get("text", str(analysis))
    return send_text_to_whatsapp(to_number, text)
