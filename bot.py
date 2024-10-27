# bot.py

import os
from telegram import Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')  # Убедитесь, что переменная окружения установлена

WEB_APP_URL = os.environ.get('WEB_APP_URL')  # URL вашего развернутого веб-приложения

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    keyboard = [
        [
            KeyboardButton(text="Открыть Журнал Сделок", web_app=WebAppInfo(url=WEB_APP_URL))
        ]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Добро пожаловать в Trend Share! Нажмите кнопку ниже, чтобы открыть журнал сделок.",
        reply_markup=reply_markup
    )

def main():
    """Запуск бота"""
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Добавляем обработчик команды /start
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
