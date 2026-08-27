"""
Parse hotel rooming XLSX files and populate rooms_requested on TourRoomCategory.

Each XLSX has columns: N, Tipo, Descrizione, Camera, Arrivo, Partenza, Cognome, Nome, ...
We count unique rooms per room type code (Tipo column) and update the DB.

File naming convention:
  rooming_3Sep_Hotel_Carlton_3.xlsx  → night_label=3Sep, hotel contains "Carlton"
  rooming_4Sep_Hotel_Arthur.xlsx     → night_label=4Sep, hotel contains "Arthur"
  rooming 2 sett paolo vi.xlsx      → night_label=2Sep, hotel contains "Paolo"

Usage:
  python import_requested_rooms.py [folder_path]

Default folder: C:\\Users\\ACER\\Downloads\\ROOMING 25 ago
"""
import os
import sys
import re
import openpyxl
from collections import Counter

# Map file patterns to (night_label, hotel_name_fragment)
FILE_PATTERNS = [
    (r'2 sett paolo vi', '2Sep', 'Paolo'),
    (r'5 ago paolo vi', '1Sep', 'Paolo'),      # 5 agosto = night 1Sep (arrival night)
    (r'3Sep_Hotel_Carlton', '3Sep', 'Carlton'),
    (r'3Sep_Hotel_Casa_dEste', '3Sep', "Casa d'Este"),
    (r'3Sep_Hotel_Europa', '3Sep', 'Europa'),
    (r'4Sep_Hotel_Arthur\.', '4Sep', 'Arthur'),
    (r'4Sep_Hotel_Arthurino', '4Sep', 'Arthurino'),
    (r'4Sep_Hotel_Maranello', '4Sep', 'Maranello'),
]


def parse_rooming_file(filepath):
    """Parse an XLSX rooming file and return room type counts."""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    # Find header row (look for "Tipo" or "N" in first column)
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=False), 1):
        vals = [str(c.value or '').strip().lower() for c in row]
        if 'tipo' in vals or 'n' in vals:
            header_row = row_idx
            break

    if not header_row:
        print(f'  WARNING: No header found in {filepath}')
        return {}

    # Find "Tipo" and "Camera" column indices
    headers = [str(c.value or '').strip().lower() for c in ws[header_row]]
    tipo_col = headers.index('tipo') if 'tipo' in headers else None
    camera_col = headers.index('camera') if 'camera' in headers else None

    if tipo_col is None:
        print(f'  WARNING: No "Tipo" column in {filepath}')
        return {}

    # Count unique rooms per type
    # A room is identified by "Camera" value; if two guests share a room,
    # they have the same Camera value (second guest has no Tipo)
    room_types = Counter()
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        vals = list(row)
        tipo = str(vals[tipo_col] or '').strip().upper() if tipo_col < len(vals) else ''
        if tipo:
            room_types[tipo] += 1

    return dict(room_types)


def match_file_to_hotel(filename):
    """Match a filename to (night_label, hotel_name_fragment)."""
    for pattern, night, hotel_frag in FILE_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            return night, hotel_frag
    return None, None


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\ACER\Downloads\ROOMING 25 ago'

    # First, just parse and show what we found
    results = []
    for fname in os.listdir(folder):
        if not fname.endswith('.xlsx'):
            continue
        night, hotel_frag = match_file_to_hotel(fname)
        if not night:
            print(f'SKIP: {fname} (no pattern match)')
            continue

        fpath = os.path.join(folder, fname)
        counts = parse_rooming_file(fpath)
        print(f'\n{fname}')
        print(f'  → night={night}, hotel=*{hotel_frag}*')
        print(f'  Room types: {dict(counts)}')
        total = sum(counts.values())
        print(f'  Total rooms: {total}')
        results.append((night, hotel_frag, counts))

    if not results:
        print('No files matched!')
        return

    # Now update DB
    print('\n--- Updating database ---')
    from app import create_app
    app = create_app()
    with app.app_context():
        from models import db, TourHotel, TourRoomCategory

        for night, hotel_frag, counts in results:
            # Find matching hotel
            hotels = TourHotel.query.filter_by(night_label=night).all()
            hotel = None
            for h in hotels:
                if hotel_frag.lower() in h.hotel_name.lower():
                    hotel = h
                    break

            if not hotel:
                print(f'  WARNING: No hotel found for night={night} fragment="{hotel_frag}"')
                print(f'    Available: {[h.hotel_name for h in hotels]}')
                continue

            print(f'\n  {hotel.hotel_name} ({hotel.night_label}):')
            categories = TourRoomCategory.query.filter_by(hotel_id=hotel.id).all()
            cat_map = {c.code.upper(): c for c in categories}

            for room_code, count in counts.items():
                cat = cat_map.get(room_code.upper())
                if cat:
                    old = cat.rooms_requested
                    cat.rooms_requested = count
                    print(f'    {room_code}: requested={count} (was {old})')
                else:
                    print(f'    {room_code}: no matching category (codes: {list(cat_map.keys())})')

        db.session.commit()
        print('\nDone!')


if __name__ == '__main__':
    main()
