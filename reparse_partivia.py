"""
Re-parse all Partivia quotes from their original email text
using the updated LLM prompt that enforces room cost extraction.

Preserves: quote_status, image_url, website_url, source, created_at
Updates:   room_rates, raw_summary, and all other extracted fields
"""

import json
import os
import sys
import time

import anthropic

# ── Bootstrap Flask app context ──────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
from models import (
    db, EmailLog, PartiviaQuote, PartiviaRoomRate,
    PartiviaMeetingRoom, PartiviaFBOption,
)

app = create_app()


def build_system_prompt(existing_quotes):
    existing_list = '\n'.join(
        f'- [id={q.id}] {q.hotel_name} ({q.city}, {q.stars or "?"}★) '
        f'— stato: {q.quote_status}, date: {q.dates_proposed or "n/a"}'
        for q in existing_quotes
    ) or '(nessun preventivo ancora registrato)'

    return f"""You are an assistant that extracts hotel quote data from emails.
The event is "N!Partivia" — a corporate incentive trip in Spain.
Possible destinations: Barcellona, Madrid, Siviglia, Valencia.

Quotes already registered:
{existing_list}

Analyze the email and extract ALL hotel quotes/proposals present.
For each quote, extract:
- hotel_name (hotel name)
- city (Barcellona, Madrid, Siviglia or Valencia — always normalize to Italian spelling)
- stars (integer 1-5 or null)
- contact_name, contact_email (hotel contact)
- website_url (hotel website URL if mentioned, or null)
- dates_proposed (proposed dates, e.g. "10-13 October 2026" — MANDATORY, always extract available dates/periods mentioned in the email)
- rooms_available (available rooms)
- min_rooms_required (minimum rooms required)
- room_rates: list of objects with room_type, rate_per_night (with €, MANDATORY — always extract the nightly rate even if you need to calculate it from a total or package price), breakfast_included (yes/no/not specified), notes (in English, about room specifics only). NEVER leave rate_per_night empty or null — if the email mentions any price for rooms, extract it. If a total/package price is given instead of per-night, divide and note "calculated from total" in notes.
- meeting_rooms: list with name, capacity, rate, notes (in English — technical details: AV equipment, layout, natural light, etc.)
- fb_options: list with meal_type (Breakfast/Lunch/Dinner/Coffee Break/Gala Dinner/DDR), price_per_person, menu_description
- cancellation_policy, payment_terms, validity_date, commission
- total_estimate (total estimate if present)
- included_services (list of included services like WiFi, parking, etc.)
- notes (in English — only about rooms and meeting rooms, not general conditions)
- raw_summary (2-3 sentence summary in English — MUST always include room rates/costs per night, e.g. "Double rooms at €180/night". Room pricing is the most important information in the summary.)
- is_update: true if updating an existing quote (with match_id), false if new
- match_id: ID of existing quote if updating, null if new

IMPORTANT: All notes and raw_summary MUST be in English. Translate if the source is in another language.

CRITICAL: Room costs (rate_per_night) and dates_proposed are the MOST important data to extract.
- Every room_rates entry MUST have a rate_per_night value with € symbol. If the email quotes room prices in ANY format (per night, per stay, per person, package), convert to per-night rate and include it.
- dates_proposed MUST always be filled if any dates or periods are mentioned in the email (check-in/check-out, event dates, availability windows).
- The raw_summary MUST always mention the room rates (e.g. "rooms from €X to €Y per night") and the proposed dates.

If the message does NOT contain quotes (e.g. simple follow-up), set is_quote=false.

Reply ONLY with valid JSON (no markdown):
{{
  "quotes": [
    {{
      "hotel_name": "Hotel Example",
      "city": "Barcellona",
      "stars": 4,
      "contact_name": "Mario Rossi",
      "contact_email": "mario@hotel.com",
      "website_url": "https://www.hotelexample.com",
      "dates_proposed": "10-13 October 2026",
      "rooms_available": "80",
      "min_rooms_required": null,
      "room_rates": [
        {{"room_type": "Double", "rate_per_night": "€ 180", "breakfast_included": "yes", "notes": "Sea view upgrade available"}}
      ],
      "meeting_rooms": [
        {{"name": "Grand Hall", "capacity": "200 pax theatre", "rate": "€ 2,000/day", "notes": "AV included, natural daylight, 250sqm"}}
      ],
      "fb_options": [
        {{"meal_type": "Dinner", "price_per_person": "€ 55/pax", "menu_description": "3-course menu"}}
      ],
      "cancellation_policy": "Free cancellation up to 30 days",
      "payment_terms": "30% upon confirmation",
      "validity_date": "30/09/2026",
      "commission": "10%",
      "total_estimate": "€ 45,000",
      "included_services": ["WiFi", "Parking", "Gym"],
      "notes": "Room upgrade available on request",
      "raw_summary": "Hotel Example offers 80 double rooms at €180/night with breakfast included...",
      "is_update": false,
      "match_id": null
    }}
  ],
  "is_quote": true,
  "message_type": "quote",
  "summary": "Received quote from Hotel Example for Barcellona..."
}}"""


def parse_llm_response(raw):
    """Clean and parse LLM JSON response."""
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
        if raw.endswith('```'):
            raw = raw[:-3]
        raw = raw.strip()
    return json.loads(raw)


def match_quote_from_parsed(parsed_quotes, quote):
    """Find the best matching parsed quote for an existing DB quote."""
    hotel_lower = quote.hotel_name.lower().strip()
    for pq in parsed_quotes:
        if pq.get('hotel_name', '').lower().strip() == hotel_lower:
            return pq
    # Fuzzy: check if hotel name is contained
    for pq in parsed_quotes:
        pq_name = pq.get('hotel_name', '').lower().strip()
        if hotel_lower in pq_name or pq_name in hotel_lower:
            return pq
    return None


def update_quote_from_parsed(quote, pq):
    """Update a quote's fields from parsed data, preserving manual fields."""
    # Fields to update from LLM
    for field in ('contact_name', 'contact_email', 'dates_proposed',
                  'rooms_available', 'min_rooms_required',
                  'cancellation_policy', 'payment_terms', 'validity_date',
                  'commission', 'total_estimate', 'notes', 'raw_summary'):
        val = pq.get(field)
        if val is not None:
            setattr(quote, field, val)

    if pq.get('included_services'):
        quote.included_services = ', '.join(pq['included_services'])

    # Replace room_rates
    if pq.get('room_rates'):
        PartiviaRoomRate.query.filter_by(quote_id=quote.id).delete()
        for rr in pq['room_rates']:
            db.session.add(PartiviaRoomRate(
                quote_id=quote.id,
                room_type=rr.get('room_type', ''),
                rate_per_night=rr.get('rate_per_night'),
                breakfast_included=rr.get('breakfast_included'),
                notes=rr.get('notes'),
            ))

    # Replace meeting_rooms
    if pq.get('meeting_rooms'):
        PartiviaMeetingRoom.query.filter_by(quote_id=quote.id).delete()
        for mr in pq['meeting_rooms']:
            db.session.add(PartiviaMeetingRoom(
                quote_id=quote.id,
                name=mr.get('name', ''),
                capacity=mr.get('capacity'),
                rate=mr.get('rate'),
                notes=mr.get('notes'),
            ))

    # Replace fb_options
    if pq.get('fb_options'):
        PartiviaFBOption.query.filter_by(quote_id=quote.id).delete()
        for fb in pq['fb_options']:
            db.session.add(PartiviaFBOption(
                quote_id=quote.id,
                meal_type=fb.get('meal_type', ''),
                price_per_person=fb.get('price_per_person'),
                menu_description=fb.get('menu_description'),
            ))


def main():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    with app.app_context():
        # Group quotes by email_log_id to avoid re-parsing the same email
        quotes = PartiviaQuote.query.filter(
            PartiviaQuote.email_log_id.isnot(None)
        ).order_by(PartiviaQuote.email_log_id).all()

        if not quotes:
            print("No quotes with email_log_id found.")
            return

        # Group by email_log_id
        email_groups = {}
        for q in quotes:
            email_groups.setdefault(q.email_log_id, []).append(q)

        print(f"Found {len(quotes)} quotes from {len(email_groups)} emails to re-parse.\n")

        all_existing = PartiviaQuote.query.order_by(PartiviaQuote.city).all()
        system_prompt = build_system_prompt(all_existing)

        total_cost = 0.0
        updated = 0
        errors = 0

        for email_log_id, group_quotes in email_groups.items():
            email_log = EmailLog.query.get(email_log_id)
            if not email_log or not email_log.testo:
                print(f"  [SKIP] Email log {email_log_id}: no text found")
                errors += 1
                continue

            hotel_names = ', '.join(q.hotel_name for q in group_quotes)
            print(f"[Email #{email_log_id}] Re-parsing for: {hotel_names}")

            try:
                response = client.messages.create(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{'role': 'user', 'content': email_log.testo}],
                )

                raw = response.content[0].text.strip()
                parsed = parse_llm_response(raw)

                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                cost = (inp * 0.80 + out * 4.00) / 1_000_000
                total_cost += cost

                if not parsed.get('is_quote'):
                    print(f"  [SKIP] LLM says not a quote")
                    continue

                parsed_quotes = parsed.get('quotes', [])
                if not parsed_quotes:
                    print(f"  [SKIP] No quotes extracted")
                    continue

                for q in group_quotes:
                    pq = match_quote_from_parsed(parsed_quotes, q)
                    if pq:
                        # Check room rates
                        room_rates = pq.get('room_rates', [])
                        rates_with_price = [
                            rr for rr in room_rates
                            if rr.get('rate_per_night')
                        ]
                        update_quote_from_parsed(q, pq)
                        updated += 1
                        print(f"  [OK] {q.hotel_name}: {len(rates_with_price)}/{len(room_rates)} room rates with price, summary: {(pq.get('raw_summary') or '')[:80]}...")
                    else:
                        print(f"  [WARN] No match for {q.hotel_name} in parsed results")
                        errors += 1

                db.session.commit()

            except json.JSONDecodeError as e:
                print(f"  [ERROR] Invalid JSON from LLM: {e}")
                errors += 1
            except Exception as e:
                print(f"  [ERROR] {e}")
                errors += 1

            # Rate limiting
            time.sleep(0.5)

        print(f"\n{'='*60}")
        print(f"Done! Updated: {updated}, Errors: {errors}")
        print(f"Total LLM cost: €{round(total_cost * 0.92, 4)}")


if __name__ == '__main__':
    main()
