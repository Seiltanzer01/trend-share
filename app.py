# app.py

import os
import logging
import traceback
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

from flask import Flask
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import openai

# Импорт расширений
from extensions import db, migrate

# Импорт моделей
import models  # Убедитесь, что models.py импортирует db из extensions.py

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

ADMIN_TELEGRAM_IDS = [427032240]

# Инициализация Flask-приложения
app = Flask(__name__)

# Настройка CSRF защиты
csrf = CSRFProtect(app)

# Контекстный процессор для предоставления CSRF токена в шаблонах
@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf()}

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
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///trades.db')
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
db.init_app(app)
migrate.init_app(app, db)

# Контекстный процессор для предоставления datetime в шаблонах
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# Фильтр для генерации URL изображений
@app.template_filter('image_url')
def image_url_filter(filename):
    if filename:
        return generate_s3_url(filename)
    return ''

# Функция для генерации URL из S3
def generate_s3_url(filename: str) -> str:
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

    # Инициализация данных при первом запуске
    @app.before_first_request
    def initialize():
        try:
            db.create_all()
            logger.info("База данных создана или уже существует.")
            create_predefined_data()
        except Exception as e:
            logger.error(f"Ошибка при инициализации базы данных: {e}")
            logger.error(traceback.format_exc())

    @app.context_processor
    def inject_admin_ids():
        return {'ADMIN_TELEGRAM_IDS': ADMIN_TELEGRAM_IDS}

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

    # Импорт маршрутов
    from routes import *

    ##################################################
    # Планировщик задач для голосования и диаграмм
    ##################################################

    scheduler = BackgroundScheduler()

    def select_random_instruments():
        """
        Выбирает по одному случайному инструменту из каждой категории: Товары, Криптовалюты, Форекс, Индексы.
        Создаёт новый Poll и связанные PollInstrument записи.
        """
        try:
            with app.app_context():
                # Проверяем, активен ли голосование
                voting_enabled = models.Config.query.filter_by(key='voting_enabled').first()
                if voting_enabled and voting_enabled.value.lower() == 'false':
                    logger.info("Голосование отключено администратором. Пропуск создания опроса.")
                    return

                # Проверяем, нет ли уже активного опроса
                active_poll = models.Poll.query.filter_by(status='active').first()
                if active_poll:
                    logger.info("Активный опрос уже существует. Пропуск создания нового опроса.")
                    return

                # Определяем категории
                required_categories = ['Товары', 'Криптовалюты', 'Форекс', 'Индексы']
                selected_instruments = []

                for category_name in required_categories:
                    category = models.InstrumentCategory.query.filter_by(name=category_name).first()
                    if category and category.instruments:
                        instrument = random.choice(category.instruments)
                        selected_instruments.append(instrument)
                        logger.info(f"Выбран инструмент '{instrument.name}' из категории '{category_name}'.")
                    else:
                        logger.warning(f"Категория '{category_name}' пуста или не найдена.")

                if not selected_instruments:
                    logger.error("Не удалось выбрать ни одного инструмента для опроса.")
                    return

                # Создаём новый опрос
                start_date = datetime.utcnow()
                end_date = start_date + timedelta(days=3)  # Голосование длится 3 дня

                poll = models.Poll(
                    start_date=start_date,
                    end_date=end_date,
                    status='active'
                )
                db.session.add(poll)
                db.session.flush()

                # Добавляем инструменты к опросу
                for instrument in selected_instruments:
                    poll_instrument = models.PollInstrument(
                        poll_id=poll.id,
                        instrument_id=instrument.id
                    )
                    db.session.add(poll_instrument)

                db.session.commit()
                logger.info(f"Новый опрос ID {poll.id} создан с инструментами {[instr.name for instr in selected_instruments]}.")

                # Планируем задачу по завершению опроса
                scheduler.add_job(
                    func=process_poll_results,
                    trigger=DateTrigger(run_date=end_date),
                    args=[poll.id],
                    id=f"process_poll_{poll.id}"
                )
        except Exception as e:
            logger.error(f"Ошибка при выборе случайных инструментов: {e}")
            logger.error(traceback.format_exc())

    def process_poll_results(poll_id):
        """
        Обрабатывает результаты опроса: получает реальные цены, находит наиболее точные прогнозы и награждает победителей.
        """
        try:
            with app.app_context():
                poll = models.Poll.query.get(poll_id)
                if not poll:
                    logger.error(f"Опрос ID {poll_id} не найден.")
                    return

                if poll.status != 'active':
                    logger.info(f"Опрос ID {poll_id} уже обработан.")
                    return

                # Получаем реальные цены для каждого инструмента через 3 дня
                real_prices = {}
                for poll_instrument in poll.poll_instruments:
                    instrument = poll_instrument.instrument
                    # Здесь предполагается, что реальные цены можно получить через yfinance
                    # Например, для 'BTC/USDT' использовать 'BTC-USD'
                    yf_ticker = instrument.name.replace('/USDT', '-USD') if '/USDT' in instrument.name else instrument.name
                    data = yf.download(yf_ticker, period='1d')
                    if not data.empty:
                        real_close_price = data['Close'].iloc[-1]
                        real_prices[instrument.id] = real_close_price
                        logger.info(f"Реальная цена для '{instrument.name}': {real_close_price}")
                    else:
                        logger.warning(f"Не удалось получить реальные цены для '{instrument.name}'.")

                poll.real_prices = real_prices
                poll.status = 'completed'
                db.session.commit()
                logger.info(f"Опрос ID {poll.id} завершен. Реальные цены: {real_prices}")

                # Находим победителей для каждого инструмента
                winners = []
                for instrument_id, real_price in real_prices.items():
                    predictions = models.UserPrediction.query.filter_by(poll_id=poll.id, instrument_id=instrument_id).all()
                    if not predictions:
                        logger.info(f"Нет прогнозов для инструмента ID {instrument_id}.")
                        continue

                    # Находим прогноз с минимальным отклонением
                    closest_prediction = min(
                        predictions,
                        key=lambda pred: abs(pred.predicted_price - real_price)
                    )
                    closest_prediction.deviation = abs(closest_prediction.predicted_price - real_price) / real_price * 100
                    winners.append(closest_prediction)

                    # Награждаем пользователя, если он еще не имеет премиум
                    user = closest_prediction.user
                    if not user.assistant_premium:
                        user.assistant_premium = True
                        db.session.commit()
                        logger.info(f"Пользователь ID {user.id} ({user.username}) награждён премиум за точный прогноз инструмента ID {instrument_id}.")

                db.session.commit()
                logger.info(f"Победители опроса ID {poll.id} обработаны.")

        except Exception as e:
            logger.error(f"Ошибка при обработке результатов опроса ID {poll_id}: {e}")
            logger.error(traceback.format_exc())

    # Инициализация планировщика задач
    scheduler = BackgroundScheduler()
    scheduler.start()

    # Планируем периодическую задачу для создания опросов каждые 3 дня
    scheduler.add_job(
        func=select_random_instruments,
        trigger=IntervalTrigger(days=3),
        id='select_random_instruments',
        name='Создание новых опросов каждые 3 дня',
        replace_existing=True
    )
    logger.info("Планировщик задач запущен и задача по созданию опросов добавлена.")

    # Добавляем задачу для проверки и завершения опросов при запуске приложения
    def check_active_polls():
        """
        Проверяет активные опросы и планирует задачи по их завершению, если срок опроса уже прошел.
        """
        try:
            with app.app_context():
                active_polls = models.Poll.query.filter_by(status='active').all()
                for poll in active_polls:
                    if poll.end_date <= datetime.utcnow():
                        process_poll_results(poll.id)
                    else:
                        # Планируем задачу по завершению опроса
                        scheduler.add_job(
                            func=process_poll_results,
                            trigger=DateTrigger(run_date=poll.end_date),
                            args=[poll.id],
                            id=f"process_poll_{poll.id}"
                        )
                        logger.info(f"Задача по завершению опроса ID {poll.id} запланирована на {poll.end_date}.")
        except Exception as e:
            logger.error(f"Ошибка при проверке активных опросов: {e}")
            logger.error(traceback.format_exc())

    scheduler.add_job(
        func=check_active_polls,
        trigger=IntervalTrigger(hours=1),
        id='check_active_polls',
        name='Проверка активных опросов каждый час',
        replace_existing=True
    )
    logger.info("Задача по проверке активных опросов добавлена.")

    # Добавление Robokassa настроек
    # (Этот блок уже присутствует выше, поэтому его можно удалить здесь)
    # Убедитесь, что все настройки Robokassa уже добавлены в app.py выше

    # **Запуск Flask-приложения**

    if __name__ == '__main__':
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
