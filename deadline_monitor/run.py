"""Entry point for deadline monitor: poll emails, parse, update DB.

Usage:
    python -m deadline_monitor.run              # process last 3 days
    python -m deadline_monitor.run --days 7     # process last 7 days
    python -m deadline_monitor.run --dry-run    # parse but don't update DB
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Add project root to path for models import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deadline_monitor.graph_client import fetch_recent_emails, tag_email
from deadline_monitor.processor import extract_email_text, parse_deadline_email, should_skip_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

MAILBOX = "info@sabae20.it"
STATE_FILE = Path(__file__).resolve().parent / ".last_check"


def _parse_date(date_str: str):
    """Try to parse a date string in DD/MM/YYYY or other common formats."""
    from datetime import datetime as dt
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.strptime(date_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _load_last_check() -> str | None:
    """Load timestamp of last successful check."""
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip() or None
    return None


def _save_last_check(iso_ts: str) -> None:
    STATE_FILE.write_text(iso_ts)


def _get_hotels_context(app) -> str:
    """Build context string of existing hotels for LLM matching."""
    from models import PartiviaQuote
    with app.app_context():
        quotes = PartiviaQuote.query.order_by(PartiviaQuote.hotel_name).all()
        if not quotes:
            return "(no hotels in system)"
        lines = []
        for q in quotes:
            lines.append(
                f"- [id={q.id}] {q.hotel_name} ({q.city}) "
                f"— deadline: {q.validity_date or 'not set'}, "
                f"status: {q.quote_status}, "
                f"contact: {q.contact_email or 'n/a'}"
            )
        return "\n".join(lines)


def _is_already_processed(app, internet_message_id: str) -> bool:
    """Check if this email was already processed (logged in email_logs)."""
    from models import EmailLog
    with app.app_context():
        existing = EmailLog.query.filter(
            EmailLog.testo.contains(internet_message_id),
            EmailLog.log_type == "deadline",
        ).first()
        return existing is not None


def _update_deadline(app, result: dict, email_text: str,
                     internet_message_id: str) -> bool:
    """Update the PartiviaQuote deadline in DB. Returns True if updated."""
    from models import EmailLog, PartiviaQuote, db

    match_id = result.get("match_hotel_id")
    hotel_name = result.get("hotel_name", "")
    new_deadline = result.get("new_deadline")
    notes = result.get("notes", "")

    if not new_deadline:
        logger.warning("No new_deadline extracted, skipping")
        return False

    with app.app_context():
        quote = None
        if match_id:
            quote = PartiviaQuote.query.get(match_id)

        # Fallback: fuzzy match by hotel name
        if not quote and hotel_name:
            all_quotes = PartiviaQuote.query.all()
            hotel_lower = hotel_name.lower()
            for q in all_quotes:
                if (hotel_lower in q.hotel_name.lower()
                        or q.hotel_name.lower() in hotel_lower):
                    quote = q
                    break

        if not quote:
            logger.warning("Could not match hotel '%s' (id=%s) in DB", hotel_name, match_id)
            return False

        old_deadline = quote.validity_date

        # Only update if new deadline is later than current
        if old_deadline and _parse_date(new_deadline) and _parse_date(old_deadline):
            if _parse_date(new_deadline) < _parse_date(old_deadline):
                logger.info(
                    "Skipping %s: new deadline %s is earlier than current %s",
                    quote.hotel_name, new_deadline, old_deadline,
                )
                return False

        quote.validity_date = new_deadline
        logger.info(
            "Updated %s deadline: %s -> %s",
            quote.hotel_name, old_deadline, new_deadline,
        )

        # Log the processed email
        log_entry = EmailLog(
            testo=f"[msg_id:{internet_message_id}]\n\n{email_text}",
            summary=f"Deadline extension: {quote.hotel_name} -> {new_deadline}. {notes}",
            log_type="deadline",
        )
        db.session.add(log_entry)
        db.session.commit()
        return True


def run(days: int = 3, dry_run: bool = False) -> dict:
    """Main entry point. Returns stats dict."""
    from app import create_app

    app = create_app()

    # Determine since when to fetch
    last_check = _load_last_check()
    if last_check:
        since_iso = last_check
        logger.info("Incremental check from %s", since_iso)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("Initial check, last %d days (since %s)", days, since_iso)

    stats = {"fetched": 0, "parsed": 0, "updated": 0, "skipped": 0, "errors": 0}

    try:
        messages = fetch_recent_emails(MAILBOX, since_iso)
    except Exception:
        logger.exception("Failed to fetch emails")
        return stats

    stats["fetched"] = len(messages)
    logger.info("Fetched %d emails", len(messages))

    if not messages:
        _save_last_check(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return stats

    hotels_context = _get_hotels_context(app)

    # Sort oldest first so newer deadlines always win
    messages.sort(key=lambda m: m.get("receivedDateTime", ""))

    for msg in messages:
        msg_id = msg.get("internetMessageId", "")
        subject = msg.get("subject", "")
        sender = (
            msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        )

        # Pre-filter: skip spam/newsletters/auto-replies
        if should_skip_email(sender, subject):
            logger.debug("Skipping (pre-filter): '%s' from %s", subject, sender)
            stats["skipped"] += 1
            continue

        # Skip already processed
        if msg_id and _is_already_processed(app, msg_id):
            stats["skipped"] += 1
            continue

        email_text = extract_email_text(msg)
        if not email_text:
            stats["skipped"] += 1
            continue

        logger.info("Processing: '%s' from %s", subject, sender)

        result = parse_deadline_email(email_text, sender, subject, hotels_context)
        if not result:
            stats["errors"] += 1
            continue

        stats["parsed"] += 1

        # Handle single result or array
        results = result.get("results", [result])
        for r in results:
            if not r.get("is_deadline_extension"):
                logger.info("Not a deadline extension, skipping")
                stats["skipped"] += 1
                continue

            confidence = r.get("confidence", "low")
            logger.info(
                "Deadline extension detected: %s -> %s (confidence: %s)",
                r.get("hotel_name"), r.get("new_deadline"), confidence,
            )

            if dry_run:
                logger.info("[DRY RUN] Would update: %s", json.dumps(r, indent=2))
                continue

            if confidence == "low":
                logger.warning("Low confidence, skipping auto-update for %s", r.get("hotel_name"))
                stats["skipped"] += 1
                continue

            if _update_deadline(app, r, email_text, msg_id):
                stats["updated"] += 1
                # Tag the email in Outlook (disabled: needs MailboxSettings.ReadWrite permission)
                # graph_msg_id = msg.get("id", "")
                # if graph_msg_id:
                #     try:
                #         tag_email(MAILBOX, graph_msg_id)
                #     except Exception:
                #         logger.warning("Failed to tag email, continuing", exc_info=True)
            else:
                stats["errors"] += 1

    # Save checkpoint
    latest_dt = max(
        (m.get("receivedDateTime", "") for m in messages), default=""
    )
    if latest_dt:
        _save_last_check(latest_dt)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Deadline extension email monitor")
    parser.add_argument("--days", type=int, default=3, help="Days to look back (first run)")
    parser.add_argument("--dry-run", action="store_true", help="Parse but don't update DB")
    args = parser.parse_args()

    stats = run(days=args.days, dry_run=args.dry_run)
    logger.info("Done. Stats: %s", json.dumps(stats))


if __name__ == "__main__":
    main()
