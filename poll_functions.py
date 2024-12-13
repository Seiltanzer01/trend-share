# poll_functions.py

import random
from datetime import datetime, timedelta
from models import Poll, PollInstrument, Instrument, UserPrediction, db
from app import logger

def start_new_poll():
    """
    Создает новый опрос, выбирая по одному инструменту из 4 категорий.
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
    for category in categories[:4]:  # Выбираем первые 4 категории
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
    Обрабатывает результаты опросов, завершенных на текущий момент.
    """
    completed_polls = Poll.query.filter_by(status='active').filter(Poll.end_date <= datetime.utcnow()).all()
    for poll in completed_polls:
        real_prices = {}
        for poll_instrument in poll.poll_instruments:
            instrument = poll_instrument.instrument
            real_price = get_real_price(instrument.name)
            if real_price is not None:
                real_prices[instrument.name] = real_price
            else:
                logger.error(f"Не удалось получить реальную цену для инструмента '{instrument.name}' в опросе ID {poll.id}.")

        poll.real_prices = real_prices
        poll.status = 'completed'
        db.session.commit()
        logger.info(f"Опрос ID {poll.id} завершен с реальными ценами: {real_prices}.")

        # Определение ближайших предсказаний
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
                # Здесь можно добавить логику награждения пользователей, например, предоставить им премиум-доступ
                user = pred.user
                if not user.assistant_premium:
                    user.assistant_premium = True
                    logger.info(f"Пользователь ID {user.id} получил премиум-доступ за точное предсказание в опросе ID {poll.id}.")
            db.session.commit()
