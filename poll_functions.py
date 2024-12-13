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
from app import logger

def get_real_price(instrument_name):
    """
    Получает текущую цену инструмента с использованием yfinance.
    :param instrument_name: Название инструмента (например, 'EUR/USD')
    :return: Текущая цена или None, если не удалось получить
    """
    try:
        ticker = yf.Ticker(instrument_name)
        data = ticker.history(period="1d")
        if data.empty:
            logger.warning(f"Данные для {instrument_name} пусты.")
            return None
        current_price = data['Close'][0]
        logger.info(f"Реальная цена для {instrument_name}: {current_price}")
        return current_price
    except Exception as e:
        logger.error(f"Ошибка при получении реальной цены для {instrument_name}: {e}")
        logger.error(traceback.format_exc())
        return None

def start_new_poll():
    """
    Создаёт новый опрос, выбирая по одному инструменту из 4 случайных категорий.
    """
    existing_active_poll = Poll.query.filter_by(status='active').first()
    if existing_active_poll:
        logger.info("Активный опрос уже существует. Пропуск создания нового.")
        return

    categories = InstrumentCategory.query.all()
    if len(categories) < 4:
        logger.error("Недостаточно категорий инструментов для создания опроса.")
        return

    selected_instruments = []
    # Выбираем 4 случайные категории
    selected_categories = random.sample(categories, min(4, len(categories)))
    for category in selected_categories:
        instruments = category.instruments
        if not instruments:
            logger.warning(f"Категория '{category.name}' не содержит инструментов.")
            continue
        instrument = random.choice(instruments)
        selected_instruments.append(instrument)

    if not selected_instruments:
        logger.error("Не удалось выбрать инструменты для опроса.")
        return

    # Создание опроса
    poll = Poll(
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=3),
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
    logger.info(f"Новый опрос ID {poll.id} создан с инструментами {[instr.name for instr in selected_instruments]}.")

def process_poll_results():
    """
    Обрабатывает результаты опросов, завершённых на текущий момент, и инициирует новые опросы.
    """
    try:
        # Получение завершённых опросов
        completed_polls = Poll.query.filter_by(status='completed').all()
        for poll in completed_polls:
            for prediction in poll.predictions:
                # Получение реальной цены (реализуйте логику получения реальной цены)
                real_price = get_real_price(prediction.instrument_id)
                prediction.real_price = real_price
                # Расчёт отклонения
                if prediction.predicted_price != 0:
                    prediction.deviation = ((real_price - prediction.predicted_price) / prediction.predicted_price) * 100
                else:
                    prediction.deviation = None
            db.session.commit()
            logger.info(f"Результаты опроса ID {poll.id} обработаны успешно.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при обработке результатов опроса: {e}")
        logger.error(traceback.format_exc())

            # Сохранение реальных цен и обновление статуса опроса
            poll.real_prices = real_prices  # Убедитесь, что поле real_prices поддерживает JSON
            poll.status = 'completed'
            db.session.commit()
            logger.info(f"Опрос ID {poll.id} завершен с реальными ценами: {real_prices}.")

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
                min_deviation = min(pred.deviation for pred in predictions if pred.deviation is not None)
                closest_predictions = [pred for pred in predictions if pred.deviation == min_deviation]

                for pred in closest_predictions:
                    # Логика награждения пользователей, например, предоставление премиум-доступа
                    user = pred.user
                    if not user.assistant_premium:
                        user.assistant_premium = True
                        logger.info(f"Пользователь ID {user.id} получил премиум-доступ за точное предсказание в опросе ID {poll.id}.")
            db.session.commit()

        # Запуск нового опроса после обработки текущих
        start_new_poll()

    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при обработке результатов опроса: {e}")
        logger.error(traceback.format_exc())
