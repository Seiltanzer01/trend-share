# poll_functions.py

import logging
import traceback
from datetime import datetime, timedelta
import random
import yfinance as yf

from app import app, db, logger
from models import Poll, PollInstrument, UserPrediction, Instrument, User, InstrumentCategory

def start_new_poll():
    """
    Создаёт новый опрос с 4 случайными инструментами, по одному из каждой категории.
    """
    try:
        logger.info("Запуск создания нового опроса.")

        # Проверка, активен ли уже опрос
        active_poll = Poll.query.filter(Poll.status == 'active').first()
        if active_poll:
            logger.info("Активный опрос уже существует. Пропуск создания нового.")
            return

        # Выбор по одному инструменту из каждой категории: Форекс, Индексы, Товары, Криптовалюты
        categories = ['Форекс', 'Индексы', 'Товары', 'Криптовалюты']
        selected_instruments = []
        for category in categories:
            category_obj = InstrumentCategory.query.filter_by(name=category).first()
            if not category_obj:
                logger.warning(f"Категория '{category}' не найдена в базе данных.")
                continue
            instruments = Instrument.query.filter_by(category_id=category_obj.id).all()
            if instruments:
                selected_instruments.append(random.choice(instruments))
            else:
                logger.warning(f"Категория '{category}' не содержит инструментов.")
        
        if len(selected_instruments) < 4:
            logger.error("Недостаточно инструментов для создания опроса. Требуется по одному из каждой категории.")
            return

        # Создание нового опроса
        new_poll = Poll(
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=1),
            status='active'
        )
        db.session.add(new_poll)
        db.session.flush()  # Получаем ID опроса

        # Добавление инструментов в опрос
        for instrument in selected_instruments:
            poll_instrument = PollInstrument(
                poll_id=new_poll.id,
                instrument_id=instrument.id
            )
            db.session.add(poll_instrument)

        db.session.commit()
        logger.info(f"Новый опрос создан с ID {new_poll.id} и инструментами {[inst.name for inst in selected_instruments]}.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при создании нового опроса: {e}")
        logger.error(traceback.format_exc())

def process_poll_results():
    """
    Обрабатывает результаты опроса: находит победителя и назначает премиум.
    Также генерирует данные для диаграмм.
    """
    try:
        logger.info("Запуск обработки результатов опроса.")

        # Получение завершённых опросов
        completed_polls = Poll.query.filter(Poll.status == 'active', Poll.end_date <= datetime.utcnow()).all()

        for poll in completed_polls:
            logger.info(f"Обработка опроса ID {poll.id}.")

            # Получение инструментов опроса
            poll_instruments = PollInstrument.query.filter_by(poll_id=poll.id).all()
            instrument_ids = [pi.instrument_id for pi in poll_instruments]
            instruments = Instrument.query.filter(Instrument.id.in_(instrument_ids)).all()

            # Получение реальных цен через 3 дня после окончания опроса
            real_prices = {}
            for instrument in instruments:
                ticker = get_yfinance_ticker(instrument.name)
                if not ticker:
                    logger.warning(f"Не удалось определить тикер для инструмента '{instrument.name}'.")
                    continue

                # Получение закрытой цены на дату окончания опроса + 3 дня
                target_date = poll.end_date + timedelta(days=3)
                price = get_close_price(ticker, target_date.date())
                if price:
                    real_prices[instrument.id] = price
                    logger.info(f"Реальная цена для '{instrument.name}' на {target_date.date()}: {price}")
                else:
                    logger.warning(f"Не удалось получить реальную цену для '{instrument.name}' на {target_date.date()}.")

            # Получение всех предсказаний пользователей
            predictions = UserPrediction.query.filter_by(poll_id=poll.id).all()

            # Вычисление отклонений
            deviations = {}
            for prediction in predictions:
                real_price = real_prices.get(prediction.instrument_id)
                if not real_price:
                    continue
                deviation = abs(prediction.predicted_price - real_price) / real_price * 100
                prediction.deviation = deviation
                deviations[prediction.id] = deviation

            db.session.commit()

            # Нахождение предсказания с наименьшим отклонением
            if deviations:
                best_prediction_id = min(deviations, key=deviations.get)
                best_prediction = UserPrediction.query.get(best_prediction_id)
                if best_prediction:
                    # Назначение премиум
                    user = User.query.get(best_prediction.user_id)
                    user.assistant_premium = True
                    db.session.commit()
                    logger.info(f"Пользователь ID {user.id} получил премиум за опрос ID {poll.id}.")
            else:
                logger.warning(f"Нет предсказаний для опроса ID {poll.id}.")

            # Обновление статуса опроса
            poll.status = 'completed'
            poll.real_prices = real_prices  # Сохраняем реальные цены
            db.session.commit()
            logger.info(f"Опрос ID {poll.id} успешно обработан.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при обработке результатов опроса: {e}")
        logger.error(traceback.format_exc())

def get_yfinance_ticker(instrument_name):
    """
    Преобразует название инструмента в тикер для yfinance.
    Например, 'BTC-USD' -> 'BTC-USD'
    """
    # Предполагается, что названия инструментов уже соответствуют тикерам yfinance
    # Если нет, необходимо реализовать соответствие
    return instrument_name

def get_close_price(ticker, target_date):
    """
    Получает закрытую цену инструмента на заданную дату.
    :param ticker: Тикер инструмента для yfinance.
    :param target_date: Дата, для которой нужно получить цену.
    :return: Закрытая цена или None.
    """
    try:
        data = yf.download(ticker, start=target_date - timedelta(days=1), end=target_date + timedelta(days=1))
        if not data.empty:
            return data['Close'].iloc[-1]
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении цены для тикера '{ticker}': {e}")
        return None
