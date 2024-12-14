# poll_functions.py

import random
import traceback
from datetime import datetime, timedelta
import yfinance as yf
from models import (
    Poll,
    PollInstrument,
    Instrument,
    UserPrediction,
    InstrumentCategory,
    db
)
from flask import current_app

# Маппинг инструментов к тикерам yfinance
YFINANCE_TICKERS = {
    'Crude Oil': 'CL=F',
    'Gold': 'GC=F',
    'Silver': 'SI=F',
    'Natural Gas': 'NG=F',
    'Copper': 'HG=F',
    'Corn': 'C=F',
    'Wheat': 'W=F',
    'Soybean': 'S=F',
    'Coffee': 'KC=F',
    'Sugar': 'SB=F',
    'BTC-USD': 'BTC-USD',
    'ETH-USD': 'ETH-USD',
    'LTC-USD': 'LTC-USD',
    'XRP-USD': 'XRP-USD',
    'BCH-USD': 'BCH-USD',
    'EUR/USD': 'EURUSD=X',
    'GBP/USD': 'GBPUSD=X',
    'USD/JPY': 'JPY=X',
    'USD/CHF': 'CHF=X',
    'AUD/USD': 'AUDUSD=X',
    'USD/CAD': 'CAD=X',
    'NZD/USD': 'NZDUSD=X',
    'EUR/GBP': 'EURGBP=X',
    'EUR/JPY': 'EURJPY=X',
    'GBP/JPY': 'GBPJPY=X',
    'S&P 500': '^GSPC',
    'Dow Jones': '^DJI',
    'NASDAQ': '^IXIC',
    'DAX': '^GDAXI',
    'FTSE 100': '^FTSE',
    'CAC 40': '^FCHI',
    'Nikkei 225': '^N225',
    'Hang Seng': '^HSI',
    'ASX 200': '^AXJO',
    'Euro Stoxx 50': '^STOXX50E',
    # Добавьте другие маппинги по необходимости
}

def get_real_price(instrument_name):
    """
    Получает текущую цену инструмента с использованием yfinance.
    :param instrument_name: Название инструмента (например, 'Crude Oil')
    :return: Текущая цена или None, если не удалось получить
    """
    try:
        ticker_symbol = YFINANCE_TICKERS.get(instrument_name)
        if not ticker_symbol:
            current_app.logger.error(f"No yfinance ticker mapping found for instrument: {instrument_name}")
            return None

        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="1d")
        if data.empty:
            current_app.logger.warning(f"Данные для {ticker_symbol} пусты.")
            return None
        current_price = data['Close'][0]
        current_app.logger.info(f"Реальная цена для {instrument_name} ({ticker_symbol}): {current_price}")
        return current_price
    except Exception as e:
        current_app.logger.error(f"Ошибка при получении реальной цены для {instrument_name}: {e}")
        current_app.logger.error(traceback.format_exc())
        return None

def start_new_poll(test_mode=False):
    """
    Создаёт новый опрос, выбирая по одному инструменту из 4 случайных категорий.
    :param test_mode: Если True, устанавливает короткую длительность опроса для тестирования.
    """
    existing_active_poll = Poll.query.filter_by(status='active').first()
    if existing_active_poll:
        current_app.logger.info("Активный опрос уже существует. Пропуск создания нового.")
        return

    categories = InstrumentCategory.query.all()
    if len(categories) < 4:
        current_app.logger.error("Недостаточно категорий инструментов для создания опроса.")
        return

    selected_instruments = []
    # Выбираем 4 случайные категории
    selected_categories = random.sample(categories, min(4, len(categories)))
    for category in selected_categories:
        instruments = category.instruments
        if not instruments:
            current_app.logger.warning(f"Категория '{category.name}' не содержит инструментов.")
            continue
        instrument = random.choice(instruments)
        selected_instruments.append(instrument)

    if not selected_instruments:
        current_app.logger.error("Не удалось выбрать инструменты для опроса.")
        return

    # Установка длительности опроса
    if test_mode:
        duration = timedelta(minutes=1)  # Для тестирования устанавливаем 1 минуту
    else:
        duration = timedelta(days=3)     # В продакшене устанавливайте 3 дня

    # Создание опроса
    poll = Poll(
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + duration,
        status='active'
    )
    db.session.add(poll)
    db.session.flush()  # Получение ID опроса

    for instrument in selected_instruments:
        poll_instrument = PollInstrument(
            poll_id=poll.id,
            instrument_id=instrument.id
        )
        db.session.add(poll_instrument)

    db.session.commit()
    current_app.logger.info(f"Новый опрос ID {poll.id} создан с инструментами {[instr.name for instr in selected_instruments]}.")
    if test_mode:
        current_app.logger.info("Опрос создан в тестовом режиме с короткой длительностью.")

def process_poll_results():
    """
    Обрабатывает результаты опросов, завершённых на текущий момент, и инициирует новые опросы.
    """
    try:
        # Получение завершённых опросов (status='active' и end_date <= сейчас)
        now = datetime.utcnow()
        completed_polls = Poll.query.filter_by(status='active').filter(Poll.end_date <= now).all()
        current_app.logger.info(f"Обработка {len(completed_polls)} завершённых опросов.")

        for poll in completed_polls:
            real_prices = {}  # Хранит реальные цены для инструментов опроса
            for prediction in poll.predictions:
                # Получение реальной цены
                instrument_name = prediction.instrument.name
                real_price = get_real_price(instrument_name)
                if real_price is not None:
                    real_prices[instrument_name] = real_price
                    prediction.real_price = real_price
                    # Расчёт отклонения
                    if prediction.predicted_price != 0:
                        prediction.deviation = ((real_price - prediction.predicted_price) / prediction.predicted_price) * 100
                    else:
                        prediction.deviation = None

            # Сохранение реальных цен и обновление статуса опроса
            poll.real_prices = real_prices  # Убедитесь, что поле real_prices поддерживает JSON
            poll.status = 'completed'
            db.session.commit()
            current_app.logger.info(f"Опрос ID {poll.id} завершен с реальными ценами: {real_prices}.")

            # Определение ближайших предсказаний для каждого инструмента
            for poll_instrument in poll.poll_instruments:
                instrument_name = poll_instrument.instrument.name
                real_price = real_prices.get(instrument_name)
                if real_price is None:
                    continue

                predictions = UserPrediction.query.filter_by(
                    poll_id=poll.id,
                    instrument_id=poll_instrument.instrument.id
                ).all()

                if not predictions:
                    continue

                # Находим минимальное отклонение
                valid_predictions = [pred for pred in predictions if pred.deviation is not None]
                if not valid_predictions:
                    continue

                min_deviation = min(pred.deviation for pred in valid_predictions)
                closest_predictions = [pred for pred in valid_predictions if pred.deviation == min_deviation]

                for pred in closest_predictions:
                    # Логика награждения пользователей, например, предоставление премиум-доступа
                    user = pred.user
                    if not user.assistant_premium:
                        user.assistant_premium = True
                        current_app.logger.info(f"Пользователь ID {user.id} получил премиум-доступ за точное предсказание в опросе ID {poll.id}.")

            db.session.commit()

        # Запуск нового опроса после обработки текущих
        start_new_poll()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при обработке результатов опроса: {e}")
        current_app.logger.error(traceback.format_exc())
