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
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def nome_completo(self):
        return f'{self.cognome} {self.nome}'.strip()


class RoomContract(db.Model):
    __tablename__ = 'room_contracts'

    id             = db.Column(db.Integer, primary_key=True)
    tipo           = db.Column(db.String(100), nullable=False)
    disponibili    = db.Column(db.Integer, nullable=False)
    tariffa_netta  = db.Column(db.Float)
    tariffa_lorda  = db.Column(db.Float)
    notte          = db.Column(db.Integer, nullable=False)  # 8, 9, 10, 11
