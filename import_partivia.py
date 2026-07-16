"""Importa i preventivi da quotes.json (output del run Partivia) nel DB."""

import json
import sys
from pathlib import Path

from app import create_app
from models import (db, PartiviaQuote, PartiviaRoomRate,
                    PartiviaMeetingRoom, PartiviaFBOption)

QUOTES_JSON = Path(__file__).parent.parent / "saba-form" / "mail_digest" / "partivia_output" / "quotes.json"


def main():
    # Percorso alternativo se passato come argomento
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else QUOTES_JSON
    if not path.exists():
        print(f"File non trovato: {path}")
        sys.exit(1)

    with open(path, encoding='utf-8') as f:
        quotes_data = json.load(f)

    print(f"Trovati {len(quotes_data)} preventivi in {path.name}")

    app = create_app()
    with app.app_context():
        existing = PartiviaQuote.query.count()
        if existing > 0:
            print(f"ATTENZIONE: ci sono già {existing} preventivi nel DB.")
            resp = input("Vuoi aggiungerli comunque? (s/N) ").strip().lower()
            if resp != 's':
                print("Annullato.")
                return

        imported = 0
        for qd in quotes_data:
            q = PartiviaQuote(
                hotel_name=qd.get('hotel_name', ''),
                city=qd.get('city', ''),
                stars=qd.get('stars'),
                contact_name=qd.get('contact_name'),
                contact_email=qd.get('contact_email'),
                dates_proposed=qd.get('dates_proposed'),
                rooms_available=qd.get('rooms_available'),
                min_rooms_required=qd.get('min_rooms_required'),
                cancellation_policy=qd.get('cancellation_policy'),
                payment_terms=qd.get('payment_terms'),
                validity_date=qd.get('validity_date'),
                commission=qd.get('commission'),
                total_estimate=qd.get('total_estimate'),
                included_services=', '.join(qd.get('included_services', [])),
                notes=qd.get('notes'),
                raw_summary=qd.get('raw_summary'),
                quote_status=qd.get('quote_status', 'da_valutare'),
                source='import',
            )
            db.session.add(q)
            db.session.flush()  # per avere q.id

            for rr in qd.get('room_rates', []):
                db.session.add(PartiviaRoomRate(
                    quote_id=q.id,
                    room_type=rr.get('room_type', ''),
                    rate_per_night=rr.get('rate_per_night'),
                    breakfast_included=rr.get('breakfast_included'),
                    notes=rr.get('notes'),
                ))

            for mr in qd.get('meeting_rooms', []):
                db.session.add(PartiviaMeetingRoom(
                    quote_id=q.id,
                    name=mr.get('name', ''),
                    capacity=mr.get('capacity'),
                    rate=mr.get('rate'),
                    notes=mr.get('notes'),
                ))

            for fb in qd.get('fb_options', []):
                db.session.add(PartiviaFBOption(
                    quote_id=q.id,
                    meal_type=fb.get('meal_type', ''),
                    price_per_person=fb.get('price_per_person'),
                    menu_description=fb.get('menu_description'),
                ))

            imported += 1
            print(f"  [{imported}] {q.hotel_name} ({q.city}) — "
                  f"{len(qd.get('room_rates', []))} tariffe, "
                  f"{len(qd.get('meeting_rooms', []))} sale, "
                  f"{len(qd.get('fb_options', []))} F&B")

        db.session.commit()
        print(f"\nImportati {imported} preventivi nel DB.")


if __name__ == '__main__':
    main()
