"""One-time script: import birth dates from allegati JSON into Guest records."""
import json
import sys
import unicodedata
from app import create_app
from models import db, Guest


def normalize(name):
    """Normalize name for fuzzy matching: lowercase, strip accents, remove apostrophes."""
    s = name.lower().strip()
    s = s.replace("'", "'").replace("'", "'")
    # Remove accents
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\ACER\Downloads\allegati_2026-08-19 equans.json"

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # Extract unique name → birth_date (take first non-null value per name)
    birth_dates = {}
    for key, date_val in data.items():
        name = key.split('/')[0].strip()
        if name not in birth_dates and date_val:
            birth_dates[name] = date_val

    print(f"Found {len(birth_dates)} unique names with birth dates in JSON")

    app = create_app()
    with app.app_context():
        guests = Guest.query.all()
        updated = 0
        not_found = []

        # Build lookup: normalized full name → Guest
        guest_lookup = {}
        for g in guests:
            key = normalize(f"{g.cognome} {g.nome}")
            guest_lookup[key] = g
            # Also reversed
            key_rev = normalize(f"{g.nome} {g.cognome}")
            if key_rev not in guest_lookup:
                guest_lookup[key_rev] = g

        for name, birth_date in birth_dates.items():
            norm = normalize(name)
            guest = guest_lookup.get(norm)
            if guest:
                guest.data_nascita = birth_date
                updated += 1
                print(f"  ✓ {name} → {birth_date}")
            else:
                not_found.append(name)

        db.session.commit()
        print(f"\nUpdated: {updated}/{len(birth_dates)}")
        if not_found:
            print(f"Not found ({len(not_found)}):")
            for n in not_found:
                print(f"  ✗ {n}")


if __name__ == '__main__':
    main()
