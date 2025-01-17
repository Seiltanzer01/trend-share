# app.py

from translations import TRANSLATIONS_RU_TO_EN
import os
import logging
import traceback
import atexit  # Added import atexit
from best_setup_voting import init_best_setup_voting_routes, auto_finalize_best_setup_voting
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from web3 import Web3  # Added Web3 import
import pytz
import boto3
from botocore.exceptions import ClientError
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from routes_staking import staking_bp  # Make sure routes_staking.py exists and contains staking_bp
# Adding OpenAI
import openai

# Adding APScheduler for job scheduling
from apscheduler.schedulers.background import BackgroundScheduler

# Import models and forms
import models  # Make sure models.py imports db from extensions.py
from poll_functions import start_new_poll, process_poll_results, update_real_prices_for_active_polls
from staking_logic import accumulate_staking_rewards

ADMIN_TELEGRAM_IDS = [427032240]

# APScheduler configuration
class ConfigScheduler:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "UTC"  # Set timezone

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(ConfigScheduler())

# Setup CSRF protection
csrf = CSRFProtect(app)

# Context processor to provide CSRF token in templates
@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf()}


# Add context processor for language:
@app.context_processor
def inject_language():
    return {'language': 'en'}  # return {'language': session.get('language', 'en')}

@app.route('/info')
def info():
    return render_template('info.html')

# Setup CORS
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            "https://trend-share.onrender.com",  # Your primary domain
            "https://t.me"                      # Telegram domain
        ]
    }
})

# Setup logging
logging.basicConfig(level=logging.INFO)  # Set to INFO; change to DEBUG if needed
logger = logging.getLogger(__name__)

# Use environment variables for sensitive data
secret_key_env = os.environ.get('SECRET_KEY', '').strip()
if not secret_key_env:
    logger.error("SECRET_KEY is not set in environment variables.")
    raise ValueError("SECRET_KEY is not set in environment variables.")
app.secret_key = secret_key_env

# Database settings
raw_database_url = os.environ.get('DATABASE_URL')

if not raw_database_url:
    logger.error("DATABASE_URL is not set in environment variables.")
    raise ValueError("DATABASE_URL is not set in environment variables.")

# Parsing and adjusting the database connection string
parsed_url = urlparse(raw_database_url)

# Check and add 'sslmode=require' if necessary
query_params = parse_qs(parsed_url.query)
if 'sslmode' not in query_params:
    query_params['sslmode'] = ['require']

new_query = urlencode(query_params, doseq=True)
parsed_url = parsed_url._replace(query=new_query)

# Updated connection string
DATABASE_URL = urlunparse(parsed_url)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# App host settings for link formation
app.config['APP_HOST'] = os.environ.get('APP_HOST', 'trend-share.onrender.com')

# Session settings
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow cross-domain requests for session cookies
app.config['SESSION_COOKIE_SECURE'] = True      # Require HTTPS
app.config['SESSION_COOKIE_DOMAIN'] = 'trend-share.onrender.com'  # Domain for cookie

# Amazon S3 settings
app.config['AWS_ACCESS_KEY_ID'] = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
app.config['AWS_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
app.config['AWS_S3_BUCKET'] = os.environ.get('AWS_S3_BUCKET', '').strip()
app.config['AWS_S3_REGION'] = os.environ.get('AWS_S3_REGION', 'us-east-1').strip()

# Check for required AWS settings
if not all([app.config['AWS_ACCESS_KEY_ID'], app.config['AWS_SECRET_ACCESS_KEY'],
            app.config['AWS_S3_BUCKET'], app.config['AWS_S3_REGION']]):
    logger.error("Some AWS settings are missing from environment variables.")
    raise ValueError("Some AWS settings are missing from environment variables.")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    region_name=app.config['AWS_S3_REGION'],
    aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY']
)

# Initialize extensions with app
db = SQLAlchemy(app)
migrate = Migrate(app, db)

init_best_setup_voting_routes(app, db)

# Context processor to provide datetime in templates
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

def translate_python(russian_text: str):
    """
    If session['language'] == 'en', translates from RU to EN (if exists in dictionary).
    Otherwise returns the original RU text.
    """
    if not russian_text:
        return russian_text
    current_lang = session.get('language', 'ru')
    if current_lang == 'en':
        return TRANSLATIONS_RU_TO_EN.get(russian_text, russian_text)
    else:
        return russian_text

# Helper functions for working with S3
def upload_file_to_s3(file: FileStorage, filename: str) -> bool:
    """
    Uploads a file to S3.
    :param file: FileStorage object.
    :param filename: File name in S3.
    :return: True if upload is successful, False otherwise.
    """
    try:
        s3_client.upload_fileobj(
            file,
            app.config['AWS_S3_BUCKET'],
            filename,
            ExtraArgs={
                "ContentType": file.content_type
            }
        )
        logger.info(f"File '{filename}' was successfully uploaded to S3.")
        return True
    except ClientError as e:
        logger.error(f"Error uploading file '{filename}' to S3: {e}")
        return False

def delete_file_from_s3(filename: str) -> bool:
    """
    Deletes a file from S3.
    :param filename: File name in S3.
    :return: True if deletion is successful, False otherwise.
    """
    try:
        s3_client.delete_object(Bucket=app.config['AWS_S3_BUCKET'], Key=filename)
        logger.info(f"File '{filename}' was successfully deleted from S3.")
        return True
    except ClientError as e:
        logger.error(f"Error deleting file '{filename}' from S3: {e}")
        return False

def generate_s3_url(filename: str) -> str:
    """
    Generates a public URL for the file in S3.
    :param filename: File name in S3.
    :return: File URL.
    """
    bucket_name = app.config['AWS_S3_BUCKET']
    region = app.config['AWS_S3_REGION']

    if region == 'us-east-1':
        url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
    else:
        url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{filename}"
    return url

# Function to get APP_HOST
def get_app_host():
    return app.config['APP_HOST']

# -------------------------------------------------------------------------
# Полный список instruments / categories_data, но храним их в БД по-русски.
# При отображении вызываем translate_python(...) при необходимости.
# -------------------------------------------------------------------------

# Function to create predefined data
def create_predefined_data():
    """
    Сохраняем оригинальные (русские) категории и критерии в БД.
    При отображении переводим через translate_python(...)
    """
    if models.InstrumentCategory.query.first():
        logger.info("Predefined data already exists. Skipping creation.")
        return

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
        {'name': 'BTC-USD', 'category': 'Криптовалюты'},
        {'name': 'ETH-USD', 'category': 'Криптовалюты'},
        {'name': 'LTC-USD', 'category': 'Криптовалюты'},
        {'name': 'XRP-USD', 'category': 'Криптовалюты'},
        {'name': 'BCH-USD', 'category': 'Криптовалюты'},
        {'name': 'ADA-USD', 'category': 'Криптовалюты'},
        {'name': 'SOL-USD', 'category': 'Криптовалюты'},
        {'name': 'DOT-USD', 'category': 'Криптовалюты'},
        {'name': 'DOGE-USD', 'category': 'Криптовалюты'},
        {'name': 'SHIB-USD', 'category': 'Криптовалюты'},
        {'name': 'MATIC-USD', 'category': 'Криптовалюты'},
        {'name': 'AVAX-USD', 'category': 'Криптовалюты'},
        {'name': 'UNI-USD', 'category': 'Криптовалюты'},
        {'name': 'ATOM-USD', 'category': 'Криптовалюты'},
        {'name': 'LINK-USD', 'category': 'Криптовалюты'},
        {'name': 'XLM-USD', 'category': 'Криптовалюты'},
        {'name': 'TRX-USD', 'category': 'Криптовалюты'},
        {'name': 'ALGO-USD', 'category': 'Криптовалюты'},
        {'name': 'AAVE-USD', 'category': 'Криптовалюты'},
        {'name': 'EOS-USD', 'category': 'Криптовалюты'},
        {'name': 'FTT-USD', 'category': 'Криптовалюты'},
        {'name': 'NEAR-USD', 'category': 'Криптовалюты'},
        {'name': 'ICP-USD', 'category': 'Криптовалюты'},
        {'name': 'FIL-USD', 'category': 'Криптовалюты'},
        {'name': 'HBAR-USD', 'category': 'Криптовалюты'},
        {'name': 'VET-USD', 'category': 'Криптовалюты'},
        {'name': 'THETA-USD', 'category': 'Криптовалюты'},
        {'name': 'GRT-USD', 'category': 'Криптовалюты'},
        {'name': 'SAND-USD', 'category': 'Криптовалюты'},
        {'name': 'MANA-USD', 'category': 'Криптовалюты'},
        {'name': 'CHZ-USD', 'category': 'Криптовалюты'},
        {'name': 'XTZ-USD', 'category': 'Криптовалюты'},
        {'name': 'CRV-USD', 'category': 'Криптовалюты'},
        {'name': 'ENS-USD', 'category': 'Криптовалюты'},
        {'name': 'DYDX-USD', 'category': 'Криптовалюты'},
        {'name': 'CAKE-USD', 'category': 'Криптовалюты'},
        {'name': 'RUNE-USD', 'category': 'Криптовалюты'},
        {'name': 'KSM-USD', 'category': 'Криптовалюты'},
        {'name': 'AXS-USD', 'category': 'Криптовалюты'},
        {'name': 'GMT-USD', 'category': 'Криптовалюты'},
        {'name': 'LUNA-USD', 'category': 'Криптовалюты'},
        {'name': 'CRO-USD', 'category': 'Криптовалюты'},
        {'name': 'FTM-USD', 'category': 'Криптовалюты'},
        {'name': 'ZIL-USD', 'category': 'Криптовалюты'},
        {'name': 'KAVA-USD', 'category': 'Криптовалюты'},
        {'name': '1INCH-USD', 'category': 'Криптовалюты'},
        {'name': 'SNX-USD', 'category': 'Криптовалюты'},
        {'name': 'BNT-USD', 'category': 'Криптовалюты'},
        {'name': 'REN-USD', 'category': 'Криптовалюты'},
        {'name': 'RSR-USD', 'category': 'Криптовалюты'},
        {'name': 'ANKR-USD', 'category': 'Криптовалюты'},
        {'name': 'LRC-USD', 'category': 'Криптовалюты'},
        {'name': 'BAT-USD', 'category': 'Криптовалюты'},
        {'name': 'CELR-USD', 'category': 'Криптовалюты'},
        {'name': 'QNT-USD', 'category': 'Криптовалюты'},
        {'name': 'GALA-USD', 'category': 'Криптовалюты'},
        {'name': 'IMX-USD', 'category': 'Криптовалюты'},
        {'name': 'FLOW-USD', 'category': 'Криптовалюты'},
        {'name': 'YFI-USD', 'category': 'Криптовалюты'},
        {'name': 'SUSHI-USD', 'category': 'Криптовалюты'}
    ]

    for instrument_data in instruments:
        category_name_ru = instrument_data['category']
        instrument_name = instrument_data['name']

        # Пишем в БД русское название категории (category_name_ru)
        category = models.InstrumentCategory.query.filter_by(name=category_name_ru).first()
        if not category:
            category = models.InstrumentCategory(name=category_name_ru)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Category '{category_name_ru}' added to DB (RU).")

        # Инструмент пишем как есть (например "EUR/USD")
        instrument = models.Instrument.query.filter_by(name=instrument_name).first()
        if not instrument:
            instrument = models.Instrument(name=instrument_name, category_id=category.id)
            db.session.add(instrument)
            logger.info(f"Instrument '{instrument_name}' added to '{category_name_ru}' category.")

    db.session.commit()
    logger.info("Instruments and (RU) categories successfully added to DB.")

    # Ниже аналогично сохраняем критерии на русском.
    categories_data = {
        'Смарт-мани': {
            'Имбалансы и дисбалансы': [
                'Imbalance (IMB)',
                'Fair Value Gap (FVG)',
                'Buy Side Imbalance Sell Side Inefficiency (BISI)',
                'Sell Side Imbalance Buy Side Inefficiency (SIBI)',
                'Balanced Price Range (BPR)'
            ],
            'Ликвидность и зоны концентрации': [
                'Liquidity Pools (LP)',
                'Equal Highs (EQH)',
                'Equal Lows (EQL)',
                'Liquidity Void (LV)',
                'Stop Hunt (SH)'
            ],
            'Ордер-блоки': [
                'Order Block (OB)',
                'Breaker Block (BB)',
                'Mitigation Block (MB)',
                'Supply and Demand Zones (SND)',
                'Point of Interest (POI)'
            ],
            'Анализ ордер-флоу': [
                'Order Flow (OF)',
                'Break of Structure (BOS)',
                'Change of Character (ChoCH)',
                'Accumulation, Manipulation, Distribution (AMD)',
                'Optimal Trade Entry (OTE)'
            ],
            'Уровни структурной ликвидности': [
                'Подтверждение уровней по ордер-флоу',
                'Зоны высокого ордерного давления',
                'Ликвидные барьеры',
                'Сквозное ликвидное покрытие',
                'Корреляция ордеров и объёма'
            ],
            'Инструменты Smart Money': [
                'Order Book Dynamics',
                'Volume Profile по ордерам',
                'Footprint Charts',
                'Delta Analysis',
                'Проверка iceberg-ордеров'
            ]
        },
        'Технический анализ': {
            'Графические модели': [
                'Фигуры разворота (Голова и плечи, двойная вершина/дно)',
                'Формации продолжения (флаги, вымпелы, клинья)',
                'Треугольники (симметричные, восходящие, нисходящие)',
                'Консолидации и боковые движения',
                'Композитный анализ фигур'
            ],
            'Динамика ценового движения': [
                'Разрывы уровней (gap analysis)',
                'Анализ фейковых пробоев',
                'Консолидация с импульсом',
                'Резкие скачки и коррекции',
                'Импульсные изменения цены'
            ],
            'Свечные паттерны': [
                'Разворотные модели (пин-бары, доджи)',
                'Поглощения (бычьи/медвежьи)',
                'Многофазное поведение свечей',
                'Комбинированные свечные сигналы',
                'Точки разворота по свечам'
            ],
            'Уровни и трендовые линии': [
                'Горизонтальные уровни поддержки/сопротивления',
                'Динамические трендовые линии',
                'Каналы тренда',
                'Зоны консолидации',
                'Многоступенчатая структура уровней'
            ],
            'Объёмно-ценовые взаимодействия': [
                'Профиль объёма в зоне входа',
                'Согласование объёма и цены',
                'Объёмные аномалии при пробое',
                'Кластеризация объёмных скачков',
                'Объёмное подтверждение тренда'
            ]
        },
        'Волны Эллиота': {
            'Импульсные и коррекционные структуры': [
                'Импульсные волны (1, 3, 5)',
                'Коррекционные волны (2, 4)',
                'Фрактальность волн',
                'Начало и конец волны',
                'Временные интервалы волн'
            ],
            'Коррекционные модели': [
                'Модель "Зигзаг"',
                'Площадки для разворота',
                'Треугольное сжатие',
                'Коррекционные параллелограммы',
                'Смешанные коррекции'
            ],
            'Фибоначчи в волновой теории': [
                'Фибоначчи-откаты для входа',
                'Соотношения волн по Фибоначчи',
                'Расширения и ретрейсы',
                'Фибоначчи уровни для SL/TP',
                'Согласование с Фибоначчи'
            ],
            'Границы и завершение волн': [
                'Точки разворота волны',
                'Соотношение длин волн',
                'Зоны ослабления импульса',
                'Временные параметры волн',
                'Завершение импульса'
            ],
            'Модели и структуры волн': [
                'Классическая модель Эллиота',
                'Подмодели импульсных волн',
                'Многофрактальные модели',
                'Анализ на разных таймфреймах',
                'Синхронизация с основным трендом'
            ],
            'Интерпретация волновых соотношений': [
                'Пропорции волн',
                'Сравнение длительности и амплитуды',
                'Корреляция с объёмом',
                'Сравнение импульсных и коррекционных волн',
                'Прогноз на основе волновой структуры'
            ]
        },
        'Price Action': {
            'Ключевые свечные модели': [
                'Пин-бары как сигнал разворота',
                'Свечные поглощения',
                'Доджи для ожидания разворота',
                'Модель "Харами"',
                'Свечи с длинными тенями'
            ],
            'Динамика ценового поведения': [
                'Формирование локальных экстремумов',
                'Консолидация с мощным прорывом',
                'Отказы от ключевых уровней',
                'Фиксация откатов',
                'Дивергенция цены и объёма'
            ],
            'Структуры поддержки/сопротивления': [
                'Устойчивые уровни поддержки/сопротивления',
                'Реверсия цены от ключевых зон',
                'Фиксированные и динамические барьеры',
                'Реакция на исторические уровни',
                'Пробой с откатом'
            ],
            'Брейк-аут и фальшивые пробои': [
                'Истинные пробои уровней',
                'Фильтрация ложных пробоев',
                'Закрытие свечи у пробитого уровня',
                'Контакт с уровнем перед пробоем',
                'Откаты после пробоя'
            ],
            'Интервальные и мультифрейм модели': [
                'Внутридневная динамика',
                'Согласование разных таймфреймов',
                'Асимметрия на краткосрочных интервалах',
                'Переход от локальных к глобальным трендам',
                'Анализ событий открытия/закрытия сессий'
            ],
            'Комплексный Price Action анализ': [
                'Согласование уровней и свечей',
                'Интеграция ценовых аномалий и объёма',
                'Контекстный рыночный анализ',
                'Мультифрейм проверка сигнала',
                'Интеграция сигналов для оптимального входа'
            ]
        },
        'Индикаторы': {
            'Осцилляторы моментума': [
                'RSI для перекупленности/перепроданности',
                'Stochastic для разворотов',
                'CCI для измерения импульса',
                'Williams %R для экстремумов',
                'ROC для динамики цены'
            ],
            'Объёмные индикаторы': [
                'OBV для подтверждения тренда',
                'Accumulation/Distribution для оценки покупки/продажи',
                'MFI для денежного потока',
                'Volume Oscillator для объёмных аномалий',
                'CMF для давления покупателей/продавцов'
            ],
            'Индикаторы волатильности': [
                'Bollinger Bands для зон перекупленности/перепроданности',
                'ATR для стоп-лоссов',
                'Keltner Channels для трендовых зон',
                'Donchian Channels для экстремумов',
                'Standard Deviation для изменчивости'
            ],
            'Скользящие средние': [
                'SMA для базового тренда',
                'EMA для оперативного отслеживания',
                'WMA для точного расчёта',
                'HMA для сглаживания шума',
                'TEMA для быстрого входа'
            ],
            'Сигнальные системы': [
                'MACD для смены тренда',
                'Пересечение скользящих для входа',
                'Дивергенция осцилляторов',
                'Осцилляторы разворота в комбинации',
                'Автоматические сигналы'
            ],
            'Индикаторы настроения рынка': [
                'VIX для неопределённости',
                'Индекс оптимизма',
                'Рыночный консенсус',
                'Сентиментальные линии',
                'Индикаторы общественного настроения'
            ]
        },
        'Психология': {
            'Эмоциональное восприятие рынка': [
                'Анализ страха как сигнала',
                'Оценка жадности и разворота',
                'Паника как возможность',
                'Эйфория и коррективы',
                'Нерешительность и риск'
            ],
            'Торговая дисциплина': [
                'Строгое следование плану',
                'Контроль риска и мани-менеджмент',
                'Ведение торгового журнала',
                'Самодисциплина',
                'Стратегия управления позицией'
            ],
            'Психология толпы': [
                'Анализ FOMO',
                'Отслеживание массовых эмоций',
                'Эффект стадного мышления',
                'Реакция рынка на новости',
                'Контртренд под давлением толпы'
            ],
            'Когнитивные искажения': [
                'Осознание подтверждения ожиданий',
                'Анализ переоценки возможностей',
                'Контроль самоуверенности',
                'Избежание ошибки выжившего',
                'Внимание к упущенным рискам'
            ],
            'Самоанализ и адаптация': [
                'Пересмотр входов для выявления ошибок',
                'Анализ успешных и неудачных сделок',
                'Корректировка стратегии',
                'Оценка эмоционального состояния',
                'Постоянное обучение'
            ],
            'Мотивация и целеполагание': [
                'Ясные краткосрочные цели',
                'Фокус на долгосрочной стратегии',
                'Визуализация успеха',
                'Позитивный настрой',
                'Поиск возможностей для роста'
            ]
        }
    }

    for category_name_ru, subcategories in categories_data.items():
        cat_record = models.CriterionCategory.query.filter_by(name=category_name_ru).first()
        if not cat_record:
            cat_record = models.CriterionCategory(name=category_name_ru)
            db.session.add(cat_record)
            db.session.flush()
            logger.info(f"Criterion category '{category_name_ru}' (ru) added to DB.")

        for subcategory_name_ru, criteria_list in subcategories.items():
            subcat_record = models.CriterionSubcategory.query.filter_by(
                name=subcategory_name_ru, category_id=cat_record.id
            ).first()
            if not subcat_record:
                subcat_record = models.CriterionSubcategory(
                    name=subcategory_name_ru,
                    category_id=cat_record.id
                )
                db.session.add(subcat_record)
                db.session.flush()
                logger.info(f"Subcategory '{subcategory_name_ru}' (ru) added to '{category_name_ru}'.")

            for criterion_name_en in criteria_list:
                # Здесь сами критерии у нас на английском:
                existing_crit = models.Criterion.query.filter_by(
                    name=criterion_name_en, subcategory_id=subcat_record.id
                ).first()
                if not existing_crit:
                    new_crit = models.Criterion(
                        name=criterion_name_en,
                        subcategory_id=subcat_record.id
                    )
                    db.session.add(new_crit)
                    logger.info(f"Criterion '{criterion_name_en}' added to subcategory '{subcategory_name_ru}'.")

    db.session.commit()
    logger.info("All categories, subcategories and criteria (RU stored) successfully added.")
    
# Wrapper functions for APScheduler jobs
def start_new_poll_test_job():
    with app.app_context():
        try:
            start_new_poll(test_mode=True)
            logger.info("Job 'Start Test Poll' executed successfully.")
        except Exception as e:
            logger.error(f"Error executing job 'Start Test Poll': {e}")
            logger.error(traceback.format_exc())

def start_new_poll_job():
    with app.app_context():
        try:
            start_new_poll()
            logger.info("Job 'Start Poll' executed successfully.")
        except Exception as e:
            logger.error(f"Error executing job 'Start Poll': {e}")
            logger.error(traceback.format_exc())

def process_poll_results_job():
    with app.app_context():
        try:
            process_poll_results()
            logger.info("Job 'Process Poll Results' executed successfully.")
        except Exception as e:
            logger.error(f"Error executing job 'Process Poll Results': {e}")
            logger.error(traceback.format_exc())

def update_real_prices_job():
    with app.app_context():
        try:
            update_real_prices_for_active_polls()
            logger.info("Job 'Update Real Prices' executed successfully.")
        except Exception as e:
            logger.error(f"Error executing job 'Update Real Prices': {e}")
            logger.error(traceback.format_exc())

# Initialize data before the first request
@app.before_first_request
def initialize():
    try:
        db.create_all()
        logger.info("Database created or already exists.")

        # Mini-hack: add missing columns if they do not exist
        try:
            with db.engine.connect() as con:
                # 1) First remove (if exists):
                con.execute("""
                    ALTER TABLE user_staking
                    DROP COLUMN IF EXISTS stake_amount
                """)
                logger.info("Column 'stake_amount' dropped from user_staking if it existed.")
    
                # Add columns to user_staking
                con.execute("""
                    ALTER TABLE user_staking
                    ADD COLUMN IF NOT EXISTS tx_hash VARCHAR(66),
                    ADD COLUMN IF NOT EXISTS staked_usd FLOAT,
                    ADD COLUMN IF NOT EXISTS staked_amount FLOAT,
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW(),
                    ADD COLUMN IF NOT EXISTS unlocked_at TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS pending_rewards FLOAT DEFAULT 0.0,
                    ADD COLUMN IF NOT EXISTS last_claim_at TIMESTAMP DEFAULT NOW()
                """)
                logger.info("Required columns added to user_staking table.")

                # Add columns private_key, unique_wallet_address and unique_private_key to user table
                con.execute("""
                    ALTER TABLE "user"
                    ADD COLUMN IF NOT EXISTS private_key VARCHAR(128),
                    ADD COLUMN IF NOT EXISTS unique_wallet_address VARCHAR(42) UNIQUE,
                    ADD COLUMN IF NOT EXISTS unique_private_key VARCHAR(128)
                """)
                logger.info("Columns 'private_key', 'unique_wallet_address' and 'unique_private_key' added to 'user' table.")
        except Exception as e:
            logger.error(f"ALTER TABLE execution failed: {e}")

        # Initialize unique_wallet_address for existing users
        try:
            users_without_wallet = User.query.filter(
                (User.unique_wallet_address == None) | (User.unique_wallet_address == '')
            ).all()
            for user in users_without_wallet:
                # Generate a unique wallet address
                user.unique_wallet_address = generate_unique_wallet_address()
                user.unique_private_key = generate_unique_private_key()
                logger.info(f"Unique wallet generated for user ID {user.id}.")
            db.session.commit()
            logger.info("Unique wallets for existing users have been initialized.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error initializing unique wallets: {e}")
            logger.error(traceback.format_exc())

        # If needed, create_predefined_data()
        # create_predefined_data()
        if not models.InstrumentCategory.query.first() or not models.CriterionCategory.query.first():
            create_predefined_data()
            create_predefined_data()
            logger.info("Predefined data successfully updated.")
            

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initializing the database: {e}")
        logger.error(traceback.format_exc())

@app.context_processor
def inject_admin_ids():
    return {'ADMIN_TELEGRAM_IDS': ADMIN_TELEGRAM_IDS}

####################
# APScheduler jobs
####################

def accumulate_staking_rewards_job():
    with app.app_context():
        accumulate_staking_rewards()

def start_new_poll_job():
    with app.app_context():
        # New poll for 10 minutes (see poll_functions.py)
        start_new_poll()

def process_poll_results_job():
    with app.app_context():
        process_poll_results()

def update_real_prices_job():
    with app.app_context():
        update_real_prices_for_active_polls()

scheduler = BackgroundScheduler(timezone=pytz.UTC)

# 1) Auto finalize best_setup_voting every 5 minutes
scheduler.add_job(
    id='Auto Finalize Best Setup Voting',
    func=lambda: auto_finalize_best_setup_voting(),
    trigger='interval',
    minutes=5,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)

# 2) Start a new poll every 10 minutes
scheduler.add_job(
    id='Start Poll',
    func=start_new_poll_job,
    trigger='interval',
    minutes=10,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)

# 3) Check poll results every 2 minutes (immediately starts a new one)
scheduler.add_job(
    id='Process Poll Results',
    func=process_poll_results_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=2)
)

# 4) Accumulate staking rewards — every minute
scheduler.add_job(
    id='Accumulate Staking Rewards',
    func=accumulate_staking_rewards_job,
    trigger='interval',
    minutes=1,
    next_run_time=datetime.utcnow() + timedelta(seconds=20)
)

# 5) Update real price every 2 minutes
scheduler.add_job(
    id='Update Real Prices',
    func=update_real_prices_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=1)
)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# Import routes after APScheduler initialization
from routes import *

# Register Blueprints
app.register_blueprint(staking_bp, url_prefix='/staking')  # Register staking_bp here

# Add OpenAI API Key
app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '').strip()
if not app.config['OPENAI_API_KEY']:
    logger.error("OPENAI_API_KEY is not set in environment variables.")
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

# Initialize OpenAI
openai.api_key = app.config['OPENAI_API_KEY']

# Add Robokassa settings
app.config['ROBOKASSA_MERCHANT_LOGIN'] = os.environ.get('ROBOKASSA_MERCHANT_LOGIN', '').strip()
app.config['ROBOKASSA_PASSWORD1'] = os.environ.get('ROBOKASSA_PASSWORD1', '').strip()
app.config['ROBOKASSA_PASSWORD2'] = os.environ.get('ROBOKASSA_PASSWORD2', '').strip()
app.config['ROBOKASSA_RESULT_URL'] = os.environ.get('ROBOKASSA_RESULT_URL', '').strip()
app.config['ROBOKASSA_SUCCESS_URL'] = os.environ.get('ROBOKASSA_SUCCESS_URL', '').strip()
app.config['ROBOKASSA_FAIL_URL'] = os.environ.get('ROBOKASSA_FAIL_URL', '').strip()

# Check for required Robokassa settings
if not all([
    app.config['ROBOKASSA_MERCHANT_LOGIN'],
    app.config['ROBOKASSA_PASSWORD1'],
    app.config['ROBOKASSA_PASSWORD2'],
    app.config['ROBOKASSA_RESULT_URL'],
    app.config['ROBOKASSA_SUCCESS_URL'],
    app.config['ROBOKASSA_FAIL_URL']
]):
    logger.error("Some Robokassa settings are missing from environment variables.")
    raise ValueError("Some Robokassa settings are missing from environment variables.")

# **Run Flask app**

if __name__ == '__main__':
    # Run the app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
