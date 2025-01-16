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

def translate_python(russian_text):
    """
    Translates string if session['language'] == 'en'.
    Otherwise returns the original string.
    """
    if not russian_text:
        return russian_text  # empty

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

# Function to create predefined data
def create_predefined_data():
    # Check if data already exists
    if models.InstrumentCategory.query.first():
        logger.info("Predefined data already exists. Skipping creation.")
        return

    # Create instrument categories and instruments
    instruments = [
        # Currency pairs (Forex)
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
        # Indices
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
        # Commodities
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
        # Cryptocurrencies
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
        # Add more instruments if needed
    ]

    for instrument_data in instruments:
        category_name = instrument_data['category']
        instrument_name = instrument_data['name']

        # Get or create category
        category = models.InstrumentCategory.query.filter_by(name=category_name).first()
        if not category:
            category = models.InstrumentCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Category '{category_name}' added.")

        # Check if instrument already exists
        instrument = models.Instrument.query.filter_by(name=instrument_name).first()
        if not instrument:
            instrument = models.Instrument(name=instrument_name, category_id=category.id)
            db.session.add(instrument)
            logger.info(f"Instrument '{instrument_name}' added to category '{category_name}'.")

    db.session.commit()
    logger.info("Instruments and instrument categories successfully added.")

    # Create criteria categories for trade justification
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
                'Формации продолжения (flags, pennants, wedges)',
                'Triangles (symmetrical, ascending, descending)',
                'Consolidations and sideways movements',
                'Composite pattern analysis'
            ],
            'Динамика ценового движения': [
                'Break of levels (gap analysis)',
                'Analysis of false breakouts',
                'Consolidation with momentum',
                'Sharp spikes and corrections',
                'Impulsive price changes'
            ],
            'Свечные паттерны': [
                'Reversal patterns (pin bars, doji)',
                'Engulfing (bullish/bearish)',
                'Multi-phase candle behavior',
                'Combined candle signals',
                'Candle reversal points'
            ],
            'Уровни и трендовые линии': [
                'Horizontal support/resistance levels',
                'Dynamic trend lines',
                'Trend channels',
                'Consolidation zones',
                'Multi-level structure'
            ],
            'Объёмно-ценовые взаимодействия': [
                'Volume profile at entry zone',
                'Price and volume alignment',
                'Volume anomalies at breakouts',
                'Clustering of volume spikes',
                'Volume confirmation of the trend'
            ]
        },
        'Волны Эллиота': {
            'Импульсные и коррекционные структуры': [
                'Impulse waves (1, 3, 5)',
                'Corrective waves (2, 4)',
                'Wave fractality',
                'Wave start and end',
                'Time intervals of waves'
            ],
            'Коррекционные модели': [
                'Zigzag model',
                'Reversal zones',
                'Triangular compression',
                'Corrective parallelograms',
                'Mixed corrections'
            ],
            'Фибоначчи в волновой теории': [
                'Fibonacci retracements for entry',
                'Fibonacci wave ratios',
                'Extensions and retracements',
                'Fibonacci levels for SL/TP',
                'Alignment with Fibonacci'
            ],
            'Границы и завершение волн': [
                'Wave reversal points',
                'Wave length ratios',
                'Impulse weakening zones',
                'Time parameters of waves',
                'Impulse completion'
            ],
            'Модели и структуры волн': [
                'Classic Elliott model',
                'Impulse wave submodels',
                'Multifractal models',
                'Analysis on various timeframes',
                'Synchronization with main trend'
            ],
            'Интерпретация волновых соотношений': [
                'Wave proportions',
                'Comparison of duration and amplitude',
                'Correlation with volume',
                'Comparison of impulse and corrective waves',
                'Forecast based on wave structure'
            ]
        },
        'Price Action': {
            'Ключевые свечные модели': [
                'Pin bars as reversal signals',
                'Candle engulfing',
                'Doji for waiting reversal',
                'Harami pattern',
                'Long shadow candles'
            ],
            'Динамика ценового поведения': [
                'Formation of local extrema',
                'Consolidation with breakout',
                'Rejection of key levels',
                'Recording pullbacks',
                'Divergence of price and volume'
            ],
            'Структуры поддержки/сопротивления': [
                'Strong support/resistance levels',
                'Price reversal from key zones',
                'Fixed and dynamic barriers',
                'Reaction to historical levels',
                'Breakout with retest'
            ],
            'Брейк-аут и фальшивые пробои': [
                'True level breakouts',
                'Filtering false breakouts',
                'Close candle at breakout level',
                'Level contact before breakout',
                'Pullbacks after breakout'
            ],
            'Интервальные и мультифрейм модели': [
                'Intraday dynamics',
                'Alignment of different timeframes',
                'Asymmetry on short intervals',
                'Transition from local to global trends',
                'Analysis of session open/close events'
            ],
            'Комплексный Price Action анализ': [
                'Alignment of levels and candles',
                'Integration of price anomalies and volume',
                'Contextual market analysis',
                'Multi-timeframe signal verification',
                'Integration of signals for optimal entry'
            ]
        },
        'Индикаторы': {
            'Осцилляторы моментума': [
                'RSI for overbought/oversold',
                'Stochastic for reversals',
                'CCI for momentum measurement',
                'Williams %R for extremes',
                'ROC for price dynamics'
            ],
            'Объёмные индикаторы': [
                'OBV for trend confirmation',
                'Accumulation/Distribution for buy/sell assessment',
                'MFI for cash flow',
                'Volume Oscillator for volume anomalies',
                'CMF for buyer/seller pressure'
            ],
            'Индикаторы волатильности': [
                'Bollinger Bands for overbought/oversold zones',
                'ATR for stop losses',
                'Keltner Channels for trend zones',
                'Donchian Channels for extremes',
                'Standard Deviation for volatility'
            ],
            'Скользящие средние': [
                'SMA for base trend',
                'EMA for real-time tracking',
                'WMA for accurate calculation',
                'HMA for noise smoothing',
                'TEMA for quick entry'
            ],
            'Сигнальные системы': [
                'MACD for trend changes',
                'Moving Average cross for entry',
                'Oscillator divergence',
                'Reversal oscillators in combination',
                'Automated signals'
            ],
            'Индикаторы настроения рынка': [
                'VIX for uncertainty',
                'Optimism Index',
                'Market consensus',
                'Sentiment lines',
                'Public sentiment indicators'
            ]
        },
        'Психология': {
            'Эмоциональное восприятие рынка': [
                'Fear analysis as a signal',
                'Evaluation of greed and reversal',
                'Panic as an opportunity',
                'Euphoria and corrections',
                'Indecision and risk'
            ],
            'Торговая дисциплина': [
                'Strict adherence to plan',
                'Risk control and money management',
                'Maintaining a trading journal',
                'Self-discipline',
                'Position management strategy'
            ],
            'Психология толпы': [
                'FOMO analysis',
                'Tracking mass emotions',
                'Herd mentality effect',
                'Market reaction to news',
                'Counter-trend under crowd pressure'
            ],
            'Когнитивные искажения': [
                'Awareness of confirmation bias',
                'Analysis of overestimation of abilities',
                'Control of overconfidence',
                'Avoiding survivorship bias',
                'Attention to missed risks'
            ],
            'Самоанализ и адаптация': [
                'Review entries to identify mistakes',
                'Analysis of successful and unsuccessful trades',
                'Strategy adjustment',
                'Evaluation of emotional state',
                'Continuous learning'
            ],
            'Мотивация и целеполагание': [
                'Clear short-term goals',
                'Focus on long-term strategy',
                'Visualization of success',
                'Positive mindset',
                'Seeking growth opportunities'
            ]
        }
    }


    for category_name, subcategories in categories_data.items():
        category = models.CriterionCategory.query.filter_by(name=category_name).first()
        if not category:
            category = models.CriterionCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Criterion category '{category_name}' added.")

        for subcategory_name, criteria_list in subcategories.items():
            subcategory = models.CriterionSubcategory.query.filter_by(name=subcategory_name, category_id=category.id).first()
            if not subcategory:
                subcategory = models.CriterionSubcategory(
                    name=subcategory_name,
                    category_id=category.id
                )
                db.session.add(subcategory)
                db.session.flush()
                logger.info(f"Subcategory '{subcategory_name}' added to category '{category_name}'.")

            for criterion_name in criteria_list:
                criterion = models.Criterion.query.filter_by(name=criterion_name, subcategory_id=subcategory.id).first()
                if not criterion:
                    criterion = models.Criterion(
                        name=criterion_name,
                        subcategory_id=subcategory.id
                    )
                    db.session.add(criterion)
                    logger.info(f"Criterion '{criterion_name}' added to subcategory '{subcategory_name}'.")

    db.session.commit()
    logger.info("Criteria, subcategories and criterion categories successfully added.")

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
