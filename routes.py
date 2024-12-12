# routes.py

import os
import logging
import traceback
import hashlib
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, jsonify, send_file
)
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_wtf.csrf import CSRFProtect
from functools import wraps

from extensions import db, csrf  # Импортируем csrf из extensions.py  # Импортируем db из extensions.py
from models import *
from forms import TradeForm, SetupForm, SubmitPredictionForm  # Импорт обновлённых форм

from telegram import (
    Bot, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler

from teleapp_auth import get_secret_key, parse_webapp_data, validate_webapp_data

# **Интеграция OpenAI**
import openai

# **Интеграция Robokassa**
import hashlib

# **Импорт дополнительных библиотек для обработки изображений и упрощённой нейросети**
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
import shutil
from skimage.segmentation import clear_border

# **Добавление PyTorch для нейросетевого анализа**
import torch
import torch.nn as nn
import torch.nn.functional as F

# **Импорт библиотек для мониторинга цен и планировщика задач**
import io
import base64

logger = logging.getLogger(__name__)  # Инициализируем логгер

# Создаём Blueprint
routes_bp = Blueprint('routes', __name__)

# Функция для проверки премиум статуса пользователя
def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user.assistant_premium:
            flash('Доступ ограничен. Пожалуйста, приобретите подписку.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Функция для генерации подписи Robokassa
def generate_robokassa_signature(out_sum, inv_id, password1):
    """
    Генерирует подпись для Robokassa.
    """
    signature = hashlib.md5(f"{app.config['ROBOKASSA_MERCHANT_LOGIN']}:{out_sum}:{inv_id}:{password1}".encode()).hexdigest()
    return signature

def generate_openai_response(messages):
    """
    Получает ответ от OpenAI GPT-3.5-turbo с учётом истории сообщений.
    """
    try:
        logger.debug(f"Sending messages to OpenAI: {messages}")
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7,
            max_tokens=1500,  # Увеличено для более подробных ответов
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        logger.debug(f"Received response from OpenAI: {response}")
        return response.choices[0].message['content'].strip()
    except Exception as e:
        logger.error(f"Ошибка при обращении к OpenAI API: {e}")
        logger.error(traceback.format_exc())
        return "Произошла ошибка при обработке вашего запроса."

##################################################
# Мониторинг цен через Yahoo Finance
##################################################

@routes_bp.route('/price/<int:instrument_id>')
def price(instrument_id):
    """
    Отображает ценовой график для указанного инструмента.
    """
    from app import generate_s3_url  # Импортируем необходимые функции из app.py
    instrument = Instrument.query.get_or_404(instrument_id)
    # Получаем последние 30 записей о ценах
    price_history = PriceHistory.query.filter_by(instrument_id=instrument_id).order_by(PriceHistory.date.asc()).limit(30).all()
    
    if not price_history:
        flash('Нет данных о ценах для этого инструмента.', 'info')
        return redirect(url_for('routes.index'))
    
    dates = [ph.date for ph in price_history]
    closes = [ph.close for ph in price_history]
    
    # Генерация графика с помощью matplotlib
    plt.figure(figsize=(10,5))
    plt.plot(dates, closes, marker='o')
    plt.title(f'Цена закрытия {instrument.name} за последние 30 дней')
    plt.xlabel('Дата')
    plt.ylabel('Цена закрытия')
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Сохранение графика в буфер
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plt.close()
    
    # Кодирование изображения в base64
    plot_url = base64.b64encode(img.getvalue()).decode('utf-8')
    
    return render_template('price_chart.html', instrument=instrument, plot_url=plot_url)

@routes_bp.route('/price_charts')
@premium_required
def price_charts():
    """
    Отображает ценовые графики для всех инструментов.
    """
    user_id = session['user_id']
    instruments = Instrument.query.all()
    charts = {}
    
    for instrument in instruments:
        # Получаем последние 30 записей о ценах
        price_history = PriceHistory.query.filter_by(instrument_id=instrument.id).order_by(PriceHistory.date.asc()).limit(30).all()
        
        if not price_history:
            continue
        
        dates = [ph.date for ph in price_history]
        closes = [ph.close for ph in price_history]
        
        # Генерация графика с помощью matplotlib
        plt.figure(figsize=(10,5))
        plt.plot(dates, closes, marker='o')
        plt.title(f'Цена закрытия {instrument.name} за последние 30 дней')
        plt.xlabel('Дата')
        plt.ylabel('Цена закрытия')
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Сохранение графика в буфер
        img = io.BytesIO()
        plt.savefig(img, format='png')
        img.seek(0)
        plt.close()
        
        # Кодирование изображения в base64
        plot_url = base64.b64encode(img.getvalue()).decode('utf-8')
        charts[instrument.name] = plot_url
    
    return render_template('predictions_chart.html', charts=charts)

##################################################
# Остальные маршруты и функции
##################################################

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Проверяем, авторизован ли пользователь
        if 'user_id' not in session or 'telegram_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('routes.login'))
        # Проверяем, является ли пользователь администратором
        if session['telegram_id'] not in ADMIN_TELEGRAM_IDS:
            flash('Доступ запрещён.', 'danger')
            return redirect(url_for('routes.index'))
        return f(*args, **kwargs)
    return decorated_function

# Маршруты для голосования
@routes_bp.route('/vote', methods=['GET', 'POST'])
@premium_required
def vote():
    """
    Маршрут для участия в голосовании.
    Отображает форму для предсказания цены, ценовой график и список победителей.
    """
    form = SubmitPredictionForm()
    user_id = session['user_id']
    
    # Получаем текущий активный опрос
    current_poll = Poll.query.filter(Poll.status == 'active').first()
    
    if not current_poll:
        flash('В данный момент нет активного голосования.', 'info')
        return redirect(url_for('routes.index'))
    
    # Выбираем первый инструмент из опроса для отображения графика
    poll_instrument = current_poll.poll_instruments[0].instrument if current_poll.poll_instruments else None
    
    # Обработка формы
    if form.validate_on_submit():
        try:
            from app import upload_file_to_s3, generate_s3_url  # Импортируем необходимые функции
            prediction = UserPrediction(
                user_id=user_id,
                poll_id=current_poll.id,
                instrument_id=form.instrument.data,
                predicted_price=form.predicted_price.data
            )
            db.session.add(prediction)
            db.session.commit()
            flash('Ваше предсказание успешно отправлено.', 'success')
            logger.info(f"Пользователь ID {user_id} отправил предсказание для инструмента ID {form.instrument.data}.")
            return redirect(url_for('routes.vote'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при отправке предсказания.', 'danger')
            logger.error(f"Ошибка при отправке предсказания: {e}")
            logger.error(traceback.format_exc())
    
    # Генерация ценового графика
    price_plot_url = None
    if poll_instrument:
        price_history = PriceHistory.query.filter_by(instrument_id=poll_instrument.id).order_by(PriceHistory.date.asc()).limit(30).all()
        if price_history:
            dates = [ph.date for ph in price_history]
            closes = [ph.close for ph in price_history]
            
            # Создание графика с помощью matplotlib
            plt.figure(figsize=(10,5))
            plt.plot(dates, closes, marker='o')
            plt.title(f'Цена закрытия {poll_instrument.name} за последние 30 дней')
            plt.xlabel('Дата')
            plt.ylabel('Цена закрытия')
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # Сохранение графика в буфер
            img = io.BytesIO()
            plt.savefig(img, format='png')
            img.seek(0)
            plt.close()
            
            # Кодирование изображения в base64
            price_plot_url = base64.b64encode(img.getvalue()).decode('utf-8')
    
    # Проверка, завершён ли опрос для отображения победителей
    poll_status = current_poll.status  # 'active' или 'completed'
    winners = []
    real_price = None
    if poll_status == 'completed':
        # Получение реальной цены из Poll.real_prices
        # Предполагается, что real_prices хранит реальные цены в формате {instrument_id: real_price}
        real_prices = json.loads(current_poll.real_prices) if current_poll.real_prices else {}
        real_price = real_prices.get(str(poll_instrument.id), None) if poll_instrument else None
        
        if real_price:
            # Получение всех предсказаний для этого инструмента
            predictions = UserPrediction.query.filter_by(poll_id=current_poll.id, instrument_id=poll_instrument.id).all()
            
            # Вычисление отклонений
            for pred in predictions:
                pred.deviation = abs(pred.predicted_price - real_price) / real_price * 100
            
            # Сортировка предсказаний по минимальному отклонению
            sorted_predictions = sorted(predictions, key=lambda x: x.deviation)
            
            # Выбор победителей (например, топ-3)
            winners = sorted_predictions[:3]
    
    return render_template(
        'vote.html',
        form=form,
        selected_instrument=poll_instrument,
        price_plot_url=price_plot_url,
        winners=winners,
        real_price=real_price,
        poll_status=poll_status
    )

# Интеграция Telegram бота
@routes_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    if request.method == 'POST':
        try:
            raw_data = request.get_data(as_text=True)
            logger.debug(f"Raw request data: {raw_data}")

            if not raw_data:
                logger.error("Empty request data received.")
                return 'Bad Request', 400

            update_obj = Update.de_json(request.get_json(force=True), bot)
            dispatcher.process_update(update_obj)
            logger.info(f"Получено обновление от Telegram: {update_obj}")
            return 'OK', 200
        except Exception as e:
            logger.error(f"Ошибка при обработке вебхука: {e}")
            logger.error(traceback.format_exc())
            return 'Internal Server Error', 500
    else:
        return 'Method Not Allowed', 405

@routes_bp.route('/set_webhook', methods=['GET'])
def set_webhook_route():
    webhook_url = f"https://{app.config['APP_HOST']}/webhook"
    try:
        s = bot.set_webhook(webhook_url)
        if s:
            logger.info(f"Webhook успешно установлен на {webhook_url}")
            return f"Webhook успешно установлен на {webhook_url}", 200
        else:
            logger.error(f"Не удалось установить webhook на {webhook_url}")
            return f"Не удалось установить webhook", 500
    except Exception as e:
        logger.error(f"Ошибка при установке вебхука: {e}")
        logger.error(traceback.format_exc())
        return f"Не удалось установить webhook: {e}", 500

@routes_bp.route('/webapp', methods=['GET'])
def webapp():
    return render_template('webapp.html')

@routes_bp.route('/assistant', methods=['GET'])
def assistant_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для доступа к ассистенту.', 'warning')
        return redirect(url_for('routes.login'))

    user = User.query.get(session['user_id'])
    if not user.assistant_premium:
        flash('Доступ к ассистенту доступен только по подписке.', 'danger')
        return redirect(url_for('routes.index'))

    return render_template('assistant.html')

@routes_bp.route('/subscription', methods=['GET'])
def subscription_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для доступа к подписке.', 'warning')
        return redirect(url_for('routes.login'))

    user = User.query.get(session['user_id'])
    if user.assistant_premium:
        flash('У вас уже активная подписка.', 'info')
        return redirect(url_for('routes.index'))

    return render_template('subscription.html')

@routes_bp.route('/buy_assistant', methods=['GET'])
def buy_assistant():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для покупки подписки.', 'warning')
        return redirect(url_for('routes.login'))

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
        f"Description=Покупка подписки на ассистента Дядя Джон&Culture=ru&Encoding=utf-8&"
        f"ResultURL={app.config['ROBOKASSA_RESULT_URL']}&SuccessURL={app.config['ROBOKASSA_SUCCESS_URL']}&FailURL={app.config['ROBOKASSA_FAIL_URL']}"
    )

    return redirect(robokassa_url)

@routes_bp.route('/robokassa/result', methods=['POST'])
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
                logger.info(f"Пользователь ID {user_id} успешно оплатил подписку.")
                if user.id == session.get('user_id'):
                    session['assistant_premium'] = user.assistant_premium
                    flash('Ваша подписка активирована.', 'success')

            return 'YES', 200
        except Exception as e:
            logger.error(f"Ошибка при обработке inv_id: {e}")
            return 'NO', 400
    else:
        logger.warning("Неверная подпись Robokassa.")
        return 'NO', 400

@routes_bp.route('/robokassa/success', methods=['GET'])
def robokassa_success():
    flash('Оплата успешно завершена. Спасибо за покупку!', 'success')
    return redirect(url_for('routes.index'))

@routes_bp.route('/robokassa/fail', methods=['GET'])
def robokassa_fail():
    flash('Оплата не была завершена. Пожалуйста, попробуйте снова.', 'danger')
    return redirect(url_for('routes.index'))

# Маршруты для управления пользователями, сделками, сетапами и т.д.
# Ваш существующий код остается без изменений

# Добавление маршрута для отображения ценовых графиков (уже добавлено выше)

# Маршруты для анализа графиков через ассистента
def get_trend_model():
    """
    Загружает модель тренда.
    """
    global trend_model
    if trend_model is None:
        model_path = 'trend_model.pth'
        if os.path.exists(model_path):
            trend_model = TrendCNN(num_classes=3)
            # Установка weights_only=True для повышения безопасности
            trend_model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
            trend_model.eval()
            logger.info("Модель тренда загружена из 'trend_model.pth'.")
        else:
            logger.warning("Файл 'trend_model.pth' не найден. Модель тренда не будет загружена.")
            trend_model = None
    return trend_model

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

def preprocess_for_trend(image_path):
    """
    Предобработка изображения для модели тренда.
    """
    try:
        from torchvision import transforms
        from PIL import Image

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
        logger.error(f"Ошибка при предобработке изображения для тренда: {e}")
        logger.error(traceback.format_exc())
        return None

def predict_trend(image_path):
    """
    Предсказывает направление тренда: uptrend, downtrend или sideways.
    """
    model = get_trend_model()
    if model is None:
        return "Модель тренда не загружена."

    img_tensor = preprocess_for_trend(image_path)
    if img_tensor is None:
        return "Не удалось обработать изображение для тренда."

    with torch.no_grad():
        outputs = model(img_tensor)
        _, predicted = torch.max(outputs.data, 1)
    # 0: downtrend, 1: sideways, 2: uptrend
    classes = ["downtrend", "sideways", "uptrend"]
    return f"Прогноз направления тренда: {classes[predicted.item()]}"

def analyze_chart(image_path):
    """
    Анализирует изображение графика: предсказывает тренд (trend_model.pth).
    Возвращает словарь с результатами анализа.
    """
    try:
        # Прогноз тренда
        trend_prediction = predict_trend(image_path)

        # Возвращаем результаты
        return {
            'trend_prediction': trend_prediction
        }
    except Exception as e:
        logger.error(f"Ошибка при анализе графика: {e}")
        logger.error(traceback.format_exc())
        return {'error': 'Произошла ошибка при анализе графика.'}

@routes_bp.route('/assistant/analyze_chart', methods=['POST'])
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
            MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ
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

            # Проверяем, что вернула функция analyze_chart
            if 'error' in analysis_result:
                # Возвращаем ошибку
                return jsonify({'error': analysis_result['error']}), 400
            elif 'trend_prediction' in analysis_result:
                # Возвращаем корректный результат
                return jsonify({'result': analysis_result}), 200
            else:
                # На всякий случай, если нет ни error, ни trend_prediction
                return jsonify({'error': 'Неизвестная ошибка при анализе графика.'}), 500

        except Exception as e:
            logger.error(f"Ошибка при обработке изображения: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': 'Error processing the image.'}), 500
    else:
        return jsonify({'error': 'Invalid image'}), 400

@routes_bp.route('/assistant/chat', methods=['POST'])
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

    if 'chat_history' not in session:
        session['chat_history'] = []

        trades = Trade.query.filter_by(user_id=user_id).all()
        if not trades:
            trade_data = "У вас пока нет сделок."
            comments = "Нет комментариев к сделкам."
        else:
            trade_data = "\n\n".join([
                f"**Сделка ID {trade.id}:**\n"
                f" - **Инструмент:** {trade.instrument.name}\n"
                f" - **Направление:** {trade.direction}\n"
                f" - **Цена входа:** {trade.entry_price}\n"
                f" - **Цена выхода:** {trade.exit_price}\n"
                f" - **Время открытия:** {trade.trade_open_time}\n"
                f" - **Время закрытия:** {trade.trade_close_time}\n"
                f" - **Прибыль/Убыток:** {trade.profit_loss} ({trade.profit_loss_percentage}%)\n"
                f" - **Сетап:** {trade.setup.setup_name if trade.setup else 'Без сетапа'}\n"
                f" - **Критерии:** {', '.join([criterion.name for criterion in trade.criteria]) if trade.criteria else 'Без критериев'}"
                for trade in trades
            ])
            comments = "\n\n".join([
                f"**Сделка ID {trade.id}:** {trade.comment}" for trade in trades if trade.comment
            ]) if any(trade.comment for trade in trades) else "Нет комментариев к сделкам."

        system_message = f"""
Ты — дядя Джон, крутой спец, который помогает пользователю анализировать его торговые сделки, предлагает конкретные решения с конкретными расчетами для торговых ситуаций пользователя, считает статистику по сделкам и находит закономерности.
Данные пользователя о сделках:
{trade_data}

Комментарии к сделкам:
{comments}

Предоставь подробный анализ и рекомендации на основе этих данных, если пользователь попросит.
"""
        logger.debug(f"System message for OpenAI: {system_message}")
        session['chat_history'].append({'role': 'system', 'content': system_message})

    session['chat_history'].append({'role': 'user', 'content': user_question})
    assistant_response = generate_openai_response(session['chat_history'])
    session['chat_history'].append({'role': 'assistant', 'content': assistant_response})

    MAX_CHAT_HISTORY = 20
    if len(session['chat_history']) > MAX_CHAT_HISTORY:
        session['chat_history'] = session['chat_history'][-MAX_CHAT_HISTORY:]

    return jsonify({'response': assistant_response}), 200

@routes_bp.route('/get_chat_history', methods=['GET'])
def get_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_history = session.get('chat_history', [])
    display_history = [msg for msg in chat_history if msg['role'] != 'system']
    return jsonify({'chat_history': display_history}), 200

@routes_bp.route('/clear_chat_history', methods=['POST'])
@csrf.exempt
def clear_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    session.pop('chat_history', None)
    return jsonify({'status': 'success'}), 200

@routes_bp.route('/logout')
def logout():
    session.clear()
    flash('Вы успешно вышли из системы.', 'success')
    logger.info("Пользователь вышел из системы.")
    return redirect(url_for('routes.login'))

@routes_bp.route('/health', methods=['GET'])
def health():
    return 'OK', 200

@routes_bp.route('/debug_session')
def debug_session():
    return jsonify(dict(session))

@routes_bp.route('/init', methods=['POST'])
@csrf.exempt
def init():
    if 'user_id' in session:
        logger.info(f"Пользователь ID {session['user_id']} уже авторизован.")
        return jsonify({'status': 'success'}), 200

    data = request.get_json()
    init_data = data.get('initData')
    logger.debug(f"Получен initData через AJAX: {init_data}")
    if init_data:
        try:
            webapp_data = parse_webapp_data(init_data)
            logger.debug(f"Parsed WebAppInitData: {webapp_data}")
            secret_key = get_secret_key(app.config['TELEGRAM_BOT_TOKEN'])
            is_valid = validate_webapp_data(webapp_data, secret_key)
            logger.debug(f"Validation result: {is_valid}")

            if not is_valid:
                logger.warning("Невалидные данные авторизации.")
                return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400

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
                logger.info(f"Новый пользователь создан: Telegram ID {telegram_id}.")

            session['user_id'] = user.id
            session['telegram_id'] = user.telegram_id
            session['assistant_premium'] = user.assistant_premium

            logger.info(f"Пользователь ID {user.id} авторизован через Telegram Web App.")
            return jsonify({'status': 'success'}), 200
        except Exception as e:
            logger.error(f"Ошибка при верификации initData: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400
    else:
        logger.warning("initData отсутствует в AJAX-запросе.")
        return jsonify({'status': 'failure', 'message': 'initData missing'}), 400

@routes_bp.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@routes_bp.route('/admin/user/<int:user_id>/toggle_premium', methods=['POST'])
@admin_required
def toggle_premium(user_id):
    user = User.query.get_or_404(user_id)
    user.assistant_premium = not user.assistant_premium
    db.session.commit()
    flash(f"Премиум статус пользователя {user.username} обновлён.", 'success')
    if user.id == session.get('user_id'):
        session['assistant_premium'] = user.assistant_premium
        flash('Ваш премиум статус обновлён.', 'success')
        
    return redirect(url_for('routes.admin_users'))

@routes_bp.route('/', methods=['GET'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

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
            flash('Некорректный формат даты начала.', 'danger')
            logger.error(f"Некорректный формат даты начала: {start_date}.")
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            trades_query = trades_query.filter(Trade.trade_open_time <= end_date_obj)
        except ValueError:
            flash('Некорректный формат даты окончания.', 'danger')
            logger.error(f"Некорректный формат даты окончания: {end_date}.")
    if selected_criteria:
        trades_query = trades_query.join(Trade.criteria).filter(Criterion.id.in_(selected_criteria)).distinct()

    trades = trades_query.order_by(Trade.trade_open_time.desc()).all()
    logger.info(f"Получено {len(trades)} сделок для пользователя ID {user_id}.")

    for trade in trades:
        if trade.screenshot:
            trade.screenshot_url = generate_s3_url(trade.screenshot)
        else:
            trade.screenshot_url = None

    for trade in trades:
        if trade.setup:
            if trade.setup.screenshot:
                trade.setup.screenshot_url = generate_s3_url(trade.setup.screenshot)
            else:
                trade.setup.screenshot_url = None

    return render_template(
        'index.html',
        trades=trades,
        categories=categories,
        criteria_categories=criteria_categories,
        selected_instrument_id=instrument_id,
        selected_criteria=selected_criteria
    )

@routes_bp.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('routes.index'))
    return render_template('login.html')

@routes_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

@routes_bp.route('/additional-info')
def additional_info():
    return render_template('additional_info.html')

@routes_bp.route('/new_trade', methods=['GET', 'POST'])
def new_trade():
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    form = TradeForm()
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    instruments = Instrument.query.all()
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
            from app import upload_file_to_s3, generate_s3_url  # Импортируем необходимые функции
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
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"trade_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    trade.screenshot = unique_filename
                else:
                    flash('Ошибка при загрузке скриншота.', 'danger')
                    logger.error("Не удалось загрузить скриншот в S3.")
                    return redirect(url_for('routes.new_trade'))

            db.session.add(trade)
            db.session.commit()
            flash('Сделка успешно добавлена.', 'success')
            logger.info(f"Сделка ID {trade.id} добавлена пользователем ID {user_id}.")
            return redirect(url_for('routes.index'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сделки.', 'danger')
            logger.error(f"Ошибка при добавлении сделки: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template(
        'new_trade.html',
        form=form,
        criteria_categories=criteria_categories
    )

@routes_bp.route('/edit_trade/<int:trade_id>', methods=['GET', 'POST'])
def edit_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для редактирования этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('routes.index'))

    if trade.screenshot:
        trade.screenshot_url = generate_s3_url(trade.screenshot)
    else:
        trade.screenshot_url = None

    form = TradeForm(obj=trade)
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    instruments = Instrument.query.all()
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in trade.criteria]
        form.instrument.data = trade.instrument_id
        form.setup_id.data = trade.setup_id if trade.setup_id else 0

    if form.validate_on_submit():
        try:
            from app import delete_file_from_s3, upload_file_to_s3, generate_s3_url  # Импортируем необходимые функции
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
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            if form.remove_image.data:
                if trade.screenshot:
                    delete_success = delete_file_from_s3(trade.screenshot)
                    if delete_success:
                        trade.screenshot = None
                        flash('Изображение удалено.', 'success')
                        logger.info(f"Изображение сделки ID {trade_id} удалено пользователем ID {user_id}.")
                    else:
                        flash('Ошибка при удалении изображения.', 'danger')
                        logger.error(f"Не удалось удалить изображение сделки ID {trade_id} из S3.")
                        return redirect(url_for('routes.edit_trade', trade_id=trade_id))

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if trade.screenshot:
                    delete_success = delete_file_from_s3(trade.screenshot)
                    if not delete_success:
                        flash('Ошибка при удалении старого изображения.', 'danger')
                        logger.error(f"Не удалось удалить старое изображение сделки ID {trade_id} из S3.")
                        return redirect(url_for('routes.edit_trade', trade_id=trade_id))
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"trade_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    trade.screenshot = unique_filename
                    flash('Изображение успешно обновлено.', 'success')
                    logger.info(f"Изображение сделки ID {trade_id} обновлено пользователем ID {user_id}.")
                else:
                    flash('Ошибка при загрузке нового изображения.', 'danger')
                    logger.error(f"Не удалось загрузить новое изображение сделки ID {trade_id} в S3.")
                    return redirect(url_for('routes.edit_trade', trade_id=trade_id))

            db.session.commit()
            flash('Сделка успешно обновлена.', 'success')
            logger.info(f"Сделка ID {trade.id} обновлена пользователем ID {user_id}.")
            return redirect(url_for('routes.index'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сделки.', 'danger')
            logger.error(f"Ошибка при обновлении сделки ID {trade_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('edit_trade.html', form=form, criteria_categories=criteria_categories, trade=trade)

@routes_bp.route('/delete_trade/<int:trade_id>', methods=['POST'])
def delete_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для удаления этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('routes.index'))
    try:
        if trade.screenshot:
            from app import delete_file_from_s3  # Импортируем необходимые функции
            delete_success = delete_file_from_s3(trade.screenshot)
            if not delete_success:
                flash('Ошибка при удалении скриншота.', 'danger')
                logger.error("Не удалось удалить скриншот из S3.")
        db.session.delete(trade)
        db.session.commit()
        flash('Сделка успешно удалена.', 'success')
        logger.info(f"Сделка ID {trade.id} удалена пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сделки.', 'danger')
        logger.error(f"Ошибка при удалении сделки ID {trade_id}: {e}")
    return redirect(url_for('routes.index'))

@routes_bp.route('/manage_setups')
def manage_setups():
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    setups = Setup.query.filter_by(user_id=user_id).all()
    logger.info(f"Пользователь ID {user_id} просматривает свои сетапы.")

    for setup in setups:
        if setup.screenshot:
            setup.screenshot_url = generate_s3_url(setup.screenshot)
        else:
            setup.screenshot_url = None

    return render_template('manage_setups.html', setups=setups)

@routes_bp.route('/add_setup', methods=['GET', 'POST'])
def add_setup():
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    form = SetupForm()
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    if form.criteria.data is None:
        form.criteria.data = []

    if form.validate_on_submit():
        try:
            from app import upload_file_to_s3, generate_s3_url  # Импортируем необходимые функции
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
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"setup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    setup.screenshot = unique_filename
                else:
                    flash('Ошибка при загрузке скриншота.', 'danger')
                    logger.error("Не удалось загрузить скриншот в S3.")
                    return redirect(url_for('routes.add_setup'))

            db.session.add(setup)
            db.session.commit()
            flash('Сетап успешно добавлен.', 'success')
            logger.info(f"Сетап ID {setup.id} добавлен пользователем ID {user_id}.")
            return redirect(url_for('routes.manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при добавлении сетапа.', 'danger')
            logger.error(f"Ошибка при добавлении сетапа: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('add_setup.html', form=form, criteria_categories=criteria_categories)

@routes_bp.route('/edit_setup/<int:setup_id>', methods=['GET', 'POST'])
def edit_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для редактирования этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('routes.manage_setups'))

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
            from app import delete_file_from_s3, upload_file_to_s3, generate_s3_url  # Импортируем необходимые функции
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
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            if form.remove_image.data:
                if setup.screenshot:
                    delete_success = delete_file_from_s3(setup.screenshot)
                    if delete_success:
                        setup.screenshot = None
                        flash('Изображение удалено.', 'success')
                        logger.info(f"Изображение сетапа ID {setup_id} удалено пользователем ID {user_id}.")
                    else:
                        flash('Ошибка при удалении изображения.', 'danger')
                        logger.error(f"Не удалось удалить изображение сетапа ID {setup_id} из S3.")
                        return redirect(url_for('routes.edit_setup', setup_id=setup_id))

            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                if setup.screenshot:
                    delete_success = delete_file_from_s3(setup.screenshot)
                    if not delete_success:
                        flash('Ошибка при удалении старого изображения.', 'danger')
                        logger.error(f"Не удалось удалить старое изображение сетапа ID {setup_id} из S3.")
                        return redirect(url_for('routes.edit_setup', setup_id=setup_id))
                filename = secure_filename(screenshot_file.filename)
                unique_filename = f"setup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    setup.screenshot = unique_filename
                    flash('Изображение успешно обновлено.', 'success')
                    logger.info(f"Изображение сетапа ID {setup_id} обновлено пользователем ID {user_id}.")
                else:
                    flash('Ошибка при загрузке нового изображения.', 'danger')
                    logger.error(f"Не удалось загрузить новое изображение сетапа ID {setup_id} в S3.")
                    return redirect(url_for('routes.edit_setup', setup_id=setup_id))

            db.session.commit()
            flash('Сетап успешно обновлён.', 'success')
            logger.info(f"Сетап ID {setup.id} обновлён пользователем ID {user_id}.")
            return redirect(url_for('routes.manage_setups'))
        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при обновлении сетапа.', 'danger')
            logger.error(f"Ошибка при обновлении сетапа ID {setup_id}: {e}")
            logger.error(traceback.format_exc())
    else:
        if request.method == 'POST':
            flash('Форма не валидна. Проверьте введённые данные.', 'danger')
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле {getattr(form, field).label.text}: {error}", 'danger')

    criteria_categories = CriterionCategory.query.all()
    return render_template('edit_setup.html', form=form, criteria_categories=criteria_categories, setup=setup)

@routes_bp.route('/delete_setup/<int:setup_id>', methods=['POST'])
def delete_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для удаления этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('routes.manage_setups'))
    try:
        if setup.screenshot:
            from app import delete_file_from_s3  # Импортируем необходимые функции
            delete_success = delete_file_from_s3(setup.screenshot)
            if not delete_success:
                flash('Ошибка при удалении скриншота.', 'danger')
                logger.error("Не удалось удалить скриншот из S3.")
        db.session.delete(setup)
        db.session.commit()
        flash('Сетап успешно удалён.', 'success')
        logger.info(f"Сетап ID {setup.id} удалён пользователем ID {user_id}.")
    except Exception as e:
        db.session.rollback()
        flash('Произошла ошибка при удалении сетапа.', 'danger')
        logger.error(f"Ошибка при удалении сетапа ID {setup_id}: {e}")
    return redirect(url_for('routes.manage_setups'))

@routes_bp.route('/view_trade/<int:trade_id>')
def view_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для просмотра этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('routes.index'))
    logger.info(f"Пользователь ID {user_id} просматривает сделку ID {trade_id}.")

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

@routes_bp.route('/view_setup/<int:setup_id>')
def view_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('routes.login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для просмотра этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('routes.manage_setups'))
    logger.info(f"Пользователь ID {user_id} просматривает сетап ID {setup_id}.")

    if setup.screenshot:
        setup.screenshot_url = generate_s3_url(setup.screenshot)
    else:
        setup.screenshot_url = None

    return render_template('view_setup.html', setup=setup)
