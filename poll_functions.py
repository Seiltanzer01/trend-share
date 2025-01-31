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
    db,
    Config,
    User
)
from flask import current_app
from best_setup_voting import send_token_reward as voting_send_token_reward

# Mapping of instruments to yfinance tickers
YFINANCE_TICKERS = {
    'Crude Oil': 'CL=F',        # WTI Crude Oil Futures
    'Gold': 'GC=F',             # Gold Futures
    'Silver': 'SI=F',           # Silver Futures
    'Natural Gas': 'NG=F',      # Natural Gas Futures
    'Copper': 'HG=F',           # Copper Futures
    'Corn': 'ZC=F',             # Corn Futures
    'Wheat': 'ZW=F',            # Wheat Futures
    'Soybean': 'ZS=F',          # Soybean Futures
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
    # add others as needed
}

def update_real_prices_for_active_polls():
    try:
        now = datetime.utcnow()
        active_polls = Poll.query.filter_by(status='active').filter(Poll.end_date > now).all()
        current_app.logger.info(f"[update_real_prices_for_active_polls] Total active polls: {len(active_polls)}")

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
        current_app.logger.info("[update_real_prices_for_active_polls] Update completed.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating real_price: {e}")
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
        current_app.logger.error(f"Error in get_real_price({instrument_name}): {e}")
        current_app.logger.error(traceback.format_exc())
        return None


def start_new_poll():
    """
    Create a new poll for 10 minutes (see intervals in app.py).
    """
    existing_poll = Poll.query.filter_by(status='active').first()
    if existing_poll:
        current_app.logger.info("An active poll already exists, skipping creation.")
        return

    cats = InstrumentCategory.query.all()
    if len(cats) < 4:
        current_app.logger.error("Not enough categories for poll (need >=4).")
        return

    chosen_cats = random.sample(cats, 4)
    chosen_instruments = []
    for cat in chosen_cats:
        if cat.instruments:
            chosen_instruments.append(random.choice(cat.instruments))

    if not chosen_instruments:
        current_app.logger.error("Failed to select instruments.")
        return

    # duration: 10 minutes
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
    current_app.logger.info(f"Created poll {poll.id} for 10 minutes, instruments: {[i.name for i in chosen_instruments]}")


def process_poll_results():
    """
    Finish polls whose end_date <= now and select one winner for each instrument (minimum deviation).
    Reward: UJO tokens (25% of best_setup_pool_size).
    After completion, start a new poll.
    """
    try:
        now = datetime.utcnow()
        ended_polls = Poll.query.filter_by(status='active').filter(Poll.end_date <= now).all()
        if not ended_polls:
            current_app.logger.info("No completed polls.")
            return

        for poll in ended_polls:
            # Update real_price/deviation once more
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

            # CHANGES: now determine the winner(s) for each instrument based on minimum deviation,
            # but choose exactly one at random (if several have the same deviation).
            # Instead of premium, award UJO tokens (25% of best_setup_pool_size).

            # 1) Calculate the guessing pool (25% of best_setup_pool_size)
            pool_config = Config.query.filter_by(key='best_setup_pool_size').first()
            if pool_config:
                total_best_setup_pool = float(pool_config.value)
            else:
                total_best_setup_pool = 0.0

            guessing_pool = total_best_setup_pool * 0.0625  # (adjusted) a quarter of the pool goes for guessing rewards

            instrument_winners = []
            for pi in poll.poll_instruments:
                instr = pi.instrument
                preds = UserPrediction.query.filter_by(poll_id=poll.id, instrument_id=instr.id).all()
                valid = [p for p in preds if p.deviation is not None]
                if not valid:
                    continue

                # Find the minimum deviation
                min_dev = min(abs(p.deviation) for p in valid)
                # Select all with that deviation
                tied_preds = [p for p in valid if abs(p.deviation) == min_dev]
                # Choose one at random among them
                winner_prediction = random.choice(tied_preds)
                instrument_winners.append(winner_prediction.user)

            if instrument_winners:
                # How many instruments have winners?
                count_instruments = len(instrument_winners)
                if guessing_pool <= 0:
                    current_app.logger.info(
                        f"Poll {poll.id} completed. Winners exist, but pool is 0.0, reward = 0."
                    )
                else:
                    reward_per_winner = guessing_pool / count_instruments

                    # Distribute the reward
                    for w in instrument_winners:
                        if not w.wallet_address:
                            current_app.logger.warning(
                                f"User {w.id} does not have a wallet_address, skipping reward."
                            )
                            continue
                        success = voting_send_token_reward(w.wallet_address, reward_per_winner)
                        if success:
                            current_app.logger.info(
                                f"User {w.id} received {reward_per_winner:.4f} UJO for accurate prediction (poll {poll.id})."
                            )
                            # Send a message via Telegram:
                            if w.telegram_id:
                                try:
                                    from routes import bot  # Import bot
                                    bot.send_message(
                                        chat_id=w.telegram_id,
                                        text=(
                                            f"Congratulations! You have won {reward_per_winner:.4f} UJO "
                                            f"for your accurate prediction in poll {poll.id}."
                                        )
                                    )
                                except Exception as e:
                                    current_app.logger.error(f"Error sending TG notification: {e}")
                        else:
                            current_app.logger.error(
                                f"Failed to send reward of {reward_per_winner:.4f} UJO to user {w.id}."
                            )
            
                current_app.logger.info(
                    f"Poll {poll.id} completed. Total winners (by instrument count): {count_instruments}."
                )
            else:
                current_app.logger.info(f"Poll {poll.id} completed. No winners.")

        # Start a new poll (immediately, for testing)
        start_new_poll()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in process_poll_results: {e}")
        current_app.logger.error(traceback.format_exc())
