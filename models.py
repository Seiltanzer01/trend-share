# models.py

from datetime import datetime
from extensions import db

# Таблицы для связи многие-ко-многим
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
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    auth_token = db.Column(db.String(64), unique=True, nullable=True)
    auth_token_creation_time = db.Column(db.DateTime, nullable=True)
    registered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    assistant_premium = db.Column(db.Boolean, default=False)
    wallet_address = db.Column(db.String(42), unique=True, nullable=True)  # Основной кошелёк
    private_key = db.Column(db.String(128), nullable=True)  # Приватный ключ основного кошелька

    # **Новые поля для уникального кошелька**
    unique_wallet_address = db.Column(db.String(42), unique=True, nullable=True)  # Уникальный кошелёк для депозитов
    unique_private_key = db.Column(db.String(128), nullable=True)  # Приватный ключ уникального кошелька

    # Связи
    trades = db.relationship('Trade', back_populates='user', lazy=True)
    setups = db.relationship('Setup', back_populates='user', lazy=True)
    predictions = db.relationship('UserPrediction', back_populates='user', lazy=True)
    user_stakings = db.relationship('UserStaking', back_populates='user', lazy=True)

class UserStaking(db.Model):
    __tablename__ = 'user_staking'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    tx_hash = db.Column(db.String(66), unique=True, nullable=False)
    staked_usd = db.Column(db.Float, nullable=False)   # реальный эквивалент
    staked_amount = db.Column(db.Float, nullable=False)# токены
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    unlocked_at = db.Column(db.DateTime, nullable=False)
    
    # Для наград
    pending_rewards = db.Column(db.Float, default=0.0)  
    last_claim_at   = db.Column(db.DateTime, nullable=False)

    user = db.relationship('User', back_populates='user_stakings')

class InstrumentCategory(db.Model):
    __tablename__ = 'instrument_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    instruments = db.relationship('Instrument', back_populates='category', lazy=True)

class Instrument(db.Model):
    __tablename__ = 'instrument'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey('instrument_category.id'), nullable=False)
    category = db.relationship('InstrumentCategory', back_populates='instruments')
    trades = db.relationship('Trade', back_populates='instrument', lazy=True)
    poll_instruments = db.relationship('PollInstrument', back_populates='instrument', lazy=True)
    price_history = db.relationship('PriceHistory', back_populates='instrument', lazy=True)
    predictions = db.relationship('UserPrediction', back_populates='instrument', lazy=True)

class CriterionCategory(db.Model):
    __tablename__ = 'criterion_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    subcategories = db.relationship('CriterionSubcategory', back_populates='category', lazy=True)

class CriterionSubcategory(db.Model):
    __tablename__ = 'criterion_subcategory'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('criterion_category.id'), nullable=False)
    category = db.relationship('CriterionCategory', back_populates='subcategories')
    criteria = db.relationship('Criterion', back_populates='subcategory', lazy=True)

class Criterion(db.Model):
    __tablename__ = 'criterion'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('criterion_subcategory.id'), nullable=False)
    
    subcategory = db.relationship('CriterionSubcategory', back_populates='criteria')

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

    user = db.relationship('User', back_populates='trades')
    instrument = db.relationship('Instrument', back_populates='trades')
    setup = db.relationship('Setup', back_populates='trades')

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

    trades = db.relationship('Trade', back_populates='setup', lazy=True)
    user = db.relationship('User', back_populates='setups')

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
    poll_instruments = db.relationship('PollInstrument', back_populates='poll', lazy=True)
    real_prices = db.Column(db.JSON, nullable=True)  # Хранит реальные цены после завершения голосования
    predictions = db.relationship('UserPrediction', back_populates='poll', lazy=True)

class PollInstrument(db.Model):
    __tablename__ = 'poll_instrument'
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    instrument = db.relationship('Instrument', back_populates='poll_instruments')
    poll = db.relationship('Poll', back_populates='poll_instruments')

class UserPrediction(db.Model):
    __tablename__ = 'user_prediction'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    predicted_price = db.Column(db.Float, nullable=False)
    real_price = db.Column(db.Float, nullable=True)        # Добавлено поле real_price
    deviation = db.Column(db.Float, nullable=True)         # Добавлено поле deviation

    __table_args__ = (
        db.UniqueConstraint('user_id', 'poll_id', 'instrument_id', name='unique_user_poll_instrument'),
    )

    user = db.relationship('User', back_populates='predictions')
    poll = db.relationship('Poll', back_populates='predictions')
    instrument = db.relationship('Instrument', back_populates='predictions')

class Config(db.Model):
    __tablename__ = 'config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(50), nullable=False)

class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    
    id = db.Column(db.Integer, primary_key=True)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.BigInteger, nullable=False)
    
    instrument = db.relationship('Instrument', back_populates='price_history')
    
    __table_args__ = (db.UniqueConstraint('instrument_id', 'date', name='_instrument_date_uc'),)

class BestSetupCandidate(db.Model):
    __tablename__ = 'best_setup_candidate'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_id = db.Column(db.Integer, db.ForeignKey('setup.id'), nullable=False)
    total_trades = db.Column(db.Integer, nullable=False)
    win_rate = db.Column(db.Float, nullable=False)  # В процентах
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BestSetupVote(db.Model):
    __tablename__ = 'best_setup_vote'
    id = db.Column(db.Integer, primary_key=True)
    voter_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('best_setup_candidate.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BestSetupPoll(db.Model):
    __tablename__ = 'best_setup_poll'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')  # active, completed
