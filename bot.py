# bot.py

import os
import logging
from datetime import datetime
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app import app, db
from models import Trade, Instrument

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Я TradeJournalBot. Как я могу помочь вам сегодня?')

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Доступные команды:\n"
        "/start - Начать общение с ботом\n"
        "/help - Получить справку\n"
        "/add_trade - Добавить новую сделку\n"
        "/view_trades - Просмотреть список сделок"
    )
    await update.message.reply_text(help_text)

# Команда /add_trade
async def add_trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Здесь можно реализовать логику добавления сделки через бота
    await update.message.reply_text('Функция добавления сделки пока не реализована.')

# Команда /view_trades
async def view_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = 1  # Замените на реальный user_id после реализации аутентификации
    trades = Trade.query.filter_by(user_id=user_id).all()
    if not trades:
        await update.message.reply_text('У вас пока нет сделок.')
        return
    message = "Ваши сделки:\n"
    for trade in trades:
        message += f"ID: {trade.id}, Инструмент: {trade.instrument.name}, Направление: {trade.direction}, Цена входа: {trade.entry_price}\n"
    await update.message.reply_text(message)

# Основная функция для запуска бота
async def main():
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

    # Запуск бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.idle()

if __name__ == '__main__':
    # Создание контекста приложения Flask для доступа к базе данных
    with app.app_context():
        db.create_all()
    asyncio.run(main())
