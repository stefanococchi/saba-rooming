"""
Import passport and driving licence files from a ZIP archive.

Usage:
    python import_tour_docs.py /path/to/allegati_2026-08-26.zip

Stores files as BLOBs in tour_guest_documents table and updates
TourGuest.passport_file / driving_file with the filename.
"""

import sys
import mimetypes
import zipfile
import unicodedata

from app import create_app
from models import db, TourGuest, TourGuestDocument


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
                words = norm_folder.split()
                for i in range(len(words)):
                    for j in range(i + 1, len(words) + 1):
                        candidate = ' '.join(words[i:j])
                        if candidate in lookup:
                            guest = lookup[candidate]
                            break
                    if guest:
                        break

            # Try matching by surname only
            if not guest:
                for g in guests:
                    if _normalise(g.cognome) in norm_folder or norm_folder in _normalise(f'{g.nome} {g.cognome}'):
                        guest = g
                        break

            if not guest:
                unmatched.append(folder)
                continue

            matched += 1

            # Remove existing docs for this guest
            TourGuestDocument.query.filter_by(guest_id=guest.id).delete()

            for entry in zf.namelist():
                if not entry.startswith(folder + '/'):
                    continue
                filename = entry.split('/')[-1]
                if not filename:
                    continue

                file_data = zf.read(entry)
                mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

                if filename.startswith('pass_'):
                    doc_type = 'passport'
                    guest.passport_file = filename
                elif filename.startswith('driv_'):
                    doc_type = 'driving'
                    guest.driving_file = filename
                else:
                    continue

                db.session.add(TourGuestDocument(
                    guest_id=guest.id,
                    doc_type=doc_type,
                    filename=filename,
                    mime_type=mime,
                    data=file_data,
                ))

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
