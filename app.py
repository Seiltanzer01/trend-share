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
        {'name': 'BNB/USDT', 'category': 'Криптовалюты'},
        {'name': 'XRP/USDT', 'category': 'Криптовалюты'},
        {'name': 'ADA/USDT', 'category': 'Криптовалюты'},
        {'name': 'SOL/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOT/USDT', 'category': 'Криптовалюты'},
        {'name': 'DOGE/USDT', 'category': 'Криптовалюты'},
        {'name': 'AVAX/USDT', 'category': 'Криптовалюты'},
        {'name': 'SHIB/USDT', 'category': 'Криптовалюты'},
        {'name': 'LTC/USDT', 'category': 'Криптовалюты'},
        {'name': 'UNI/USDT', 'category': 'Криптовалюты'},
        {'name': 'BCH/USDT', 'category': 'Криптовалюты'},
        {'name': 'LINK/USDT', 'category': 'Криптовалюты'},
        {'name': 'ALGO/USDT', 'category': 'Криптовалюты'},
        {'name': 'MATIC/USDT', 'category': 'Криптовалюты'},
        {'name': 'ATOM/USDT', 'category': 'Криптовалюты'},
        {'name': 'VET/USDT', 'category': 'Криптовалюты'},
        {'name': 'FTT/USDT', 'category': 'Криптовалюты'},
        {'name': 'TRX/USDT', 'category': 'Криптовалюты'},
        {'name': 'ETC/USDT', 'category': 'Криптовалюты'},
        {'name': 'XLM/USDT', 'category': 'Криптовалюты'},
        {'name': 'FIL/USDT', 'category': 'Криптовалюты'},
        {'name': 'THETA/USDT', 'category': 'Криптовалюты'},
        {'name': 'ICP/USDT', 'category': 'Криптовалюты'},
        {'name': 'XMR/USDT', 'category': 'Криптовалюты'},
        {'name': 'EOS/USDT', 'category': 'Криптовалюты'},
        {'name': 'AAVE/USDT', 'category': 'Криптовалюты'},
        {'name': 'KSM/USDT', 'category': 'Криптовалюты'},
        {'name': 'NEO/USDT', 'category': 'Криптовалюты'},
        {'name': 'MKR/USDT', 'category': 'Криптовалюты'},
        {'name': 'DASH/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZEC/USDT', 'category': 'Криптовалюты'},
        {'name': 'COMP/USDT', 'category': 'Криптовалюты'},
        {'name': 'CAKE/USDT', 'category': 'Криптовалюты'},
        {'name': 'SNX/USDT', 'category': 'Криптовалюты'},
        {'name': 'ENJ/USDT', 'category': 'Криптовалюты'},
        {'name': 'GRT/USDT', 'category': 'Криптовалюты'},
        {'name': 'SUSHI/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZIL/USDT', 'category': 'Криптовалюты'},
        {'name': 'BAT/USDT', 'category': 'Криптовалюты'},
        {'name': 'CHZ/USDT', 'category': 'Криптовалюты'},
        {'name': 'RUNE/USDT', 'category': 'Криптовалюты'},
        {'name': 'QTUM/USDT', 'category': 'Криптовалюты'},
        {'name': 'ZEN/USDT', 'category': 'Криптовалюты'},
        {'name': 'ONT/USDT', 'category': 'Криптовалюты'},
        {'name': 'OMG/USDT', 'category': 'Криптовалюты'},
        {'name': 'IOST/USDT', 'category': 'Криптовалюты'},
        {'name': 'KAVA/USDT', 'category': 'Криптовалюты'},
        {'name': '1INCH/USDT', 'category': 'Криптовалюты'},
        {'name': 'CELO/USDT', 'category': 'Криптовалюты'},
        {'name': 'BTT/USDT', 'category': 'Криптовалюты'},
        {'name': 'ANKR/USDT', 'category': 'Криптовалюты'},
        {'name': 'SC/USDT', 'category': 'Криптовалюты'},
        {'name': 'DGB/USDT', 'category': 'Криптовалюты'},
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

# Функция для парсинга init_data
def parse_init_data(init_data_str):
    data = {}
    try:
        for pair in init_data_str.split('\n'):
            key, value = pair.split('=', 1)
            data[key] = value
    except Exception as e:
        logger.error(f"Ошибка при парсинге init_data: {e}")
    return data

# Маршруты аутентификации

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/telegram_auth', methods=['POST'])
def telegram_auth():
    data = request.get_json()
    if not data or 'init_data' not in data:
        logger.warning("Нет данных для авторизации или отсутствует init_data.")
        return jsonify({'status': 'error', 'message': 'Нет данных для авторизации'}), 400

    init_data_str = data.get('init_data')
    data_dict = parse_init_data(init_data_str)

    # Извлечение hash и удаление его из данных
    hash_received = data_dict.pop('hash', None)
    if not hash_received:
        logger.warning("Hash отсутствует в данных авторизации.")
        return jsonify({'status': 'error', 'message': 'Hash отсутствует'}), 400

    # Проверка актуальности auth_date (например, не старше 1 дня)
    auth_date = int(data_dict.get('auth_date', 0))
    current_time = int(datetime.utcnow().timestamp())
    if current_time - auth_date > 86400:
        logger.warning("Данные авторизации устарели.")
        return jsonify({'status': 'error', 'message': 'Данные авторизации устарели'}), 400

    # Сортировка параметров по ключу
    sorted_keys = sorted(data_dict.keys())
    check_string = '\n'.join([f"{key}={data_dict[key]}" for key in sorted_keys])

    # Вычисление секретного ключа
    bot_token = os.environ.get('TELEGRAM_TOKEN', '').strip()
    if not bot_token:
        logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
        return jsonify({'status': 'error', 'message': 'Серверная ошибка'}), 500

    secret_key = hashlib.sha256(bot_token.encode()).digest()

    # Вычисление HMAC
    hmac_computed = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    # Сравнение полученного хеша с вычисленным
    if not hmac.compare_digest(hmac_computed, hash_received):
        logger.warning("Hash не совпадает. Данные авторизации недействительны.")
        return jsonify({'status': 'error', 'message': 'Данные авторизации недействительны'}), 400

    # Получение или создание пользователя
    telegram_id = data_dict.get('id')
    first_name = data_dict.get('first_name')
    last_name = data_dict.get('last_name', '')
    username = data_dict.get('username', '')
    photo_url = data_dict.get('photo_url', '')

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
        db.session.add(user)
        db.session.commit()
        logger.info(f"Создан новый пользователь: {username} (ID: {telegram_id})")

    # Сохранение данных пользователя в сессии
    session['user_id'] = user.id
    session['telegram_id'] = telegram_id

    logger.info(f"Пользователь {username} (ID: {telegram_id}) успешно авторизовался.")
    return jsonify({'status': 'ok'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Главная страница — список сделок с фильтрацией
@app.route('/', methods=['GET'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

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
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            trades_query = trades_query.filter(Trade.trade_open_time <= end_date_obj)
        except ValueError:
            flash('Некорректный формат даты окончания.', 'danger')
    if selected_criteria:
        trades_query = trades_query.join(Trade.criteria).filter(Criterion.id.in_(selected_criteria)).distinct()

    trades = trades_query.order_by(Trade.trade_open_time.desc()).all()

    return render_template('index.html', trades=trades, categories=categories, criteria_categories=criteria_categories, selected_instrument_id=instrument_id)

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
        trade = Trade(
            user_id=user_id,
            instrument_id=form.instrument.data,
            direction=form.direction.data,
            entry_price=form.entry_price.data,
            exit_price=form.exit_price.data if form.exit_price.data else None,
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
            screenshot_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            trade.screenshot = filename  # Добавляем поле screenshot в модели Trade

        db.session.add(trade)
        try:
            db.session.commit()
            flash('Сделка успешно добавлена.', 'success')
            logger.info(f"Сделка ID {trade.id} добавлена пользователем ID {user_id}.")
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сделки.', 'danger')
            logger.error(f"Ошибка при добавлении сделки: {e}")
        return redirect(url_for('index'))
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
def edit_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для редактирования этой сделки.', 'danger')
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
        trade.instrument_id = form.instrument.data
        trade.direction = form.direction.data
        trade.entry_price = form.entry_price.data
        trade.exit_price = form.exit_price.data if form.exit_price.data else None
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
            filename = secure_filename(screenshot_file.filename)
            screenshot_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            trade.screenshot = filename

        try:
            db.session.commit()
            flash('Сделка успешно обновлена.', 'success')
            logger.info(f"Сделка ID {trade.id} обновлена пользователем ID {user_id}.")
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сделки.', 'danger')
            logger.error(f"Ошибка при обновлении сделки: {e}")
        return redirect(url_for('index'))
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
    return render_template('edit_trade.html', form=form, criteria_categories=criteria_categories, trade=trade, grouped_instruments=grouped_instruments)

# Удалить сделку
@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
def delete_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для удаления этой сделки.', 'danger')
        return redirect(url_for('index'))
    try:
        if trade.screenshot:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], trade.screenshot)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(trade)
        db.session.commit()
        flash('Сделка успешно удалена.', 'success')
        logger.info(f"Сделка ID {trade.id} удалена пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сделки.', 'danger')
        logger.error(f"Ошибка при удалении сделки: {e}")
    return redirect(url_for('index'))

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
            screenshot_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            setup.screenshot = filename

        db.session.add(setup)
        try:
            db.session.commit()
            flash('Сетап успешно добавлен.', 'success')
            logger.info(f"Сетап ID {setup.id} добавлен пользователем ID {user_id}.")
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сетапа.', 'danger')
            logger.error(f"Ошибка при добавлении сетапа: {e}")
        return redirect(url_for('manage_setups'))
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
        return redirect(url_for('manage_setups'))
    form = SetupForm(obj=setup)
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Установка выбранных критериев
    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in setup.criteria]

    if form.validate_on_submit():
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
            filename = secure_filename(screenshot_file.filename)
            screenshot_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            setup.screenshot = filename

        try:
            db.session.commit()
            flash('Сетап успешно обновлён.', 'success')
            logger.info(f"Сетап ID {setup.id} обновлён пользователем ID {user_id}.")
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сетапа.', 'danger')
            logger.error(f"Ошибка при обновлении сетапа: {e}")
        return redirect(url_for('manage_setups'))
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
def delete_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для удаления этого сетапа.', 'danger')
        return redirect(url_for('manage_setups'))
    try:
        if setup.screenshot:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], setup.screenshot)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(setup)
        db.session.commit()
        flash('Сетап успешно удалён.', 'success')
        logger.info(f"Сетап ID {setup.id} удалён пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сетапа.', 'danger')
        logger.error(f"Ошибка при удалении сетапа: {e}")
    return redirect(url_for('manage_setups'))

# Управление сетапами
@app.route('/manage_setups')
def manage_setups():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setups = Setup.query.filter_by(user_id=user_id).all()
    return render_template('manage_setups.html', setups=setups)

# Просмотр сделки
@app.route('/view_trade/<int:trade_id>')
def view_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для просмотра этой сделки.', 'danger')
        return redirect(url_for('index'))
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
        return redirect(url_for('manage_setups'))
    return render_template('view_setup.html', setup=setup)

# Обслуживание загруженных файлов
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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
