# models.py

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

trade_criteria = db.Table('trade_criteria',
    db.Column('trade_id', db.Integer, db.ForeignKey('trade.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

setup_criteria = db.Table('setup_criteria',
    db.Column('setup_id', db.Integer, db.ForeignKey('setup.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.Integer, unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    trades = db.relationship('Trade', backref='user', lazy=True)
    setups = db.relationship('Setup', backref='user', lazy=True)

class InstrumentCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    instruments = db.relationship('Instrument', backref='category', lazy=True)

class Instrument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    category_id = db.Column(db.Integer, db.ForeignKey('instrument_category.id'), nullable=False)
    trades = db.relationship('Trade', backref='instrument', lazy=True)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    direction = db.Column(db.String(10))
    entry_price = db.Column(db.Float)
    exit_price = db.Column(db.Float, nullable=True)
    trade_open_time = db.Column(db.Date)
    trade_close_time = db.Column(db.Date, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    setup_id = db.Column(db.Integer, db.ForeignKey('setup.id'), nullable=True)
    screenshot = db.Column(db.String(100), nullable=True)
    profit_loss = db.Column(db.Float, nullable=True)
    profit_loss_percentage = db.Column(db.Float, nullable=True)
    criteria = db.relationship('Criterion', secondary=trade_criteria, backref='trades')

class Setup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_name = db.Column(db.String(100))
    description = db.Column(db.Text, nullable=True)
    screenshot = db.Column(db.String(100), nullable=True)
    criteria = db.relationship('Criterion', secondary=setup_criteria, backref='setups')
    trades = db.relationship('Trade', backref='setup', lazy=True)

class CriterionCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    subcategories = db.relationship('CriterionSubcategory', backref='category', lazy=True)

class CriterionSubcategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    category_id = db.Column(db.Integer, db.ForeignKey('criterion_category.id'), nullable=False)
    criteria = db.relationship('Criterion', backref='subcategory', lazy=True)

class Criterion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    subcategory_id = db.Column(db.Integer, db.ForeignKey('criterion_subcategory.id'), nullable=False)
