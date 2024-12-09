# routes.py

import os
import logging
import traceback
import hashlib
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
from extensions import db  # Импортируем db из extensions.py
from models import *
from forms import TradeForm, SetupForm  # Импорт обновлённых форм

from telegram import (
    Bot, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update
)
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler

from teleapp_auth import get_secret_key, parse_webapp_data, validate_webapp_data
from functools import wraps

# **Интеграция OpenAI**
import openai

# **Импорт дополнительных библиотек для обработки изображений и анализа**
import cv2
import numpy as np
import pandas as pd
import mplfinance as mpf
# import pytesseract  # Удален pytesseract
import shutil
from prophet import Prophet  # Для прогнозирования

# **Добавление Torch для нейросетевого анализа**
import torch
import torch.nn as nn
import torch.optim as optim

# Ленивая инициализация нейросетевой модели
nn_model = None

def get_nn_model():
    """
    Ленивая инициализация нейросетевой модели.
    """
    global nn_model
    if nn_model is None:
        nn_model = SimpleNN(input_size=9, hidden_size=16, output_size=1)
        model_path = 'model.pth'
        if os.path.exists(model_path):
            nn_model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
            nn_model.eval()
            logger.info("Нейросетевая модель загружена из 'model.pth'.")
        else:
            logger.warning("Файл модели 'model.pth' не найден. Нейросетевая модель не будет загружена.")
            nn_model = None
    return nn_model

# Определение нейросетевой модели
class SimpleNN(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(SimpleNN, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.fc2(out)
        return out

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Проверяем, авторизован ли пользователь
        if 'user_id' not in session or 'telegram_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        # Проверяем, является ли пользователь администратором
        if session['telegram_id'] not in ADMIN_TELEGRAM_IDS:
            flash('Доступ запрещён.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Инициализация OpenAI API
app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '').strip()
if not app.config['OPENAI_API_KEY']:
    logger.error("OPENAI_API_KEY не установлен в переменных окружения.")
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения.")

openai.api_key = app.config['OPENAI_API_KEY']

# **Интеграция Robokassa**
app.config['ROBOKASSA_MERCHANT_LOGIN'] = os.environ.get('ROBOKASSA_MERCHANT_LOGIN', '').strip()
app.config['ROBOKASSA_PASSWORD1'] = os.environ.get('ROBOKASSA_PASSWORD1', '').strip()
app.config['ROBOKASSA_PASSWORD2'] = os.environ.get('ROBOKASSA_PASSWORD2', '').strip()
app.config['ROBOKASSA_RESULT_URL'] = os.environ.get('ROBOKASSA_RESULT_URL', '').strip()
app.config['ROBOKASSA_SUCCESS_URL'] = os.environ.get('ROBOKASSA_SUCCESS_URL', '').strip()
app.config['ROBOKASSA_FAIL_URL'] = os.environ.get('ROBOKASSA_FAIL_URL', '').strip()

# Проверка наличия необходимых Robokassa настроек
if not all([
    app.config['ROBOKASSA_MERCHANT_LOGIN'],
    app.config['ROBOKASSA_PASSWORD1'],
    app.config['ROBOKASSA_PASSWORD2'],
    app.config['ROBOKASSA_RESULT_URL'],
    app.config['ROBOKASSA_SUCCESS_URL'],
    app.config['ROBOKASSA_FAIL_URL']
]):
    logger.error("Некоторые Robokassa настройки отсутствуют в переменных окружения.")
    raise ValueError("Некоторые Robokassa настройки отсутствуют в переменных окружения.")

# Вспомогательные функции

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

# Функции для обработки и анализа графиков

# Константы для масштабов графика
MIN_PRICE = 34000.0  # Минимальная цена на оси Y
MAX_PRICE = 35000.0  # Максимальная цена на оси Y
START_DATE = datetime(2023, 9, 19)  # Начальная дата на оси X
FREQUENCY = timedelta(hours=4)  # Частота свечей (например, 4 часа)

def preprocess_image(image_path):
    """
    Предобрабатывает изображение для анализа графика.
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Не удалось загрузить изображение: {image_path}")
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Увеличение контрастности
        gray = cv2.equalizeHist(gray)
        # Применение адаптивной бинаризации
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 11, 2)
        # Удаление шума с помощью морфологии
        kernel = np.ones((3,3), np.uint8)
        opening = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=2)
        return opening
    except Exception as e:
        logger.error(f"Ошибка при предобработке изображения: {e}")
        logger.error(traceback.format_exc())
        return None

def detect_candlesticks(preprocessed_img, original_img):
    """
    Обнаруживает японские свечи на графике и извлекает их данные.
    Возвращает DataFrame с колонками: date, open, high, low, close
    """
    try:
        # Используем контурный анализ для обнаружения свечей
        contours, _ = cv2.findContours(preprocessed_img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        candlesticks = []

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            if 0.1 < aspect_ratio < 0.3 and 20 < h < 200:
                # Предполагаем, что свеча имеет узкий и высокий прямоугольник
                candlesticks.append((x, y, w, h))
                cv2.rectangle(original_img, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Сортируем свечи по оси X
        candlesticks = sorted(candlesticks, key=lambda c: c[0])

        data = []
        img_height, img_width = preprocessed_img.shape

        for index, c in enumerate(candlesticks):
            x, y, w, h = c

            # Определение даты на основе индекса свечи
            date = START_DATE + index * FREQUENCY

            # Преобразование Y-пикселей в цены
            # Предполагаем, что верх графика соответствует MAX_PRICE, ниж графика - MIN_PRICE
            open_price = MIN_PRICE + (img_height - (y + h)) / img_height * (MAX_PRICE - MIN_PRICE)
            close_price = MIN_PRICE + (img_height - y) / img_height * (MAX_PRICE - MIN_PRICE)

            # Определение high и low на основе высоты свечи
            high_price = max(open_price, close_price) + (h / img_height) * (MAX_PRICE - MIN_PRICE) * 0.1
            low_price = min(open_price, close_price) - (h / img_height) * (MAX_PRICE - MIN_PRICE) * 0.1

            data.append({
                'date': date,
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2)
            })

        if data:
            df = pd.DataFrame(data)
            df = df.drop_duplicates(subset=['date'])
            df = df.sort_values(by='date')
            logger.info(f"Обнаружено {len(df)} свечей.")
            return df, original_img
        else:
            logger.warning("Свечи не обнаружены на графике.")
            return pd.DataFrame(), original_img
    except Exception as e:
        logger.error(f"Ошибка при обнаружении свечей: {e}")
        logger.error(traceback.format_exc())
        return pd.DataFrame(), original_img

def perform_technical_analysis(df):
    """
    Выполняет технический анализ на основе данных свечей.
    Возвращает анализ в виде строки.
    """
    try:
        if df.empty:
            return "Нет данных для анализа."

        # Вычисление скользящих средних
        df['MA20'] = df['close'].rolling(window=20, min_periods=1).mean()
        df['MA50'] = df['close'].rolling(window=50, min_periods=1).mean()

        # Вычисление RSI
        df['RSI'] = compute_rsi(df['close'], window=14)

        # Вычисление MACD
        df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

        # Прогнозирование с использованием Prophet
        forecast = forecast_with_prophet(df)

        last_close = df['close'].iloc[-1]
        forecast_price = forecast['yhat'].iloc[-1] if not forecast.empty else "N/A"

        # Нейросетевой анализ
        nn_analysis = neural_network_analysis(df)

        analysis = f"""
### Технический Анализ

**Скользящие Средние:**
- MA20: {df['MA20'].iloc[-1]:.2f}
- MA50: {df['MA50'].iloc[-1]:.2f}

**RSI:**
- {df['RSI'].iloc[-1]:.2f}

**MACD:**
- MACD: {df['MACD'].iloc[-1]:.2f}
- Signal: {df['Signal'].iloc[-1]:.2f}

**Прогноз:**
- Следующая цена: {forecast_price}

**Нейросетевой Анализ:**
{nn_analysis}
"""

        return analysis
    except Exception as e:
        logger.error(f"Ошибка при выполнении технического анализа: {e}")
        logger.error(traceback.format_exc())
        return "Ошибка при выполнении технического анализа."

def compute_rsi(series, window=14):
    """
    Вычисляет индекс относительной силы (RSI).
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def forecast_with_prophet(df):
    """
    Выполняет прогнозирование цен с использованием Prophet.
    Возвращает DataFrame с прогнозом.
    """
    try:
        prophet_df = df[['date', 'close']].rename(columns={'date': 'ds', 'close': 'y'})
        model = Prophet()
        model.fit(prophet_df)
        future = model.make_future_dataframe(periods=5)  # Прогноз на 5 свечей
        forecast = model.predict(future)
        return forecast
    except Exception as e:
        logger.error(f"Ошибка при прогнозировании с использованием Prophet: {e}")
        logger.error(traceback.format_exc())
        return pd.DataFrame()

def neural_network_analysis(df):
    """
    Выполняет нейросетевой анализ данных свечей.
    Возвращает строку с результатом анализа.
    """
    try:
        model = get_nn_model()
        if model is None:
            return "Нейросетевая модель не загружена."

        # Подготовка данных
        feature_columns = ['open', 'high', 'low', 'close', 'MA20', 'MA50', 'RSI', 'MACD', 'Signal']
        X = df[feature_columns].values[:-1]  # Все кроме последнего
        y = (df['close'].values[1:] > df['close'].values[:-1]).astype(int)  # 1: Цена выросла, 0: снизилась

        if len(X) < 10:
            return "Недостаточно данных для нейросетевого анализа."

        # Нормализация данных
        X_mean = X.mean(axis=0)
        X_std = X.std(axis=0)
        X = (X - X_mean) / X_std

        # Преобразование в тензоры
        X_tensor = torch.tensor(X, dtype=torch.float32)

        # Прогнозирование
        with torch.no_grad():
            predictions = torch.sigmoid(model(X_tensor))
            predicted = (predictions > 0.5).float()
            accuracy = (predicted.squeeze() == torch.tensor(y, dtype=torch.float32)).float().mean().item()

        analysis = f"Нейросетевая модель предсказывает направление цены с точностью: {accuracy * 100:.2f}%"

        return analysis
    except Exception as e:
        logger.error(f"Ошибка при нейросетевом анализе: {e}")
        logger.error(traceback.format_exc())
        return "Ошибка при нейросетевом анализе."

def analyze_chart(image_path):
    """
    Анализирует изображение графика и выполняет технический анализ.
    Возвращает словарь с результатами анализа и URL графика.
    """
    try:
        # Предобработка изображения
        preprocessed_img = preprocess_image(image_path)
        if preprocessed_img is None:
            return {'error': 'Не удалось обработать изображение.'}

        # Обнаружение свечей и получение DataFrame
        candlestick_df, annotated_img = detect_candlesticks(preprocessed_img, cv2.imread(image_path))
        if candlestick_df.empty:
            return {'error': 'Не удалось извлечь данные свечей из графика.'}

        # Выполнение технического анализа
        analysis = perform_technical_analysis(candlestick_df)

        # Визуализация графика с индикаторами
        chart_filename = f"analysis_chart_{int(datetime.utcnow().timestamp())}.png"
        chart_path = os.path.join('static', 'images', chart_filename)
        os.makedirs(os.path.dirname(chart_path), exist_ok=True)
        mpf.plot(
            candlestick_df.set_index('date'),
            type='candle',
            style='charles',
            title='Анализированный график',
            mav=(20, 50),
            volume=False,
            savefig=chart_path
        )
        analysis_chart_url = url_for('static', filename=f'images/{chart_filename}', _external=True)

        return {
            'analysis': analysis,
            'chart_url': analysis_chart_url
        }
    except Exception as e:
        logger.error(f"Ошибка при анализе графика: {e}")
        logger.error(traceback.format_exc())
        return {'error': 'Произошла ошибка при анализе графика.'}

# Функция для анализа графика ассистентом
@app.route('/assistant/analyze_chart', methods=['POST'])
@csrf.exempt  # Исключаем из CSRF-защиты, так как используется AJAX
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
            # Ограничение размера файла
            MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ
            image.seek(0, os.SEEK_END)
            file_size = image.tell()
            image.seek(0)  # Сброс позиции чтения

            if file_size > MAX_IMAGE_SIZE:
                return jsonify({'error': 'Image size exceeds 5 MB limit.'}), 400

            # Сохранение изображения временно
            filename = secure_filename(image.filename)
            temp_dir = 'temp'
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, filename)
            image.save(temp_path)

            # Анализируем изображение
            analysis_result = analyze_chart(temp_path)

            if 'error' in analysis_result:
                # Удаляем временный файл
                os.remove(temp_path)
                return jsonify({'error': analysis_result['error']}), 400

            # Удаляем временный файл
            os.remove(temp_path)

            return jsonify({'result': analysis_result}), 200
        except Exception as e:
            logger.error(f"Ошибка при обработке изображения: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': 'Error processing the image.'}), 500
    else:
        return jsonify({'error': 'Invalid image'}), 400

# Маршрут для чата ассистента
@app.route('/assistant/chat', methods=['POST'])
@csrf.exempt  # Исключаем из CSRF-защиты
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

    # Инициализируем историю чата, если её ещё нет
    if 'chat_history' not in session:
        session['chat_history'] = []

        # Получаем данные пользователя из базы при первой инициализации
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

        # Формируем системное сообщение для OpenAI
        system_message = f"""
Ты — дядя Джон, крутой спец, который помогает пользователю анализировать его торговые сделки, предлагает конкретные решения с конкретными расчетами для торговых ситуаций пользователя, считает статистику по сделкам и находит закономерности.
Данные пользователя о сделках:
{trade_data}

Комментарии к сделкам:
{comments}

Предоставь подробный анализ и рекомендации на основе этих данных, если пользователь попросит.
"""

        logger.debug(f"System message for OpenAI: {system_message}")

        # Добавляем системное сообщение в историю
        session['chat_history'].append({'role': 'system', 'content': system_message})

    # Добавляем сообщение пользователя в историю
    session['chat_history'].append({'role': 'user', 'content': user_question})

    # Получаем ответ от OpenAI с учётом истории чата
    assistant_response = generate_openai_response(session['chat_history'])

    # Добавляем ответ ассистента в историю
    session['chat_history'].append({'role': 'assistant', 'content': assistant_response})

    # Ограничиваем длину истории чата
    MAX_CHAT_HISTORY = 20
    if len(session['chat_history']) > MAX_CHAT_HISTORY:
        session['chat_history'] = session['chat_history'][-MAX_CHAT_HISTORY:]

    return jsonify({'response': assistant_response}), 200

# Маршрут для получения истории чата
@app.route('/get_chat_history', methods=['GET'])
def get_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_history = session.get('chat_history', [])
    # Исключаем системное сообщение из истории для отображения
    display_history = [msg for msg in chat_history if msg['role'] != 'system']
    return jsonify({'chat_history': display_history}), 200

# Маршрут для очистки истории чата
@app.route('/clear_chat_history', methods=['POST'])
@csrf.exempt
def clear_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    session.pop('chat_history', None)
    return jsonify({'status': 'success'}), 200

# Остальные маршруты вашего приложения
# ...

# Маршруты аутентификации

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы успешно вышли из системы.', 'success')
    logger.info("Пользователь вышел из системы.")
    return redirect(url_for('login'))

# Маршрут здоровья для проверки состояния приложения
@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

# Маршрут Временный для Отладки
@app.route('/debug_session')
def debug_session():
    return jsonify(dict(session))

# Обработка initData через маршрут /init с использованием teleapp-auth
@csrf.exempt  # Исключаем из CSRF-защиты
@app.route('/init', methods=['POST'])
def init():
    if 'user_id' in session:
        logger.info(f"Пользователь ID {session['user_id']} уже авторизован.")
        return jsonify({'status': 'success'}), 200

    data = request.get_json()
    init_data = data.get('initData')
    logger.debug(f"Получен initData через AJAX: {init_data}")
    if init_data:
        try:
            # Верификация initData с использованием teleapp-auth
            webapp_data = parse_webapp_data(init_data)
            logger.debug(f"Parsed WebAppInitData: {webapp_data}")

            # Получаем секретный ключ из телеграм-бота
            secret_key = get_secret_key(app.config['TELEGRAM_BOT_TOKEN'])

            # Валидация данных
            is_valid = validate_webapp_data(webapp_data, secret_key)
            logger.debug(f"Validation result: {is_valid}")

            if not is_valid:
                logger.warning("Невалидные данные авторизации.")
                return jsonify({'status': 'failure', 'message': 'Invalid initData'}), 400

            # Извлечение данных пользователя из webapp_data
            telegram_id = int(webapp_data.user.id)
            first_name = webapp_data.user.first_name
            last_name = webapp_data.user.last_name or ''
            username = webapp_data.user.username or ''

            # Поиск или создание пользователя
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

            # Устанавливаем сессию пользователя
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

# Админские маршруты
@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle_premium', methods=['POST'])
@admin_required
def toggle_premium(user_id):
    user = User.query.get_or_404(user_id)
    user.assistant_premium = not user.assistant_premium
    db.session.commit()
    flash(f"Премиум статус пользователя {user.username} обновлён.", 'success')
    # Если изменяемый пользователь — текущий пользователь, обновляем сессию
    if user.id == session.get('user_id'):
        session['assistant_premium'] = user.assistant_premium
        flash('Ваш премиум статус обновлён.', 'success')
        
    return redirect(url_for('admin_users'))
    
# Главная страница — список сделок
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

    # Генерация S3 URL для скриншотов сделок
    for trade in trades:
        if trade.screenshot:
            trade.screenshot_url = generate_s3_url(trade.screenshot)
        else:
            trade.screenshot_url = None

    # Генерация S3 URL для скриншотов сетапов
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

# Страница авторизации
@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

# Маршрут для страницы "Политика конфиденциальности"
@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

# Маршрут для страницы "Доп. информация"
@app.route('/additional-info')
def additional_info():
    return render_template('additional_info.html')
    
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
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Инициализация form.criteria.data пустым списком, если оно None
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
            # Расчёт прибыли/убытка
            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            # Обработка критериев
            selected_criteria_ids = form.criteria.data
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
                # Убедитесь, что имя файла уникально
                unique_filename = f"trade_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    trade.screenshot = unique_filename  # Сохраняем имя файла для формирования URL
                else:
                    flash('Ошибка при загрузке скриншота.', 'danger')
                    logger.error("Не удалось загрузить скриншот в S3.")
                    return redirect(url_for('new_trade'))

            db.session.add(trade)
            db.session.commit()
            flash('Сделка успешно добавлена.', 'success')
            logger.info(f"Сделка ID {trade.id} добавлена пользователем ID {user_id}.")
            return redirect(url_for('index'))
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

# Редактировать сделку
@app.route('/edit_trade/<int:trade_id>', methods=['GET', 'POST'])
def edit_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для редактирования этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))

    # Генерация S3 URL для скриншота, если он есть
    if trade.screenshot:
        trade.screenshot_url = generate_s3_url(trade.screenshot)
    else:
        trade.screenshot_url = None

    form = TradeForm(obj=trade)
    # Заполнение списка сетапов
    setups = Setup.query.filter_by(user_id=user_id).all()
    form.setup_id.choices = [(0, 'Выберите сетап')] + [(setup.id, setup.setup_name) for setup in setups]
    # Заполнение списка инструментов
    instruments = Instrument.query.all()
    form.instrument.choices = [(instrument.id, instrument.name) for instrument in instruments]
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Установка выбранных критериев
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

            # Расчёт прибыли/убытка
            if trade.exit_price:
                trade.profit_loss = (trade.exit_price - trade.entry_price) * (1 if trade.direction == 'Buy' else -1)
                trade.profit_loss_percentage = (trade.profit_loss / trade.entry_price) * 100
            else:
                trade.profit_loss = None
                trade.profit_loss_percentage = None

            # Обработка критериев
            trade.criteria.clear()
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        trade.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            # Обработка удаления текущего изображения
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
                        return redirect(url_for('edit_trade', trade_id=trade_id))

            # Обработка загрузки нового изображения
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                # Если уже существует изображение и пользователь не решил удалить его, удалим старое
                if trade.screenshot:
                    delete_success = delete_file_from_s3(trade.screenshot)
                    if not delete_success:
                        flash('Ошибка при удалении старого изображения.', 'danger')
                        logger.error(f"Не удалось удалить старое изображение сделки ID {trade_id} из S3.")
                        return redirect(url_for('edit_trade', trade_id=trade_id))
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
                    return redirect(url_for('edit_trade', trade_id=trade_id))

            db.session.commit()
            flash('Сделка успешно обновлена.', 'success')
            logger.info(f"Сделка ID {trade.id} обновлена пользователем ID {user_id}.")
            return redirect(url_for('index'))
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

# Удалить сделку
@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
def delete_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для удаления этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))
    try:
        if trade.screenshot:
            # Удаление файла из S3
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
    return redirect(url_for('index'))

# Управление сетапами
@app.route('/manage_setups')
def manage_setups():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setups = Setup.query.filter_by(user_id=user_id).all()
    logger.info(f"Пользователь ID {user_id} просматривает свои сетапы.")

    # Генерация S3 URL для скриншотов сетапов
    for setup in setups:
        if setup.screenshot:
            setup.screenshot_url = generate_s3_url(setup.screenshot)
        else:
            setup.screenshot_url = None

    return render_template('manage_setups.html', setups=setups)

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
        try:
            setup = Setup(
                user_id=user_id,
                setup_name=form.setup_name.data,
                description=form.description.data
            )
            # Обработка критериев
            selected_criteria_ids = form.criteria.data
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
                # Убедитесь, что имя файла уникально
                unique_filename = f"setup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                upload_success = upload_file_to_s3(screenshot_file, unique_filename)
                if upload_success:
                    setup.screenshot = unique_filename
                else:
                    flash('Ошибка при загрузке скриншота.', 'danger')
                    logger.error("Не удалось загрузить скриншот в S3.")
                    return redirect(url_for('add_setup'))

            db.session.add(setup)
            db.session.commit()
            flash('Сетап успешно добавлен.', 'success')
            logger.info(f"Сетап ID {setup.id} добавлен пользователем ID {user_id}.")
            return redirect(url_for('manage_setups'))
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

# Редактировать сетап
@app.route('/edit_setup/<int:setup_id>', methods=['GET', 'POST'])
def edit_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для редактирования этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался редактировать сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))

    # Генерация S3 URL для скриншота, если он есть
    if setup.screenshot:
        setup.screenshot_url = generate_s3_url(setup.screenshot)
    else:
        setup.screenshot_url = None

    form = SetupForm(obj=setup)
    # Заполнение списка критериев
    form.criteria.choices = [(criterion.id, criterion.name) for criterion in Criterion.query.all()]

    # Установка выбранных критериев
    if request.method == 'GET':
        form.criteria.data = [criterion.id for criterion in setup.criteria]

    if form.validate_on_submit():
        try:
            setup.setup_name = form.setup_name.data
            setup.description = form.description.data

            # Обработка критериев
            setup.criteria.clear()
            selected_criteria_ids = form.criteria.data
            for criterion_id in selected_criteria_ids:
                try:
                    criterion = Criterion.query.get(int(criterion_id))
                    if criterion:
                        setup.criteria.append(criterion)
                except (ValueError, TypeError):
                    logger.error(f"Некорректный ID критерия: {criterion_id}")

            # Обработка удаления текущего изображения
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
                        return redirect(url_for('edit_setup', setup_id=setup_id))

            # Обработка загрузки нового изображения
            screenshot_file = form.screenshot.data
            if screenshot_file and isinstance(screenshot_file, FileStorage):
                # Если уже существует изображение и пользователь не решил удалить его, удалим старое
                if setup.screenshot:
                    delete_success = delete_file_from_s3(setup.screenshot)
                    if not delete_success:
                        flash('Ошибка при удалении старого изображения.', 'danger')
                        logger.error(f"Не удалось удалить старое изображение сетапа ID {setup_id} из S3.")
                        return redirect(url_for('edit_setup', setup_id=setup_id))
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
                    return redirect(url_for('edit_setup', setup_id=setup_id))

            db.session.commit()
            flash('Сетап успешно обновлён.', 'success')
            logger.info(f"Сетап ID {setup.id} обновлён пользователем ID {user_id}.")
            return redirect(url_for('manage_setups'))
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

# Удалить сетап
@app.route('/delete_setup/<int:setup_id>', methods=['POST'])
def delete_setup(setup_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    setup = Setup.query.get_or_404(setup_id)
    if setup.user_id != user_id:
        flash('У вас нет прав для удаления этого сетапа.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался удалить сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    try:
        if setup.screenshot:
            # Удаление файла из S3
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
    return redirect(url_for('manage_setups'))

# Просмотр сделки
@app.route('/view_trade/<int:trade_id>')
def view_trade(trade_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    trade = Trade.query.get_or_404(trade_id)
    if trade.user_id != user_id:
        flash('У вас нет прав для просмотра этой сделки.', 'danger')
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сделку ID {trade_id}, которая ему не принадлежит.")
        return redirect(url_for('index'))
    logger.info(f"Пользователь ID {user_id} просматривает сделку ID {trade_id}.")

    # Генерация S3 URL для скриншота, если он есть
    if trade.screenshot:
        trade.screenshot_url = generate_s3_url(trade.screenshot)
    else:
        trade.screenshot_url = None

    # Генерация S3 URL для скриншота сетапа, если он есть
    if trade.setup:
        if trade.setup.screenshot:
            trade.setup.screenshot_url = generate_s3_url(trade.setup.screenshot)
        else:
            trade.setup.screenshot_url = None

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
        logger.warning(f"Пользователь ID {user_id} попытался просмотреть сетап ID {setup_id}, который ему не принадлежит.")
        return redirect(url_for('manage_setups'))
    logger.info(f"Пользователь ID {user_id} просматривает сетап ID {setup_id}.")

    # Генерация S3 URL для скриншота, если он есть
    if setup.screenshot:
        setup.screenshot_url = generate_s3_url(setup.screenshot)
    else:
        setup.screenshot_url = None

    return render_template('view_setup.html', setup=setup)

# **Интеграция Telegram бота и обработчиков**

# Получение токена бота из переменных окружения
app.config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TOKEN = app.config['TELEGRAM_BOT_TOKEN']
if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не установлен в переменных окружения.")
    exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, workers=1, use_context=True)

# Обработчики команд

def start_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /start от пользователя {user.id} ({user.username})")
    try:
        # Поиск или создание пользователя в базе данных
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
                logger.info(f"Новый пользователь создан: Telegram ID {user.id}.")

        # Отправка сообщения с кнопкой Web App
        message_text = f"Привет, {user.first_name}! Нажмите кнопку ниже, чтобы открыть приложение."

        web_app_url = f"https://{get_app_host()}/webapp"  # Обновлённый URL Web App
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Открыть приложение",
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
        logger.info(f"Сообщение с Web App кнопкой отправлено пользователю {user.id} ({user.username}) на команду /start.")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /start: {e}")
        logger.error(traceback.format_exc())
        context.bot.send_message(chat_id=update.effective_chat.id, text="Произошла ошибка при обработке команды /start.")

def help_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /help от пользователя {user.id} ({user.username})")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом и открыть приложение\n"
        "/help - Получить справку\n"
        "/test - Тестовая команда для проверки работы бота\n"
    )
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text=help_text)
        logger.info(f"Ответ на /help отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /help: {e}")
        logger.error(traceback.format_exc())

def test_command(update, context):
    user = update.effective_user
    logger.info(f"Получена команда /test от пользователя {user.id} ({user.username})")
    try:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Команда /test работает корректно!')
        logger.info(f"Ответ на /test отправлен пользователю {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /test: {e}")
        logger.error(traceback.format_exc())

def button_click(update, context):
    query = update.callback_query
    query.answer()
    user = update.effective_user
    data = query.data
    logger.info(f"Получено нажатие кнопки '{data}' от пользователя {user.id} ({user.username})")

    try:
        query.edit_message_text(text="Используйте встроенную кнопку для взаимодействия с Web App.")
        logger.info(f"Обработано нажатие кнопки '{data}' от пользователя {user.id} ({user.username}).")
    except Exception as e:
        logger.error(f"Ошибка при обработке нажатия кнопки: {e}")
        logger.error(traceback.format_exc())

# Добавление обработчиков к диспетчеру
dispatcher.add_handler(CommandHandler('start', start_command))
dispatcher.add_handler(CommandHandler('help', help_command))
dispatcher.add_handler(CommandHandler('test', test_command))
dispatcher.add_handler(CallbackQueryHandler(button_click))

# Обработчик вебхуков
@csrf.exempt  # Исключаем из CSRF-защиты только этот маршрут
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            raw_data = request.get_data(as_text=True)
            logger.debug(f"Raw request data: {raw_data}")

            # Проверка, что данные присутствуют
            if not raw_data:
                logger.error("Empty request data received.")
                return 'Bad Request', 400

            update = Update.de_json(request.get_json(force=True), bot)
            dispatcher.process_update(update)
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
def set_webhook_route():
    webhook_url = f"https://{get_app_host()}/webhook"
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

# Отдельный маршрут для Web App
@app.route('/webapp', methods=['GET'])
def webapp():
    return render_template('webapp.html')

# **Интеграция Ассистента "Дядя Джон"**

# Маршрут для страницы ассистента
@app.route('/assistant', methods=['GET'])
def assistant_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для доступа к ассистенту.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user.assistant_premium:
        flash('Доступ к ассистенту доступен только по подписке.', 'danger')
        return redirect(url_for('index'))
    
    return render_template('assistant.html')

# **Интеграция Robokassa**

# Маршрут для страницы подписки
@app.route('/subscription', methods=['GET'])
def subscription_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для доступа к подписке.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if user.assistant_premium:
        flash('У вас уже активная подписка.', 'info')
        return redirect(url_for('index'))
    
    return render_template('subscription.html')

# Маршрут для покупки ассистента через Robokassa
@app.route('/buy_assistant', methods=['GET'])
def buy_assistant():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему для покупки подписки.', 'warning')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    amount = 1000  # Установите цену за подписку в рублях

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

# Маршрут для обработки результата платежа от Robokassa
@app.route('/robokassa/result', methods=['POST'])
def robokassa_result():
    data = request.form
    out_sum = data.get('OutSum')
    inv_id = data.get('InvoiceID')
    signature = data.get('SignatureValue')
    
    password1 = app.config['ROBOKASSA_PASSWORD1']
    
    correct_signature = hashlib.md5(f"{out_sum}:{inv_id}:{password1}".encode()).hexdigest()
    
    if signature.lower() == correct_signature.lower():
        # Разделяем inv_id на user_id и timestamp
        try:
            user_id_str, timestamp = inv_id.split('_')
            user_id = int(user_id_str)
            # Обновляем статус пользователя
            user = User.query.get(user_id)
            if user:
                user.assistant_premium = True  # Поле assistant_premium должно быть добавлено в модель User
                db.session.commit()
                logger.info(f"Пользователь ID {user_id} успешно оплатил подписку.")
                
                # Если оплаченный пользователь — текущий пользователь, обновляем сессию
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

# Маршрут для успешного завершения платежа
@app.route('/robokassa/success', methods=['GET'])
def robokassa_success():
    flash('Оплата успешно завершена. Спасибо за покупку!', 'success')
    return redirect(url_for('index'))

# Маршрут для неудачного завершения платежа
@app.route('/robokassa/fail', methods=['GET'])
def robokassa_fail():
    flash('Оплата не была завершена. Пожалуйста, попробуйте снова.', 'danger')
    return redirect(url_for('index'))

# **Запуск Flask-приложения**

if __name__ == '__main__':
    # Запуск приложения
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
