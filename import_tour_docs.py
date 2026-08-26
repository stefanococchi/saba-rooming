"""
Import passport and driving licence files from a ZIP archive.

Usage:
    python import_tour_docs.py /path/to/allegati_2026-08-26.zip

Extracts files into static/tour_docs/<guest_id>/ and updates
TourGuest.passport_file / driving_file columns.
"""

import sys
import os
import zipfile
import unicodedata

from app import create_app
from models import db, TourGuest


def _normalise(s):
    """Lowercase, strip accents, collapse spaces."""
    s = s.strip().lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = ' '.join(s.split())
    return s


def import_docs(zip_path):
    app = create_app()
    with app.app_context():
        guests = TourGuest.query.all()

        # Build lookup: normalised "nome cognome" and "cognome nome" → guest
        lookup = {}
        for g in guests:
            keys = [
                _normalise(f'{g.nome} {g.cognome}'),
                _normalise(f'{g.cognome} {g.nome}'),
                _normalise(g.cognome),
                _normalise(g.nome),
            ]
            for k in keys:
                if k and k not in lookup:
                    lookup[k] = g

        static_dir = os.path.join(os.path.dirname(__file__), 'static', 'tour_docs')
        os.makedirs(static_dir, exist_ok=True)

        zf = zipfile.ZipFile(zip_path)

        # Get unique folders (person names)
        folders = set()
        for n in zf.namelist():
            parts = n.split('/')
            if len(parts) >= 2 and parts[0]:
                folders.add(parts[0])

        matched = 0
        unmatched = []

        for folder in sorted(folders):
            norm_folder = _normalise(folder)

            # Try exact match first
            guest = lookup.get(norm_folder)

            # Try partial matches if no exact
            if not guest:
                # Try each word combination
                words = norm_folder.split()
                for i in range(len(words)):
                    for j in range(i + 1, len(words) + 1):
                        candidate = ' '.join(words[i:j])
                        if candidate in lookup:
                            guest = lookup[candidate]
                            break
                    if guest:
                        break

            # Try matching by surname only (last word)
            if not guest and words:
                for g in guests:
                    if _normalise(g.cognome) in norm_folder or norm_folder in _normalise(f'{g.nome} {g.cognome}'):
                        guest = g
                        break

            if not guest:
                unmatched.append(folder)
                continue

            matched += 1
            guest_dir = os.path.join(static_dir, str(guest.id))
            os.makedirs(guest_dir, exist_ok=True)

            # Extract files for this person
            for entry in zf.namelist():
                if not entry.startswith(folder + '/'):
                    continue
                filename = entry.split('/')[-1]
                if not filename:
                    continue

                # Write file
                target = os.path.join(guest_dir, filename)
                with open(target, 'wb') as f:
                    f.write(zf.read(entry))

                # Relative path from static/
                rel_path = f'tour_docs/{guest.id}/{filename}'

                if filename.startswith('pass_'):
                    guest.passport_file = rel_path
                elif filename.startswith('driv_'):
                    guest.driving_file = rel_path

            print(f'  {folder} → {guest.cognome} {guest.nome} (id={guest.id})')

        db.session.commit()
        print(f'\nMatched: {matched}/{len(folders)}')
        if unmatched:
            print(f'Unmatched ({len(unmatched)}):')
            for u in unmatched:
                print(f'  - {u}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: python {sys.argv[0]} <zip_path>')
        sys.exit(1)
    import_docs(sys.argv[1])
