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

Reply ONLY with valid JSON (no markdown, no ```json blocks):
{
  "is_deadline_extension": true,
  "hotel_name": "exact hotel name as in the email",
  "new_deadline": "DD/MM/YYYY",
  "notes": "brief summary in English of what was confirmed",
  "confidence": "high",
  "match_hotel_id": 123
}

If the email is NOT about a deadline extension (e.g. it's a new quote, a cancellation, a newsletter, spam, auto-reply, etc.), reply with exactly:
{"is_deadline_extension": false}

IMPORTANT:
- Extract the NEW deadline date, not the old one
- Match the hotel by name, being flexible with spelling variations
- If the email mentions multiple hotels, return an array of objects under "results" key
- Dates must be in DD/MM/YYYY format
- You MUST always reply with valid JSON, nothing else
"""

# Domains/senders to skip entirely (newsletters, spam, auto-replies)
SKIP_SENDERS = {
    "no-reply@", "noreply@", "newsletter@", "marketing@",
    "commerciale@veratour", "info@7796726", "no-reply@m1.email.samsung",
    "no-reply@info.costa.it", "no-reply@indeed.com",
}

# Subject patterns to skip
SKIP_SUBJECTS = [
    r"respuesta\s+autom[áa]tica",
    r"out\s+of\s+office",
    r"fuori\s+ufficio",
    r"riepilogo\s+settimanale",
    r"apertura\s+vendite",
    r"prova\s+a\s+vincere",
]


def should_skip_email(sender: str, subject: str) -> bool:
    """Pre-filter: skip obvious non-relevant emails."""
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    for skip in SKIP_SENDERS:
        if skip in sender_lower:
            return True

    for pattern in SKIP_SUBJECTS:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            return True

    return False


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
    # Truncate very long emails to avoid token waste
    if len(content) > 8000:
        content = content[:8000] + "\n\n[... truncated ...]"
    return content.strip() or msg.get("bodyPreview", "")


def _extract_json(raw: str) -> dict | None:
    """Try to extract JSON from LLM response, handling markdown wrapping."""
    raw = raw.strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` blocks
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


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
        result = _extract_json(raw)
        if result is None:
            logger.warning("Could not parse LLM response as JSON: %s", raw[:200])
        return result
    except Exception:
        logger.exception("LLM call failed")
        return None
