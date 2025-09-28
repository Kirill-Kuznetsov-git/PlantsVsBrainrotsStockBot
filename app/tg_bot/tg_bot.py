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
STOCKS_PER_PAGE = 6  # Текущий + 5 предыдущих


class StockBot:
    def __init__(self):
        self.db: MotorDatabase = get_db()
        self.stock_collection = self.db.stocks
        self.subscriptions_collection = self.db.plant_subscriptions
        
        # Список доступных предметов для подписки
        # Теперь включаем и seeds и gear
        self.available_items = {
            # Seeds
            'sunflower': {'emoji': '🌻', 'name': 'Sunflower', 'type': 'seed'},
            'pumpkin': {'emoji': '🎃', 'name': 'Pumpkin', 'type': 'seed'},
            'dragon_fruit': {'emoji': '🐉', 'name': 'Dragon Fruit', 'type': 'seed'},
            'eggplant': {'emoji': '🍆', 'name': 'Eggplant', 'type': 'seed'},
            'cactus': {'emoji': '🌵', 'name': 'Cactus', 'type': 'seed'},
            'strawberry': {'emoji': '🍓', 'name': 'Strawberry', 'type': 'seed'},
            'corn': {'emoji': '🌽', 'name': 'Corn', 'type': 'seed'},
            'tomato': {'emoji': '🍅', 'name': 'Tomato', 'type': 'seed'},
            'carrot': {'emoji': '🥕', 'name': 'Carrot', 'type': 'seed'},
            'pepper': {'emoji': '🌶️', 'name': 'Pepper', 'type': 'seed'},
            # Gear
            'common_chest': {'emoji': '📦', 'name': 'Common Chest', 'type': 'gear'},
            'rare_chest': {'emoji': '💎', 'name': 'Rare Chest', 'type': 'gear'},
            'legendary_chest': {'emoji': '👑', 'name': 'Legendary Chest', 'type': 'gear'},
            'fertilizer': {'emoji': '💩', 'name': 'Fertilizer', 'type': 'gear'},
            'water_can': {'emoji': '💧', 'name': 'Water Can', 'type': 'gear'},
            'shovel': {'emoji': '🔧', 'name': 'Shovel', 'type': 'gear'}
        }
        
    def format_stock(self, stock: dict, is_current: bool = False) -> str:
        """Форматирование одного стока для отображения"""
        message_parts = []
        
        # Заголовок с датой
        created_at = stock.get('created_at')
        if created_at:
            try:
                # Если это уже datetime объект
                if isinstance(created_at, datetime):
                    dt = created_at
                else:
                    # Если это строка
                    dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                formatted_date = dt.strftime('%d.%m.%Y %H:%M UTC')
                message_parts.append(f"📅 <b>{formatted_date}</b>")
            except:
                message_parts.append(f"📅 <b>{created_at}</b>")
        
        # Статус
        if is_current:
            message_parts.append("✅ <b>ТЕКУЩИЙ СТОК</b>")
        
        message_parts.append("")  # Пустая строка
        
        # Семена
        seeds_stock = stock.get('seeds_stock', {})
        if seeds_stock:
            message_parts.append("<b>🌱 Семена:</b>")
            for seed_name, quantity in seeds_stock.items():
                # Находим эмодзи для семени
                emoji = ''
                for item_id, item_info in self.available_items.items():
                    if item_info['name'].lower() == seed_name.lower() and item_info['type'] == 'seed':
                        emoji = item_info['emoji'] + ' '
                        break
                message_parts.append(f"{emoji}{seed_name}: <b>{quantity}</b>")
        
        # Снаряжение
        gear_stock = stock.get('gear_stock', {})
        if gear_stock:
            message_parts.append("\n<b>⚔️ Снаряжение:</b>")
            for gear_name, quantity in gear_stock.items():
                # Находим эмодзи для снаряжения
                emoji = ''
                for item_id, item_info in self.available_items.items():
                    if item_info['name'].lower() == gear_name.lower() and item_info['type'] == 'gear':
                        emoji = item_info['emoji'] + ' '
                        break
                message_parts.append(f"{emoji}{gear_name}: <b>{quantity}</b>")
        
        return "\n".join(message_parts)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        keyboard = [
            [KeyboardButton("📊 Текущий сток")],
            [KeyboardButton("📜 История стоков")],
            [KeyboardButton("🔔 Автосток")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_message = (
            "🌱 <b>Добро пожаловать в Plants vs Brainrots Stock Bot!</b>\n\n"
            "Я помогу вам отслеживать изменения стоков.\n\n"
            "<b>Доступные команды:</b>\n"
            "• /current - Показать текущий сток\n"
            "• /history - История стоков\n"
            "• /autostock - Управление подписками\n\n"
            "Или используйте кнопки меню ниже 👇"
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    async def current_stock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать текущий сток (самый последний по created_at)"""
        # Находим сток с самым поздним created_at
        current_stock = await self.stock_collection.find_one(
            {},
            sort=[('created_at', -1)]
        )
        
        if current_stock:
            message = self.format_stock(current_stock, is_current=True)
            await update.message.reply_text(message, parse_mode='HTML')
        else:
            await update.message.reply_text(
                "❌ <b>Стоки не найдены</b>\n\n"
                "Возможно, парсер еще не начал работу или произошла ошибка.",
                parse_mode='HTML'
            )
    
    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать историю стоков (текущий + 5 предыдущих)"""
        # Получаем 6 последних стоков
        stocks = await self.stock_collection.find({}).sort('created_at', -1).limit(STOCKS_PER_PAGE).to_list(length=STOCKS_PER_PAGE)
        
        if not stocks:
            await update.message.reply_text(
                "📭 <b>История стоков пуста</b>\n\n"
                "Подождите, пока парсер соберет данные.",
                parse_mode='HTML'
            )
            return
        
        # Формируем сообщение
        message_parts = ["📜 <b>История стоков</b>\n"]
        
        for i, stock in enumerate(stocks):
            message_parts.append(f"\n{'='*30}\n")
            # Первый сток - текущий
            message_parts.append(self.format_stock(stock, is_current=(i == 0)))
        
        message = "\n".join(message_parts)
        
        await update.message.reply_text(
            message,
            parse_mode='HTML'
        )
    
    async def autostock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для управления автостоком"""
        await self.show_autostock_menu(update, context, from_command=True)
    
    async def show_autostock_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, from_command: bool = False):
        """Показать меню управления подписками на предметы"""
        user_id = update.effective_user.id
        
        # Получаем текущие подписки пользователя
        user_sub = await self.subscriptions_collection.find_one({'user_id': user_id})
        subscribed_items = user_sub.get('items', []) if user_sub else []
        
        # Создаем клавиатуру с предметами
        keyboard = []
        
        # Сначала семена
        keyboard.append([InlineKeyboardButton("🌱 СЕМЕНА", callback_data="noop")])
        row = []
        for item_id, item_info in self.available_items.items():
            if item_info['type'] == 'seed':
                is_subscribed = item_id in subscribed_items
                button_text = f"{'✅' if is_subscribed else '❌'} {item_info['emoji']} {item_info['name']}"
                callback_data = f"toggle_item_{item_id}"
                
                row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
        
        if row:
            keyboard.append(row)
        
        # Затем снаряжение
        keyboard.append([InlineKeyboardButton("⚔️ СНАРЯЖЕНИЕ", callback_data="noop")])
        row = []
        for item_id, item_info in self.available_items.items():
            if item_info['type'] == 'gear':
                is_subscribed = item_id in subscribed_items
                button_text = f"{'✅' if is_subscribed else '❌'} {item_info['emoji']} {item_info['name']}"
                callback_data = f"toggle_item_{item_id}"
                
                row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
        
        if row:
            keyboard.append(row)
        
        # Кнопка очистки всех подписок
        if subscribed_items:
            keyboard.append([InlineKeyboardButton("🗑️ Отписаться от всех", callback_data="clear_subscriptions")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем сообщение
        message = "🔔 <b>Управление автостоком</b>\n\n"
        
        if subscribed_items:
            message += f"Вы подписаны на {len(subscribed_items)} предметов.\n"
            message += "Вы получите уведомление, когда они появятся в стоке.\n\n"
        else:
            message += "Вы не подписаны ни на один предмет.\n\n"
        
        message += "Нажмите на предмет, чтобы подписаться или отписаться:"
        
        # Отправляем или редактируем сообщение
        if from_command:
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.callback_query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
            await update.callback_query.answer()
    
    async def toggle_item_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
        """Переключить подписку на предмет"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # Проверяем, что предмет существует
        if item_id not in self.available_items:
            await update.callback_query.answer("❌ Неизвестный предмет")
            return
        
        # Получаем текущие подписки
        user_sub = await self.subscriptions_collection.find_one({'user_id': user_id})
        subscribed_items = user_sub.get('items', []) if user_sub else []
        
        # Переключаем подписку
        item_info = self.available_items[item_id]
        if item_id in subscribed_items:
            subscribed_items.remove(item_id)
            await update.callback_query.answer(f"❌ Отписались от {item_info['emoji']} {item_info['name']}")
        else:
            subscribed_items.append(item_id)
            await update.callback_query.answer(f"✅ Подписались на {item_info['emoji']} {item_info['name']}")
        
        # Сохраняем в базу
        await self.subscriptions_collection.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'user_id': user_id,
                    'username': username,
                    'items': subscribed_items,
                    'updated_at': datetime.utcnow()
                }
            },
            upsert=True
        )
        
        # Обновляем меню
        await self.show_autostock_menu(update, context)
    
    async def clear_all_subscriptions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Очистить все подписки"""
        user_id = update.effective_user.id
        
        # Удаляем подписки
        await self.subscriptions_collection.delete_one({'user_id': user_id})
        
        await update.callback_query.answer("🗑️ Все подписки удалены")
        
        # Обновляем меню
        await self.show_autostock_menu(update, context)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        data = query.data
        
        if data == "noop":
            await query.answer()
            return
        
        if data.startswith("toggle_item_"):
            item_id = data.replace("toggle_item_", "")
            await self.toggle_item_subscription(update, context, item_id)
        elif data == "clear_subscriptions":
            await self.clear_all_subscriptions(update, context)
    
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений (кнопок меню)"""
        text = update.message.text
        
        if text == "📊 Текущий сток":
            await self.current_stock_command(update, context)
        elif text == "📜 История стоков":
            await self.history_command(update, context)
        elif text == "🔔 Автосток":
            await self.autostock_command(update, context)
        else:
            await update.message.reply_text(
                "❓ Неизвестная команда. Используйте меню или команды:\n"
                "/current - текущий сток\n"
                "/history - история стоков\n"
                "/autostock - управление автостоком"
            )


def main():
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
    app.add_handler(CommandHandler("autostock", bot.autostock_command))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.text_handler))
    
    # Запускаем бота
    print("🤖 Бот запущен и готов к работе!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

