#app.py

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
import openai

from apscheduler.schedulers.background import BackgroundScheduler

import models  # Убедитесь, что models.py импортирует db из extensions.py
from poll_functions import start_new_poll, process_poll_results, update_real_prices_for_active_polls
from staking_logic import accumulate_staking_rewards

ADMIN_TELEGRAM_IDS = [427032240]

class ConfigScheduler:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "UTC"

app = Flask(__name__)
app.config.from_object(ConfigScheduler())

csrf = CSRFProtect(app)

@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf()}

@app.route('/info')
def info():
    return render_template('info.html')

CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            "https://trend-share.onrender.com",
            "https://t.me"
        ]
    }
})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

secret_key_env = os.environ.get('SECRET_KEY', '').strip()
if not secret_key_env:
    logger.error("SECRET_KEY не установлен в переменных окружения.")
    raise ValueError("SECRET_KEY не установлен в переменных окружения.")
app.secret_key = secret_key_env

raw_database_url = os.environ.get('DATABASE_URL')
if not raw_database_url:
    logger.error("DATABASE_URL не установлен в переменных окружения.")
    raise ValueError("DATABASE_URL не установлен в переменных окружения.")

parsed_url = urlparse(raw_database_url)
query_params = parse_qs(parsed_url.query)
if 'sslmode' not in query_params:
    query_params['sslmode'] = ['require']
new_query = urlencode(query_params, doseq=True)
parsed_url = parsed_url._replace(query=new_query)
DATABASE_URL = urlunparse(parsed_url)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['APP_HOST'] = os.environ.get('APP_HOST', 'trend-share.onrender.com')

app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_DOMAIN'] = 'trend-share.onrender.com'

app.config['AWS_ACCESS_KEY_ID'] = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
app.config['AWS_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
app.config['AWS_S3_BUCKET'] = os.environ.get('AWS_S3_BUCKET', '').strip()
app.config['AWS_S3_REGION'] = os.environ.get('AWS_S3_REGION', 'us-east-1').strip()

if not all([app.config['AWS_ACCESS_KEY_ID'], app.config['AWS_SECRET_ACCESS_KEY'],
            app.config['AWS_S3_BUCKET'], app.config['AWS_S3_REGION']]):
    logger.error("Некоторые AWS настройки отсутствуют в переменных окружения.")
    raise ValueError("Некоторые AWS настройки отсутствуют в переменных окружения.")

s3_client = boto3.client(
    's3',
    region_name=app.config['AWS_S3_REGION'],
    aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY']
)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

init_best_setup_voting_routes(app, db)

@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

def upload_file_to_s3(file: FileStorage, filename: str) -> bool:
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
    try:
        s3_client.delete_object(Bucket=app.config['AWS_S3_BUCKET'], Key=filename)
        logger.info(f"Файл '{filename}' успешно удалён из S3.")
        return True
    except ClientError as e:
        logger.error(f"Ошибка при удалении файла '{filename}' из S3: {e}")
        return False

def generate_s3_url(filename: str) -> str:
    bucket_name = app.config['AWS_S3_BUCKET']
    region = app.config['AWS_S3_REGION']
    if region == 'us-east-1':
        url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
    else:
        url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{filename}"
    return url

def get_app_host():
    return app.config['APP_HOST']

# Функция для создания предопределённых данных с upsert (merge)
def create_predefined_data():
    # Обновляем/вставляем категории инструментов и инструменты
    instruments = [
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
        # ... остальные инструменты
    ]

    for instrument_data in instruments:
        category_name = instrument_data['category']
        instrument_name = instrument_data['name']
        new_category = models.InstrumentCategory(name=category_name)
        category = db.session.merge(new_category)
        db.session.flush()  # чтобы получить category.id
        new_instrument = models.Instrument(name=instrument_name, category_id=category.id)
        db.session.merge(new_instrument)
    db.session.commit()
    logger.info("Инструменты и категории инструментов успешно обновлены.")

    # Обновляем/вставляем категории критериев, подкатегории и критерии
    categories_data = {
        'Смарт-мани': {
            'Уровни': [
                'Уровни поддержки и сопротивления',
                'Психологические уровни',
                'Фибоначчи уровни',
                'Pivot Points',
                'Ключевые ценовые зоны'
            ],
            'Ликвидность': [
                'Зоны высокой ликвидности',
                'Области накопления капитала',
                'Имбаланс рынка',
                'Объёмные скопления',
                'Аномальные объёмы'
            ],
            'Позиционирование крупных игроков': [
                'Скрытые ордера',
                'Действия институционалов',
                'Крупные сделки',
                'Анализ Dark Pool',
                'Отчёты COT'
            ],
            'Перетоки капитала': [
                'Накопление на низких ценах',
                'Распределение на высоких ценах',
                'Смена направления капитала',
                'Объёмные всплески',
                'Анализ ликвидности в экстремумах'
            ],
            'Инсайдерская активность': [
                'Данные от инсайдеров',
                'Официальные отчёты',
                'Необычные ордеры',
                'Аномальное изменение объёмов',
                'Следование крупным позициям'
            ],
            'Анализ спроса и предложения': [
                'Баланс покупателей и продавцов',
                'Динамика изменения объёмов',
                'Оценка ликвидности',
                'Перекупленность и перепроданность',
                'Фронты ценового воздействия'
            ]
        },
        'Технический анализ': {
            'Графические модели': [
                'Фигуры разворота (голова и плечи, двойная вершина/дно)',
                'Фигуры продолжения тренда (флаги, вымпелы)',
                'Треугольники',
                'Клинья',
                'Пластинчатые модели'
            ],
            'Ценовая динамика': [
                'Прорывы уровней',
                'Отскоки от уровней',
                'Фейковые пробои',
                'Консолидация цены',
                'Резкие импульсы'
            ],
            'Свечные паттерны': [
                'Пин-бары',
                'Доджи',
                'Бычьи/медвежьи поглощения',
                'Харами',
                'Свечи с длинными тенями'
            ],
            'Уровни и структура': [
                'Горизонтальные уровни поддержки и сопротивления',
                'Трендовые линии',
                'Каналы и диапазоны',
                'Центровые уровни (точки разворота)',
                'Многоступенчатые уровни'
            ],
            'Объём и ценовые реакции': [
                'Паттерны объёмного распределения',
                'Анализ кластеров спроса и предложения',
                'Формирование объёмных аномалий',
                'Объёмное усиление движения',
                'Анализ волн стоимости'
            ]
        },
        'Волны Эллиота': {
            'Основные волны': [
                'Импульсные волны',
                'Коррекционные волны',
                'Волны 1 и 5',
                'Волны 2 и 4',
                'Волна 3 как самая сильная'
            ],
            'Коррекционные модели': [
                'Зигзаг',
                'Площадки',
                'Треугольники',
                'Параллелограммы',
                'Комбинированные коррекции'
            ],
            'Фибоначчи соотношения': [
                'Отношения коррекции',
                'Проекции волн',
                'Расширения волн',
                'Измерение импульсов',
                'Построение уровней'
            ],
            'Границы волн': [
                'Определение начала волны',
                'Идентификация разворотных зон',
                'Сравнение размеров волн',
                'Временные рамки',
                'Анализ завершения тренда'
            ],
            'Модели волн': [
                'Стандартная модель Эллиота',
                'Расширенные модели',
                'Сложные коррекции',
                'Множественные разбиения',
                'Волновая структура рынка'
            ],
            'Анализ импульсов': [
                'Сила импульса',
                'Длительность импульса',
                'Риск и прибыль',
                'Волновые отношения',
                'Синхронизация с трендом'
            ]
        },
        'Price Action': {
            'Свечные модели': [
                'Пин-бар',
                'Бар-бар',
                'Внутрисвечные паттерны',
                'Разворотные свечи',
                'Свечи с длинными тенями'
            ],
            'Уровни поддержки/сопротивления': [
                'Ключевые ценовые уровни',
                'Психологические зоны',
                'Рассогласования уровня',
                'Поддержка после отката',
                'Сопротивление перед отскоком'
            ],
            'Формации разворота': [
                'Двойное дно/двойная вершина',
                'Голова и плечи',
                'Тройная вершина/дно',
                'Формация “Подкова”',
                'Внутридневное разворотное распределение'
            ],
            'Брейк-аут паттерны': [
                'Пробой уровня сопротивления',
                'Пробой уровня поддержки',
                'Фейковые пробои',
                'Ложный пробой',
                'Устойчивые прорывы'
            ],
            'Внутрисвечные структуры': [
                'Баровые комбинации',
                'Линии закрытия и открытия',
                'Поглощение',
                'Разрыв между свечами',
                'Двойное дно свечи'
            ],
            'Ключевые ценовые уровни': [
                'Исторические максимумы/минимумы',
                'Критические разворотные зоны',
                'Центральные уровни рынка',
                'Места скопления ордеров',
                'Асимметрия отскоков'
            ]
        },
        'Индикаторы': {
            'Моментум индикаторы': [
                'RSI (Relative Strength Index)',
                'Stochastic Oscillator',
                'CCI (Commodity Channel Index)',
                'Williams %R',
                'ROC (Rate of Change)'
            ],
            'Объёмные индикаторы': [
                'On Balance Volume (OBV)',
                'Accumulation/Distribution',
                'Money Flow Index (MFI)',
                'Volume Oscillator',
                'Chaikin Money Flow'
            ],
            'Волатильность': [
                'Bollinger Bands',
                'Average True Range (ATR)',
                'Keltner Channels',
                'Donchian Channels',
                'Standard Deviation'
            ],
            'Динамические скользящие средние': [
                'SMA (Simple Moving Average)',
                'EMA (Exponential Moving Average)',
                'WMA (Weighted Moving Average)',
                'Hull Moving Average (HMA)',
                'TEMA (Triple Exponential Moving Average)'
            ],
            'Системы сигналов': [
                'MACD (Moving Average Convergence Divergence)',
                'Дивергенции',
                'Кроссинговые сигналы',
                'Фильтры тренда',
                'Сигналы разворота'
            ],
            'Индикаторы настроения': [
                'Индекс страха (VIX)',
                'Индекс рыночного сентимента',
                'Индикаторы консенсуса',
                'Индикаторы оптимизма/пессимизма',
                'Сентиментальные осцилляторы'
            ]
        },
        'Психология': {
            'Эмоциональное состояние сделки': [
                'Уверенность при входе',
                'Чувство неуверенности или сомнения',
                'Эмоциональное спокойствие',
                'Переживания из-за риска',
                'Эмоциональный подъем после успеха'
            ],
            'Качество принятия решения': [
                'Следование торговому плану',
                'Объективный анализ рынка',
                'Индивидуальность решения',
                'Отсутствие импульсивности',
                'Рациональность выбора точки входа'
            ],
            'Исполнение сделки': [
                'Своевременность входа/выхода',
                'Точность исполнения ордеров',
                'Соблюдение стоп-лоссов',
                'Оценка проскальзывания',
                'Корректность размещения ордеров'
            ],
            'Анализ результата сделки': [
                'Соответствие ожиданий и реальности',
                'Объективный разбор ошибок',
                'Выводы для будущих сделок',
                'Анализ риска и прибыли',
                'Оценка рыночного поведения после закрытия'
            ],
            'Уроки и самоанализ': [
                'Запись наблюдений по эмоциям',
                'Выявление повторяющихся шаблонов',
                'Разработка корректирующих действий',
                'Оценка соблюдения стратегии',
                'Планы по совершенствованию навыков'
            ],
            'Психологическая устойчивость': [
                'Способность справляться с убытками',
                'Контроль над эмоциями при прибыли',
                'Подготовленность к стрессовым ситуациям',
                'Сохранение концентрации во время волатильности',
                'Адаптация к изменению рыночных условий'
            ]
        }
    }

    for category_name, subcategories in categories_data.items():
        new_cat = models.CriterionCategory(name=category_name)
        category = db.session.merge(new_cat)
        db.session.flush()
        for subcategory_name, criteria_list in subcategories.items():
            new_subcat = models.CriterionSubcategory(name=subcategory_name, category_id=category.id)
            subcategory = db.session.merge(new_subcat)
            db.session.flush()
            for criterion_name in criteria_list:
                new_crit = models.Criterion(name=criterion_name, subcategory_id=subcategory.id)
                db.session.merge(new_crit)
    db.session.commit()
    logger.info("Критерии, подкатегории и категории критериев успешно обновлены.")

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

scheduler = BackgroundScheduler(timezone=pytz.UTC)
scheduler.add_job(
    id='Auto Finalize Best Setup Voting',
    func=lambda: auto_finalize_best_setup_voting(),
    trigger='interval',
    minutes=5,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)
scheduler.add_job(
    id='Start Poll',
    func=start_new_poll_job,
    trigger='interval',
    minutes=10,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=5)
)
scheduler.add_job(
    id='Process Poll Results',
    func=process_poll_results_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=2)
)
scheduler.add_job(
    id='Accumulate Staking Rewards',
    func=accumulate_staking_rewards_job,
    trigger='interval',
    minutes=1,
    next_run_time=datetime.utcnow() + timedelta(seconds=20)
)
scheduler.add_job(
    id='Update Real Prices',
    func=update_real_prices_job,
    trigger='interval',
    minutes=2,
    next_run_time=datetime.now(pytz.UTC) + timedelta(minutes=1)
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

from routes import *

app.register_blueprint(staking_bp, url_prefix='/staking')

app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '').strip()
if not app.config['OPENAI_API_KEY']:
    logger.error("OPENAI_API_KEY не установлен в переменных окружения.")
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения.")
openai.api_key = app.config['OPENAI_API_KEY']

app.config['ROBOKASSA_MERCHANT_LOGIN'] = os.environ.get('ROBOKASSA_MERCHANT_LOGIN', '').strip()
app.config['ROBOKASSA_PASSWORD1'] = os.environ.get('ROBOKASSA_PASSWORD1', '').strip()
app.config['ROBOKASSA_PASSWORD2'] = os.environ.get('ROBOKASSA_PASSWORD2', '').strip()
app.config['ROBOKASSA_RESULT_URL'] = os.environ.get('ROBOKASSA_RESULT_URL', '').strip()
app.config['ROBOKASSA_SUCCESS_URL'] = os.environ.get('ROBOKASSA_SUCCESS_URL', '').strip()
app.config['ROBOKASSA_FAIL_URL'] = os.environ.get('ROBOKASSA_FAIL_URL', '').strip()

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

