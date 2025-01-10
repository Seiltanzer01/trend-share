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
    'Crude Oil': 'CL=F',        # WTI Crude Oil Futures
    'Gold': 'GC=F',             # Gold Futures
    'Silver': 'SI=F',           # Silver Futures
    'Natural Gas': 'NG=F',      # Natural Gas Futures
    'Copper': 'HG=F',           # Copper Futures
    'Corn': 'ZC=F',             # Corn Futures
    'Wheat': 'ZW=F',            # Wheat Futures
    'Soybean': 'ZS=F',         # Soybean Futures
    'Coffee': 'KC=F',           # Coffee Futures
    'Sugar': 'SB=F',            # Sugar Futures
    'BTC-USD': 'BTC-USD',       # Bitcoin to USD
    'ETH-USD': 'ETH-USD',       # Ethereum to USD
    'LTC-USD': 'LTC-USD',       # Litecoin to USD
    'XRP-USD': 'XRP-USD',       # Ripple to USD
    'NEO/USDT': 'NEO-USD',      # NEO to USD
    'BCH-USD': 'BCH-USD',       # Bitcoin Cash to USD
    'EUR/USD': 'EURUSD=X',      # Euro to USD
    'GBP/USD': 'GBPUSD=X',      # British Pound to USD
    'USD/JPY': 'JPY=X',         # USD to Japanese Yen
    'USD/CHF': 'CHF=X',         # USD to Swiss Franc
    'AUD/USD': 'AUDUSD=X',      # Australian Dollar to USD
    'USD/CAD': 'CAD=X',         # USD to Canadian Dollar
    'NZD/USD': 'NZDUSD=X',      # New Zealand Dollar to USD
    'EUR/GBP': 'EURGBP=X',      # Euro to British Pound
    'EUR/JPY': 'EURJPY=X',      # Euro to Japanese Yen
    'GBP/JPY': 'GBPJPY=X',      # British Pound to Japanese Yen
    'S&P 500': '^GSPC',         # S&P 500 Index
    'Dow Jones': '^DJI',        # Dow Jones Industrial Average
    'NASDAQ': '^IXIC',          # NASDAQ Composite
    'DAX': '^GDAXI',            # DAX Performance Index
    'FTSE 100': '^FTSE',        # FTSE 100 Index
    'CAC 40': '^FCHI',          # CAC 40 Index
    'Nikkei 225': '^N225',      # Nikkei 225 Index
    'Hang Seng': '^HSI',        # Hang Seng Index
    'ASX 200': '^AXJO',         # S&P/ASX 200 Index
    'Euro Stoxx 50': '^STOXX50E' # EURO STOXX 50 Index
    #нужно добавить другие
}

def update_real_prices_for_active_polls():
    """
    Обновляет real_price и deviation для предсказаний в активных опросах.
    """
    try:
        now = datetime.utcnow()
        active_polls = Poll.query.filter_by(status='active').filter(Poll.end_date > now).all()
        current_app.logger.info(f"Обновление real_price для {len(active_polls)} активных опросов.")
        
        for poll in active_polls:
            for prediction in poll.predictions:
                instrument_name = prediction.instrument.name
                real_price = get_real_price(instrument_name)

                if real_price is not None:
                    prediction.real_price = real_price
                    if prediction.predicted_price != 0:
                        prediction.deviation = ((real_price - prediction.predicted_price) / prediction.predicted_price) * 100
                    else:
                        prediction.deviation = None
                    current_app.logger.debug(
                        f"[update_real_prices_for_active_polls] User {prediction.user_id}, Poll {poll.id}: "
                        f"Predicted={prediction.predicted_price}, Real={real_price}, Dev={prediction.deviation}"
                    )
        
        db.session.commit()
        current_app.logger.info("Обновление real_price и deviation завершено.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при обновлении real_price для активных опросов: {e}")
        current_app.logger.error(traceback.format_exc())


def get_real_price(instrument_name):
    """
    Получаем текущую цену инструмента с использованием yfinance.
    """
    try:
        ticker_symbol = YFINANCE_TICKERS.get(instrument_name)
        if not ticker_symbol:
            current_app.logger.error(f"No yfinance ticker mapping for instrument: {instrument_name}")
            return None

        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="1d")
        if data.empty:
            current_app.logger.warning(f"YFinance data empty for {ticker_symbol}.")
            return None
        current_price = data['Close'][-1]
        current_app.logger.info(f"Реальная цена для {instrument_name} ({ticker_symbol}): {current_price}")
        return float(current_price)
    except Exception as e:
        current_app.logger.error(f"Ошибка при get_real_price: {e}")
        current_app.logger.error(traceback.format_exc())
        return None


def start_new_poll(test_mode=False):
    """
    Теперь опрос создаётся раз в 5 дней (смотрите app.py),
    выбирает 4 случайные категории, из каждой - по 1 инструмент.
    """
    # Проверяем, нет ли уже активного опроса
    existing_active_poll = Poll.query.filter_by(status='active').first()
    if existing_active_poll:
        current_app.logger.info("Активный опрос уже существует. Пропуск создания нового.")
        return

    categories = InstrumentCategory.query.all()
    if len(categories) < 4:
        current_app.logger.error("Недостаточно категорий инструментов для создания опроса.")
        return

    import random
    selected_categories = random.sample(categories, 4)
    selected_instruments = []
    for cat in selected_categories:
        if cat.instruments:
            selected_instruments.append(random.choice(cat.instruments))

    if not selected_instruments:
        current_app.logger.error("Не удалось выбрать инструменты для опроса.")
        return

    # Если test_mode, 5 минут, иначе 5 дней
    if test_mode:
        duration = timedelta(minutes=2)
    else:
        duration = timedelta(days=5)

    poll = Poll(
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + duration,
        status='active'
    )
    db.session.add(poll)
    db.session.flush()

    for instr in selected_instruments:
        pi = PollInstrument(poll_id=poll.id, instrument_id=instr.id)
        db.session.add(pi)

    db.session.commit()
    current_app.logger.info(f"Новый опрос ID {poll.id} создан. Инструменты: {', '.join(i.name for i in selected_instruments)}")


def process_poll_results():
    """
    Обрабатываем результаты опросов, которые завершились (status='active', end_date <= now).
    Выбираем по каждому активу ближайшего к реальности, собираем победителей,
    потом случайно 1 из них получает премиум.
    """
    try:
        now = datetime.utcnow()
        completed_polls = Poll.query.filter_by(status='active').filter(Poll.end_date <= now).all()
        if not completed_polls:
            current_app.logger.info("Нет завершённых опросов для обработки.")
            return

        for poll in completed_polls:
            real_prices = {}
            # Обновим real_price/deviation
            for pred in poll.predictions:
                instrument_name = pred.instrument.name
                rp = get_real_price(instrument_name)
                if rp is not None:
                    pred.real_price = rp
                    if pred.predicted_price != 0:
                        pred.deviation = ((rp - pred.predicted_price) / pred.predicted_price) * 100
                    else:
                        pred.deviation = None
                    real_prices[instrument_name] = rp
            poll.real_prices = real_prices
            poll.status = 'completed'
            db.session.commit()

            # Теперь найдём победителей по каждому инструменту
            all_winners = []  # Список (User)

            poll_instruments = PollInstrument.query.filter_by(poll_id=poll.id).all()
            for pi in poll_instruments:
                instr = pi.instrument
                preds = UserPrediction.query.filter_by(poll_id=poll.id, instrument_id=instr.id).all()
                if not preds:
                    continue
                # valid preds
                valid_preds = [p for p in preds if p.deviation is not None]
                if not valid_preds:
                    continue

                min_dev = min(abs(p.deviation) for p in valid_preds)
                # Берём тех, у кого abs(deviation) == min_dev
                winners_for_instr = [p.user for p in valid_preds if abs(p.deviation) == min_dev]
                # Если есть несколько, это означает несколько победителей по этому инструменту
                # Но дальше случайный общий от всех 4
                if winners_for_instr:
                    all_winners.extend(winners_for_instr)

            # Теперь из all_winners берём случайного одного
            if all_winners:
                winner = random.choice(all_winners)
                if not winner.assistant_premium:
                    winner.assistant_premium = True
                    db.session.commit()
                current_app.logger.info(f"Случайный победитель за опрос {poll.id} => user_id={winner.id}")
                # Уведомим (пример: flash)
                flash(f"Поздравляем! Пользователь {winner.username or winner.first_name} получил премиум!", 'success')
            else:
                current_app.logger.info(f"В опросе {poll.id} нет победителей.")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при process_poll_results: {e}")
        current_app.logger.error(traceback.format_exc())
