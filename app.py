# app.py

import os
import traceback
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, redirect, url_for, flash, request,
    send_from_directory, session, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from wtforms import (
    StringField, SelectField, FloatField, DateField, TextAreaField,
    FileField, SubmitField, SelectMultipleField
)
from wtforms.validators import DataRequired, Optional
from flask_wtf.file import FileAllowed

from telegram import (
    Bot, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler

import logging
import requests
import threading

# Инициализация Flask-приложения
app = Flask(__name__)

# Настройка CORS
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            "https://trend-share.onrender.com",  # Ваш основной домен
            "https://t.me"                      # Домен Telegram
        ]
    }
})

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)  # Установлено на DEBUG для детальной отладки
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

# Настройка APP_HOST для формирования ссылок
app.config['APP_HOST'] = os.environ.get('APP_HOST', 'trend-share.onrender.com')

# Настройки сессии
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Позволяет куки-сессиям работать в кросс-доменных запросах
app.config['SESSION_COOKIE_SECURE'] = True      # Требует HTTPS
app.config['SESSION_COOKIE_DOMAIN'] = 'trend-share.onrender.com'  # Указание домена для куки

# Настройки загрузки файлов
app.config['UPLOAD_FOLDER'] = 'uploads'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Настройка токена бота для использования в приложении
app.config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
if not app.config['TELEGRAM_BOT_TOKEN']:
    logger.error("TELEGRAM_BOT_TOKEN не установлен в переменных окружения.")
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения.")

# Инициализация SQLAlchemy
db = SQLAlchemy(app)

# Инициализация Flask-Migrate
migrate = Migrate(app, db)

# Контекстный процессор для предоставления datetime в шаблонах
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# Вспомогательная функция для получения хоста приложения
def get_app_host():
    """
    Возвращает хост приложения для формирования ссылок.
    """
    return app.config.get('APP_HOST', 'trend-share.onrender.com')

# Модели базы данных

# Пользователи
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    trades = db.relationship('Trade', backref='user', lazy=True)
    setups = db.relationship('Setup', backref='user', lazy=True)

# Категории инструментов
class InstrumentCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    instruments = db.relationship('Instrument', backref='category', lazy=True)

# Инструменты
class Instrument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('instrument_category.id'), nullable=False)
    trades = db.relationship('Trade', backref='instrument', lazy=True)

# Категории критериев
class CriterionCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    subcategories = db.relationship('CriterionSubcategory', backref='category', lazy=True)

# Подкатегории критериев
class CriterionSubcategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('criterion_category.id'), nullable=False)
    criteria = db.relationship('Criterion', backref='subcategory', lazy=True)

# Критерии
class Criterion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('criterion_subcategory.id'), nullable=False)
    trades = db.relationship('Trade', secondary='trade_criteria', backref='criteria')

# Вспомогательная таблица для связи сделок с критериями
trade_criteria = db.Table('trade_criteria',
    db.Column('trade_id', db.Integer, db.ForeignKey('trade.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

# Сделки
class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    instrument_id = db.Column(db.Integer, db.ForeignKey('instrument.id'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'Buy' или 'Sell'
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    trade_open_time = db.Column(db.Date, nullable=False)
    trade_close_time = db.Column(db.Date, nullable=True)
    profit_loss = db.Column(db.Float, nullable=True)
    profit_loss_percentage = db.Column(db.Float, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    screenshot = db.Column(db.String(300), nullable=True)
    setup_id = db.Column(db.Integer, db.ForeignKey('setup.id'), nullable=True)

# Сетапы
class Setup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    setup_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    screenshot = db.Column(db.String(300), nullable=True)
    criteria = db.relationship('Criterion', secondary='setup_criteria', backref='setups')

# Вспомогательная таблица для связи сетапов с критериями
setup_criteria = db.Table('setup_criteria',
    db.Column('setup_id', db.Integer, db.ForeignKey('setup.id'), primary_key=True),
    db.Column('criterion_id', db.Integer, db.ForeignKey('criterion.id'), primary_key=True)
)

# Формы

class TradeForm(FlaskForm):
    instrument = SelectField('Инструмент', coerce=int, validators=[DataRequired()])
    direction = SelectField('Направление', choices=[('Buy', 'Buy'), ('Sell', 'Sell')], validators=[DataRequired()])
    entry_price = FloatField('Цена входа', validators=[DataRequired()])
    exit_price = FloatField('Цена выхода', validators=[Optional()])
    trade_open_time = DateField('Дата открытия', format='%Y-%m-%d', validators=[DataRequired()])
    trade_close_time = DateField('Дата закрытия', format='%Y-%m-%d', validators=[Optional()])
    comment = TextAreaField('Комментарий', validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png'], 'Изображения только!')])
    setup_id = SelectField('Сетап', coerce=int, validators=[Optional()])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    submit = SubmitField('Сохранить')

class SetupForm(FlaskForm):
    setup_name = StringField('Название сетапа', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[Optional()])
    screenshot = FileField('Скриншот', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png'], 'Изображения только!')])
    criteria = SelectMultipleField('Критерии', coerce=int, validators=[Optional()])
    submit = SubmitField('Сохранить')

# Функция для проверки подлинности данных Telegram Web App
def verify_telegram_auth(data_dict):
    try:
        token = app.config['TELEGRAM_BOT_TOKEN']
        secret_key = hashlib.sha256(token.encode('utf-8')).digest()

        hash_to_check = data_dict.pop('hash', '')
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(data_dict.items())])

        hmac_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()

        return hmac.compare_digest(hmac_hash, hash_to_check.lower())
    except Exception as e:
        logger.error(f"Ошибка при проверке авторизации Telegram: {e}")
        logger.error(traceback.format_exc())
        return False

# Функция для создания предопределённых данных
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
        {'name': 'LTC/USDT', 'category': 'Криптовалюты'},
        {'name': 'XRP/USDT', 'category': 'Криптовалюты'},
        {'name': 'BCH/USDT', 'category': 'Криптовалюты'},
        {'name': 'ADA/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOT/USDT', 'category': 'Криптовалюты'},
        {'name': 'LINK/USDT', 'category': 'Криптовалюты'},
        {'name': 'BNB/USDT', 'category': 'Криптовалюты'},
        {'name': 'SOL/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOGE/USDT', 'category': 'Криптовалюты'},
        {'name': 'MATIC/USDT', 'category': 'Криптовалюты'},
        {'name': 'AVAX/USDT', 'category': 'Криптовалюты'},
        {'name': 'TRX/USDT', 'category': 'Криптовалюты'},
        {'name': 'UNI/USDT', 'category': 'Криптовалюты'},
        {'name': 'ATOM/USDT', 'category': 'Криптовалюты'},
        {'name': 'FIL/USDT', 'category': 'Криптовалюты'},
        {'name': 'ALGO/USDT', 'category': 'Криптовалюты'},
        {'name': 'ICP/USDT', 'category': 'Криптовалюты'},
        {'name': 'ETC/USDT', 'category': 'Криптовалюты'},
        {'name': 'VET/USDT', 'category': 'Криптовалюты'},
        {'name': 'EOS/USDT', 'category': 'Криптовалюты'},
        {'name': 'AAVE/USDT', 'category': 'Криптовалюты'},
        {'name': 'THETA/USDT', 'category': 'Криптовалюты'},
        {'name': 'XLM/USDT', 'category': 'Криптовалюты'},
        {'name': 'NEO/USDT', 'category': 'Криптовалюты'},
        {'name': 'DASH/USDT', 'category': 'Криптовалюты'},
        {'name': 'KSM/USDT', 'category': 'Криптовалюты'},
        {'name': 'BAT/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZEC/USDT', 'category': 'Криптовалюты'},
        {'name': 'MKR/USDT', 'category': 'Криптовалюты'},
        {'name': 'COMP/USDT', 'category': 'Криптовалюты'},
        {'name': 'SNX/USDT', 'category': 'Криптовалюты'},
        {'name': 'SUSHI/USDT', 'category': 'Криптовалюты'},
        {'name': 'YFI/USDT', 'category': 'Криптовалюты'},
        {'name': 'REN/USDT', 'category': 'Криптовалюты'},
        {'name': 'UMA/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZRX/USDT', 'category': 'Криптовалюты'},
        {'name': 'CRV/USDT', 'category': 'Криптовалюты'},
        {'name': 'BNT/USDT', 'category': 'Криптовалюты'},
        {'name': 'LRC/USDT', 'category': 'Криптовалюты'},
        {'name': 'BAL/USDT', 'category': 'Криптовалюты'},
        {'name': 'MANA/USDT', 'category': 'Криптовалюты'},
        {'name': 'CHZ/USDT', 'category': 'Криптовалюты'},
        {'name': 'FTT/USDT', 'category': 'Криптовалюты'},
        {'name': 'CELR/USDT', 'category': 'Криптовалюты'},
        {'name': 'ENJ/USDT', 'category': 'Криптовалюты'},
        {'name': 'GRT/USDT', 'category': 'Криптовалюты'},
        {'name': '1INCH/USDT', 'category': 'Криптовалюты'},
        {'name': 'SAND/USDT', 'category': 'Криптовалюты'},
        {'name': 'AXS/USDT', 'category': 'Криптовалюты'},
        {'name': 'FLOW/USDT', 'category': 'Криптовалюты'},
        {'name': 'RUNE/USDT', 'category': 'Криптовалюты'},
        {'name': 'GALA/USDT', 'category': 'Криптовалюты'},
        {'name': 'KAVA/USDT', 'category': 'Криптовалюты'},
        {'name': 'QTUM/USDT', 'category': 'Криптовалюты'},
        {'name': 'FTM/USDT', 'category': 'Криптовалюты'},
        {'name': 'ONT/USDT', 'category': 'Криптовалюты'},
        {'name': 'HNT/USDT', 'category': 'Криптовалюты'},
        {'name': 'ICX/USDT', 'category': 'Криптовалюты'},
        {'name': 'RLC/USDT', 'category': 'Криптовалюты'},
        {'name': 'GNO/USDT', 'category': 'Криптовалюты'},
        {'name': 'OMG/USDT', 'category': 'Криптовалюты'},
        {'name': 'DGB/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZIL/USDT', 'category': 'Криптовалюты'},
        {'name': 'TFUEL/USDT', 'category': 'Криптовалюты'},
        {'name': 'BTS/USDT', 'category': 'Криптовалюты'},
        {'name': 'NANO/USDT', 'category': 'Криптовалюты'},
        {'name': 'XEM/USDT', 'category': 'Криптовалюты'},
        {'name': 'HOT/USDT', 'category': 'Криптовалюты'},
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
                criterion = Criterion.query.filter_by(name=criterion_name, subcategory_id=subcategory.id).first()
                if not criterion:
                    criterion = Criterion(
                        name=criterion_name,
                        subcategory_id=subcategory.id
                    )
                    db.session.add(criterion)
                    logger.info(f"Критерий '{criterion_name}' добавлен в подкатегорию '{subcategory_name}'.")

    db.session.commit()
    logger.info("Критерии, подкатегории и категории критериев успешно добавлены.")

# Инициализация данных при первом запуске
@app.before_first_request
def initialize():
    with app.app_context():
        create_predefined_data()

# Маршруты аутентификации

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы успешно вышли из системы.', 'success')
    logger.info("Пользователь вышел из системы.")
    return redirect(url_for('login'))

# Маршрут здоровья для проверки состояния приложения
@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

# Главная страница — список сделок с фильтрацией и обработкой initData
@app.route('/', methods=['GET', 'HEAD'])
def index():
    if request.method == 'HEAD':
        return '', 200  # Возвращаем 200 OK для HEAD-запросов

    if 'user_id' not in session:
        # Проверяем наличие данных авторизации из Telegram Web App
        init_data = request.args.get('initData') or request.args.get('init_data')
        logger.debug(f"Получен initData: {init_data}")
        if init_data:
            data = dict(urllib.parse.parse_qsl(init_data))
            logger.debug(f"Разобранные данные initData: {data}")
            if verify_telegram_auth(data):
                telegram_id = int(data.get('id'))
                first_name = data.get('first_name')
                last_name = data.get('last_name')
                username = data.get('username')

                # Поиск или создание пользователя
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

                # Устанавливаем сессию пользователя
                session['user_id'] = user.id
                session['telegram_id'] = user.telegram_id
                logger.info(f"Пользователь ID {user.id} авторизован через Telegram Web App.")

                # Перенаправляем на главную страницу без initData
                return redirect(url_for('index'))
            else:
                flash('Не удалось подтвердить подлинность данных Telegram.', 'danger')
                logger.warning("Не удалось подтвердить подлинность данных Telegram.")
                return redirect(url_for('login'))
        else:
            # Если данных нет, отображаем страницу авторизации
            logger.debug("initData отсутствует в запросе.")
            return redirect(url_for('login'))

    # Если пользователь уже авторизован, отображаем главную страницу
    user_id = session['user_id']
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

# Страница авторизации (инструкции для пользователей, которые открывают приложение вне Telegram)
@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

# Добавить новую сделку
@app.route('/new_trade', methods=['GET', 'POST'])
def new_trade():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
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

    # Инициализация form.criteria.data пустым списком, если оно None
    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
            trade = Trade(
                user_id=user_id,
                instrument_id=form.instrument.data,
                direction=form.direction.data,
                entry_price=form.entry_price.data,
                exit_price=form.exit_price.data if form.exit_price.data else None,
                trade_open_time=form.trade_open_time.data,
                trade_close_time=form.trade_close_time.data if form.exit_price.data else None,
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
            selected_criteria_ids = request.form.getlist('criteria')
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        trade.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                trade.screenshot = filename  # Добавляем поле screenshot в модели Trade
                logger.info(f"Скриншот '{filename}' сохранён для сделки.")

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
    return render_template(
        'new_trade.html',
        form=form,
        criteria_categories=criteria_categories,
        grouped_instruments=grouped_instruments
    )

# Редактировать сделку
@app.route('/edit_trade/<int:trade_id>', methods=['GET', 'POST'])
def edit_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для редактирования этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))

    form = TradeForm(obj=trade)
    # Заполнение списка сетапов
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    # Устанавливаем choices для поля instrument
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in Instrument.query.all()]
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Установка выбранных критериев
    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in trade.criteria]
        form.instrument.data = trade.instrument_id
        form.setup_id.data = trade.setup_id if trade.setup_id else 0

    if form.validate_on_submit():
        try:
            trade.instrument_id = form.instrument.data
            trade.direction = form.direction.data
            trade.entry_price = form.entry_price.data
            trade.exit_price = form.exit_price.data if form.exit_price.data else None
            trade.trade_open_time = form.trade_open_time.data
            trade.trade_close_time = form.trade_close_time.data if form.exit_price.data else None
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
            trade.criteria.clear()
            selected_criteria_ids = request.form.getlist('criteria')
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        trade.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

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
            logger.info(f"Сделка ID {trade.id} обновлена пользователем ID {user_id}.")
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
def delete_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для удаления этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сделку ID {trade_id}, которая ему не принадлежит.")
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
        logger.info(f"Сделка ID {trade.id} удалена пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сделки.', 'danger')
        logger.error(f"Ошибка при удалении сделки ID {trade_id}: {e}")
    return redirect(url_for('index'))

# Управление сетапами
@app.route('/manage_setups')
def manage_setups():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setups = Setup.query.filter_by(user_id=user_id).all()
    logger.info(f"Пользователь ID {user_id} просматривает свои сетапы.")
    return render_template('manage_setups.html', setups=setups)

# Добавить новый сетап
@app.route('/add_setup', methods=['GET', 'POST'])
def add_setup():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    form = SetupForm()
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Инициализация form.criteria.data пустым списком, если оно None
    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
            setup = Setup(
                user_id=user_id,
                setup_name=form.setup_name.data,
                description=form.description.data
            )
            # Обработка критериев
            selected_criteria_ids = request.form.getlist('criteria')
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        setup.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            # Обработка скриншота
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                screenshot_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                screenshot_file.save(screenshot_path)
                setup.screenshot = filename
                logger.info(f"Скриншот '{filename}' сохранён для сетапа.")

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
def edit_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для редактирования этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    form = SetupForm(obj=setup)
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Установка выбранных критериев
    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in setup.criteria]

    if form.validate_on_submit():
        try:
            setup.setup_name = form.setup_name.data
            setup.description = form.description.data

            # Обработка критериев
            setup.criteria.clear()
            selected_criteria_ids = request.form.getlist('criteria')
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        setup.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

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
            logger.info(f"Сетап ID {setup.id} обновлён пользователем ID {user_id}.")
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
    return render_template(
        'edit_setup.html',
        form=form,
        criteria_categories=criteria_categories,
        setup=setup
    )

# Удалить сетап
@app.route('/delete_setup/<int:setup_id>', methods=['POST'])
def delete_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для удаления этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сетап ID {setup_id}, который ему не принадлежит.")
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
        logger.info(f"Сетап ID {setup.id} удалён пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сетапа.', 'danger')
        logger.error(f"Ошибка при удалении сетапа ID {setup_id}: {e}")
    return redirect(url_for('manage_setups'))

# Просмотр сделки
@app.route('/view_trade/<int:trade_id>')
def view_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для просмотра этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))
    logger.info(f"Пользователь ID {user_id} просматривает сделку ID {trade_id}.")
    return render_template('view_trade.html', trade=trade)

# Просмотр сетапа
@app.route('/view_setup/<int:setup_id>')
def view_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для просмотра этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    logger.info(f"Пользователь ID {user_id} просматривает сетап ID {setup_id}.")
    return render_template('view_setup.html', setup=setup)

# Обслуживание загруженных файлов
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# **Инициализация Telegram бота и обработчиков**

# Получение токена бота из переменных окружения
TOKEN = app.config['TELEGRAM_BOT_TOKEN']
if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен в переменных окружения.")
    exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, workers=1, use_context=True)  # Изменено workers=1

# Обработчики команд

def start_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /start от пользователя {user.id} ({user.username})")
    try:
        # Поиск или создание пользователя в базе данных
        with app.app_context():
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

        # Отправка сообщения с кнопкой Web App
        message_text = (
            f"Привет, {user.first_name}! Нажмите кнопку ниже, чтобы открыть приложение."
        )

        # Создание кнопки с Web App
        web_app_url = f"https://{get_app_host()}/"  # Ваш URL приложения
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

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message_text,
            reply_markup=keyboard
        )
        logger.info(f"Сообщение с Web App кнопкой отправлено пользователю {user.id} ({user.username}) на команду /start.")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /start: {e}")
        logger.error(traceback.format_exc())
        context.bot.send_message(chat_id=update.effective_chat.id, text="Произошла ошибка при обработке команды /start.")

def help_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /help от пользователя {user.id} ({user.username})")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом и открыть приложение\n"
        "/help - Получить справку\n"
        "/test - Тестовая команда для проверки работы бота\n"
    )
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text=help_text)
        logger.info(f"Ответ на /help отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /help: {e}")
        logger.error(traceback.format_exc())

def test_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /test от пользователя {user.id} ({user.username})")
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Команда /test работает корректно!')
        logger.info(f"Ответ на /test отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /test: {e}")
        logger.error(traceback.format_exc())

def button_click(update, context):
    query = update.callback_query
    query.answer()
    user = update.effective_user
    data = query.data
    logger.info(f"Получено нажатие кнопки '{data}' от пользователя {user.id} ({user.username})")

    query.edit_message_text(text="Используйте встроенную кнопку для взаимодействия с Web App.")
    logger.warning(f"Неизвестная или ненужная кнопка '{data}' от пользователя {user.id} ({user.username}).")

# Добавление обработчиков к диспетчеру
dispatcher.add_handler(CommandHandler('start', start_command))
dispatcher.add_handler(CommandHandler('help', help_command))
dispatcher.add_handler(CommandHandler('test', test_command))
dispatcher.add_handler(CallbackQueryHandler(button_click))

# Обработчик вебхуков
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            update = Update.de_json(request.get_json(force=True), bot)
            dispatcher.process_update(update)
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
    webhook_url = f"https://{get_app_host()}/webhook"
    s = bot.set_webhook(webhook_url)
    if s:
        logger.info(f"Webhook успешно установлен на {webhook_url}")
        return f"Webhook успешно установлен на {webhook_url}", 200
    else:
        logger.error(f"Не удалось установить webhook на {webhook_url}")
        return f"Не удалось установить webhook", 500

# Обработка initData через основной маршрут
@app.route('/init', methods=['POST'])
def init():
    data = request.get_json()
    init_data = data.get('initData')
    logger.debug(f"Получен initData через AJAX: {init_data}")
    if init_data:
        data_dict = dict(urllib.parse.parse_qsl(init_data))
        logger.debug(f"Разобранные данные initData через AJAX: {data_dict}")
        if verify_telegram_auth(data_dict):
            telegram_id = int(data_dict.get('id'))
            first_name = data_dict.get('first_name')
            last_name = data_dict.get('last_name')
            username = data_dict.get('username')

            # Поиск или создание пользователя
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

            # Устанавливаем сессию пользователя
            session['user_id'] = user.id
            session['telegram_id'] = user.telegram_id

            logger.info(f"Пользователь ID {user.id} авторизован через Telegram Web App.")

            return jsonify({'status': 'success'}), 200
        else:
            logger.warning("Не удалось подтвердить подлинность данных Telegram через AJAX.")
            return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400
    else:
        logger.warning("initData отсутствует в AJAX-запросе.")
        return jsonify({'status': 'failure', 'message': 'initData missing'}), 400

# **Запуск Flask-приложения**

if __name__ == '__main__':
    # Запуск приложения
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
