# app.py
import requests
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
from staking_logic import (
    web3,
    WETH_CONTRACT_ADDRESS,
    UJO_CONTRACT_ADDRESS,
    get_token_decimals,
    accumulate_staking_rewards
)

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
    return {'language': session.get('language', 'en')} #чтобы от сессии
    #return {'language': 'en'}  #если жестко en

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

from mini_game import mini_game_bp, distribute_game_rewards

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

@app.context_processor
def utility_processor():
    """
    Возвращаем функцию translate_python в контекст шаблонов,
    чтобы её можно было вызывать прямо в Jinja2.
    """
    return dict(translate_python=translate_python)

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

        # Открываем одно соединение и внутри него делаем все нужные запросы
        with db.engine.connect() as con:

            # Добавляем новую таблицу для игры
            try:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS user_game_score (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES "user"(id),
                        weekly_points INTEGER NOT NULL DEFAULT 0,
                        times_played_today INTEGER NOT NULL DEFAULT 0,
                        last_played_date DATE,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                logger.info("Table user_game_score created/exists.")
            except Exception as e:
                logger.error(f"Error creating user_game_score: {e}")

            # Инициализация столбцов для сохранения очков
            try:
                con.execute("""
                    ALTER TABLE user_game_score
                    ADD COLUMN IF NOT EXISTS weekly_points INTEGER NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS times_played_today INTEGER NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS last_played_date DATE
                """)
                logger.info("Columns for user_game_score table added.")
            except Exception as e:
                logger.error(f"Error altering user_game_score table: {e}")

            # -- 1) Выполняем ALTER TABLE
            try:
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
                    ADD COLUMN IF NOT EXISTS unique_private_key VARCHAR(128),
                    ADD COLUMN IF NOT EXISTS game_scores INTEGER
                """)
                logger.info("Columns 'private_key', 'unique_wallet_address' and 'unique_private_key' added to 'user' table.")
                
                # Добавляем poll_id в таблицу best_setup_candidate
                con.execute("""
                    ALTER TABLE best_setup_candidate
                    ADD COLUMN IF NOT EXISTS poll_id INTEGER
                """)
                logger.info("Column 'poll_id' added to best_setup_candidate if it didn't exist.")

                con.execute("""
                    ALTER TABLE "user"
                    DROP CONSTRAINT IF EXISTS user_unique_wallet_address_key
                """)
                logger.info("Dropped unique constraint from user.unique_wallet_address if it existed.")

                # Добавляем столбец real_prices в best_setup_poll
                con.execute("""
                    ALTER TABLE best_setup_poll
                    ADD COLUMN IF NOT EXISTS real_prices JSON
                """)
                logger.info("Column 'real_prices' added to best_setup_poll if it didn't exist.")

                # Добавляем voting_screenshot в best_setup_candidate
                con.execute("""
                    ALTER TABLE best_setup_candidate
                    ADD COLUMN IF NOT EXISTS voting_screenshot VARCHAR(255)
                """)
                logger.info("Column 'voting_screenshot' added to best_setup_candidate if it didn't exist.")

            except Exception as e:
                logger.error(f"ALTER TABLE execution failed: {e}")

            # -- 2) Создаём таблицу user_game_score
            try:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS user_game_score (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES "user"(id),
                        weekly_points INTEGER NOT NULL DEFAULT 0,
                        times_played_today INTEGER NOT NULL DEFAULT 0,
                        last_played_date DATE,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                logger.info("Table user_game_score created/exists.")
            except Exception as e:
                logger.error(f"Error creating user_game_score: {e}")

            # -- 3) Проверяем, есть ли config(key='game_rewards_pool_size'):
            res = con.execute("""
                SELECT * FROM config WHERE key='game_rewards_pool_size'
            """)
            row = res.fetchone()
            if not row:
                try:
                    con.execute("""
                        INSERT INTO config(key, value) VALUES('game_rewards_pool_size','100')
                    """)
                    logger.info("Default game_rewards_pool_size=100 set in config.")
                except Exception as e:
                    logger.error(f"Error inserting game_rewards_pool_size in config: {e}")

        # -- 4) Инициализация unique_wallet_address для пользователей (уже вне with, т.к. дальше используем ORM)
        try:
            users_without_wallet = models.User.query.filter(
                (models.User.unique_wallet_address == None) | (models.User.unique_wallet_address == '')
            ).all()
            for user in users_without_wallet:
                # Вместо генерации - временно присвоим пустые значения
                user.unique_wallet_address = ""
                user.unique_private_key = ""

            db.session.commit()
            logger.info("Unique wallets for existing users have been initialized (now set to empty).")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error initializing unique wallets: {e}")
            logger.error(traceback.format_exc())

        # -- 5) При необходимости заполняем предустановленные данные
        if not models.InstrumentCategory.query.first() or not models.CriterionCategory.query.first():
            create_predefined_data()
            create_predefined_data()
            logger.info("Predefined data successfully updated.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initializing the database: {e}")
        logger.error(traceback.format_exc())

        # -- 5) При необходимости заполняем предустановленные данные
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
def distribute_game_rewards_job():
    with app.app_context():
        distribute_game_rewards()

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

#6) P2E

scheduler.add_job(
    id='Distribute Weekly Game Rewards',
    func=distribute_game_rewards_job,   # <-- вызываем "обёртку"
    trigger='cron',
    day_of_week='sun',
    hour=23,
    minute=59
    
)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

##########################################
# 7) Ежедневная покупка ровно 100000 UJO #
##########################################
def buy_exact_ujo_from_eth(
    private_key: str,
    user_address: str,
    ujo_amount: float,
    paraswap_api_url="https://api.paraswap.io",
    version="6.2"
) -> bool:
    """
    Покупаем ровно ujo_amount UJO на уникальном кошельке user_address.
    Алгоритм:
      1) Получаем quote с side=BUY, но srcToken=WETH, destToken=UJO.
      2) Из quote берём srcAmount (сколько WETH нужно).
      3) Если у пользователя не хватает WETH, делаем deposit_eth_to_weth на недостающую сумму.
      4) Делаем POST /transactions/ с полученным priceRoute, отправляем транзакцию.

    Предполагается, что если у пользователя не хватает ETH — сделка упадёт.
    """
    try:
        # --- 0) Читаем decimals для UJO ---
        from staking_logic import deposit_eth_to_weth, get_token_balance
        ujo_decimals = get_token_decimals(UJO_CONTRACT_ADDRESS)
        desired_ujo_wei = int(ujo_amount * 10**ujo_decimals)

        chain_id = web3.eth.chain_id

        # --- 1) Запрашиваем котировку "WETH -> UJO, side=BUY" ---
        quote_url = f"{paraswap_api_url}/quote"
        params_quote = {
            "version": version,
            "srcToken": WETH_CONTRACT_ADDRESS,
            "destToken": UJO_CONTRACT_ADDRESS,
            "amount": str(desired_ujo_wei),  # <-- "amount" = желаемое кол-во UJO в wei
            "userAddress": user_address,
            "side": "BUY",
            "srcDecimals": 18,                  # WETH decimals = 18
            "destDecimals": ujo_decimals,
            "chainId": chain_id,
            "mode": "market"
        }
        resp_q = requests.get(quote_url, params=params_quote)
        if resp_q.status_code != 200:
            logger.error(f"[buy_exact_ujo] ParaSwap quote(BUY) failed: {resp_q.text}")
            return False
        data_q = resp_q.json()
        price_route = data_q.get("priceRoute")
        if not price_route:
            logger.error("[buy_exact_ujo] No priceRoute in WETH->UJO BUY quote response.")
            return False

        # Из priceRoute нам важно узнать, сколько WETH нужно:
        needed_weth_wei = price_route.get("srcAmount")
        if not needed_weth_wei or not needed_weth_wei.isdigit():
            logger.error("[buy_exact_ujo] srcAmount not found in priceRoute.")
            return False

        needed_weth_float = float(needed_weth_wei) / 10**18  # т.к. WETH decimals=18
        logger.info(f"[buy_exact_ujo] Need ~{needed_weth_float} WETH to buy {ujo_amount} UJO.")

        # --- 2) Проверяем, есть ли у нас достаточно WETH, если нет — делаем deposit из ETH ---
        current_weth = get_token_balance(user_address, weth_contract)
        if current_weth < needed_weth_float - 1e-12:
            # нужно задепозитить разницу
            missing = needed_weth_float - current_weth
            logger.info(f"[buy_exact_ujo] Not enough WETH; need {missing} more. Trying deposit from ETH.")
            ok_deposit = deposit_eth_to_weth(private_key, user_address, missing)
            if not ok_deposit:
                logger.error("[buy_exact_ujo] deposit_eth_to_weth failed.")
                return False
            # теперь WETH должно хватать

        # --- 3) POST /transactions/... ---
        tx_url = f"{paraswap_api_url}/transactions/{chain_id}"
        tx_payload = {
            "priceRoute": price_route,
            "srcToken": WETH_CONTRACT_ADDRESS,
            "destToken": UJO_CONTRACT_ADDRESS,
            "srcAmount": needed_weth_wei,   # сколько WETH будем тратить
            "userAddress": user_address,
            "slippage": 1000  # 10%
        }
        resp_tx = requests.post(tx_url, json=tx_payload)
        if resp_tx.status_code != 200:
            logger.error(f"[buy_exact_ujo] /transactions build error: {resp_tx.text}")
            return False
        tx_data = resp_tx.json()
        if "to" not in tx_data or "data" not in tx_data:
            logger.error(f"[buy_exact_ujo] Invalid /transactions response: {tx_data}")
            return False

        # --- 4) Подписываем и отправляем ---
        to_address = Web3.to_checksum_address(tx_data["to"])
        nonce = web3.eth.get_transaction_count(user_address)
        transaction = {
            "to": to_address,
            "data": tx_data["data"],
            "value": int(tx_data["value"]),       # Возможно 0, т.к. расходуем WETH
            "gasPrice": int(tx_data["gasPrice"]),
            "gas": int(tx_data["gas"]),
            "nonce": nonce,
            "chainId": chain_id
        }
        signed_tx = web3.eth.account.sign_transaction(transaction, private_key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"[buy_exact_ujo] Final BUY tx sent, hash={Web3.to_hex(tx_hash)}")

        rcpt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if rcpt.status == 1:
            logger.info("[buy_exact_ujo] success! 100k UJO purchased.")
            return True
        else:
            logger.error("[buy_exact_ujo] Tx reverted.")
            return False

    except Exception as e:
        logger.exception("[buy_exact_ujo] exception:")
        return False


def daily_buy_100k_ujo():
    """
    Задание: каждый день покупать ровно 100000 UJO на уникальном кошельке админа
    (telegram_id=427032240). Нужно, чтобы на этом кошельке было достаточно ETH
    для сделки (и газа).
    """
    with app.app_context():
        from models import User
        admin_user = User.query.filter_by(telegram_id=427032240).first()
        if not admin_user or not admin_user.unique_wallet_address or not admin_user.unique_private_key:
            logger.info("Admin user wallet not found or not generated.")
            return
        try:
            exact_amount = 100000.0  # ровно 100k
            success = buy_exact_ujo_from_eth(
                admin_user.unique_private_key,
                Web3.to_checksum_address(admin_user.unique_wallet_address),
                exact_amount
            )
            if success:
                logger.info("Daily buy of EXACT 100000 UJO for admin succeeded.")
            else:
                logger.error("Daily buy of EXACT 100000 UJO for admin failed.")
        except Exception as ex:
            logger.exception("Error in daily_buy_100k_ujo job:")


# 7) Добавляем новую задачу APScheduler на каждый день в полночь
#scheduler.add_job(
    #id='Daily Admin Purchase EXACT 100k UJO',
    #func=daily_buy_100k_ujo,
    #trigger='cron',
    #hour=0,
    #minute=0
#)
scheduler.add_job(
    id='Daily Admin Purchase EXACT 100k UJO',
    func=daily_buy_100k_ujo,
    trigger='interval',
    minutes=10,  # Устанавливаем интервал в 10 минут для тестирования
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=10)
)

# Import routes after APScheduler initialization
from routes import *

# Register Blueprints
app.register_blueprint(staking_bp, url_prefix='/staking')  # Register staking_bp here

app.register_blueprint(mini_game_bp, url_prefix='/game')

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
