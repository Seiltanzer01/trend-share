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
    try:
        now = datetime.utcnow()
        active_polls = Poll.query.filter_by(status='active').filter(Poll.end_date > now).all()
        current_app.logger.info(f"[update_real_prices_for_active_polls] Всего активных опросов: {len(active_polls)}")

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
        db.session.commit()
        current_app.logger.info("[update_real_prices_for_active_polls] Обновление завершено.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при обновлении real_price: {e}")
        current_app.logger.error(traceback.format_exc())


def get_real_price(instrument_name):
    try:
        ticker_symbol = YFINANCE_TICKERS.get(instrument_name)
        if not ticker_symbol:
            current_app.logger.error(f"No yfinance ticker for instrument {instrument_name}")
            return None

        ticker = yf.Ticker(ticker_symbol)
        data = ticker.history(period="1d")
        if data.empty:
            current_app.logger.warning(f"Empty yfinance data for {instrument_name}")
            return None
        current_price = data['Close'][-1]
        current_app.logger.debug(f"Real price for {instrument_name}: {current_price}")
        return float(current_price)
    except Exception as e:
        current_app.logger.error(f"Ошибка get_real_price({instrument_name}): {e}")
        current_app.logger.error(traceback.format_exc())
        return None


def start_new_poll():
    """
    Создаём опрос на 10 минут (см. intervals в app.py).
    """
    existing_poll = Poll.query.filter_by(status='active').first()
    if existing_poll:
        current_app.logger.info("Уже есть активный опрос, пропускаем создание.")
        return

    cats = InstrumentCategory.query.all()
    if len(cats) < 4:
        current_app.logger.error("Не хватает категорий для опроса (нужно >=4).")
        return

    chosen_cats = random.sample(cats, 4)
    chosen_instruments = []
    for cat in chosen_cats:
        if cat.instruments:
            chosen_instruments.append(random.choice(cat.instruments))

    if not chosen_instruments:
        current_app.logger.error("Не удалось выбрать инструменты.")
        return

    # длительность 10 минут
    duration = timedelta(minutes=10)
    now = datetime.utcnow()

    poll = Poll(
        start_date=now,
        end_date=now + duration,
        status='active'
    )
    db.session.add(poll)
    db.session.flush()

    for instr in chosen_instruments:
        pi = PollInstrument(poll_id=poll.id, instrument_id=instr.id)
        db.session.add(pi)

    db.session.commit()
    current_app.logger.info(f"Создан опрос {poll.id} на 10 минут, инструменты: {[i.name for i in chosen_instruments]}")


def process_poll_results():
    """
    Завершаем опросы, если end_date <= сейчас, и выбираем победителя.
    После этого можно сразу вызвать start_new_poll(), если хотим без пауз.
    """
    try:
        now = datetime.utcnow()
        ended_polls = Poll.query.filter_by(status='active').filter(Poll.end_date <= now).all()
        if not ended_polls:
            current_app.logger.info("Нет завершённых опросов.")
            return

        for poll in ended_polls:
            # обновляем ещё раз real_price/deviation
            for pred in poll.predictions:
                rp = get_real_price(pred.instrument.name)
                if rp is not None:
                    pred.real_price = rp
                    if pred.predicted_price != 0:
                        pred.deviation = ((rp - pred.predicted_price) / pred.predicted_price) * 100
                    else:
                        pred.deviation = None

            poll.status = 'completed'
            db.session.commit()

            # выберем победителя
            all_winners = []
            for pi in poll.poll_instruments:
                instr = pi.instrument
                preds = UserPrediction.query.filter_by(poll_id=poll.id, instrument_id=instr.id).all()
                valid = [p for p in preds if p.deviation is not None]
                if not valid:
                    continue
                min_dev = min(abs(p.deviation) for p in valid)
                winners_for_instr = [p.user for p in valid if abs(p.deviation) == min_dev]
                all_winners.extend(winners_for_instr)

            if all_winners:
                import random
                winner = random.choice(all_winners)
                if not winner.assistant_premium:
                    winner.assistant_premium = True
                db.session.commit()
                current_app.logger.info(f"Опрос {poll.id} завершён. Победитель: user_id={winner.id}")
            else:
                current_app.logger.info(f"Опрос {poll.id} завершён. Нет победителей.")

        # Если хотим сразу запускать новый опрос:
        start_new_poll()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка process_poll_results: {e}")
        current_app.logger.error(traceback.format_exc())
