"""Process deadline-extension emails: LLM parse + DB update."""

import json
import logging
import os
import re

import anthropic

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You analyze emails related to hotel option deadline extensions for the event "N!Partivia" (corporate incentive trip in Spain).

You will receive:
1. The email text
2. A list of hotels currently in the system with their current deadline

Your task: determine if this email confirms an extension of the option deadline for one of the hotels.

Reply ONLY with valid JSON (no markdown):
{
  "is_deadline_extension": true/false,
  "hotel_name": "exact hotel name as in the email",
  "new_deadline": "DD/MM/YYYY",
  "notes": "brief summary in English of what was confirmed",
  "confidence": "high" or "medium" or "low",
  "match_hotel_id": <id from the list if you can match, else null>
}

If the email is NOT about a deadline extension (e.g. it's a new quote, a cancellation, etc.), set is_deadline_extension to false and leave other fields null.

IMPORTANT:
- Extract the NEW deadline date, not the old one
- Match the hotel by name, being flexible with spelling variations
- If the email mentions multiple hotels, return an array of objects under "results" key
- Dates must be in DD/MM/YYYY format
"""


def _strip_html(html: str) -> str:
    """Minimal HTML to text conversion."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_email_text(msg: dict) -> str:
    """Extract readable text from a Graph message dict."""
    body = msg.get("body", {})
    content = body.get("content", "")
    if body.get("contentType", "").lower() == "html":
        content = _strip_html(content)
    return content.strip() or msg.get("bodyPreview", "")


def parse_deadline_email(email_text: str, sender: str, subject: str,
                         hotels_context: str) -> dict | None:
    """Use Claude to determine if email is a deadline extension confirmation.

    Returns parsed result dict or None on error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return None

    user_message = (
        f"From: {sender}\n"
        f"Subject: {subject}\n\n"
        f"--- Email body ---\n{email_text}\n\n"
        f"--- Hotels in system ---\n{hotels_context}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        return json.loads(raw)
    except Exception:
        logger.exception("LLM parsing failed")
        return None
