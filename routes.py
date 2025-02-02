# routes.py

import json
from app import translate_python
import pytz
import os
import logging
import traceback
import hashlib
import matplotlib.pyplot as plt  # Import moved to the top
import io
import base64
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify
)
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_wtf.csrf import CSRFProtect
from wtforms.validators import DataRequired, Optional

from app import app, csrf, db, s3_client, logger, get_app_host, upload_file_to_s3, delete_file_from_s3, generate_s3_url, ADMIN_TELEGRAM_IDS
from models import *
from forms import TradeForm, SetupForm, SubmitPredictionForm  # Import updated forms
from telegram import (
    Bot, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler
from staking_logic import get_token_price_in_usd
from teleapp_auth import get_secret_key, parse_webapp_data, validate_webapp_data
from functools import wraps
from best_setup_voting import send_token_reward as voting_send_token_reward

# **OpenAI Integration**
import openai
import yfinance as yf

def generate_openai_response(messages):
    """
    Gets a response from OpenAI GPT-3.5-turbo based on message history.
    """
    try:
        logger.debug(f"Sending messages to OpenAI: {messages}")
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7,
            max_tokens=900,  # Increased for more detailed responses
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        logger.debug(f"Received response from OpenAI: {response}")
        return response.choices[0].message['content'].strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
        logger.error(traceback.format_exc())
        return "An error occurred while processing your request."
        
# **Import additional libraries for image processing and simplified neural network**
import cv2
import numpy as np
import pandas as pd
import mplfinance as mpf
import shutil
from skimage.segmentation import clear_border

# **Add PyTorch for neural network analysis**
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms
from PIL import Image

# Import functions for voting and charts
from poll_functions import start_new_poll, process_poll_results, get_real_price  # Import get_real_price

# **Initialize OpenAI API**
app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '').strip()
if not app.config['OPENAI_API_KEY']:
    logger.error("OPENAI_API_KEY is not set in environment variables.")
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")

openai.api_key = app.config['OPENAI_API_KEY']

##################################################
# Trend Model (trend_model.pth)
##################################################

trend_model = None

class TrendCNN(nn.Module):
    def __init__(self, num_classes=3):
        super(TrendCNN, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2)
        )
        self.classifier = nn.Sequential(
            nn.Linear(32 * 32 * 32, 128),
            nn.ReLU(),
            nn.Linear(128, num_classes)
        )
        
    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        x = self.classifier(x)
        return x

def get_trend_model():
    global trend_model
    if trend_model is None:
        model_path = 'trend_model.pth'
        if os.path.exists(model_path):
            trend_model = TrendCNN(num_classes=3)
            # Set map_location to ensure compatibility across devices
            trend_model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
            trend_model.eval()
            logger.info("Trend model loaded from 'trend_model.pth'.")
        else:
            logger.warning("File 'trend_model.pth' not found. Trend model will not be loaded.")
            trend_model = None
    return trend_model
    

def preprocess_for_trend(image_path):
    """
    Preprocesses the image for trend model.
    """
    try:
        if not os.path.exists(image_path):
            return None

        transform = transforms.Compose([
            transforms.Resize((128, 128)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5])
        ])

        img = Image.open(image_path).convert('RGB')
        img_tensor = transform(img).unsqueeze(0)
        return img_tensor
    except Exception as e:
        logger.error(f"Error preprocessing image for trend: {e}")
        logger.error(traceback.format_exc())
        return None

def predict_trend(image_path):
    """
    Predicts trend direction: uptrend, downtrend or sideways.
    """
    model = get_trend_model()
    if model is None:
        return "Trend model not loaded."

    img_tensor = preprocess_for_trend(image_path)
    if img_tensor is None:
        return "Failed to process image for trend."

    with torch.no_grad():
        outputs = model(img_tensor)
        _, predicted = torch.max(outputs.data, 1)
    # 0: downtrend, 1: sideways, 2: uptrend
    classes = ["downtrend", "sideways", "uptrend"]
    return f"Trend prediction: {classes[predicted.item()]}"

##################################################
# Chart analysis and preprocessing
##################################################

def analyze_chart(image_path):
    """
    Analyzes the chart image: predicts trend (trend_model.pth).
    Returns a dictionary with analysis results.
    """
    try:
        # Trend prediction
        trend_prediction = predict_trend(image_path)

        # Return the results
        return {
            'trend_prediction': trend_prediction
        }
    except Exception as e:
        logger.error(f"Error analyzing chart: {e}")
        logger.error(traceback.format_exc())
        return {'error': 'An error occurred while analyzing the chart.'}

##################################################
# Restore authorization and Telegram bot
# Initialize Telegram bot
##################################################

app.config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TOKEN = app.config['TELEGRAM_BOT_TOKEN']
if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN is not set in environment variables.")
    exit(1)

bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, workers=1, use_context=True)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in
        if 'user_id' not in session or 'telegram_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        # Check if the user is an admin
        if session['telegram_id'] not in ADMIN_TELEGRAM_IDS:
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.assistant_premium:
            flash('Access denied. Please purchase a premium subscription.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def start_command(update, context):
    user = update.effective_user
    logger.info(f"Received /start command from user {user.id} ({user.username})")
    try:
        with app.app_context():
            user_record = User.query.filter_by(telegram_id=user.id).first()
            if not user_record:
                user_record = User(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    registered_at=datetime.utcnow()
                )
                db.session.add(user_record)
                db.session.commit()
                logger.info(f"New user created: Telegram ID {user.id}.")

        message_text = f"Hi, {user.first_name}! Click the button below to open the app."
        web_app_url = f"https://{get_app_host()}/webapp"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Open App",
                        web_app=WebAppInfo(url=web_app_url)
                    )
                ]
            ]
        )

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message_text,
            reply_markup=keyboard
        )
        logger.info(f"Web App button message sent to user {user.id} ({user.username}) for /start command.")
    except Exception as e:
        logger.error(f"Error processing /start command: {e}")
        logger.error(traceback.format_exc())
        context.bot.send_message(chat_id=update.effective_chat.id, text="An error occurred processing /start command.")

def help_command(update, context):
    user = update.effective_user
    logger.info(f"Received /help command from user {user.id} ({user.username})")
    help_text = (
        "Available commands:\n"
        "/start - Begin interaction with the bot and open the app\n"
        "/help - Get help\n"
        "/test - Test command to check bot functionality\n"
    )
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text=help_text)
        logger.info(f"Help response sent to user {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Error sending /help response: {e}")
        logger.error(traceback.format_exc())

def test_command(update, context):
    user = update.effective_user
    logger.info(f"Received /test command from user {user.id} ({user.username})")
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Command /test is working correctly!')
        logger.info(f"Test response sent to user {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Error sending /test response: {e}")
        logger.error(traceback.format_exc())

def button_click(update, context):
    query = update.callback_query
    query.answer()
    user = update.effective_user
    data = query.data
    logger.info(f"Button '{data}' clicked by user {user.id} ({user.username})")

    try:
        query.edit_message_text(text="Please use the embedded button to interact with the Web App.")
        logger.info(f"Button '{data}' click processed for user {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Error processing button click: {e}")
        logger.error(traceback.format_exc())

# Add command handlers to dispatcher
dispatcher.add_handler(CommandHandler('start', start_command))
dispatcher.add_handler(CommandHandler('help', help_command))
dispatcher.add_handler(CommandHandler('test', test_command))
dispatcher.add_handler(CallbackQueryHandler(button_click))

##################################################
# Routes for voting and assistant
##################################################


@app.route('/assistant/analyze_chart', methods=['POST'])
@csrf.exempt
def assistant_analyze_chart():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.assistant_premium:
        return jsonify({'error': 'Access denied. Please purchase a subscription.'}), 403

    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image = request.files['image']
    if image.filename == '':
        return jsonify({'error': 'No selected image'}), 400

    if image:
        try:
            MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
            image.seek(0, os.SEEK_END)
            file_size = image.tell()
            image.seek(0)
            if file_size > MAX_IMAGE_SIZE:
                return jsonify({'error': 'Image size exceeds 5 MB limit.'}), 400

            filename = secure_filename(image.filename)
            temp_dir = 'temp'
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, filename)
            image.save(temp_path)

            analysis_result = analyze_chart(temp_path)
            os.remove(temp_path)

            # Check what analyze_chart returned
            if 'error' in analysis_result:
                return jsonify({'error': analysis_result['error']}), 400
            elif 'trend_prediction' in analysis_result:
                return jsonify({'result': analysis_result}), 200
            else:
                return jsonify({'error': 'Unknown error during chart analysis.'}), 500

        except Exception as e:
            logger.error(f"Error processing image: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': 'Error processing the image.'}), 500
    else:
        return jsonify({'error': 'Invalid image'}), 400

@app.route('/vote', methods=['GET', 'POST'])
def vote():
    """
    Route for participating in voting. (Free section)
    """
    if 'user_id' not in session:
        flash('Please log in to participate in the vote.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    
    # Check if voting is enabled
    voting_config = Config.query.filter_by(key='voting_enabled').first()
    if not voting_config or voting_config.value != 'true':
        flash('Voting is currently disabled.', 'info')
        return redirect(url_for('index'))

    # Get active poll with additional filter for end_date
    active_poll = Poll.query.filter_by(status='active').filter(Poll.end_date > datetime.utcnow()).first()
    if not active_poll:
        flash('No active voting at the moment.', 'info')
        return redirect(url_for('index'))

    form = SubmitPredictionForm()

    if request.method == 'POST':
        # Get poll instruments
        poll_instruments = PollInstrument.query.filter_by(poll_id=active_poll.id).all()
        instruments = [pi.instrument for pi in poll_instruments]
        form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]

        try:
            if form.validate_on_submit():
                selected_instrument_id = form.instrument.data
                predicted_price_str = request.form.get('predicted_price', '').strip()
                # Меняем запятые на точки:
                predicted_price_str = predicted_price_str.replace(',', '.')

                try:
                    predicted_price = float(predicted_price_str)
                except ValueError:
                    flash('Invalid price format. Use "." or "," as decimal separator.', 'danger')
                    return redirect(url_for('vote'))

                # Теперь подменяем в самой форме, чтобы дальше все проверки шли с нормальным float
                form.predicted_price.data = predicted_price

                # Check if user has already voted for the selected instrument in this poll
                existing_prediction = UserPrediction.query.filter_by(
                    user_id=user_id,
                    poll_id=active_poll.id,
                    instrument_id=selected_instrument_id
                ).first()

                if existing_prediction:
                    flash('You have already voted for this instrument in the current poll.', 'info')
                    existing_predictions = UserPrediction.query.filter_by(
                        user_id=user_id,
                        poll_id=active_poll.id
                    ).all()
                    return render_template(
                        'vote.html',
                        form=None,
                        active_poll=active_poll,
                        existing_predictions=existing_predictions
                    )

                # **Added validations**

                now = datetime.utcnow()
                cutoff_time = active_poll.end_date - timedelta(days=2)
                if now > cutoff_time:
                    flash('Predictions cannot be submitted less than 2 days before the poll ends.', 'danger')
                    logger.info(f"User {user_id} attempted to vote too late for poll {active_poll.id}.")
                    return redirect(url_for('vote'))

                instrument = Instrument.query.get(selected_instrument_id)
                if not instrument:
                    flash('The selected instrument does not exist.', 'danger')
                    logger.error(f"Instrument ID {selected_instrument_id} not found.")
                    return redirect(url_for('vote'))

                real_price = get_real_price(instrument.name)
                if real_price is None:
                    flash('Failed to get the current real price for the selected instrument. Please try again later.', 'danger')
                    logger.error(f"Failed to get real price for instrument {instrument.name}.")
                    return redirect(url_for('vote'))

                lower_bound = 0.8 * real_price
                upper_bound = 1.2 * real_price
                if not (lower_bound <= predicted_price <= upper_bound):
                    flash(f'The predicted price must be between {lower_bound:.2f} and {upper_bound:.2f}.', 'danger')
                    logger.info(
                        f"User ID {user_id} submitted prediction {predicted_price} outside the allowed range "
                        f"for instrument {instrument.name}. Real price: {real_price}."
                    )
                    return redirect(url_for('vote'))

                # Create prediction
                user_prediction = UserPrediction(
                    user_id=user_id,
                    poll_id=active_poll.id,
                    instrument_id=selected_instrument_id,
                    predicted_price=predicted_price
                )
                db.session.add(user_prediction)
                db.session.commit()
                flash('Your prediction has been saved successfully.', 'success')
                logger.info(
                    f"User ID {user_id} made a prediction for instrument ID {selected_instrument_id} "
                    f"in poll ID {active_poll.id}."
                )

                return redirect(url_for('vote'))
            else:
                flash('The form is not valid. Please check the entered data.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while saving your prediction.', 'danger')
            logger.error(f"Error saving prediction for user ID {user_id}: {e}")
            logger.error(traceback.format_exc())
            return redirect(url_for('vote'))
    else:
        poll_instruments = PollInstrument.query.filter_by(poll_id=active_poll.id).all()
        instruments = [pi.instrument for pi in poll_instruments]
        form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]

    existing_predictions = UserPrediction.query.filter_by(
        user_id=user_id,
        poll_id=active_poll.id
    ).all()

    return render_template(
        'vote.html',
        form=form if not existing_predictions else None,
        active_poll=active_poll,
        existing_predictions=existing_predictions
    )

@app.route('/fetch_charts', methods=['GET'])
def fetch_charts():
    if 'user_id' not in session:
        return jsonify({'error':'Unauthorized'}),401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user.assistant_premium:
        return jsonify({'error': 'Forbidden'}), 403

    charts = {}

    active_polls = Poll.query.filter_by(status='active').filter(Poll.end_date > datetime.utcnow()).all()
    logger.debug(f"Found {len(active_polls)} active polls.")

    for poll in active_polls:
        logger.debug(f"Processing poll ID {poll.id}. Instruments: {[pi.instrument.name for pi in poll.poll_instruments]}")
        for pi in poll.poll_instruments:
            instr = pi.instrument
            predictions = UserPrediction.query.filter_by(poll_id=poll.id, instrument_id=instr.id).all()
            logger.debug(f"[fetch_charts] {len(predictions)} predictions for {instr.name} (poll {poll.id}).")

            if not predictions:
                continue

            # Log to check if there is a 0.0 value
            for p in predictions:
                logger.debug(f"UserPred: user={p.user_id}, predicted={p.predicted_price}, real={p.real_price}")

            df = pd.DataFrame([{
                'user': p.user.username or p.user.first_name,
                'predicted_price': float(p.predicted_price or 0.0)
            } for p in predictions])

            if df.empty:
                continue

            real_price = predictions[0].real_price

            plt.figure(figsize=(10, 6))
            plt.hist(df['predicted_price'], bins=20, color='green', alpha=0.7)
            plt.xlabel('Predicted Price')
            plt.ylabel('Number of Predictions')
            plt.title(f'Prediction Distribution for {instr.name} (Poll {poll.id})')

            if real_price is not None:
                plt.axvline(float(real_price), color='red', linestyle='dashed', linewidth=2,
                            label=f'Real Price: {real_price}')
                plt.legend()

            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            image_base64 = base64.b64encode(buf.getvalue()).decode()
            plt.close()

            charts[f"Active - {instr.name} (Poll {poll.id})"] = image_base64

    logger.debug(f"Total charts to send: {len(charts)}.")
    return jsonify({'charts': charts})

@app.route('/fetch_predictions', methods=['GET'])
def fetch_predictions():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    active_poll = Poll.query.filter_by(status='active').filter(Poll.end_date > datetime.utcnow()).first()
    if not active_poll:
        return jsonify({'error': 'No active poll.'}), 404

    predictions = UserPrediction.query.filter_by(
        user_id=user_id,
        poll_id=active_poll.id
    ).all()

    predictions_data = [{
        'instrument': pred.instrument.name,
        'predicted_price': pred.predicted_price,
        'real_price': pred.real_price,
        'deviation': pred.deviation
    } for pred in predictions]

    return jsonify({'predictions': predictions_data}), 200
    
@app.route('/predictions_chart', methods=['GET'])
@premium_required
def predictions_chart():
    return render_template('predictions_chart.html')

def generate_chart_base64(user_prediction):
    try:
        real_price = getattr(user_prediction, 'real_price', None)
        deviation = getattr(user_prediction, 'deviation', None)

        if real_price is None or deviation is None:
            return None

        plt.figure(figsize=(6, 4))
        plt.bar(['Predicted Price', 'Real Price'], [user_prediction.predicted_price, real_price], color=['blue', 'green'])
        plt.title('Comparison of Predicted and Real Prices')
        plt.ylabel('Price')
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()

        return image_base64
    except Exception as e:
        logger.error(f"Error generating chart: {e}")
        logger.error(traceback.format_exc())
        return None

@app.route('/vote_results', methods=['GET'])
@admin_required
def vote_results():
    completed_polls = Poll.query.filter(Poll.status == 'completed').all()
    return render_template('vote_results.html', polls=completed_polls)

@app.route('/subscription', methods=['GET'])
def subscription():
    if 'user_id' not in session:
        flash('Please log in first.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    my_wallet = os.environ.get("MY_WALLET_ADDRESS", "")
    
    token_price_usd = get_token_price_in_usd()
    if token_price_usd <= 0:
        flash('Failed to get the current token price. Please try again later.', 'danger')
        logger.error("Failed to get the current token price for UJO.")
        token_price_usd = 1.0
    
    TOKEN_DECIMALS = int(os.environ.get("TOKEN_DECIMALS", 18))
    TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS", "0xYOUR_UJO_CONTRACT_ADDRESS")
    
    return render_template(
        'subscription.html',
        user=user,
        MY_WALLET_ADDRESS=my_wallet,
        token_price_usd=token_price_usd,
        TOKEN_DECIMALS=TOKEN_DECIMALS,
        TOKEN_CONTRACT_ADDRESS=TOKEN_CONTRACT_ADDRESS
    )

@app.route('/buy_assistant', methods=['GET'])
def buy_assistant():
    if 'user_id' not in session:
        flash('Please log in to purchase a subscription.', 'warning')
        return redirect(url_for('login'))

    user_id = session['user_id']
    amount = 1000
    inv_id = f"{user_id}_{int(datetime.utcnow().timestamp())}"
    out_sum = f"{amount}.00"
    merchant_login = app.config['ROBOKASSA_MERCHANT_LOGIN']
    password1 = app.config['ROBOKASSA_PASSWORD1']

    signature = generate_robokassa_signature(out_sum, inv_id, password1)

    robokassa_url = (
        f"https://auth.robokassa.ru/Merchant/Index.aspx?"
        f"MerchantLogin={merchant_login}&OutSum={out_sum}&InvoiceID={inv_id}&SignatureValue={signature}&"
        f"Description=Purchase of Uncle John Assistant Subscription&Culture=ru&Encoding=utf-8&"
        f"ResultURL={app.config['ROBOKASSA_RESULT_URL']}&SuccessURL={app.config['ROBOKASSA_SUCCESS_URL']}&FailURL={app.config['ROBOKASSA_FAIL_URL']}"
    )

    return redirect(robokassa_url)


@app.route('/robokassa/result', methods=['POST'])
def robokassa_result():
    data = request.form
    out_sum = data.get('OutSum')
    inv_id = data.get('InvoiceID')
    signature = data.get('SignatureValue')

    password1 = app.config['ROBOKASSA_PASSWORD1']
    correct_signature = hashlib.md5(f"{app.config['ROBOKASSA_MERCHANT_LOGIN']}:{out_sum}:{inv_id}:{password1}".encode()).hexdigest()

    if signature.lower() == correct_signature.lower():
        try:
            user_id_str, timestamp = inv_id.split('_')
            user_id = int(user_id_str)
            user = User.query.get(user_id)
            if user:
                user.assistant_premium = True
                db.session.commit()
                logger.info(f"User ID {user_id} successfully paid for subscription.")
                if user.id == session.get('user_id'):
                    session['assistant_premium'] = user.assistant_premium
                    flash('Your subscription has been activated.', 'success')

            return 'YES', 200
        except Exception as e:
            logger.error(f"Error processing inv_id: {e}")
            return 'NO', 400
    else:
        logger.warning("Invalid Robokassa signature.")
        return 'NO', 400

@app.route('/robokassa/success', methods=['GET'])
def robokassa_success():
    flash('Payment completed successfully. Thank you for your purchase!', 'success')
    return redirect(url_for('index'))

@app.route('/robokassa/fail', methods=['GET'])
def robokassa_fail():
    flash('Payment was not completed. Please try again.', 'danger')
    return redirect(url_for('index'))

@app.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    if request.method == 'POST':
        try:
            raw_data = request.get_data(as_text=True)
            logger.debug(f"Raw request data: {raw_data}")

            if not raw_data:
                logger.error("Empty request data received.")
                return 'Bad Request', 400

            update = Update.de_json(request.get_json(force=True), bot)
            dispatcher.process_update(update)
            logger.info(f"Received Telegram update: {update}")
            return 'OK', 200
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            logger.error(traceback.format_exc())
            return 'Internal Server Error', 500
    else:
        return 'Method Not Allowed', 405

@app.route('/set_webhook', methods=['GET'])
def set_webhook_route():
    webhook_url = f"https://{get_app_host()}/webhook"
    try:
        s = bot.set_webhook(webhook_url)
        if s:
            logger.info(f"Webhook successfully set to {webhook_url}")
            return f"Webhook successfully set to {webhook_url}", 200
        else:
            logger.error(f"Failed to set webhook to {webhook_url}")
            return f"Failed to set webhook", 500
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        logger.error(traceback.format_exc())
        return f"Failed to set webhook: {e}", 500

@app.route('/webapp', methods=['GET'])
def webapp():
    return render_template('webapp.html')

@app.route('/assistant', methods=['GET'])
def assistant_page():
    if 'user_id' not in session:
        flash('Please log in to access the assistant.', 'warning')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user.assistant_premium:
        flash('The assistant is available to premium users only.', 'danger')
        return redirect(url_for('index'))

    return render_template('assistant.html')

############################
# 2) Настраиваем функцию "create_trades" для OpenAI
############################
FUNCTIONS = [
    {
        "name": "create_trades",
        "description": "Create up to 5 new trades in the user's journal. If confirm=false, just ask user for confirmation. If confirm=true, finalize in DB.",
        "parameters": {
            "type": "object",
            "properties": {
                "trades": {
                    "type": "array",
                    "description": "Array of trades to create.",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "instrument": {
                                "type": "string",
                                "description": "e.g. 'EUR/USD', 'BTC-USD', must exist in DB"
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["Buy", "Sell"],
                                "description": "Buy or Sell"
                            },
                            "entry_price": {
                                "type": "number",
                                "description": "Entry price > 0"
                            },
                            "open_time": {
                                "type": "string",
                                "description": "Time the trade was opened, format 'YYYY-MM-DD HH:MM:SS'"
                            },
                            "exit_price": {
                                "type": "number",
                                "description": "Optional exit price",
                                "nullable": True
                            },
                            "close_time": {
                                "type": "string",
                                "description": "Optional close time, same format",
                                "nullable": True
                            },
                            "comment": {
                                "type": "string",
                                "description": "Optional comment"
                            }
                        },
                        "required": ["instrument", "direction", "entry_price", "open_time"]
                    }
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Whether to actually finalize trades in the DB (true) or just propose them (false)."
                }
            },
            "required": ["trades", "confirm"]
        }
    }
]


@app.route('/assistant/chat', methods=['POST'])
@csrf.exempt
def assistant_chat():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user or not user.assistant_premium:
        return jsonify({'error': 'Access denied. Please purchase a subscription.'}), 403

    data = request.get_json()
    user_question = data.get('question')

    if not user_question:
        return jsonify({'error': 'No question provided'}), 400

    # Инициализация chat_history (как и раньше)
    if 'chat_history' not in session:
        session['chat_history'] = []

        trades = Trade.query.filter_by(user_id=user_id).all()
        if not trades:
            trade_data = "You currently have no trades."
            comments = "No comments on trades."
        else:
            trade_data = "\n\n".join([
                f"**Trade ID {trade.id}:**\n"
                f" - **Instrument:** {trade.instrument.name}\n"
                f" - **Direction:** {trade.direction}\n"
                f" - **Entry Price:** {trade.entry_price}\n"
                f" - **Exit Price:** {trade.exit_price}\n"
                f" - **Open Time:** {trade.trade_open_time}\n"
                f" - **Close Time:** {trade.trade_close_time}\n"
                f" - **Profit/Loss:** {trade.profit_loss} ({trade.profit_loss_percentage}%)\n"
                f" - **Setup:** {trade.setup.setup_name if trade.setup else 'No setup'}\n"
                f" - **Criteria:** {', '.join([criterion.name for criterion in trade.criteria]) if trade.criteria else 'No criteria'}"
                for trade in trades
            ])
            comments = "\n\n".join([
                f"**Trade ID {trade.id}:** {trade.comment}" 
                for trade in trades if trade.comment
            ]) if any(trade.comment for trade in trades) else "No comments on trades."

        # Расширяем system_message, добавляя правила для Function Calling
        system_message = f"""
You are Uncle John, a versatile trading assistant with the following capabilities:

1. **Analyze Trades:**
   - Review and analyze the user's existing trades.
   - Provide detailed insights, statistics, and identify patterns.
   - Analyze trade comments and suggest improvements or highlight strengths.

2. **Educate and Advise:**
   - Offer educational content on trading strategies.
   - Explain complex trading concepts in simple terms.
   - Propose specific strategies with calculations and figures based on user's trading data.
   - If you ask for advice or help, always give a specific solution, using in detail numbers, indicators, situations, examples. Avoid general information.

3. **Manage Trades:**
   - Add new trades to the user's journal by calling the function `create_trades(...)`.
   - Ensure that new trades meet all required criteria and validate input data.

**Important Rules:**

- **Function Calling (`create_trades`):**
  - **When to Call:**
    - Only call `create_trades(...)` if the user explicitly requests to add or create new trades.
    - Do not call `create_trades(...)` during analysis or educational interactions.
  
  - **Parameters for `create_trades(...)`:**
    1. `trades`: An array of up to 5 trade objects. Each trade must include:
       - `instrument` (string, e.g., 'EUR/USD', 'BTC-USD')
       - `direction` (enum: 'Buy' or 'Sell')
       - `entry_price` (number > 0)
       - `open_time` (string in 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' format)
       - `exit_price` (optional number)
       - `close_time` (optional string)
       - `comment` (optional string)
    
    2. `confirm`: (boolean)
       - If `confirm=false`: The user is describing trades without confirmation. Respond with a summary and ask for confirmation.
       - If `confirm=true`: Finalize and add the trades to the database.

  - **Validation:**
    - Ensure `open_time` and `close_time` are in the correct format. If only a date is provided ('YYYY-MM-DD'), interpret it as 'YYYY-MM-DD 00:00:00'.
    - If more than 5 trades are provided, politely refuse and inform the user of the limit.
    - If required fields are missing or data is invalid, ask the user to provide corrections.

- **Context Separation:**
  - **Analysis and Education:**
    - When the user asks to analyze, review, or explain existing trades or trading strategies, focus on providing insights and analysis in normal text (no function call).
  
  - **Adding Trades:**
    - Only engage in adding trades when the user explicitly states the intent to do so (e.g., "add a new trade", "create trade", "confirm these trades").

- **Handling Alternative Instrument Names:**
  - Users may refer to instruments using alternative names or in different languages (e.g., "euro" -> "EUR/USD"). If needed, map synonyms to existing instrument names in the DB.

- **Response Style:**
  - Always keep messages short and clear.
  - If user says "confirm" or "yes" to finalize trades, finalize them with `confirm=true`.
  - If user is only analyzing or discussing, do not call `create_trades`.
  - If finalizing trades, you may end the conversation.
  - If you ask for advice or help, always give a specific solution, using in detail numbers, indicators, situations, examples. Avoid general information.

**Existing Trades Summary:**
{trade_data}

**User Trade Comments:**
{comments}

"""
        logger.debug(f"System message for OpenAI: {system_message}")
        session['chat_history'].append({'role': 'system', 'content': system_message})

    # Добавляем сообщение пользователя
    session['chat_history'].append({'role': 'user', 'content': user_question})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=session['chat_history'],
            functions=FUNCTIONS,
            function_call="auto",
            temperature=0.7,
            max_tokens=900,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        assistant_message = response["choices"][0]["message"]

        # Если ассистент решил вызвать функцию:
        if assistant_message.get("function_call"):
            fn_name = assistant_message["function_call"]["name"]
            fn_args_json = assistant_message["function_call"]["arguments"]
            try:
                fn_args = json.loads(fn_args_json)
            except:
                fn_args = {}

            if fn_name == "create_trades":
                assistant_response_new = handle_create_trades(user_id, fn_args)
                return assistant_response_new
            else:
                error_text = f"Error: unknown function call '{fn_name}'."
                session['chat_history'].append({'role': 'assistant', 'content': error_text})
                return jsonify({'response': error_text}), 200
        else:
            assistant_response_new = assistant_message["content"]
            session['chat_history'].append({'role': 'assistant', 'content': assistant_response_new})

    except Exception as e:
        logger.error(f"OpenAI API error: {e}", exc_info=True)
        assistant_response_new = "Sorry, an error occurred with the AI server."
        session['chat_history'].append({'role': 'assistant', 'content': assistant_response_new})

    # Ограничиваем длину истории
    MAX_CHAT_HISTORY = 20
    if len(session['chat_history']) > MAX_CHAT_HISTORY:
        session['chat_history'] = session['chat_history'][-MAX_CHAT_HISTORY:]

    return jsonify({'response': assistant_response_new}), 200


@app.route('/get_chat_history', methods=['GET'])
def get_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_history = session.get('chat_history', [])
    # Системные сообщения скрываем
    display_history = [msg for msg in chat_history if msg['role'] != 'system']
    return jsonify({'chat_history': display_history}), 200

@app.route('/clear_chat_history', methods=['POST'])
@csrf.exempt
def clear_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    session.pop('chat_history', None)
    return jsonify({'status': 'success'}), 200

@app.route('/logout')
def logout():
    session.clear()
    flash('You have successfully logged out.', 'success')
    logger.info("User logged out.")
    return redirect(url_for('info'))

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

@app.route('/debug_session')
def debug_session():
    return jsonify(dict(session))

@app.route('/init', methods=['POST'])
@csrf.exempt
def init():
    if 'user_id' in session:
        logger.info(f"User ID {session['user_id']} is already logged in.")
        return jsonify({'status': 'success'}), 200

    data = request.get_json()
    init_data = data.get('initData')
    logger.debug(f"Received initData via AJAX: {init_data}")
    if init_data:
        try:
            webapp_data = parse_webapp_data(init_data)
            logger.debug(f"Parsed WebAppInitData: {webapp_data}")
            secret_key = get_secret_key(app.config['TELEGRAM_BOT_TOKEN'])
            is_valid = validate_webapp_data(webapp_data, secret_key)
            logger.debug(f"Validation result: {is_valid}")

            if not is_valid:
                logger.warning("Invalid authorization data.")
                return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400

            language_code = getattr(webapp_data.user, 'language_code', 'en')
            session['language'] = language_code

            telegram_id = int(webapp_data.user.id)
            first_name = webapp_data.user.first_name
            last_name = webapp_data.user.last_name or ''
            username = webapp_data.user.username or ''

            user = User.query.filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    registered_at=datetime.utcnow()
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"New user created: Telegram ID {telegram_id}.")

            session['user_id'] = user.id
            session['telegram_id'] = user.telegram_id
            session['assistant_premium'] = user.assistant_premium

            logger.info(f"User ID {user.id} logged in via Telegram Web App.")
            return jsonify({'status': 'success'}), 200
        except Exception as e:
            logger.error(f"Error verifying initData: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400
    else:
        logger.warning("initData not provided in AJAX request.")
        return jsonify({'status': 'failure', 'message': 'Go to Telegram'}), 400

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    voting_config = Config.query.filter_by(key='voting_enabled').first()
    pool_config = Config.query.filter_by(key='best_setup_pool_size').first()
    existing_pool_size = pool_config.value if pool_config else '0'

    return render_template(
        'admin_users.html',
        users=users,
        voting_config=voting_config,
        existing_pool_size=existing_pool_size
    )

@app.route('/admin/toggle_voting', methods=['POST'])
@admin_required
def toggle_voting():
    try:
        voting_config = Config.query.filter_by(key='voting_enabled').first()
        if not voting_config:
            voting_config = Config(key='voting_enabled', value='false')
            db.session.add(voting_config)
        
        voting_config.value = 'false' if voting_config.value == 'true' else 'true'
        db.session.commit()
        
        flash(f"Voting has been {'disabled' if voting_config.value == 'false' else 'enabled'}.", 'success')
        logger.info(f"Voting {'disabled' if voting_config.value == 'false' else 'enabled'} by admin.")
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while toggling voting.', 'danger')
        logger.error(f"Error toggling voting: {e}")
        logger.error(traceback.format_exc())
    
    return redirect(url_for('admin_users'))
    
@app.route('/admin/user/<int:user_id>/toggle_premium', methods=['POST'])
@admin_required
def toggle_premium(user_id):
    user = User.query.get_or_404(user_id)
    user.assistant_premium = not user.assistant_premium
    db.session.commit()
    flash(f"Premium status for user {user.username} has been updated.", 'success')
    if user.id == session.get('user_id'):
        session['assistant_premium'] = user.assistant_premium
        flash('Your premium status has been updated.', 'success')
        
    return redirect(url_for('admin_users'))

@app.route('/admin/set_pool_size', methods=['POST'])
@admin_required
def set_pool_size():
    pool_size = request.form.get('pool_size', '0').strip()
    try:
        config_record = Config.query.filter_by(key='best_setup_pool_size').first()
        if not config_record:
            config_record = Config(key='best_setup_pool_size', value='0')
            db.session.add(config_record)
        
        config_record.value = pool_size
        db.session.commit()
        flash(f"Prize pool size updated: {pool_size} UJO", 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error saving prize pool.', 'danger')
        logger.error(f"Error in set_pool_size: {e}", exc_info=True)
    
    return redirect(url_for('admin_users'))

@app.route('/', methods=['GET'])
def index():
    if 'user_id' in session:
        user_id = session['user_id']
        categories = InstrumentCategory.query.all()
        criteria_categories = CriterionCategory.query.all()

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
                flash('Invalid start date format.', 'danger')
                logger.error(f"Invalid start date format: {start_date}.")
        if end_date:
            try:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                trades_query = trades_query.filter(Trade.trade_open_time <= end_date_obj)
            except ValueError:
                flash('Invalid end date format.', 'danger')
                logger.error(f"Invalid end date format: {end_date}.")
        if selected_criteria:
            trades_query = trades_query.join(Trade.criteria).filter(Criterion.id.in_(selected_criteria)).distinct()

        trades = trades_query.order_by(Trade.trade_open_time.desc()).all()
        logger.info(f"Retrieved {len(trades)} trades for user ID {user_id}.")

        for trade in trades:
            if trade.screenshot:
                trade.screenshot_url = generate_s3_url(trade.screenshot)
            else:
                trade.screenshot_url = None

            if trade.setup and trade.setup.screenshot:
                trade.setup.screenshot_url = generate_s3_url(trade.setup.screenshot)
            else:
                if trade.setup:
                    trade.setup.screenshot_url = None

        return render_template(
            'index.html',
            trades=trades,
            categories=categories,
            criteria_categories=criteria_categories,
            selected_instrument_id=instrument_id,
            selected_criteria=selected_criteria
        )
    else:
        return render_template('info.html')

@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

@app.route('/white-paper')
def white_paper():
    return render_template('white_paper.html')

@app.route('/additional-info')
def additional_info():
    return render_template('additional_info.html')

@app.route('/new_trade', methods=['GET', 'POST'])
def new_trade():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    form = TradeForm()
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Select setup')] + [(setup.id, setup.setup_name) for setup in setups]
    instruments = Instrument.query.all()
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
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
            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        trade.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Invalid criterion ID: {criterion_id}")

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"trade_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    trade.screenshot = unique_filename
                else:
                    flash('Error uploading screenshot.', 'danger')
                    logger.error("Failed to upload screenshot to S3.")
                    return redirect(url_for('new_trade'))

            db.session.add(trade)
            db.session.commit()
            flash('Trade added successfully.', 'success')
            logger.info(f"Trade ID {trade.id} added by user ID {user_id}.")
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the trade.', 'danger')
            logger.error(f"Error adding trade: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('The form is not valid. Please check the entered data.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in field {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template(
        'new_trade.html',
        form=form,
        criteria_categories=criteria_categories
    )

@app.route('/edit_trade/<int:trade_id>', methods=['GET', 'POST'])
def edit_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('You do not have permission to edit this trade.', 'danger')
        logger.warning(f"User ID {user_id} attempted to edit trade ID {trade_id} not belonging to them.")
        return redirect(url_for('index'))

    if trade.screenshot:
        trade.screenshot_url = generate_s3_url(trade.screenshot)
    else:
        trade.screenshot_url = None

    if trade.setup:
        if trade.setup.screenshot:
            trade.setup.screenshot_url = generate_s3_url(trade.setup.screenshot)
        else:
            trade.setup.screenshot_url = None

    form = TradeForm(obj=trade)
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Select setup')] + [(setup.id, setup.setup_name) for setup in setups]
    instruments = Instrument.query.all()
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in trade.criteria]
        form.instrument.data = trade.instrument_id
        form.setup_id.data = trade.setup_id if trade.setup_id else 0

    if form.validate_on_submit():
        try:
            trade.instrument_id = form.instrument.data
            trade.direction = form.direction.data
            trade.entry_price = form.entry_price.data
            trade.exit_price = form.exit_price.data if form.exit_price.data else None
            trade.trade_open_time = form.trade_open_time.data
            trade.trade_close_time = form.trade_close_time.data if form.trade_close_time.data else None
            trade.comment = form.comment.data
            trade.setup_id = form.setup_id.data if form.setup_id.data != 0 else None

            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            trade.criteria.clear()
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        trade.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Invalid criterion ID: {criterion_id}")

            if form.remove_image.data:
                if trade.screenshot:
                    delete_success = delete_file_from_s3(trade.screenshot)
                    if delete_success:
                        trade.screenshot = None
                        flash('Image deleted.', 'success')
                        logger.info(f"Image for trade ID {trade_id} deleted by user ID {user_id}.")
                    else:
                        flash('Error deleting image.', 'danger')
                        logger.error(f"Failed to delete image for trade ID {trade_id} from S3.")
                        return redirect(url_for('edit_trade', trade_id=trade_id))

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if trade.screenshot:
                    delete_success = delete_file_from_s3(trade.screenshot)
                    if not delete_success:
                        flash('Error deleting old image.', 'danger')
                        logger.error(f"Failed to delete old image for setup ID {trade_id} from S3.")
                        return redirect(url_for('edit_trade', trade_id=trade_id))
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"trade_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    trade.screenshot = unique_filename
                    flash('Image updated successfully.', 'success')
                    logger.info(f"Image for trade ID {trade_id} updated by user ID {user_id}.")
                else:
                    flash('Error uploading new image.', 'danger')
                    logger.error(f"Failed to upload new image for trade ID {trade_id} to S3.")
                    return redirect(url_for('edit_trade', trade_id=trade_id))

            db.session.commit()
            flash('Trade updated successfully.', 'success')
            logger.info(f"Trade ID {trade.id} updated by user ID {user_id}.")
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the trade.', 'danger')
            logger.error(f"Error updating trade ID {trade_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('The form is not valid. Please check the entered data.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in field {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('edit_trade.html', form=form, criteria_categories=criteria_categories, trade=trade)

@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
def delete_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('You do not have permission to delete this trade.', 'danger')
        logger.warning(f"User ID {user_id} attempted to delete trade ID {trade_id} not belonging to them.")
        return redirect(url_for('index'))
    try:
        if trade.screenshot:
            delete_success = delete_file_from_s3(trade.screenshot)
            if not delete_success:
                flash('Error deleting screenshot.', 'danger')
                logger.error("Failed to delete screenshot from S3.")
        db.session.delete(trade)
        db.session.commit()
        flash('Trade deleted successfully.', 'success')
        logger.info(f"Trade ID {trade.id} deleted by user ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the trade.', 'danger')
        logger.error(f"Error deleting trade ID {trade_id}: {e}")
    return redirect(url_for('index'))

@app.route('/manage_setups')
def manage_setups():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setups = Setup.query.filter_by(user_id=user_id).all()
    logger.info(f"User ID {user_id} is viewing their setups.")

    for setup in setups:
        if setup.screenshot:
            setup.screenshot_url = generate_s3_url(setup.screenshot)
        else:
            setup.screenshot_url = None

    return render_template('manage_setups.html', setups=setups)

@app.route('/add_setup', methods=['GET', 'POST'])
def add_setup():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    form = SetupForm()
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
            setup = Setup(
                user_id=user_id,
                setup_name=form.setup_name.data,
                description=form.description.data
            )
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        setup.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Invalid criterion ID: {criterion_id}")

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"setup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    setup.screenshot = unique_filename
                else:
                    flash('Error uploading screenshot.', 'danger')
                    logger.error("Failed to upload screenshot to S3.")
                    return redirect(url_for('add_setup'))

            db.session.add(setup)
            db.session.commit()
            flash('Setup added successfully.', 'success')
            logger.info(f"Setup ID {setup.id} added by user ID {user_id}.")
            return redirect(url_for('manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while adding the setup.', 'danger')
            logger.error(f"Error adding setup: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('The form is not valid. Please check the entered data.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in field {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('add_setup.html', form=form, criteria_categories=criteria_categories)

@app.route('/edit_setup/<int:setup_id>', methods=['GET', 'POST'])
def edit_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('You do not have permission to edit this setup.', 'danger')
        logger.warning(f"User ID {user_id} attempted to edit setup ID {setup_id} not belonging to them.")
        return redirect(url_for('manage_setups'))

    if setup.screenshot:
        setup.screenshot_url = generate_s3_url(setup.screenshot)
    else:
        setup.screenshot_url = None

    form = SetupForm(obj=setup)
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in setup.criteria]

    if form.validate_on_submit():
        try:
            setup.setup_name = form.setup_name.data
            setup.description = form.description.data

            setup.criteria.clear()
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        setup.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Invalid criterion ID: {criterion_id}")

            if form.remove_image.data:
                if setup.screenshot:
                    delete_success = delete_file_from_s3(setup.screenshot)
                    if delete_success:
                        setup.screenshot = None
                        flash('Image deleted.', 'success')
                        logger.info(f"Image for setup ID {setup_id} deleted by user ID {user_id}.")
                    else:
                        flash('Error deleting image.', 'danger')
                        logger.error(f"Failed to delete image for setup ID {setup_id} from S3.")
                        return redirect(url_for('edit_setup', setup_id=setup_id))

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if setup.screenshot:
                    delete_success = delete_file_from_s3(setup.screenshot)
                    if not delete_success:
                        flash('Error deleting old image.', 'danger')
                        logger.error(f"Failed to delete old image for setup ID {setup_id} from S3.")
                        return redirect(url_for('edit_setup', setup_id=setup_id))
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"setup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    setup.screenshot = unique_filename
                    flash('Image updated successfully.', 'success')
                    logger.info(f"Image for setup ID {setup_id} updated by user ID {user_id}.")
                else:
                    flash('Error uploading new image.', 'danger')
                    logger.error(f"Failed to upload new image for setup ID {setup_id} to S3.")
                    return redirect(url_for('edit_setup', setup_id=setup_id))

            db.session.commit()
            flash('Setup updated successfully.', 'success')
            logger.info(f"Setup ID {setup.id} updated by user ID {user_id}.")
            return redirect(url_for('manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the setup.', 'danger')
            logger.error(f"Error updating setup ID {setup_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('The form is not valid. Please check the entered data.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in field {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('edit_setup.html', form=form, criteria_categories=criteria_categories, setup=setup)

@app.route('/delete_setup/<int:setup_id>', methods=['POST'])
def delete_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('You do not have permission to delete this setup.', 'danger')
        logger.warning(f"User ID {user_id} attempted to delete setup ID {setup_id} not belonging to them.")
        return redirect(url_for('manage_setups'))
    try:
        if setup.screenshot:
            delete_success = delete_file_from_s3(setup.screenshot)
            if not delete_success:
                flash('Error deleting screenshot.', 'danger')
                logger.error("Failed to delete screenshot from S3.")
        db.session.delete(setup)
        db.session.commit()
        flash('Setup deleted successfully.', 'success')
        logger.info(f"Setup ID {setup.id} deleted by user ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the setup.', 'danger')
        logger.error(f"Error deleting setup ID {setup_id}: {e}")
    return redirect(url_for('manage_setups'))

@app.route('/view_trade/<int:trade_id>')
def view_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('You do not have permission to view this trade.', 'danger')
        logger.warning(f"User ID {user_id} attempted to view trade ID {trade_id} not belonging to them.")
        return redirect(url_for('index'))
    logger.info(f"User ID {user_id} is viewing trade ID {trade_id}.")

    if trade.screenshot:
        trade.screenshot_url = generate_s3_url(trade.screenshot)
    else:
        trade.screenshot_url = None

    if trade.setup:
        if trade.setup.screenshot:
            trade.setup.screenshot_url = generate_s3_url(trade.setup.screenshot)
        else:
            trade.setup.screenshot_url = None

    return render_template('view_trade.html', trade=trade)

@app.route('/view_setup/<int:setup_id>')
def view_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('You do not have permission to view this setup.', 'danger')
        logger.warning(f"User ID {user_id} attempted to view setup ID {setup_id} not belonging to them.")
        return redirect(url_for('manage_setups'))
    logger.info(f"User ID {user_id} is viewing setup ID {setup_id}.")

    if setup.screenshot:
        setup.screenshot_url = generate_s3_url(setup.screenshot)
    else:
        setup.screenshot_url = None

    return render_template('view_setup.html', setup=setup)


@app.route('/get_user_stakes', methods=['GET'])
def get_user_stakes():
    if 'user_id' not in session:
        return jsonify({'error':'Unauthorized'}),401
    user_id = session['user_id']
    stakings = UserStaking.query.filter_by(user_id=user_id).all()
    data = []
    for s in stakings:
        data.append({
            'id': s.id,
            'tx_hash': s.tx_hash,
            'staked_usd': round(s.staked_usd, 2),
            'staked_amount': round(s.staked_amount, 4),
            'created_at': s.created_at.isoformat(),
            'unlocked_at': s.unlocked_at.isoformat(),
            'pending_rewards': round(s.pending_rewards, 4),
            'last_claim_at': s.last_claim_at.isoformat()
        })
    return jsonify({'stakes': data}), 200

@app.route('/claim_staking_rewards', methods=['POST'])
def claim_staking_rewards():
    if 'user_id' not in session:
        return jsonify({'error':'Unauthorized'}),401
    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error':'User not found'}),404
    stakings = UserStaking.query.filter_by(user_id=user_id).all()
    if not stakings:
        return jsonify({'error':'You have no staking.'}),400

    now = datetime.utcnow()
    totalRewards = 0.0
    updated_stakes = []
    for s in stakings:
        if s.staked_amount > 0:
            delta = now - s.last_claim_at
            if delta.total_seconds() >= 7 * 24 * 3600:
                totalRewards += s.pending_rewards
                s.pending_rewards = 0.0
                s.last_claim_at = now
                updated_stakes.append(s)
    if totalRewards <= 0:
        return jsonify({'error':'Nothing to claim yet, or a week has not passed.'}),400
    
    if not user.wallet_address:
        return jsonify({'error':'No wallet address'}),400
    
    success = voting_send_token_reward(user.wallet_address, totalRewards)
    if success:
        db.session.commit()
        return jsonify({'message': f'Claim of {totalRewards:.4f} UJO successfully sent to {user.wallet_address}.'}),200
    else:
        db.session.rollback()
        return jsonify({'error':'Transaction error.'}),400

@app.route('/unstake_staking', methods=['POST'])
def unstake_staking():
    if 'user_id' not in session:
        return jsonify({'error':'Unauthorized'}),401
    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error':'User not found'}),404
    
    stakings = UserStaking.query.filter_by(user_id=user_id).all()
    if not stakings:
        return jsonify({'error':'You have no staking'}),400
    
    now = datetime.utcnow()
    total_unstake = 0.0
    changed_stakes = []
    for st in stakings:
        if st.staked_amount > 0 and now >= st.unlocked_at:
            total_unstake += st.staked_amount
            st.staked_amount = 0.0
            st.pending_rewards = 0.0
            changed_stakes.append(st)
    if total_unstake <= 0:
        return jsonify({'error':'No stakes available (30 days have not passed).'}),400
    
    fee = total_unstake * 0.01
    withdraw_amount = total_unstake - fee
    success = voting_send_token_reward(user.wallet_address, withdraw_amount)
    if success:
        db.session.commit()
        active_left = UserStaking.query.filter(
            UserStaking.user_id == user_id,
            UserStaking.staked_amount > 0
        ).all()
        if not active_left:
            user.assistant_premium = False
            db.session.commit()
        return jsonify({'message': f'Unstaked {withdraw_amount:.4f} UJO (1% fee deducted = {fee:.4f}).'}),200
    else:
        db.session.rollback()
        return jsonify({'error':'Transaction error during unstake'}),400


def parse_date_time(dt_str: str) -> datetime:
    """
    Парсит строку даты/времени. Поддерживает форматы:
      1) 'YYYY-MM-DD HH:MM:SS'
      2) 'YYYY-MM-DD' (тогда автоматически добавляется '00:00:00')
    При неудаче выбрасывает ValueError.
    """
    dt_str = dt_str.strip()
    # Сначала пробуем "YYYY-MM-DD HH:MM:SS"
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        # Пробуем "YYYY-MM-DD"
        try:
            d = datetime.strptime(dt_str, "%Y-%m-%d")
            return d
        except ValueError:
            raise ValueError(
                f"Invalid date/time format: '{dt_str}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'."
            )

def _find_instrument_by_substring(user_input: str) -> Instrument:
    """
    Ищет инструмент в БД по подстроке (case-insensitive), сначала используя словарь
    синонимов, а затем — частичное совпадение. Если находит ровно один инструмент,
    возвращает его. Если нет совпадений или несколько совпадений, бросает ValueError.
    """

    # 1) Определяем словарь синонимов (можно расширять):
    SYNONYMS = {
        "серебро": "Silver",
        "xag": "Silver",
        "xag/usd": "Silver",
        "silver": "Silver",
        "gold": "Gold",
        "золото": "Gold",
        # Можно добавлять: "euro": "EUR/USD", "евро": "EUR/USD" и т.д.
    }

    user_input_lower = user_input.lower().strip()

    # 2) Если это слово есть в словаре синонимов, подменяем
    if user_input_lower in SYNONYMS:
        mapped_name = SYNONYMS[user_input_lower]
        user_input_lower = mapped_name.lower()  # например "Silver".lower() = "silver"

    # 3) Собираем все инструменты из БД
    all_instruments = Instrument.query.all()

    matches = []
    for instr in all_instruments:
        # Сравниваем lower-версию имени инструмента с user_input_lower
        # но при этом делаем проверку "содержит ли"
        db_instrument_lower = instr.name.lower()
        if user_input_lower in db_instrument_lower:
            matches.append(instr)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        conflict_names = ", ".join(i.name for i in matches)
        raise ValueError(f"Ambiguous instrument '{user_input}'. Matches: {conflict_names}")
    else:
        raise ValueError(f"Instrument '{user_input}' not found in DB.")
        

def _create_new_trade_in_db(user_id, instrument, direction, entry_price, open_time,
                            exit_price=None, close_time=None, comment=None):
    """
    Пример внутренней функции, сохраняющей ОДНУ сделку в БД,
    теперь с «поиском» инструмента по подстроке (case-insensitive).
    """
    # Вместо строгого filter_by(name=instrument), делаем простой partial match
    instrument_record = _find_instrument_by_substring(instrument)

    if direction not in ["Buy", "Sell"]:
        raise ValueError(f"Direction must be 'Buy' or 'Sell', got '{direction}'.")

    if entry_price <= 0:
        raise ValueError(f"Entry price must be > 0, got {entry_price}.")

    open_dt = parse_date_time(open_time)
    close_dt = None
    if close_time:
        close_dt = parse_date_time(close_time)

    trade = Trade(
        user_id=user_id,
        instrument_id=instrument_record.id,
        direction=direction,
        entry_price=entry_price,
        trade_open_time=open_dt,
        exit_price=exit_price if exit_price else None
    )

    if close_dt:
        trade.trade_close_time = close_dt

    if comment:
        trade.comment = comment

    # Если задан exit_price, считаем profit_loss
    if trade.exit_price:
        sign = 1 if trade.direction == 'Buy' else -1
        trade.profit_loss = (trade.exit_price - trade.entry_price) * sign
        trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
    else:
        trade.profit_loss = None
        trade.profit_loss_percentage = None

    db.session.add(trade)
    return trade

def check_duplicate_trade(user_id, instrument_str, direction_str, entry_price_val, open_time_str):
    try:
        instrument_obj = _find_instrument_by_substring(instrument_str)
    except ValueError:
        return False  # Или обработайте ошибку соответствующим образом

    try:
        open_dt = parse_date_time(open_time_str)
    except ValueError:
        return False

    existing_trade = Trade.query.filter(
        Trade.user_id == user_id,
        Trade.instrument_id == instrument_obj.id,
        Trade.direction == direction_str,
        Trade.entry_price == entry_price_val,
        Trade.trade_open_time == open_dt
    ).first()

    return existing_trade is not None

def handle_create_trades(user_id, fn_args):
    trades = fn_args.get("trades", [])
    confirm = fn_args.get("confirm", False)

    if not trades:
        msg = "No trades provided."
        session['chat_history'].append({'role': 'assistant', 'content': msg})
        return jsonify({'response': msg}), 200

    if len(trades) > 5:
        msg = "You are trying to create more than 5 trades in one request, which is not allowed."
        session['chat_history'].append({'role': 'assistant', 'content': msg})
        return jsonify({'response': msg}), 200

    if not confirm:
        summary_lines = []
        for i, t in enumerate(trades, start=1):
            line = (f"Trade #{i}: {t.get('instrument')} {t.get('direction')} at {t.get('entry_price')} "
                    f"(open: {t.get('open_time')})")
            summary_lines.append(line)
        summary_text = "\n".join(summary_lines)
        answer = (
            f"I've noted these trades (NOT YET CREATED):\n\n"
            f"{summary_text}\n\n"
            "Please say 'confirm' or 'yes' to finalize, or 'no' to cancel."
        )
        session['chat_history'].append({'role': 'assistant', 'content': answer})
        return jsonify({"response": answer}), 200
    else:
        created_ids = []
        duplicates_skipped = 0
        try:
            for t in trades:
                instrument_str = t["instrument"]
                direction_str = t["direction"]
                entry_price_val = t["entry_price"]
                open_time_str = t["open_time"]
                exit_price_val = t.get("exit_price")
                close_time_str = t.get("close_time")
                comment_str = t.get("comment")

                if check_duplicate_trade(
                    user_id,
                    instrument_str,
                    direction_str,
                    entry_price_val,
                    open_time_str
                ):
                    duplicates_skipped += 1
                    continue

                new_trade = _create_new_trade_in_db(
                    user_id=user_id,
                    instrument=instrument_str,
                    direction=direction_str,
                    entry_price=entry_price_val,
                    open_time=open_time_str,
                    exit_price=exit_price_val,
                    close_time=close_time_str,
                    comment=comment_str
                )
                db.session.flush()
                created_ids.append(new_trade.id)

            db.session.commit()

            # После добавления сделок — очищаем историю, чтобы диалог закончился
            session.pop('chat_history', None)

            if created_ids:
                text = f"Successfully created trades with IDs: {created_ids}"
                if duplicates_skipped > 0:
                    text += f" (skipped {duplicates_skipped} duplicates)."
            else:
                if duplicates_skipped > 0:
                    text = "All provided trades were duplicates; no new trades created."
                else:
                    text = "No trades created for unknown reasons."

            # Дополнительная фраза (по желанию):
            text += "\n\nConversation ended. Chat history cleared."

            return jsonify({"response": text}), 200

        except Exception as e:
            db.session.rollback()
            error_text = f"Error creating trades: {str(e)}"
            session['chat_history'].append({'role': 'assistant', 'content': error_text})
            return jsonify({"response": error_text}), 200

        except Exception as e:
            db.session.rollback()
            error_text = f"Error creating trades: {str(e)}"
            session['chat_history'].append({'role': 'assistant', 'content': error_text})
            return jsonify({"response": error_text}), 200
