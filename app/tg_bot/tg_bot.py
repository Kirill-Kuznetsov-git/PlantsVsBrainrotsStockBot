import os
import asyncio
from datetime import datetime, timezone
import sys

# Добавляем путь к корневой директории проекта
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)


from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase as MotorDatabase

from mongo_init import get_db

load_dotenv()

# Настройки из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Настройки пагинации
STOCKS_PER_PAGE = 5


class StockBot:
    def __init__(self):
        self.db: MotorDatabase = get_db()
        self.stock_collection = self.db.stock
        
    def format_stock(self, stock: dict) -> str:
        """Форматирование одного стока для отображения"""
        message_parts = []
        
        # Заголовок с датой
        created_at = stock.get('createdAt', '')
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                formatted_date = dt.strftime('%d.%m.%Y %H:%M UTC')
                message_parts.append(f"📅 <b>{formatted_date}</b>")
            except:
                message_parts.append(f"📅 <b>{created_at}</b>")
        
        # Статус активности
        if stock.get('active'):
            message_parts.append("✅ <b>ТЕКУЩИЙ АКТИВНЫЙ СТОК</b>")
        
        # ID стока
        message_parts.append(f"🆔 ID: <code>{stock.get('id', 'N/A')}</code>")
        message_parts.append("")  # Пустая строка
        
        # Данные о растениях
        plants_data = stock.get('plants_data', [])
        if plants_data:
            message_parts.append("<b>📊 Изменения стока:</b>")
            for plant in plants_data:
                name = plant.get('name', '')
                value = plant.get('value', '')
                message_parts.append(f"{name}: <b>{value}</b>")
        else:
            # Пытаемся извлечь из embeds
            embeds = stock.get('embeds', [])
            if embeds and len(embeds) > 0:
                fields = embeds[0].get('fields', [])
                if fields:
                    message_parts.append("<b>📊 Изменения стока:</b>")
                    for field in fields:
                        name = field.get('name', '')
                        value = field.get('value', '')
                        message_parts.append(f"{name}: <b>{value}</b>")
        
        return "\n".join(message_parts)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        keyboard = [
            [KeyboardButton("📊 Текущий сток")],
            [KeyboardButton("📜 История стоков")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_message = (
            "🌱 <b>Добро пожаловать в Plants vs Brainrots Stock Bot!</b>\n\n"
            "Я помогу вам отслеживать изменения стоков.\n\n"
            "<b>Доступные команды:</b>\n"
            "• /current - Показать текущий активный сток\n"
            "• /history - История всех стоков\n\n"
            "Или используйте кнопки меню ниже 👇"
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    async def current_stock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать текущий активный сток"""
        # Находим активный сток
        current_stock = await self.stock_collection.find_one({'active': True})
        
        if current_stock:
            message = self.format_stock(current_stock)
            await update.message.reply_text(message, parse_mode='HTML')
        else:
            await update.message.reply_text(
                "❌ <b>Активный сток не найден</b>\n\n"
                "Возможно, парсер еще не начал работу или произошла ошибка.",
                parse_mode='HTML'
            )
    
    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать историю стоков с пагинацией"""
        await self.show_stocks_page(update, context, page=0)
    
    async def show_stocks_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        """Показать страницу со стоками"""
        # Считаем общее количество стоков
        total_stocks = await self.stock_collection.count_documents({})
        
        if total_stocks == 0:
            await update.message.reply_text(
                "📭 <b>История стоков пуста</b>\n\n"
                "Подождите, пока парсер соберет данные.",
                parse_mode='HTML'
            )
            return
        
        # Получаем стоки для текущей страницы
        skip = page * STOCKS_PER_PAGE
        stocks = await self.stock_collection.find({}).sort('createdAt', -1).skip(skip).limit(STOCKS_PER_PAGE).to_list(length=STOCKS_PER_PAGE)
        
        # Формируем сообщение
        message_parts = [f"📜 <b>История стоков (страница {page + 1})</b>\n"]
        
        for i, stock in enumerate(stocks, 1):
            message_parts.append(f"\n{'='*30}\n")
            message_parts.append(self.format_stock(stock))
        
        message = "\n".join(message_parts)
        
        # Создаем клавиатуру для навигации
        keyboard = []
        buttons = []
        
        # Кнопка "Назад"
        if page > 0:
            buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page-1}"))
        
        # Информация о странице
        total_pages = (total_stocks + STOCKS_PER_PAGE - 1) // STOCKS_PER_PAGE
        buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        
        # Кнопка "Вперед"
        if skip + STOCKS_PER_PAGE < total_stocks:
            buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"page_{page+1}"))
        
        if buttons:
            keyboard.append(buttons)
        
        # Кнопка обновления
        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{page}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        # Отправляем или редактируем сообщение
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message, 
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            await update.callback_query.answer()
        else:
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        data = query.data
        
        if data == "noop":
            await query.answer()
            return
        
        if data.startswith("page_"):
            page = int(data.split("_")[1])
            await self.show_stocks_page(update, context, page)
        elif data.startswith("refresh_"):
            page = int(data.split("_")[1])
            await self.show_stocks_page(update, context, page)
            await query.answer("✅ Обновлено!")
    
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений (кнопок меню)"""
        text = update.message.text
        
        if text == "📊 Текущий сток":
            await self.current_stock_command(update, context)
        elif text == "📜 История стоков":
            await self.history_command(update, context)
        else:
            await update.message.reply_text(
                "❓ Неизвестная команда. Используйте меню или команды:\n"
                "/current - текущий сток\n"
                "/history - история стоков"
            )


async def main():
    """Основная функция запуска бота"""
    # Проверяем токен
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не установлен в переменных окружения!")
        return
    
    # Создаем экземпляр бота
    bot = StockBot()
    
    # Создаем приложение
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("current", bot.current_stock_command))
    app.add_handler(CommandHandler("history", bot.history_command))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.text_handler))
    
    # Запускаем бота
    print("🤖 Бот запущен и готов к работе!")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())

