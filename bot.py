# bot.py

import os
import logging
import asyncio
import traceback

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app import app, db
from models import Trade, User

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /start от пользователя {user.id} ({user.username})")
    try:
        await update.message.reply_text('Привет! Я TradeJournalBot. Как я могу помочь вам сегодня?')
        logger.info(f"Ответ отправлен пользователю {user.id} ({user.username}) на команду /start")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /start: {e}")
        logger.error(traceback.format_exc())

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /help от пользователя {user.id} ({user.username})")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом\n"
        "/help - Получить справку\n"
        "/add_trade - Добавить новую сделку\n"
        "/view_trades - Просмотреть список сделок\n"
        "/register - Зарегистрироваться"
    )
    try:
        await update.message.reply_text(help_text)
        logger.info(f"Ответ на /help отправлен пользователю {user.id} ({user.username})")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на /help: {e}")
        logger.error(traceback.format_exc())

# Команда /add_trade
async def add_trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /add_trade от пользователя {user.id} ({user.username})")
    try:
        # Здесь можно реализовать логику добавления сделки через бота
        await update.message.reply_text('Функция добавления сделки пока не реализована.')
        logger.info(f"Ответ на /add_trade отправлен пользователю {user.id} ({user.username})")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /add_trade: {e}")
        logger.error(traceback.format_exc())

# Команда /view_trades
async def view_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Получена команда /view_trades от пользователя {user.id} ({user.username})")
    telegram_id = user.id
    with app.app_context():
        user_record = User.query.filter_by(telegram_id=telegram_id).first()
        if not user_record:
            try:
                await update.message.reply_text('Пользователь не найден. Пожалуйста, зарегистрируйтесь с помощью команды /register.')
                logger.info(f"Пользователь {user.id} ({user.username}) не зарегистрирован.")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения незарегистрированному пользователю: {e}")
                logger.error(traceback.format_exc())
            return
        user_id = user_record.id
        trades = Trade.query.filter_by(user_id=user_id).all()
        if not trades:
            try:
                await update.message.reply_text('У вас пока нет сделок.')
                logger.info(f"Пользователь {user.id} ({user.username}) не имеет сделок.")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения о пустом списке сделок: {e}")
                logger.error(traceback.format_exc())
            return
        message = "Ваши сделки:\n"
        for trade in trades:
            message += f"ID: {trade.id}, Инструмент: {trade.instrument.name}, Направление: {trade.direction}, Цена входа: {trade.entry_price}\n"
        try:
            await update.message.reply_text(message)
            logger.info(f"Список сделок отправлен пользователю {user.id} ({user.username})")
        except Exception as e:
            logger.error(f"Ошибка при отправке списка сделок: {e}")
            logger.error(traceback.format_exc())

# Команда /register
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    logger.info(f"Получена команда /register от пользователя {user.id} ({user.username})")
    with app.app_context():
        existing_user = User.query.filter_by(telegram_id=telegram_id).first()
        if existing_user:
            try:
                await update.message.reply_text('Вы уже зарегистрированы.')
                logger.info(f"Пользователь {user.id} ({user.username}) уже зарегистрирован.")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения о существующей регистрации: {e}")
                logger.error(traceback.format_exc())
            return
        new_user = User(telegram_id=telegram_id, username=user.username, first_name=user.first_name, last_name=user.last_name)
        db.session.add(new_user)
        try:
            db.session.commit()
            await update.message.reply_text('Регистрация прошла успешно.')
            logger.info(f"Пользователь {user.id} ({user.username}) зарегистрирован успешно.")
        except Exception as e:
            db.session.rollback()
            await update.message.reply_text('Произошла ошибка при регистрации.')
            logger.error(f"Ошибка при регистрации пользователя {user.id} ({user.username}): {e}")
            logger.error(traceback.format_exc())

# Основная функция для запуска бота
def main():
    TOKEN = os.environ.get('TELEGRAM_TOKEN')
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен в переменных окружения.")
        return

    # Создание приложения бота
    application = ApplicationBuilder().token(TOKEN).build()

    # Добавление обработчиков команд
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('add_trade', add_trade_command))
    application.add_handler(CommandHandler('view_trades', view_trades_command))
    application.add_handler(CommandHandler('register', register_command))

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
