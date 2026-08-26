"""
Import Liqui Moly Tour data from rooming XLSX into tour_* tables.

Usage:
    python import_tour.py /path/to/rooming_2026-08-26.xlsx

Reads the Completed sheet (guests + room assignments) and the Inventory
sheet (hotels + room categories).  Idempotent: drops and recreates all
tour_* rows on every run.
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

from app import create_app
from models import (db, TourHotel, TourRoomCategory,
                    TourGuest, TourRoomAssignment)

# ── Excel column-key → hotel metadata ────────────────────────────────

HOTEL_MAP = {
    # column_key          night_label  hotel_name                   city        night_date         rooms_blocked
    '1Sep_Paolovi':      ('1Sep',     'Centro Paolo VI',           'Brescia',  date(2026, 9, 1),  0),
    '2Sep_Paolovi':      ('2Sep',     'Centro Paolo VI',           'Brescia',  date(2026, 9, 2),  95),
    '3Sep_CasaEste':     ('3Sep',     "Hotel Casa d'Este 4*",      'Ferrara',  date(2026, 9, 3),  50),
    '3Sep_Carlton':      ('3Sep',     'Hotel Carlton 3*',          'Ferrara',  date(2026, 9, 3),  30),
    '3Sep_Europa':       ('3Sep',     'Hotel Europa 3*',           'Ferrara',  date(2026, 9, 3),  17),
    '4Sep_Arthur':       ('4Sep',     'Hotel Arthur',              'Maranello', date(2026, 9, 4),  43),
    '4Sep_Arthurino':    ('4Sep',     'Hotel Arthurino',           'Maranello', date(2026, 9, 4),  19),
    '4Sep_AcetaiaBoni':  ('4Sep',     'Dependance Boni',           'Maranello', date(2026, 9, 4),  8),
    '4Sep_Village':      ('4Sep',     'Hotel Maranello Village',   'Maranello', date(2026, 9, 4),  30),
    '5Sep_Paolovi':      ('5Sep',     'Centro Paolo VI',           'Brescia',  date(2026, 9, 5),  95),
}

# Spreadsheet column index (1-based) → column_key
COL_TO_KEY = {
    15: '1Sep_Paolovi',       # O
    17: '2Sep_Paolovi',       # Q
    19: '3Sep_CasaEste',      # S
    20: '3Sep_Carlton',       # T
    21: '3Sep_Europa',        # U
    22: '4Sep_Arthur',        # V
    23: '4Sep_Arthurino',     # W
    24: '4Sep_AcetaiaBoni',   # X
    25: '4Sep_Village',       # Y
    26: '5Sep_Paolovi',       # Z
}

# ── Inventory from the spreadsheet (hotel_name+night → categories) ───

INVENTORY = {
    # (night_label, hotel_name): [(category_name, code, rooms_available), ...]
    ('2Sep', 'Centro Paolo VI'): [
        ('Garden Single', 'GS', 23),
        ('Double Room (twin beds on request)', 'DBL', 18),
        ('King Room', 'KING', 17),
        ('Single Room', 'SGL', 14),
        ('Panorama Room', 'PAN', 9),
        ('King+ Room', 'KINGP', 7),
        ('XL Room', 'XL', 3),
        ('MonoloK', 'MONO', 3),
        ('FlatS', 'FLAT', 1),
    ],
    ('3Sep', "Hotel Casa d'Este 4*"): [
        ('Classic Single', 'CS', 4),
        ('Classic Double - Single Use', 'CD', 5),
        ('Premium Double - Single Use', 'PD', 25),
        ('Superior Double - Single Use', 'SD', 3),
        ('Deluxe Double - Single Use', 'DD', 2),
        ('Family Room - Single Use', 'FAM', 2),
        ('Junior Suite - Single Use', 'JS', 6),
        ('Suite - Single Use', 'SUITE', 2),
        ('Royal Suite - Single Use', 'ROYAL', 1),
    ],
    ('3Sep', 'Hotel Carlton 3*'): [
        ('Twin Rooms', 'TWIN', 10),
        ('Double Rooms', 'DBL', 10),
        ('Standard Room', 'TBC', 10),
    ],
    ('3Sep', 'Hotel Europa 3*'): [
        ('Single Rooms with Single Bed', 'SGL', 6),
        ('Double / Double for Single Use', 'DBL', 11),
    ],
    ('4Sep', 'Hotel Arthur'): [
        ('Junior Suites', 'JS', 3),
        ('Hotel Arthur Rooms', 'STD', 40),
    ],
    ('4Sep', 'Hotel Arthurino'): [
        ('House Arthurino Rooms', 'HOUSE', 5),
        ('Arthurino Rooms', 'STD', 14),
    ],
    ('4Sep', 'Dependance Boni'): [
        ('Dependance Boni Rooms', 'BONI', 8),
    ],
    ('4Sep', 'Hotel Maranello Village'): [
        ('Standard Double for Single Use', 'STD', 16),
        ('Deluxe Double for Single Use', 'DLX', 14),
    ],
    ('5Sep', 'Centro Paolo VI'): [
        ('Garden Single', 'GS', 27),
        ('Double Room (twin beds on request)', 'DBL', 15),
        ('King Room', 'KING', 18),
        ('Single Room', 'SGL', 14),
        ('Panorama Room', 'PAN', 8),
        ('King+ Room', 'KINGP', 7),
        ('XL Room', 'XL', 2),
        ('MonoloK', 'MONO', 3),
        ('FlatS', 'FLAT', 1),
    ],
}

# ── Helpers ──────────────────────────────────────────────────────────


def _read_xlsx_raw(path):
    """Read an xlsx without openpyxl, using raw XML."""
    zf = zipfile.ZipFile(path)
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

    # shared strings
    ss = []
    if 'xl/sharedStrings.xml' in zf.namelist():
        tree = ET.parse(zf.open('xl/sharedStrings.xml'))
        for si in tree.getroot().findall(f'{ns}si'):
            texts = si.findall(f'.//{ns}t')
            ss.append(''.join(t.text or '' for t in texts))

    # sheet1 = Completed
    tree = ET.parse(zf.open('xl/worksheets/sheet1.xml'))
    rows = []
    for row_el in tree.getroot().findall(f'.//{ns}row'):
        cells = {}
        for c in row_el.findall(f'{ns}c'):
            ref = c.get('r')
            val_el = c.find(f'{ns}v')
            val = val_el.text if val_el is not None else None
            if c.get('t') == 's' and val is not None:
                val = ss[int(val)]
            if val is not None:
                # parse column index from ref like "AA12"
                col_letters = ''.join(ch for ch in ref if ch.isalpha())
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
                cells[col_idx] = val
        rows.append(cells)
    return rows


def _parse_bool(val):
    if not val:
        return False
    return str(val).strip().lower() in ('yes', 'sì', 'si', 'true', '1', 'x', 'v')


def _serial_to_date_str(val):
    """Convert Excel serial date (e.g. 46267) to readable date."""
    try:
        serial = int(float(val))
        # Excel serial: 1 = 1900-01-01, but with the 1900 leap year bug
        from datetime import timedelta, date as dt_date
        base = dt_date(1899, 12, 30)
        d = base + timedelta(days=serial)
        return d.strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return str(val) if val else None


# ── Main ─────────────────────────────────────────────────────────────


def import_tour(xlsx_path):
    app = create_app()
    with app.app_context():
        # Clean previous tour data
        TourRoomAssignment.query.delete()
        TourGuest.query.delete()
        TourRoomCategory.query.delete()
        TourHotel.query.delete()
        db.session.commit()
        print('Cleaned tour tables.')

        # 1. Create hotels
        hotel_objs = {}  # column_key → TourHotel
        for col_key, (night_label, name, city, night_date, blocked) in HOTEL_MAP.items():
            h = TourHotel(
                night_label=night_label,
                night_date=night_date,
                column_key=col_key,
                hotel_name=name,
                city=city,
                rooms_blocked=blocked,
            )
            db.session.add(h)
            db.session.flush()
            hotel_objs[col_key] = h

            # Add room categories from INVENTORY
            # Inventory lists least→most important; reverse so sort_order 0 = best
            inv_key = (night_label, name)
            cats = INVENTORY.get(inv_key, [])
            for sort_order, (cat_name, code, avail) in enumerate(reversed(cats)):
                db.session.add(TourRoomCategory(
                    hotel_id=h.id,
                    category_name=cat_name,
                    code=code,
                    rooms_available=avail,
                    sort_order=sort_order,
                ))

        db.session.commit()
        print(f'Created {len(hotel_objs)} hotels with room categories.')

        # 2. Import guests from Completed sheet
        rows = _read_xlsx_raw(xlsx_path)
        if not rows:
            print('No data found.')
            return

        # Skip header (row 0)
        guest_count = 0
        for cells in rows[1:]:
            cognome = (cells.get(1) or '').strip()
            if not cognome:
                continue

            nome = (cells.get(2) or '').strip()
            g = TourGuest(
                cognome=cognome,
                nome=nome,
                email=(cells.get(3) or '').strip() or None,
                arrivo_mezzo=(cells.get(4) or '').strip() or None,
                nazionalita=(cells.get(5) or '').strip() or None,
                sept2=_parse_bool(cells.get(6)),
                telefono=(cells.get(7) or '').strip() or None,
                titolo=(cells.get(8) or '').strip() or None,
                arrivo_data=_serial_to_date_str(cells.get(9)),
                room_with=(cells.get(10) or '').strip() or None,
                car_number=(cells.get(11) or '').strip() or None,
                car_with=(cells.get(12) or '').strip() or None,
                vip=(cells.get(13) or '').strip() or None,
                client_room_note=(cells.get(14) or '').strip() or None,
                dinner=_parse_bool(cells.get(16)),     # col P = dinner
                payment=(cells.get(18) or '').strip() or None,   # col R = payment
                cloth_size=(cells.get(27) or '').strip() or None,  # col AA
                diet=(cells.get(28) or '').strip() or None,        # col AB
                notes=(cells.get(29) or '').strip() or None,       # col AC

                email_requests=(cells.get(30) or '').strip() or None,  # col AD
                source='xlsx',
            )
            # Detect cancelled participants (CANCELLED in notes, fee was paid)
            if g.notes and 'CANCELLED' in g.notes.upper():
                g.payment = 'PAID-CANCELLED'

            db.session.add(g)
            db.session.flush()

            # Room assignments from hotel columns (skip cancelled guests)
            if g.payment != 'PAID-CANCELLED':
                for col_idx, col_key in COL_TO_KEY.items():
                    room_code = (cells.get(col_idx) or '').strip()
                    if room_code:
                        hotel = hotel_objs[col_key]
                        db.session.add(TourRoomAssignment(
                            guest_id=g.id,
                            hotel_id=hotel.id,
                            room_code=room_code,
                        ))

            guest_count += 1

        db.session.commit()
        print(f'Imported {guest_count} guests with room assignments.')

        # Summary
        total_assignments = TourRoomAssignment.query.count()
        print(f'Total room assignments: {total_assignments}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: python {sys.argv[0]} <xlsx_path>')
        sys.exit(1)
    import_tour(sys.argv[1])
