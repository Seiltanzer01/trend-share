# app.py

import os
import traceback
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime

from flask import (
    Flask, render_template, redirect, url_for, flash,
    request, send_from_directory, session, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, upgrade
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, DecimalField, TextAreaField, DateTimeField, FileField, SelectMultipleField
from wtforms.validators import DataRequired, Length, Optional

from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, CallbackQueryHandler
)

import logging
import requests
import asyncio
from dotenv import load_dotenv

# Импорт Flask-Talisman
from flask_talisman import Talisman

# Загрузка переменных окружения из .env файла (если используется)
load_dotenv()

# Инициализация Flask-приложения
app = Flask(__name__)

# Настройка CORS
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            "https://trend-share.onrender.com",  # Ваш основной домен
            "https://oauth.telegram.org",        # Домен Telegram OAuth
            "https://web.telegram.org",         # Домен Telegram WebApp
            "https://telegram.org"              # Домен Telegram
        ]
    }
})

# Настройка логирования
logging.basicConfig(level=logging.INFO)  # Измените на DEBUG для детального логирования
logger = logging.getLogger(__name__)

# Использование переменных окружения для конфиденциальных данных
secret_key_env = os.environ.get('SECRET_KEY', '').strip()
if not secret_key_env:
    logger.error("SECRET_KEY не установлен в переменных окружения.")
    raise ValueError("SECRET_KEY не установлен в переменных окружения.")
app.secret_key = secret_key_env

# Настройки базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///trades.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка APP_HOST для формирования ссылок авторизации
app.config['APP_HOST'] = os.environ.get('APP_HOST', 'trend-share.onrender.com')

# Настройка токена бота для использования в приложении
app.config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_TOKEN', '').strip()
if not app.config['TELEGRAM_BOT_TOKEN']:
    logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
    raise ValueError("TELEGRAM_TOKEN не установлен в переменных окружения.")

# Настройки сессии
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Позволяет куки-сессиям работать в кросс-доменных запросах
app.config['SESSION_COOKIE_SECURE'] = True  # Требует HTTPS

# Инициализация SQLAlchemy
db = SQLAlchemy(app)

# Инициализация Flask-Migrate
migrate = Migrate(app, db)

# Инициализация Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Название маршрута для страницы логина

# Настройка папки для загрузки файлов
app.config['UPLOAD_FOLDER'] = 'uploads'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Контекстный процессор для предоставления datetime в шаблонах
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# Вспомогательная функция для получения хоста приложения
def get_app_host():
    """
    Возвращает хост приложения для формирования ссылок авторизации.
    """
    return app.config.get('APP_HOST', 'trend-share.onrender.com')

# Настройка Content Security Policy с помощью Flask-Talisman
csp = """
default-src 'self' https://telegram.org https://web.telegram.org https://oauth.telegram.org;
script-src 'self' https://telegram.org https://web.telegram.org https://oauth.telegram.org 'nonce-{nonce}';
style-src 'self' https://telegram.org https://web.telegram.org https://oauth.telegram.org 'unsafe-inline';
img-src 'self' data: https://telegram.org https://web.telegram.org https://oauth.telegram.org;
frame-ancestors 'self' https://web.telegram.org https://oauth.telegram.org https://telegram.org;
"""

talisman = Talisman(
    app,
    content_security_policy=csp,
    content_security_policy_nonce_in=['script-src'],
    frame_options=None  # Отключаем X-Frame-Options, чтобы использовать frame-ancestors в CSP
)

# Определение моделей

# Association table for many-to-many relationship between Trade and Criterion
trade_criteria = db.Table('trade_criteria',
    db.Column('trade_id', db.Integer, db.ForeignKey('trade.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

# Association table for many-to-many relationship between Setup and Criterion
setup_criteria = db.Table('setup_criteria',
    db.Column('setup_id', db.Integer, db.ForeignKey('setup.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.Integer, unique=True, nullable=False)
    username = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    trades = db.relationship('Trade', backref='user', lazy=True)
    setups = db.relationship('Setup', backref='user', lazy=True)

    def get_id(self):
        return str(self.id)

class InstrumentCategory(db.Model):
    __tablename__ = 'instrument_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    instruments = db.relationship('Instrument', backref='category', lazy=True)

class Instrument(db.Model):
    __tablename__ = 'instrument'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('instrument_category.id'), nullable=False)
    trades = db.relationship('Trade', backref='instrument', lazy=True)

class CriterionCategory(db.Model):
    __tablename__ = 'criterion_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    subcategories = db.relationship('CriterionSubcategory', backref='category', lazy=True)

class CriterionSubcategory(db.Model):
    __tablename__ = 'criterion_subcategory'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('criterion_category.id'), nullable=False)
    criteria = db.relationship('Criterion', backref='subcategory', lazy=True)

class Criterion(db.Model):
    __tablename__ = 'criterion'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('criterion_subcategory.id'), nullable=False)
    trades = db.relationship('Trade', secondary=trade_criteria, backref=db.backref('criteria', lazy='dynamic'))
    setups = db.relationship('Setup', secondary=setup_criteria, backref=db.backref('criteria', lazy='dynamic'))

class Trade(db.Model):
    __tablename__ = 'trade'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'Buy' или 'Sell'
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    trade_open_time = db.Column(db.DateTime, nullable=False)
    trade_close_time = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    setup_id = db.Column(db.Integer, db.ForeignKey('setup.id'), nullable=True)
    profit_loss = db.Column(db.Float, nullable=True)
    profit_loss_percentage = db.Column(db.Float, nullable=True)
    screenshot = db.Column(db.String(300), nullable=True)

class Setup(db.Model):
    __tablename__ = 'setup'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    screenshot = db.Column(db.String(300), nullable=True)
    trades = db.relationship('Trade', backref='setup', lazy=True)

# Определение форм

class TradeForm(FlaskForm):
    instrument = SelectField('Инструмент', coerce=int, validators=[DataRequired()])
    direction = SelectField('Направление', choices=[('Buy', 'Buy'), ('Sell', 'Sell')], validators=[DataRequired()])
    entry_price = DecimalField('Цена входа', places=2, validators=[DataRequired()])
    exit_price = DecimalField('Цена выхода', places=2, validators=[Optional()])
    trade_open_time = DateTimeField('Время открытия сделки', format='%Y-%m-%d %H:%M', validators=[DataRequired()])
    trade_close_time = DateTimeField('Время закрытия сделки', format='%Y-%m-%d %H:%M', validators=[Optional()])
    comment = TextAreaField('Комментарий', validators=[Optional(), Length(max=500)])
    setup_id = SelectField('Сетап', coerce=int, validators=[Optional()])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional()])
    submit = SubmitField('Сохранить')

class SetupForm(FlaskForm):
    setup_name = StringField('Название сетапа', validators=[DataRequired(), Length(max=150)])
    description = TextAreaField('Описание', validators=[Optional(), Length(max=1000)])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional()])
    submit = SubmitField('Сохранить')

# Функция загрузки предопределённых данных
def create_predefined_data():
    # Проверяем, есть ли уже данные
    if InstrumentCategory.query.first():
        logger.info("Предопределённые данные уже существуют. Пропуск создания.")
        return

    # Создаём категории инструментов и инструменты
    instruments = [
        # Валютные пары (Форекс)
        {'name': 'EUR/USD', 'category': 'Форекс'},
        {'name': 'GBP/USD', 'category': 'Форекс'},
        {'name': 'USD/JPY', 'category': 'Форекс'},
        {'name': 'USD/CHF', 'category': 'Форекс'},
        {'name': 'AUD/USD', 'category': 'Форекс'},
        {'name': 'USD/CAD', 'category': 'Форекс'},
        {'name': 'NZD/USD', 'category': 'Форекс'},
        {'name': 'EUR/GBP', 'category': 'Форекс'},
        {'name': 'EUR/JPY', 'category': 'Форекс'},
        {'name': 'GBP/JPY', 'category': 'Форекс'},
        # Индексы
        {'name': 'S&P 500', 'category': 'Индексы'},
        {'name': 'Dow Jones', 'category': 'Индексы'},
        {'name': 'NASDAQ', 'category': 'Индексы'},
        {'name': 'DAX', 'category': 'Индексы'},
        {'name': 'FTSE 100', 'category': 'Индексы'},
        {'name': 'CAC 40', 'category': 'Индексы'},
        {'name': 'Nikkei 225', 'category': 'Индексы'},
        {'name': 'Hang Seng', 'category': 'Индексы'},
        {'name': 'ASX 200', 'category': 'Индексы'},
        {'name': 'Euro Stoxx 50', 'category': 'Индексы'},
        # Товары
        {'name': 'Gold', 'category': 'Товары'},
        {'name': 'Silver', 'category': 'Товары'},
        {'name': 'Crude Oil', 'category': 'Товары'},
        {'name': 'Natural Gas', 'category': 'Товары'},
        {'name': 'Copper', 'category': 'Товары'},
        {'name': 'Corn', 'category': 'Товары'},
        {'name': 'Wheat', 'category': 'Товары'},
        {'name': 'Soybean', 'category': 'Товары'},
        {'name': 'Coffee', 'category': 'Товары'},
        {'name': 'Sugar', 'category': 'Товары'},
        # Криптовалюты
        {'name': 'BTC/USDT', 'category': 'Криптовалюты'},
        {'name': 'ETH/USDT', 'category': 'Криптовалюты'},
        {'name': 'BNB/USDT', 'category': 'Криптовалюты'},
        {'name': 'XRP/USDT', 'category': 'Криптовалюты'},
        {'name': 'ADA/USDT', 'category': 'Криптовалюты'},
        {'name': 'SOL/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOT/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOGE/USDT', 'category': 'Криптовалюты'},
        {'name': 'AVAX/USDT', 'category': 'Криптовалюты'},
        {'name': 'SHIB/USDT', 'category': 'Криптовалюты'},
        # Добавьте больше инструментов по необходимости
    ]

    for instrument_data in instruments:
        category_name = instrument_data['category']
        instrument_name = instrument_data['name']

        # Получаем или создаём категорию
        category = InstrumentCategory.query.filter_by(name=category_name).first()
        if not category:
            category = InstrumentCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Категория '{category_name}' добавлена.")

        # Проверяем, существует ли инструмент
        instrument = Instrument.query.filter_by(name=instrument_name).first()
        if not instrument:
            instrument = Instrument(name=instrument_name, category_id=category.id)
            db.session.add(instrument)
            logger.info(f"Инструмент '{instrument_name}' добавлен в категорию '{category_name}'.")

    db.session.commit()
    logger.info("Инструменты и категории инструментов успешно добавлены.")

    # Создаём категории критериев, подкатегории и критерии
    categories_data = {
        'Технический анализ': {
            'Трендовые индикаторы': [
                'Скользящая средняя (MA)',
                'Экспоненциальная скользящая средняя (EMA)',
                'Линии тренда',
                'Parabolic SAR',
                'Индекс среднего направления движения (ADX)'
            ],
            'Осцилляторы': [
                'Индекс относительной силы (RSI)',
                'Стохастик',
                'MACD',
                'CCI (Commodity Channel Index)',
                'Momentum'
            ],
            'Объёмные индикаторы': [
                'On Balance Volume (OBV)',
                'Индекс денежного потока (MFI)',
                'Accumulation/Distribution',
                'Volume Profile',
                'VWAP (Volume Weighted Average Price)'
            ],
            'Волатильность': [
                'Bollinger Bands',
                'ATR (Average True Range)',
                'Каналы Кельтнера',
                'Donchian Channels',
                'Envelope Channels'
            ],
            'Фигуры технического анализа': [
                'Голова и плечи',
                'Двойная вершина/двойное дно',
                'Флаги и вымпелы',
                'Клинья',
                'Треугольники'
            ],
            'Свечные паттерны': [
                'Молот и перевёрнутый молот',
                'Поглощение',
                'Доджи',
                'Харами',
                'Завеса из тёмных облаков'
            ]
        },
        'Смарт-мани': {
            'Уровни': [
                'Уровни поддержки',
                'Уровни сопротивления',
                'Психологические уровни',
                'Фибоначчи уровни',
                'Pivot Points'
            ],
            'Ликвидность': [
                'Зоны ликвидности',
                'Области с высокими объёмами',
                'Накопление и распределение',
                'Имбаланс рынка',
                'Stop Loss Hunting'
            ],
            'Позиционирование крупных игроков': [
                'Крупные сделки',
                'Объёмные всплески',
                'Open Interest',
                'Commitment of Traders (COT) Report',
                'Dark Pool Prints'
            ]
        },
        'Рыночная структура': {
            'Тренды': [
                'Восходящий тренд',
                'Нисходящий тренд',
                'Боковой тренд',
                'Изменение тренда',
                'Ложные пробои'
            ],
            'Импульсы и коррекции': [
                'Импульсные движения',
                'Коррекционные движения',
                'Волны Эллиотта',
                'Цикличность рынка',
                'Время коррекции'
            ],
            'Паттерны': [
                'Price Action паттерны',
                'Паттерн 1-2-3',
                'Пин-бары',
                'Внутренний бар',
                'Outside Bar'
            ]
        },
        'Психологические факторы': {
            'Эмоции': [
                'Страх',
                'Жадность',
                'Уверенность',
                'Нерешительность',
                'Переутомление'
            ],
            'Дисциплина': [
                'Следование торговому плану',
                'Риск-менеджмент',
                'Мани-менеджмент',
                'Журналирование сделок',
                'Самоконтроль'
            ],
            'Психология толпы': [
                'Следование за толпой',
                'Противоположное мнение',
                'Эффект FOMO',
                'Панические продажи',
                'Эйфория рынка'
            ]
        },
        'Фундаментальный анализ': {
            'Экономические индикаторы': [
                'Валовой внутренний продукт (ВВП)',
                'Уровень безработицы',
                'Процентные ставки',
                'Инфляция',
                'Торговый баланс'
            ],
            'Корпоративные показатели': [
                'Прибыль на акцию (EPS)',
                'Срок окупаемости инвестиций (ROI)',
                'Долговая нагрузка',
                'Маржа прибыли',
                'Доходность капитала (ROE)'
            ]
        },
        'Психология рынка': {
            'Поведенческие паттерны': [
                'Чрезмерная оптимистичность',
                'Чрезмерный пессимизм',
                'Ретестирование уровней',
                'Формирование новых трендов',
                'Контртрендовые движения'
            ]
        }
    }

    for category_name, subcategories in categories_data.items():
        category = CriterionCategory.query.filter_by(name=category_name).first()
        if not category:
            category = CriterionCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Категория критерия '{category_name}' добавлена.")

        for subcategory_name, criteria_list in subcategories.items():
            subcategory = CriterionSubcategory.query.filter_by(name=subcategory_name, category_id=category.id).first()
            if not subcategory:
                subcategory = CriterionSubcategory(
                    name=subcategory_name,
                    category_id=category.id
                )
                db.session.add(subcategory)
                db.session.flush()
                logger.info(f"Подкатегория '{subcategory_name}' добавлена в категорию '{category_name}'.")

            for criterion_name in criteria_list:
                criterion = Criterion.query.filter_by(name=criterion_name).first()
                if not criterion:
                    criterion = Criterion(
                        name=criterion_name,
                        subcategory_id=subcategory.id
                    )
                    db.session.add(criterion)
                    logger.info(f"Критерий '{criterion_name}' добавлен в подкатегорию '{subcategory_name}'.")

    db.session.commit()
    logger.info("Критерии, подкатегории и категории критериев успешно добавлены.")

# Вызываем функцию перед первым запросом
@app.before_first_request
def initialize():
    with app.app_context():
        try:
            upgrade()  # Применение миграций
            create_predefined_data()
            logger.info("Миграции применены и предопределённые данные созданы.")
        except Exception as e:
            logger.error(f"Ошибка при применении миграций: {e}")
            logger.error(traceback.format_exc())
            exit(1)

# Функция для проверки подписи данных из Telegram Web App
def verify_telegram_webapp(init_data):
    """
    Проверяет подпись данных из Telegram Web App.

    :param init_data: Строка initData из Telegram Web App
    :return: True, если подпись корректна, иначе False
    """
    try:
        TELEGRAM_BOT_TOKEN = app.config['TELEGRAM_BOT_TOKEN']
        secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()

        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        hash_ = parsed_data.pop('hash', None)
        if not hash_:
            logger.warning("Отсутствует поле 'hash' в initData.")
            return False

        # Сортировка ключей по алфавиту
        sorted_items = sorted(parsed_data.items())
        data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted_items)
        hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        logger.debug("----- Проверка подписи данных Telegram -----")
        logger.debug(f"Data Check String:\n{data_check_string}")
        logger.debug(f"Вычисленный HMAC Hash: {hmac_hash}")
        logger.debug(f"Полученный Hash: {hash_}")
        logger.debug("--------------------------------------------")

        # Используем compare_digest для безопасного сравнения
        return hmac.compare_digest(hmac_hash, hash_)
    except Exception as e:
        logger.error(f"Ошибка при проверке подписи данных Telegram Web App: {e}")
        logger.error(traceback.format_exc())
        return False

# Загрузка пользователя для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Маршруты аутентификации

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/telegram_login', methods=['POST'])
def telegram_login():
    """
    Обработчик данных авторизации от Telegram Login Widget.
    Принимает данные через JSON.
    """
    if not request.is_json:
        logger.warning("Некорректный тип запроса. Ожидается JSON.")
        return jsonify({'success': False, 'message': 'Некорректный тип запроса.'}), 400

    data = request.get_json()
    logger.debug(f"Получены данные для авторизации через браузер: {data}")

    if not data:
        logger.warning("Отсутствуют данные авторизации.")
        return jsonify({'success': False, 'message': 'Отсутствуют данные для авторизации.'}), 400

    try:
        auth_date = int(data.get('auth_date', 0))
    except ValueError:
        logger.warning("Некорректное значение auth_date.")
        return jsonify({'success': False, 'message': 'Некорректное значение auth_date.'}), 400

    if time.time() - auth_date > 600:
        logger.warning("Время авторизации истекло.")
        return jsonify({'success': False, 'message': 'Время авторизации истекло.'}), 401

    check_hash = data.pop('hash', None)
    if not check_hash:
        logger.warning("Отсутствует hash в данных авторизации.")
        return jsonify({'success': False, 'message': 'Отсутствует hash.'}), 400

    # Создание строки для проверки подписи
    data_check_arr = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = '\n'.join(data_check_arr)
    secret_key = hashlib.sha256(app.config['TELEGRAM_BOT_TOKEN'].encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    logger.debug(f"data_check_string: {data_check_string}")
    logger.debug(f"hmac_hash: {hmac_hash}")
    logger.debug(f"check_hash: {check_hash}")

    if not hmac.compare_digest(hmac_hash, check_hash):
        logger.warning("Неверная подпись данных.")
        return jsonify({'success': False, 'message': 'Неверная подпись данных.'}), 401

    # Авторизация прошла успешно
    telegram_id = data.get('id')
    username = data.get('username')
    first_name = data.get('first_name')
    last_name = data.get('last_name')

    # Поиск или создание пользователя в базе данных
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            registered_at=datetime.utcnow()
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"Новый пользователь создан: Telegram ID {telegram_id}.")

    # Установка сессии пользователя
    login_user(user)
    logger.info(f"Пользователь ID {user.id} (Telegram ID {telegram_id}) авторизовался через браузер.")
    logger.debug(f"Текущая сессия: {session}")

    return jsonify({'success': True, 'redirect_url': url_for('index')}), 200

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы.', 'success')
    logger.info("Пользователь вышел из системы.")
    return redirect(url_for('login'))

# Маршрут здоровья для проверки состояния приложения
@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

# Маршрут для обработки авторизации из Telegram Web App
@app.route('/telegram_webapp_login', methods=['POST'])
def telegram_webapp_login():
    """
    Обработчик данных авторизации из Telegram Web App.
    """
    if not request.is_json:
        logger.warning("Некорректный тип запроса. Ожидается JSON.")
        return jsonify({'success': False, 'message': 'Некорректный тип запроса.'}), 400

    data = request.get_json()
    init_data = data.get('initData', '')
    user_data = data.get('user')

    logger.debug(f"Получены данные для авторизации через Telegram Web App: initData={init_data}, user={user_data}")

    if not init_data or not user_data:
        logger.warning("Отсутствуют данные авторизации.")
        return jsonify({'success': False, 'message': 'Отсутствуют данные для авторизации.'}), 400

    # Проверяем подлинность данных с помощью функции проверки Telegram
    if not verify_telegram_webapp(init_data):
        logger.warning("Неверная подпись данных.")
        return jsonify({'success': False, 'message': 'Неверная подпись данных.'}), 401

    # Авторизация прошла успешно
    telegram_id = user_data.get('id')
    username = user_data.get('username')
    first_name = user_data.get('first_name')
    last_name = user_data.get('last_name')

    # Поиск или создание пользователя в базе данных
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            registered_at=datetime.utcnow()
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"Новый пользователь создан: Telegram ID {telegram_id}.")

    # Установка сессии пользователя
    login_user(user)
    logger.info(f"Пользователь ID {user.id} (Telegram ID {telegram_id}) авторизовался через Telegram Web App.")
    logger.debug(f"Текущая сессия: {session}")

    return jsonify({'success': True, 'redirect_url': url_for('index')}), 200

# Главная страница — список сделок с фильтрацией
@app.route('/', methods=['GET', 'HEAD'])
@login_required
def index():
    if request.method == 'HEAD':
        return '', 200  # Возвращаем 200 OK для HEAD-запросов

    user_id = current_user.id
    categories = InstrumentCategory.query.all()
    criteria_categories = CriterionCategory.query.all()

    # Получение параметров фильтрации из запроса
    instrument_id = request.args.get('instrument_id', type=int)
    direction = request.args.get('direction')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    selected_criteria = request.args.getlist('filter_criteria', type=int)

    trades_query = Trade.query.filter_by(user_id=user_id)

    if instrument_id:
        trades_query = trades_query.filter(Trade.instrument_id == instrument_id)
    if direction:
        trades_query = trades_query.filter(Trade.direction == direction)
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            trades_query = trades_query.filter(Trade.trade_open_time >= start_date_obj)
        except ValueError:
            flash('Некорректный формат даты начала.', 'danger')
            logger.error(f"Некорректный формат даты начала: {start_date}.")
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            trades_query = trades_query.filter(Trade.trade_open_time <= end_date_obj)
        except ValueError:
            flash('Некорректный формат даты окончания.', 'danger')
            logger.error(f"Некорректный формат даты окончания: {end_date}.")
    if selected_criteria:
        trades_query = trades_query.join(Trade.criteria).filter(Criterion.id.in_(selected_criteria)).distinct()

    trades = trades_query.order_by(Trade.trade_open_time.desc()).all()
    logger.info(f"Получено {len(trades)} сделок для пользователя ID {user_id}.")

    return render_template(
        'index.html',
        trades=trades,
        categories=categories,
        criteria_categories=criteria_categories,
        selected_instrument_id=instrument_id
    )

# Добавить новую сделку
@app.route('/new_trade', methods=['GET', 'POST'])
@login_required
def new_trade():
    user_id = current_user.id
    form = TradeForm()
    # Заполнение списка сетапов
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    # Заполнение списка инструментов
    instruments = Instrument.query.all()
    # Группировка инструментов по категориям
    grouped_instruments = {}
    for category in InstrumentCategory.query.all():
        grouped_instruments[category.name] = Instrument.query.filter_by(category_id=category.id).all()
    # Устанавливаем choices для поля instrument
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in Instrument.query.all()]
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.validate_on_submit():
        try:
            trade = Trade(
                user_id=user_id,
                instrument_id=form.instrument.data,
                direction=form.direction.data,
                entry_price=float(form.entry_price.data),
                exit_price=float(form.exit_price.data) if form.exit_price.data else None,
                trade_open_time=form.trade_open_time.data,
                trade_close_time=form.trade_close_time.data if form.trade_close_time.data else None,
                comment=form.comment.data,
                setup_id=form.setup_id.data if form.setup_id.data != 0 else None
            )
            # Расчёт прибыли/убытка
            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            # Обработка критериев
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                criterion = Criterion.query.get(criterion_id)
                if criterion:
                    trade.criteria.append(criterion)

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                trade.screenshot = filename  # Добавляем поле screenshot в модели Trade
                logger.info(f"Скриншот '{filename}' сохранён для сделки ID {trade.id}.")

            db.session.add(trade)
            db.session.commit()
            flash('Сделка успешно добавлена.', 'success')
            logger.info(f"Сделка ID {trade.id} добавлена пользователем ID {user_id}.")
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сделки.', 'danger')
            logger.error(f"Ошибка при добавлении сделки: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('new_trade.html', form=form, criteria_categories=criteria_categories, grouped_instruments=grouped_instruments)

# Редактировать сделку
@app.route('/edit_trade/<int:trade_id>', methods=['GET', 'POST'])
@login_required
def edit_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        flash('У вас нет прав для редактирования этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался редактировать сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))

    form = TradeForm(obj=trade)
    # Заполнение списка сетапов
    setups = Setup.query.filter_by(user_id=current_user.id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    # Устанавливаем choices для поля instrument
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in Instrument.query.all()]
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in trade.criteria]
        form.setup_id.data = trade.setup_id if trade.setup_id else 0

    if form.validate_on_submit():
        try:
            trade.instrument_id = form.instrument.data
            trade.direction = form.direction.data
            trade.entry_price = float(form.entry_price.data)
            trade.exit_price = float(form.exit_price.data) if form.exit_price.data else None
            trade.trade_open_time = form.trade_open_time.data
            trade.trade_close_time = form.trade_close_time.data if form.trade_close_time.data else None
            trade.comment = form.comment.data
            trade.setup_id = form.setup_id.data if form.setup_id.data != 0 else None

            # Расчёт прибыли/убытка
            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            # Обработка критериев
            trade.criteria = []
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                criterion = Criterion.query.get(criterion_id)
                if criterion:
                    trade.criteria.append(criterion)

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if trade.screenshot:
                    old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], trade.screenshot)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
                        logger.info(f"Старый скриншот '{trade.screenshot}' удалён для сделки ID {trade_id}.")
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                trade.screenshot = filename
                logger.info(f"Новый скриншот '{filename}' сохранён для сделки ID {trade.id}.")

            db.session.commit()
            flash('Сделка успешно обновлена.', 'success')
            logger.info(f"Сделка ID {trade.id} обновлёна пользователем ID {current_user.id}.")
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сделки.', 'danger')
            logger.error(f"Ошибка при обновлении сделки ID {trade_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    # Группировка инструментов по категориям
    grouped_instruments = {}
    for category in InstrumentCategory.query.all():
        grouped_instruments[category.name] = Instrument.query.filter_by(category_id=category.id).all()
    return render_template(
        'edit_trade.html',
        form=form,
        criteria_categories=criteria_categories,
        trade=trade,
        grouped_instruments=grouped_instruments
    )

# Удалить сделку
@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
@login_required
def delete_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        flash('У вас нет прав для удаления этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался удалить сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))
    try:
        if trade.screenshot:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], trade.screenshot)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Скриншот '{trade.screenshot}' удалён для сделки ID {trade_id}.")
        db.session.delete(trade)
        db.session.commit()
        flash('Сделка успешно удалена.', 'success')
        logger.info(f"Сделка ID {trade.id} удалена пользователем ID {current_user.id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сделки.', 'danger')
        logger.error(f"Ошибка при удалении сделки ID {trade_id}: {e}")
    return redirect(url_for('index'))

# Управление сетапами
@app.route('/manage_setups')
@login_required
def manage_setups():
    user_id = current_user.id
    setups = Setup.query.filter_by(user_id=user_id).all()
    logger.info(f"Пользователь ID {user_id} просматривает свои сетапы.")
    return render_template('manage_setups.html', setups=setups)

# Добавить новый сетап
@app.route('/add_setup', methods=['GET', 'POST'])
@login_required
def add_setup():
    user_id = current_user.id
    form = SetupForm()
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.validate_on_submit():
        try:
            setup = Setup(
                user_id=user_id,
                setup_name=form.setup_name.data,
                description=form.description.data
            )
            # Обработка критериев
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                criterion = Criterion.query.get(criterion_id)
                if criterion:
                    setup.criteria.append(criterion)

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                setup.screenshot = filename
                logger.info(f"Скриншот '{filename}' сохранён для сетапа ID {setup.id}.")

            db.session.add(setup)
            db.session.commit()
            flash('Сетап успешно добавлен.', 'success')
            logger.info(f"Сетап ID {setup.id} добавлен пользователем ID {user_id}.")
            return redirect(url_for('manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сетапа.', 'danger')
            logger.error(f"Ошибка при добавлении сетапа: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('add_setup.html', form=form, criteria_categories=criteria_categories)

# Редактировать сетап
@app.route('/edit_setup/<int:setup_id>', methods=['GET', 'POST'])
@login_required
def edit_setup(setup_id):
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != current_user.id:
        flash('У вас нет прав для редактирования этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался редактировать сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    form = SetupForm(obj=setup)
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in setup.criteria]

    if form.validate_on_submit():
        try:
            setup.setup_name = form.setup_name.data
            setup.description = form.description.data

            # Обработка критериев
            setup.criteria = []
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                criterion = Criterion.query.get(criterion_id)
                if criterion:
                    setup.criteria.append(criterion)

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if setup.screenshot:
                    old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], setup.screenshot)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
                        logger.info(f"Старый скриншот '{setup.screenshot}' удалён для сетапа ID {setup_id}.")
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                setup.screenshot = filename
                logger.info(f"Новый скриншот '{filename}' сохранён для сетапа ID {setup.id}.")

            db.session.commit()
            flash('Сетап успешно обновлён.', 'success')
            logger.info(f"Сетап ID {setup.id} обновлён пользователем ID {current_user.id}.")
            return redirect(url_for('manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сетапа.', 'danger')
            logger.error(f"Ошибка при обновлении сетапа ID {setup_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('edit_setup.html', form=form, criteria_categories=criteria_categories, setup=setup)

# Удалить сетап
@app.route('/delete_setup/<int:setup_id>', methods=['POST'])
@login_required
def delete_setup(setup_id):
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != current_user.id:
        flash('У вас нет прав для удаления этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался удалить сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    try:
        if setup.screenshot:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], setup.screenshot)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Скриншот '{setup.screenshot}' удалён для сетапа ID {setup_id}.")
        db.session.delete(setup)
        db.session.commit()
        flash('Сетап успешно удалён.', 'success')
        logger.info(f"Сетап ID {setup.id} удалён пользователем ID {current_user.id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сетапа.', 'danger')
        logger.error(f"Ошибка при удалении сетапа ID {setup_id}: {e}")
    return redirect(url_for('manage_setups'))

# Просмотр сделки
@app.route('/view_trade/<int:trade_id>')
@login_required
def view_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        flash('У вас нет прав для просмотра этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался просмотреть сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))
    logger.info(f"Пользователь ID {current_user.id} просматривает сделку ID {trade_id}.")
    return render_template('view_trade.html', trade=trade)

# Просмотр сетапа
@app.route('/view_setup/<int:setup_id>')
@login_required
def view_setup(setup_id):
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != current_user.id:
        flash('У вас нет прав для просмотра этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {current_user.id} попытался просмотреть сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    logger.info(f"Пользователь ID {current_user.id} просматривает сетап ID {setup_id}.")
    return render_template('view_setup.html', setup=setup)

# Обслуживание загруженных файлов
@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# **Telegram Bot Handlers**

# Команда /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /start от пользователя {user.id} ({user.username})")
    try:
        # Поиск или создание пользователя в базе данных
        user_record = User.query.filter_by(telegram_id=user.id).first()
        if not user_record:
            user_record = User(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                registered_at=datetime.utcnow()
            )
            db.session.add(user_record)
            db.session.commit()
            logger.info(f"Новый пользователь создан: Telegram ID {user.id}.")

        # Отправка сообщения пользователю с приветствием и ссылкой на веб-приложение
        message_text = (
            f"Привет, {user.first_name}! Чтобы воспользоваться приложением, нажмите кнопку ниже."
        )

        # Создание кнопки с Web App
        web_app_url = f"https://{get_app_host()}/login"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Открыть приложение",
                        web_app=WebAppInfo(url=web_app_url)
                    )
                ]
            ]
        )

        await update.message.reply_text(
            message_text,
            reply_markup=keyboard
        )
        logger.info(f"Сообщение с Web App кнопкой отправлено пользователю {user.id} ({user.username}) на команду /start.")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /start: {e}")
        logger.error(traceback.format_exc())

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /help от пользователя {user.id} ({user.username})")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом и получить доступ к приложению\n"
        "/help - Получить справку\n"
        "/test - Тестовая команда для проверки работы бота"
    )
    try:
        await update.message.reply_text(help_text)
        logger.info(f"Ответ на /help отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /help: {e}")
        logger.error(traceback.format_exc())

# Команда /test
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /test от пользователя {user.id} ({user.username})")
    try:
        await update.message.reply_text('Команда /test работает корректно!')
        logger.info(f"Ответ на /test отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /test: {e}")
        logger.error(traceback.format_exc())

# Обработчик кнопок CallbackQuery
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    data = query.data
    logger.info(f"Получено нажатие кнопки '{data}' от пользователя {user.id} ({user.username})")

    await query.edit_message_text(text="Используйте встроенную кнопку для взаимодействия с Web App.")
    logger.warning(f"Неизвестная или не нужная кнопка '{data}' от пользователя {user.id} ({user.username}).")

# **Инициализация Telegram бота и приложения**

# Получение токена бота из переменных окружения
TOKEN = app.config['TELEGRAM_BOT_TOKEN']
if not TOKEN:
    logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
    exit(1)

# Инициализация бота и приложения Telegram
application = ApplicationBuilder().token(TOKEN).build()

# Добавление обработчиков команд к приложению
application.add_handler(CommandHandler('start', start_command))
application.add_handler(CommandHandler('help', help_command))
application.add_handler(CommandHandler('test', test_command))

# Добавление обработчика CallbackQueryHandler к приложению
application.add_handler(CallbackQueryHandler(button_click))

# **Flask Routes for Telegram Webhooks**

@app.route('/webhook', methods=['POST'])
def webhook_route():
    """Обработчик вебхуков от Telegram."""
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            # Обработка обновления
            asyncio.run_coroutine_threadsafe(application.process_update(update), asyncio.get_event_loop())
            logger.info(f"Получено обновление от Telegram: {update}")
            return 'OK', 200
        except Exception as e:
            logger.error(f"Ошибка при обработке вебхука: {e}")
            logger.error(traceback.format_exc())
            return 'Internal Server Error', 500
    else:
        return 'Method Not Allowed', 405

# Маршрут для установки вебхука
@app.route('/set_webhook', methods=['GET'])
def set_webhook_route():
    """Маршрут для установки вебхука Telegram."""
    webhook_url = f"https://{get_app_host()}/webhook"
    bot_token = app.config['TELEGRAM_BOT_TOKEN']
    if not bot_token:
        logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
        return "TELEGRAM_TOKEN не установлен", 500
    set_webhook_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        response = requests.post(set_webhook_url, data={"url": webhook_url})
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                logger.info(f"Webhook успешно установлен на {webhook_url}")
                return f"Webhook успешно установлен на {webhook_url}", 200
            else:
                logger.error(f"Не удалось установить webhook: {result}")
                return f"Не удалось установить webhook: {result.get('description')}", 500
        else:
            logger.error(f"Ошибка HTTP при установке webhook: {response.status_code}")
            return f"Ошибка HTTP: {response.status_code}", 500
    except Exception as e:
        logger.error(f"Ошибка при установке webhook: {e}")
        logger.error(traceback.format_exc())
        return "Произошла ошибка при установке webhook", 500

# **Запуск Flask-приложения**

if __name__ == '__main__':
    # Для локальной разработки только
    with app.app_context():
        try:
            upgrade()  # Применение миграций
            create_predefined_data()
            logger.info("Миграции применены и предопределённые данные созданы.")
        except Exception as e:
            logger.error(f"Ошибка при применении миграций: {e}")
            logger.error(traceback.format_exc())
            exit(1)
    # Запуск Telegram бота через вебхуки уже настроен, поэтому не нужно запускать polling
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
