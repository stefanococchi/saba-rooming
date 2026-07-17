from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
    source                = db.Column(db.String(20), default='manual')  # manual, xlsx, email
    email_log_id          = db.Column(db.Integer, db.ForeignKey('email_logs.id'))
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def nome_completo(self):
        return f'{self.cognome} {self.nome}'.strip()


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
    source              = db.Column(db.String(20), default='email')
    email_log_id        = db.Column(db.Integer, db.ForeignKey('email_logs.id'))
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow,
                                    onupdate=datetime.utcnow)

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
