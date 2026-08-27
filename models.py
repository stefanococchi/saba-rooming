from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ── Auth & Audit ──────────────────────────────────────────────────────


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id                   = db.Column(db.Integer, primary_key=True)
    username             = db.Column(db.String(80), unique=True, nullable=False)
    email                = db.Column(db.String(150), unique=True, nullable=False)
    password_hash        = db.Column(db.String(256))
    is_superuser         = db.Column(db.Boolean, default=False)
    role                 = db.Column(db.String(20), default='user')   # superuser, user, client
    is_active            = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=True)
    sections             = db.Column(db.String(200), default='')  # comma-separated: rooming,partivia,tour
    failed_login_attempts = db.Column(db.Integer, default=0)
    microsoft_id         = db.Column(db.String(100), unique=True, nullable=True)
    ms_access_token      = db.Column(db.Text, nullable=True)
    ms_refresh_token     = db.Column(db.Text, nullable=True)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, pw)

    def register_failed_login(self):
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= 3:
            self.password_hash = None
            self.failed_login_attempts = 0
            self.must_change_password = True

    def reset_failed_logins(self):
        self.failed_login_attempts = 0

    def can_access(self, section):
        if self.is_superuser:
            return True
        allowed = [s.strip() for s in (self.sections or '').split(',') if s.strip()]
        if not allowed:
            return True  # no restriction = all sections
        return section in allowed

    @property
    def allowed_sections(self):
        if self.is_superuser:
            return ['rooming', 'partivia', 'tour']
        allowed = [s.strip() for s in (self.sections or '').split(',') if s.strip()]
        return allowed if allowed else ['rooming', 'partivia', 'tour']


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id           = db.Column(db.Integer, primary_key=True)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_email   = db.Column(db.String(150))
    section      = db.Column(db.String(20))       # rooming, partivia, tour
    entity_type  = db.Column(db.String(50))        # Guest, PartiviaQuote, TourGuest, ...
    entity_id    = db.Column(db.Integer)
    action       = db.Column(db.String(20))        # create, update, delete, restore, import, assign, unassign
    changes      = db.Column(db.JSON)              # {field: {old: X, new: Y}}
    summary      = db.Column(db.Text)
    ip_address   = db.Column(db.String(50))


class Todo(db.Model):
    __tablename__ = 'todos'

    id           = db.Column(db.Integer, primary_key=True)
    section      = db.Column(db.String(20), nullable=False, index=True)  # rooming, partivia, tour
    title        = db.Column(db.String(300), nullable=False)
    description  = db.Column(db.Text)
    owner        = db.Column(db.String(100))
    priority     = db.Column(db.String(20), default='normal')   # low, normal, high, urgent
    status       = db.Column(db.String(20), default='todo')     # todo, in_progress, done
    due_date     = db.Column(db.Date)
    created_by   = db.Column(db.String(100))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)


# ── Rooming ───────────────────────────────────────────────────────────


class Guest(db.Model):
    __tablename__ = 'guests'

    id                    = db.Column(db.Integer, primary_key=True)
    cognome               = db.Column(db.String(100), nullable=False)
    nome                  = db.Column(db.String(100), nullable=False)
    email                 = db.Column(db.String(200))
    telefono              = db.Column(db.String(50))
    sede_lavoro           = db.Column(db.String(200))
    presenza_8            = db.Column(db.Boolean, default=False)
    presenza_9            = db.Column(db.Boolean, default=False)
    presenza_10           = db.Column(db.Boolean, default=False)
    presenza_11           = db.Column(db.Boolean, default=False)
    volo_arrivo           = db.Column(db.String(200))
    volo_partenza         = db.Column(db.String(200))
    aeroporto_partenza    = db.Column(db.String(200))
    aeroporto_arrivo      = db.Column(db.String(200))
    pickup_bus_andata     = db.Column(db.String(100))
    pickup_bus_ritorno    = db.Column(db.String(100))
    parcheggio_linate     = db.Column(db.Boolean, default=False)
    parcheggio_hotel      = db.Column(db.Boolean, default=False)
    divide_stanza_con     = db.Column(db.String(200))
    restrizioni_alimentari = db.Column(db.String(300))
    tipo_camera           = db.Column(db.String(100))
    camera_assegnata      = db.Column(db.String(100))
    note_form             = db.Column(db.Text)
    note                  = db.Column(db.Text)
    data_nascita          = db.Column(db.String(20))
    source                = db.Column(db.String(20), default='manual')  # manual, xlsx, email
    pnr_group_id          = db.Column(db.Integer, db.ForeignKey('pnr_groups.id'))
    email_log_id          = db.Column(db.Integer, db.ForeignKey('email_logs.id'))
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted               = db.Column(db.Boolean, default=False, index=True)
    deleted_at            = db.Column(db.DateTime)

    @property
    def nome_completo(self):
        return f'{self.cognome} {self.nome}'.strip()


class RoomingClientToken(db.Model):
    __tablename__ = 'rooming_client_tokens'

    id         = db.Column(db.Integer, primary_key=True)
    label      = db.Column(db.String(100))
    token      = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PnrGroup(db.Model):
    __tablename__ = 'pnr_groups'

    id              = db.Column(db.Integer, primary_key=True)
    pnr_code        = db.Column(db.String(20), nullable=False, unique=True)
    group_name      = db.Column(db.String(100))
    seats           = db.Column(db.Integer, nullable=False)
    volo_andata     = db.Column(db.String(20))
    data_andata     = db.Column(db.String(20))
    rotta_andata    = db.Column(db.String(10))   # es. LINPMO
    orario_andata   = db.Column(db.String(20))   # es. 0955-1135
    volo_ritorno    = db.Column(db.String(20))
    data_ritorno    = db.Column(db.String(20))
    rotta_ritorno   = db.Column(db.String(10))
    orario_ritorno  = db.Column(db.String(20))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    guests = db.relationship('Guest', backref='pnr_group', lazy='joined')


class EmailLog(db.Model):
    __tablename__ = 'email_logs'

    id         = db.Column(db.Integer, primary_key=True)
    testo      = db.Column(db.Text, nullable=False)
    summary    = db.Column(db.Text)
    log_type   = db.Column(db.String(20), default='rooming')  # 'rooming' or 'partivia'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RoomContract(db.Model):
    __tablename__ = 'room_contracts'

    id             = db.Column(db.Integer, primary_key=True)
    tipo           = db.Column(db.String(100), nullable=False)
    disponibili    = db.Column(db.Integer, nullable=False)
    tariffa_netta  = db.Column(db.Float)
    tariffa_lorda  = db.Column(db.Float)
    notte          = db.Column(db.Integer, nullable=False)  # 8, 9, 10, 11


# ── Partivia: preventivi hotel ──────────────────────────────────────


class PartiviaQuote(db.Model):
    __tablename__ = 'partivia_quotes'

    id                  = db.Column(db.Integer, primary_key=True)
    hotel_name          = db.Column(db.String(200), nullable=False)
    city                = db.Column(db.String(100), nullable=False)
    stars               = db.Column(db.Integer)
    contact_name        = db.Column(db.String(200))
    contact_email       = db.Column(db.String(200))
    dates_proposed      = db.Column(db.Text)
    rooms_available     = db.Column(db.Text)
    min_rooms_required  = db.Column(db.Text)
    cancellation_policy = db.Column(db.Text)
    payment_terms       = db.Column(db.Text)
    validity_date       = db.Column(db.Text)
    commission          = db.Column(db.Text)
    total_estimate      = db.Column(db.Text)
    included_services   = db.Column(db.Text)       # comma-separated
    notes               = db.Column(db.Text)
    raw_summary         = db.Column(db.Text)
    quote_status        = db.Column(db.String(100), default='da_valutare')
    address             = db.Column(db.Text)
    image_url           = db.Column(db.Text)
    website_url         = db.Column(db.Text)
    vat_included        = db.Column(db.String(20))  # 'yes', 'no', 'unknown'
    hidden              = db.Column(db.Boolean, default=False)
    source              = db.Column(db.String(20), default='email')
    email_log_id        = db.Column(db.Integer, db.ForeignKey('email_logs.id'))
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow,
                                    onupdate=datetime.utcnow)
    deleted             = db.Column(db.Boolean, default=False, index=True)
    deleted_at          = db.Column(db.DateTime)

    room_rates    = db.relationship('PartiviaRoomRate', backref='quote',
                                    cascade='all, delete-orphan', lazy='joined')
    meeting_rooms = db.relationship('PartiviaMeetingRoom', backref='quote',
                                    cascade='all, delete-orphan', lazy='joined')
    fb_options    = db.relationship('PartiviaFBOption', backref='quote',
                                    cascade='all, delete-orphan', lazy='joined')


class PartiviaRoomRate(db.Model):
    __tablename__ = 'partivia_room_rates'

    id                 = db.Column(db.Integer, primary_key=True)
    quote_id           = db.Column(db.Integer,
                                   db.ForeignKey('partivia_quotes.id'), nullable=False)
    room_type          = db.Column(db.Text, nullable=False)
    rate_per_night     = db.Column(db.Text)
    breakfast_included = db.Column(db.Text)
    notes              = db.Column(db.Text)


class PartiviaMeetingRoom(db.Model):
    __tablename__ = 'partivia_meeting_rooms'

    id       = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer,
                         db.ForeignKey('partivia_quotes.id'), nullable=False)
    name     = db.Column(db.Text, nullable=False)
    capacity = db.Column(db.Text)
    rate     = db.Column(db.Text)
    notes    = db.Column(db.Text)


class PartiviaFBOption(db.Model):
    __tablename__ = 'partivia_fb_options'

    id               = db.Column(db.Integer, primary_key=True)
    quote_id         = db.Column(db.Integer,
                                 db.ForeignKey('partivia_quotes.id'), nullable=False)
    meal_type        = db.Column(db.Text, nullable=False)
    price_per_person = db.Column(db.Text)
    menu_description = db.Column(db.Text)


class BudgetOverride(db.Model):
    __tablename__ = 'budget_overrides'

    id         = db.Column(db.Integer, primary_key=True)
    data       = db.Column(db.JSON, default=dict)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Tour: Liqui Moly / eventi itineranti ─────────────────────────────


class TourHotel(db.Model):
    __tablename__ = 'tour_hotels'

    id             = db.Column(db.Integer, primary_key=True)
    night_label    = db.Column(db.String(20), nullable=False)   # "1Sep", "2Sep", …
    night_date     = db.Column(db.Date)                         # 2026-09-01
    column_key     = db.Column(db.String(50), nullable=False, unique=True)  # "2Sep_Paolovi"
    hotel_name     = db.Column(db.String(200), nullable=False)
    city           = db.Column(db.String(100))
    rooms_blocked  = db.Column(db.Integer, default=0)

    categories  = db.relationship('TourRoomCategory', backref='hotel',
                                   cascade='all, delete-orphan', lazy='joined',
                                   order_by='TourRoomCategory.sort_order')
    assignments = db.relationship('TourRoomAssignment', backref='hotel',
                                   cascade='all, delete-orphan', lazy='dynamic')


class TourRoomCategory(db.Model):
    __tablename__ = 'tour_room_categories'

    id              = db.Column(db.Integer, primary_key=True)
    hotel_id        = db.Column(db.Integer, db.ForeignKey('tour_hotels.id'), nullable=False)
    category_name   = db.Column(db.String(100), nullable=False)
    code            = db.Column(db.String(20), nullable=False)
    rooms_available = db.Column(db.Integer, default=0)
    rooms_requested = db.Column(db.Integer, default=0)  # camere originali richieste all'hotel
    sort_order      = db.Column(db.Integer, default=0)  # lower = more important


class TourGuest(db.Model):
    __tablename__ = 'tour_guests'

    id                = db.Column(db.Integer, primary_key=True)
    cognome           = db.Column(db.String(100), nullable=False)
    nome              = db.Column(db.String(100), nullable=False)
    email             = db.Column(db.String(200))
    telefono          = db.Column(db.String(50))
    nazionalita       = db.Column(db.String(100))
    titolo            = db.Column(db.String(10))        # Mr, Mrs
    arrivo_mezzo      = db.Column(db.String(50))        # Airplane, Car, Train, Other
    arrivo_data       = db.Column(db.String(20))        # data arrivo (es. "2Sep")
    room_with         = db.Column(db.String(200))       # compagno di stanza
    car_number        = db.Column(db.String(20))
    car_with          = db.Column(db.String(200))       # compagno di auto
    vip               = db.Column(db.String(50))        # VIP, ULTRA VIP, blank
    client_room_note  = db.Column(db.Text)
    dinner            = db.Column(db.Boolean, default=False)   # cena 2 Set
    dinner_5sep       = db.Column(db.Boolean, default=False)   # cena 5 Set
    sept2             = db.Column(db.Boolean, default=False)   # presenza 2 Set
    payment           = db.Column(db.String(50))        # PAID, TO COLLECT, NO NEED …
    cloth_size        = db.Column(db.String(10))        # S, M, L, XL, XXL, XXXL
    diet              = db.Column(db.String(300))
    notes             = db.Column(db.Text)
    email_requests    = db.Column(db.Text)
    passport_file     = db.Column(db.String(300))   # path relative to static/
    driving_file      = db.Column(db.String(300))   # path relative to static/
    source            = db.Column(db.String(20), default='manual')
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow,
                                   onupdate=datetime.utcnow)
    deleted           = db.Column(db.Boolean, default=False, index=True)
    deleted_at        = db.Column(db.DateTime)

    room_assignments = db.relationship('TourRoomAssignment', backref='guest',
                                        cascade='all, delete-orphan', lazy='joined')

    @property
    def nome_completo(self):
        return f'{self.cognome} {self.nome}'.strip()


class TourRoomAssignment(db.Model):
    __tablename__ = 'tour_room_assignments'

    id         = db.Column(db.Integer, primary_key=True)
    guest_id   = db.Column(db.Integer, db.ForeignKey('tour_guests.id'), nullable=False)
    hotel_id   = db.Column(db.Integer, db.ForeignKey('tour_hotels.id'), nullable=False)
    room_code  = db.Column(db.String(20))   # GS, KING, DBL-1, SGL, X …


class TourHotelToken(db.Model):
    """Unique access token for each hotel to view their guest documents."""
    __tablename__ = 'tour_hotel_tokens'

    id         = db.Column(db.Integer, primary_key=True)
    hotel_id   = db.Column(db.Integer, db.ForeignKey('tour_hotels.id'), nullable=False)
    token      = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hotel      = db.relationship('TourHotel', backref='tokens')


class TourGuestDocument(db.Model):
    """Passport and driving licence stored as BLOBs in DB."""
    __tablename__ = 'tour_guest_documents'

    id         = db.Column(db.Integer, primary_key=True)
    guest_id   = db.Column(db.Integer, db.ForeignKey('tour_guests.id'), nullable=False)
    doc_type   = db.Column(db.String(20), nullable=False)   # 'passport' or 'driving'
    filename   = db.Column(db.String(200))                   # original filename
    mime_type  = db.Column(db.String(100))                   # e.g. image/jpeg, application/pdf
    data       = db.Column(db.LargeBinary)                   # file content

    guest      = db.relationship('TourGuest', backref=db.backref(
                    'documents', cascade='all, delete-orphan', lazy='select'))


class TourClientToken(db.Model):
    """Access token for external clients to view the tour dashboard."""
    __tablename__ = 'tour_client_tokens'

    id         = db.Column(db.Integer, primary_key=True)
    label      = db.Column(db.String(100))              # e.g. "Liqui Moly team"
    token      = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TourHotelAccessLog(db.Model):
    """Log of every access to the hotel document portal."""
    __tablename__ = 'tour_hotel_access_logs'

    id         = db.Column(db.Integer, primary_key=True)
    token_id   = db.Column(db.Integer, db.ForeignKey('tour_hotel_tokens.id'), nullable=False)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.Text)
    action     = db.Column(db.String(50), default='view')  # view, download_one, download_all
    detail     = db.Column(db.String(200))                  # e.g. guest name for download_one
    accessed_at = db.Column(db.DateTime, default=datetime.utcnow)

    token      = db.relationship('TourHotelToken', backref='access_logs')
