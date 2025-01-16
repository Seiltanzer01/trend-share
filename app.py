# app.py

import os
import logging
import traceback
import atexit  # Добавляем импорт atexit
from best_setup_voting import init_best_setup_voting_routes, auto_finalize_best_setup_voting
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from web3 import Web3  # Добавляем импорт Web3
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
from routes_staking import staking_bp  # Убедитесь, что routes_staking.py существует и содержит staking_bp
# Добавление OpenAI
import openai

# Добавление APScheduler для планирования задач
from apscheduler.schedulers.background import BackgroundScheduler

# Импорт моделей и форм
import models  # Убедитесь, что models.py импортирует db из extensions.py
from poll_functions import start_new_poll, process_poll_results, update_real_prices_for_active_polls
from staking_logic import accumulate_staking_rewards

ADMIN_TELEGRAM_IDS = [427032240]

# Конфигурация APScheduler
class ConfigScheduler:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "UTC"  # Устанавливаем таймзону

# Инициализация Flask-приложения
app = Flask(__name__)
app.config.from_object(ConfigScheduler())

# Настройка CSRF защиты
csrf = CSRFProtect(app)

# Контекстный процессор для предоставления CSRF токена в шаблонах
@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf()}

# Добавляем контекстный процессор для языка:
@app.context_processor
def inject_language():
    return {'language': 'en'}                       #return {'language': session.get('language', 'en')}

@app.route('/info')
def info():
    return render_template('info.html')

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
logging.basicConfig(level=logging.INFO)  # Установлено на INFO, можно изменить на DEBUG при необходимости
logger = logging.getLogger(__name__)

# Использование переменных окружения для конфиденциальных данных
secret_key_env = os.environ.get('SECRET_KEY', '').strip()
if not secret_key_env:
    logger.error("SECRET_KEY не установлен в переменных окружения.")
    raise ValueError("SECRET_KEY не установлен в переменных окружения.")
app.secret_key = secret_key_env

# Настройки базы данных
raw_database_url = os.environ.get('DATABASE_URL')

if not raw_database_url:
    logger.error("DATABASE_URL не установлен в переменных окружения.")
    raise ValueError("DATABASE_URL не установлен в переменных окружения.")

# Парсинг и корректировка строки подключения к базе данных
parsed_url = urlparse(raw_database_url)

# Проверка и добавление 'sslmode=require' если необходимо
query_params = parse_qs(parsed_url.query)
if 'sslmode' not in query_params:
    query_params['sslmode'] = ['require']

new_query = urlencode(query_params, doseq=True)
parsed_url = parsed_url._replace(query=new_query)

# Обновлённая строка подключения
DATABASE_URL = urlunparse(parsed_url)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройки APP_HOST для формирования ссылок
app.config['APP_HOST'] = os.environ.get('APP_HOST', 'trend-share.onrender.com')

# Настройки сессии
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Позволяет куки-сессиям работать в кросс-доменных запросах
app.config['SESSION_COOKIE_SECURE'] = True      # Требует HTTPS
app.config['SESSION_COOKIE_DOMAIN'] = 'trend-share.onrender.com'  # Указание домена для куки

# Настройки Amazon S3
app.config['AWS_ACCESS_KEY_ID'] = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
app.config['AWS_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
app.config['AWS_S3_BUCKET'] = os.environ.get('AWS_S3_BUCKET', '').strip()
app.config['AWS_S3_REGION'] = os.environ.get('AWS_S3_REGION', 'us-east-1').strip()

# Проверка наличия необходимых AWS настроек
if not all([app.config['AWS_ACCESS_KEY_ID'], app.config['AWS_SECRET_ACCESS_KEY'],
            app.config['AWS_S3_BUCKET'], app.config['AWS_S3_REGION']]):
    logger.error("Некоторые AWS настройки отсутствуют в переменных окружения.")
    raise ValueError("Некоторые AWS настройки отсутствуют в переменных окружения.")

# Инициализация клиента S3
s3_client = boto3.client(
    's3',
    region_name=app.config['AWS_S3_REGION'],
    aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY']
)

# Инициализация расширений с приложением
db = SQLAlchemy(app)
migrate = Migrate(app, db)

init_best_setup_voting_routes(app, db)

# Контекстный процессор для предоставления datetime в шаблонах
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# Вспомогательные функции для работы с S3
def upload_file_to_s3(file: FileStorage, filename: str) -> bool:
    """
    Загружает файл в S3.
    :param file: FileStorage объект.
    :param filename: Имя файла в S3.
    :return: True при успешной загрузке, False иначе.
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
        logger.info(f"Файл '{filename}' успешно загружен в S3.")
        return True
    except ClientError as e:
        logger.error(f"Ошибка при загрузке файла '{filename}' в S3: {e}")
        return False

def delete_file_from_s3(filename: str) -> bool:
    """
    Удаляет файл из S3.
    :param filename: Имя файла в S3.
    :return: True при успешном удалении, False иначе.
    """
    try:
        s3_client.delete_object(Bucket=app.config['AWS_S3_BUCKET'], Key=filename)
        logger.info(f"Файл '{filename}' успешно удалён из S3.")
        return True
    except ClientError as e:
        logger.error(f"Ошибка при удалении файла '{filename}' из S3: {e}")
        return False

def generate_s3_url(filename: str) -> str:
    """
    Генерирует публичный URL для файла в S3.
    :param filename: Имя файла в S3.
    :return: URL файла.
    """
    bucket_name = app.config['AWS_S3_BUCKET']
    region = app.config['AWS_S3_REGION']

    if region == 'us-east-1':
        url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
    else:
        url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{filename}"
    return url

# Функция для получения APP_HOST
def get_app_host():
    return app.config['APP_HOST']

# Функция для создания предопределённых данных
def create_predefined_data():
    # Проверяем, есть ли уже данные
    if models.InstrumentCategory.query.first():
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
        # Добавьте больше инструментов по необходимости
    ]

    for instrument_data in instruments:
        category_name = instrument_data['category']
        instrument_name = instrument_data['name']

        # Получаем или создаём категорию
        category = models.InstrumentCategory.query.filter_by(name=category_name).first()
        if not category:
            category = models.InstrumentCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Категория '{category_name}' добавлена.")

        # Проверяем, существует ли инструмент
        instrument = models.Instrument.query.filter_by(name=instrument_name).first()
        if not instrument:
            instrument = models.Instrument(name=instrument_name, category_id=category.id)
            db.session.add(instrument)
            logger.info(f"Инструмент '{instrument_name}' добавлен в категорию '{category_name}'.")

    db.session.commit()
    logger.info("Инструменты и категории инструментов успешно добавлены.")

    # Создаём категории критериев для обоснования сделки
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


    for category_name, subcategories in categories_data.items():
        category = models.CriterionCategory.query.filter_by(name=category_name).first()
        if not category:
            category = models.CriterionCategory(name=category_name)
            db.session.add(category)
            db.session.flush()
            logger.info(f"Категория критерия '{category_name}' добавлена.")

        for subcategory_name, criteria_list in subcategories.items():
            subcategory = models.CriterionSubcategory.query.filter_by(name=subcategory_name, category_id=category.id).first()
            if not subcategory:
                subcategory = models.CriterionSubcategory(
                    name=subcategory_name,
                    category_id=category.id
                )
                db.session.add(subcategory)
                db.session.flush()
                logger.info(f"Подкатегория '{subcategory_name}' добавлена в категорию '{category_name}'.")

            for criterion_name in criteria_list:
                criterion = models.Criterion.query.filter_by(name=criterion_name, subcategory_id=subcategory.id).first()
                if not criterion:
                    criterion = models.Criterion(
                        name=criterion_name,
                        subcategory_id=subcategory.id
                    )
                    db.session.add(criterion)
                    logger.info(f"Критерий '{criterion_name}' добавлен в подкатегорию '{subcategory_name}'.")

    db.session.commit()
    logger.info("Критерии, подкатегории и категории критериев успешно добавлены.")

# Обёртки для задач APScheduler
def start_new_poll_test_job():
    with app.app_context():
        try:
            start_new_poll(test_mode=True)
            logger.info("Задача 'Start Test Poll' выполнена успешно.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи 'Start Test Poll': {e}")
            logger.error(traceback.format_exc())

def start_new_poll_job():
    with app.app_context():
        try:
            start_new_poll()
            logger.info("Задача 'Start Poll' выполнена успешно.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи 'Start Poll': {e}")
            logger.error(traceback.format_exc())

def process_poll_results_job():
    with app.app_context():
        try:
            process_poll_results()
            logger.info("Задача 'Process Poll Results' выполнена успешно.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи 'Process Poll Results': {e}")
            logger.error(traceback.format_exc())

def update_real_prices_job():
    with app.app_context():
        try:
            update_real_prices_for_active_polls()
            logger.info("Задача 'Update Real Prices' выполнена успешно.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи 'Update Real Prices': {e}")
            logger.error(traceback.format_exc())

# Инициализация данных при первом запуске
@app.before_first_request
def initialize():
    try:
        db.create_all()
        logger.info("База данных создана или уже существует.")

        # Мини-хак: Добавляем нужные колонки, если их нет
        try:
            with db.engine.connect() as con:
                 # 1) Сначала удаляем (если есть):
                con.execute("""
                    ALTER TABLE user_staking
                    DROP COLUMN IF EXISTS stake_amount
                """)
                logger.info("Колонка 'stake_amount' удалена из user_staking (если существовала).")
    
                # Добавление колонок в user_staking
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
                logger.info("Необходимые колонки добавлены в таблицу user_staking.")

                # Добавление колонок private_key, unique_wallet_address и unique_private_key в таблицу user
                con.execute("""
                    ALTER TABLE "user"
                    ADD COLUMN IF NOT EXISTS private_key VARCHAR(128),
                    ADD COLUMN IF NOT EXISTS unique_wallet_address VARCHAR(42) UNIQUE,
                    ADD COLUMN IF NOT EXISTS unique_private_key VARCHAR(128)
                """)
                logger.info("Колонки 'private_key', 'unique_wallet_address' и 'unique_private_key' добавлены в таблицу 'user'.")
        except Exception as e:
            logger.error(f"Не удалось выполнить ALTER TABLE: {e}")

        # Инициализация unique_wallet_address для существующих пользователей
        try:
            users_without_wallet = User.query.filter(
                (User.unique_wallet_address == None) | (User.unique_wallet_address == '')
            ).all()
            for user in users_without_wallet:
                # Генерация уникального адреса кошелька
                user.unique_wallet_address = generate_unique_wallet_address()
                user.unique_private_key = generate_unique_private_key()
                logger.info(f"Уникальный кошелёк сгенерирован для пользователя ID {user.id}.")
            db.session.commit()
            logger.info("Уникальные кошельки для существующих пользователей инициализированы.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при инициализации уникальных кошельков: {e}")
            logger.error(traceback.format_exc())

        # Если нужно, create_predefined_data()
        # create_predefined_data()
        if not models.InstrumentCategory.query.first() or not models.CriterionCategory.query.first():
            create_predefined_data()
            create_predefined_data()
            logger.info("Предопределённые данные успешно обновлены.")
            

    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        logger.error(traceback.format_exc())

@app.context_processor
def inject_admin_ids():
    return {'ADMIN_TELEGRAM_IDS': ADMIN_TELEGRAM_IDS}

####################
# Планировщики APScheduler
####################

def accumulate_staking_rewards_job():
    with app.app_context():
        accumulate_staking_rewards()

def start_new_poll_job():
    with app.app_context():
        # Новый опрос на 10 минут (см. poll_functions.py)
        start_new_poll()

def process_poll_results_job():
    with app.app_context():
        process_poll_results()

def update_real_prices_job():
    with app.app_context():
        update_real_prices_for_active_polls()

scheduler = BackgroundScheduler(timezone=pytz.UTC)

# 1) Автозавершение best_setup_voting каждые 5 минут
scheduler.add_job(
    id='Auto Finalize Best Setup Voting',
    func=lambda: auto_finalize_best_setup_voting(),
    trigger='interval',
    minutes=5,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)

# 2) Запуск нового опроса каждые 10 минут
scheduler.add_job(
    id='Start Poll',
    func=start_new_poll_job,
    trigger='interval',
    minutes=10,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)

# 3) Проверка завершения опроса каждые 2 минуты (сразу запускает новый)
scheduler.add_job(
    id='Process Poll Results',
    func=process_poll_results_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=2)
)

# 4) Накопление стейкинг наград — каждую минуту
scheduler.add_job(
    id='Accumulate Staking Rewards',
    func=accumulate_staking_rewards_job,
    trigger='interval',
    minutes=1,
    next_run_time=datetime.utcnow() + timedelta(seconds=20)
)

# 5) Обновление реальной цены каждые 2 минуты
scheduler.add_job(
    id='Update Real Prices',
    func=update_real_prices_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=1)
)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# Импорт маршрутов после инициализации APScheduler
from routes import *

# Регистрация Blueprints
app.register_blueprint(staking_bp, url_prefix='/staking')  # Регистрация staking_bp здесь

# Добавление OpenAI API Key
app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '').strip()
if not app.config['OPENAI_API_KEY']:
    logger.error("OPENAI_API_KEY не установлен в переменных окружения.")
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения.")

# Инициализация OpenAI
openai.api_key = app.config['OPENAI_API_KEY']

# Добавление Robokassa настроек
app.config['ROBOKASSA_MERCHANT_LOGIN'] = os.environ.get('ROBOKASSA_MERCHANT_LOGIN', '').strip()
app.config['ROBOKASSA_PASSWORD1'] = os.environ.get('ROBOKASSA_PASSWORD1', '').strip()
app.config['ROBOKASSA_PASSWORD2'] = os.environ.get('ROBOKASSA_PASSWORD2', '').strip()
app.config['ROBOKASSA_RESULT_URL'] = os.environ.get('ROBOKASSA_RESULT_URL', '').strip()
app.config['ROBOKASSA_SUCCESS_URL'] = os.environ.get('ROBOKASSA_SUCCESS_URL', '').strip()
app.config['ROBOKASSA_FAIL_URL'] = os.environ.get('ROBOKASSA_FAIL_URL', '').strip()

# Проверка наличия необходимых Robokassa настроек
if not all([
    app.config['ROBOKASSA_MERCHANT_LOGIN'],
    app.config['ROBOKASSA_PASSWORD1'],
    app.config['ROBOKASSA_PASSWORD2'],
    app.config['ROBOKASSA_RESULT_URL'],
    app.config['ROBOKASSA_SUCCESS_URL'],
    app.config['ROBOKASSA_FAIL_URL']
]):
    logger.error("Некоторые Robokassa настройки отсутствуют в переменных окружения.")
    raise ValueError("Некоторые Robokassa настройки отсутствуют в переменных окружения.")

# **Запуск Flask-приложения**

if __name__ == '__main__':
    # Запуск приложения
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
