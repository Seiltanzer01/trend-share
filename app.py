# app.py

import os
import asyncio
import traceback
import threading
from flask import Flask, render_template, redirect, url_for, flash, request, send_from_directory, session, jsonify
from forms import TradeForm, SetupForm
from models import db, User, Trade, Setup, Criterion, CriterionCategory, CriterionSubcategory, Instrument, InstrumentCategory
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_migrate import Migrate
from datetime import datetime
import logging
import requests
import hashlib
import hmac
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
import urllib.parse  # Для декодирования URL-энкодированных данных

# Инициализация Flask-приложения
app = Flask(__name__)

# Использование переменных окружения для конфиденциальных данных
app.secret_key = os.environ.get('SECRET_KEY', 'your_default_secret_key')

# Настройки базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///trades.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация SQLAlchemy
db.init_app(app)

# Инициализация Flask-Migrate
migrate = Migrate(app, db)

# Настройка папки для загрузки файлов
app.config['UPLOAD_FOLDER'] = 'uploads'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Контекстный процессор для предоставления datetime в шаблонах
@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# Функция для создания предопределённых данных
def create_predefined_data():
    # Проверяем, есть ли уже данные
    if InstrumentCategory.query.first():
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

        # Проверяем, существует ли инструмент
        instrument = Instrument.query.filter_by(name=instrument_name).first()
        if not instrument:
            instrument = Instrument(name=instrument_name, category_id=category.id)
            db.session.add(instrument)

    db.session.commit()

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
        category = CriterionCategory(name=category_name)
        db.session.add(category)
        db.session.flush()

        for subcategory_name, criteria_list in subcategories.items():
            subcategory = CriterionSubcategory(
                name=subcategory_name,
                category_id=category.id
            )
            db.session.add(subcategory)
            db.session.flush()

            for criterion_name in criteria_list:
                criterion = Criterion(
                    name=criterion_name,
                    subcategory_id=subcategory.id
                )
                db.session.add(criterion)

    db.session.commit()

# Вызываем функцию перед первым запросом
@app.before_first_request
def setup_data():
    create_predefined_data()

# Функция для парсинга init_data с использованием urllib.parse.parse_qsl
def parse_init_data(init_data_str):
    """
    Парсинг init_data с использованием urllib.parse.parse_qsl
    """
    try:
        pairs = urllib.parse.parse_qsl(init_data_str, keep_blank_values=True)
        data = {key: value for key, value in pairs}
        return data
    except Exception as e:
        logger.error(f"Ошибка при парсинге init_data с помощью parse_qsl: {e}")
        return {}

# Функция для проверки HMAC
def verify_hmac(init_data_str, bot_token):
    """
    Проверяет HMAC подпись init_data.
    Возвращает True, если подпись корректна, иначе False.
    """
    try:
        data = parse_init_data(init_data_str)
        hash_received = data.pop('hash', None)
        if not hash_received:
            logger.warning("Hash отсутствует в данных авторизации.")
            return False

        # Сортировка параметров по ключу
        sorted_keys = sorted(data.keys())
        check_string = '\n'.join([f"{key}={data[key]}" for key in sorted_keys])

        # Вычисление секретного ключа
        secret_key = hashlib.sha256(bot_token.encode('utf-8')).digest()

        # Вычисление HMAC
        hmac_computed = hmac.new(secret_key, check_string.encode('utf-8'), hashlib.sha256).hexdigest()

        # Логирование для отладки
        logger.debug(f"Check string:\n{check_string}")
        logger.debug(f"Computed HMAC: {hmac_computed}")
        logger.debug(f"Received hash:   {hash_received}")

        # Сравнение HMAC
        return hmac.compare_digest(hmac_computed, hash_received)
    except Exception as e:
        logger.error(f"Ошибка при проверке HMAC: {e}")
        logger.error(traceback.format_exc())
        return False

# Маршруты аутентификации

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/telegram_auth', methods=['POST'])
def telegram_auth():
    # Попытка получить данные как JSON
    data = request.get_json()
    logger.info(f"Получены данные для авторизации: {data}")

    if not data or 'init_data' not in data:
        # Если не удалось получить как JSON, попробуем как form data
        init_data_str = request.form.get('init_data')
        if not init_data_str:
            logger.warning("Нет данных для авторизации или отсутствует init_data.")
            return jsonify({'status': 'error', 'message': 'Нет данных для авторизации'}), 400
    else:
        init_data_str = data.get('init_data')
        logger.info(f"Получено init_data: {init_data_str}")

    # Проверка HMAC
    bot_token = os.environ.get('TELEGRAM_TOKEN', '').strip()
    if not bot_token:
        logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
        return jsonify({'status': 'error', 'message': 'Серверная ошибка'}), 500

    if not verify_hmac(init_data_str, bot_token):
        logger.warning("Hash не совпадает. Данные авторизации недействительны.")
        return jsonify({'status': 'error', 'message': 'Данные авторизации недействительны'}), 400

    # Парсинг данных после успешной проверки HMAC
    data_dict = parse_init_data(init_data_str)
    hash_received = data_dict.pop('hash', None)

    # Извлечение информации о пользователе из поля 'user'
    try:
        user_data = json.loads(data_dict.get('user', '{}'))
        telegram_id = int(user_data.get('id'))
        first_name = user_data.get('first_name', '')
        last_name = user_data.get('last_name', '')
        username = user_data.get('username', '')
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Ошибка при извлечении данных пользователя: {e}")
        return jsonify({'status': 'error', 'message': 'Некорректные данные пользователя'}), 400

    # Получение или создание пользователя
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
        db.session.add(user)
        try:
            db.session.commit()
            logger.info(f"Создан новый пользователь: {username} (ID: {telegram_id})")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при создании пользователя: {e}")
            return jsonify({'status': 'error', 'message': 'Ошибка при создании пользователя'}), 500

    # Сохранение данных пользователя в сессии
    session['user_id'] = user.id
    session['telegram_id'] = telegram_id

    logger.info(f"Пользователь {username} (ID: {telegram_id}) успешно авторизовался.")
    return jsonify({'status': 'ok'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Остальные маршруты (index, new_trade, edit_trade, delete_trade, etc.) остаются без изменений
# ...

# **Telegram Bot Handlers**

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /start от пользователя {user.id} ({user.username})")
    try:
        await update.message.reply_text('Привет! Я TradeJournalBot. Как я могу помочь вам сегодня?')
        logger.info(f"Ответ отправлен пользователю {user.id} ({user.username}) на команду /start")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /start: {e}")
        logger.error(traceback.format_exc())

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /help от пользователя {user.id} ({user.username})")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом\n"
        "/help - Получить справку\n"
        "/add_trade - Добавить новую сделку\n"
        "/view_trades - Просмотреть список сделок\n"
        "/register - Зарегистрировать пользователя"
    )
    try:
        await update.message.reply_text(help_text)
        logger.info(f"Ответ на /help отправлен пользователю {user.id} ({user.username})")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /help: {e}")
        logger.error(traceback.format_exc())

# Команда /add_trade
async def add_trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /add_trade от пользователя {user.id} ({user.username})")
    try:
        # Здесь вы можете реализовать логику добавления сделки через бота
        await update.message.reply_text('Функция добавления сделки пока не реализована.')
        logger.info(f"Ответ на /add_trade отправлен пользователю {user.id} ({user.username})")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /add_trade: {e}")
        logger.error(traceback.format_exc())

# Команда /view_trades
async def view_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /view_trades от пользователя {user.id} ({user.username})")
    telegram_id = user.id
    user_record = User.query.filter_by(telegram_id=telegram_id).first()
    if not user_record:
        try:
            await update.message.reply_text('Пользователь не найден. Пожалуйста, зарегистрируйтесь с помощью команды /register.')
            logger.info(f"Пользователь {user.id} ({user.username}) не зарегистрирован.")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения незарегистрированному пользователю: {e}")
            logger.error(traceback.format_exc())
        return
    user_id = user_record.id
    trades = Trade.query.filter_by(user_id=user_id).all()
    if not trades:
        try:
            await update.message.reply_text('У вас пока нет сделок.')
            logger.info(f"Пользователь {user.id} ({user.username}) не имеет сделок.")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения о пустом списке сделок: {e}")
            logger.error(traceback.format_exc())
        return
    message = "Ваши сделки:\n"
    for trade in trades:
        message += f"ID: {trade.id}, Инструмент: {trade.instrument.name}, Направление: {trade.direction}, Цена входа: {trade.entry_price}\n"
    try:
        await update.message.reply_text(message)
        logger.info(f"Список сделок отправлен пользователю {user.id} ({user.username})")
    except Exception as e:
        logger.error(f"Ошибка при отправке списка сделок: {e}")
        logger.error(traceback.format_exc())

# Команда /register
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    logger.info(f"Получена команда /register от пользователя {user.id} ({user.username})")
    existing_user = User.query.filter_by(telegram_id=telegram_id).first()
    if existing_user:
        try:
            await update.message.reply_text('Вы уже зарегистрированы.')
            logger.info(f"Пользователь {user.id} ({user.username}) уже зарегистрирован.")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения о существующей регистрации: {e}")
            logger.error(traceback.format_exc())
        return
    new_user = User(telegram_id=telegram_id, username=user.username, first_name=user.first_name, last_name=user.last_name)
    db.session.add(new_user)
    try:
        db.session.commit()
        await update.message.reply_text('Регистрация прошла успешно.')
        logger.info(f"Пользователь {user.id} ({user.username}) зарегистрирован успешно.")
    except Exception as e:
        db.session.rollback()
        await update.message.reply_text('Произошла ошибка при регистрации.')
        logger.error(f"Ошибка при регистрации пользователя {user.id} ({user.username}): {e}")
        logger.error(traceback.format_exc())

# **Инициализация Telegram бота и приложения**

# Получение токена бота из переменных окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
    exit(1)

# Инициализация бота и приложения Telegram
builder = ApplicationBuilder().token(TOKEN)

# Построение приложения
application = builder.build()

# Добавление обработчиков команд к приложению
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('help', help_command))
application.add_handler(CommandHandler('add_trade', add_trade_command))
application.add_handler(CommandHandler('view_trades', view_trades_command))
application.add_handler(CommandHandler('register', register_command))

# Создание и запуск цикла событий в фоновом потоке
loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

background_thread = threading.Thread(target=start_background_loop, args=(loop,), daemon=True)
background_thread.start()
logger.info("Фоновый цикл событий asyncio запущен.")

# Инициализация Telegram Application в фоновом цикле событий
async def initialize_application():
    try:
        await application.initialize()
        await application.start()
        logger.info("Telegram Application успешно инициализировано и запущено.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации Telegram Application: {e}")
        logger.error(traceback.format_exc())

# Запускаем инициализацию приложения в фоновом цикле событий
asyncio.run_coroutine_threadsafe(initialize_application(), loop)

# **Flask Routes for Telegram Webhooks**

# Маршрут для обработки вебхуков от Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработчик вебхуков от Telegram."""
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            # Отправляем задачу в фоновый цикл событий
            asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
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
def set_webhook():
    """Маршрут для установки вебхука Telegram."""
    webhook_url = f"https://{request.host}/webhook"
    bot_token = os.environ.get('TELEGRAM_TOKEN')
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
    # Инициализация базы данных и создание предопределённых данных
    with app.app_context():
        db.create_all()
        create_predefined_data()

    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Запуск Flask-приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
