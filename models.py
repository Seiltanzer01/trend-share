# models.py

from datetime import datetime
from extensions import db
from collections import defaultdict

# Таблицы для связи многих ко многим
trade_criteria = db.Table('trade_criteria',
    db.Column('trade_id', db.Integer, db.ForeignKey('trade.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

setup_criteria = db.Table('setup_criteria',
    db.Column('setup_id', db.Integer, db.ForeignKey('setup.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)  # Изменено на BigInteger
    username = db.Column(db.String(80), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    auth_token = db.Column(db.String(64), unique=True, nullable=True)
    auth_token_creation_time = db.Column(db.DateTime, nullable=True)
    registered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    assistant_premium = db.Column(db.Boolean, default=False)  # Новое поле для подписки на ассистента
    trades = db.relationship('Trade', backref='user', lazy=True)
    setups = db.relationship('Setup', backref='user', lazy=True)
    predictions = db.relationship('UserPrediction', backref='user', lazy=True)

class InstrumentCategory(db.Model):
    __tablename__ = 'instrument_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    instruments = db.relationship('Instrument', backref='category', lazy=True)

class Instrument(db.Model):
    __tablename__ = 'instrument'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey('instrument_category.id'), nullable=False)
    trades = db.relationship('Trade', backref='instrument', lazy=True)
    poll_instruments = db.relationship('PollInstrument', backref='instrument', lazy=True)

class CriterionCategory(db.Model):
    __tablename__ = 'criterion_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    subcategories = db.relationship('CriterionSubcategory', backref='category', lazy=True)

class CriterionSubcategory(db.Model):
    __tablename__ = 'criterion_subcategory'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('criterion_category.id'), nullable=False)
    criteria = db.relationship('Criterion', backref='subcategory', lazy=True)

class Criterion(db.Model):
    __tablename__ = 'criterion'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('criterion_subcategory.id'), nullable=False)

    # Отношение с Trade
    trades = db.relationship(
        'Trade',
        secondary=trade_criteria,
        back_populates='criteria'
    )

    # Отношение с Setup
    setups = db.relationship(
        'Setup',
        secondary=setup_criteria,
        back_populates='criteria'
    )

class Trade(db.Model):
    __tablename__ = 'trade'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'Buy' или 'Sell'
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    trade_open_time = db.Column(db.Date, nullable=False)
    trade_close_time = db.Column(db.Date, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    setup_id = db.Column(db.Integer, db.ForeignKey('setup.id'), nullable=True)
    screenshot = db.Column(db.String(100), nullable=True)
    profit_loss = db.Column(db.Float, nullable=True)
    profit_loss_percentage = db.Column(db.Float, nullable=True)

    # Отношение с Criterion
    criteria = db.relationship(
        'Criterion',
        secondary=trade_criteria,
        back_populates='trades'
    )

class Setup(db.Model):
    __tablename__ = 'setup'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    screenshot = db.Column(db.String(100), nullable=True)

    # Отношение с Criterion
    criteria = db.relationship(
        'Criterion',
        secondary=setup_criteria,
        back_populates='setups'
    )

    trades = db.relationship('Trade', backref='setup', lazy=True)

class LoginToken(db.Model):
    __tablename__ = 'login_token'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    telegram_id = db.Column(db.BigInteger, db.ForeignKey('user.telegram_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

# Новые модели для голосования
class Poll(db.Model):
    __tablename__ = 'poll'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active')  # 'active' или 'completed'
    poll_instruments = db.relationship('PollInstrument', backref='poll', lazy=True)
    real_prices = db.Column(db.JSON, nullable=True)  # Хранит реальные цены после завершения голосования
    predictions = db.relationship('UserPrediction', backref='poll', lazy=True)

class PollInstrument(db.Model):
    __tablename__ = 'poll_instrument'
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    instrument = db.relationship('Instrument')

class UserPrediction(db.Model):
    __tablename__ = 'user_prediction'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    predicted_price = db.Column(db.Float, nullable=False)
    deviation = db.Column(db.Float, nullable=True)  # Отклонение от реальной цены после завершения голосования

    user = db.relationship('User')
    poll = db.relationship('Poll')
    instrument = db.relationship('Instrument')

# Модель Config для хранения настроек приложения
class Config(db.Model):
    __tablename__ = 'config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(50), nullable=False)
