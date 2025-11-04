import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
import aiohttp
from motor.motor_asyncio import AsyncIOMotorDatabase
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mongo_init import get_db

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
log_handlers = [logging.StreamHandler()]

# Пытаемся добавить файловый обработчик
try:
    os.makedirs('/app/logs', exist_ok=True)
    log_handlers.append(logging.FileHandler('/app/logs/parser_worker.log', encoding='utf-8'))
except (PermissionError, OSError) as e:
    print(f"Warning: Cannot create log file: {e}. Using console output only.")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# URL API
API_URL = "https://plantsvsbrainrots.com/api/latest-message"
REQUEST_INTERVAL = 5  # секунды


class StockParser:
    def __init__(self):
        self.db: AsyncIOMotorDatabase = None
        self.collection = None
        self.subscriptions_collection = None
        self.session: aiohttp.ClientSession = None
        self.bot: Bot = None
        
        # Маппинг названий растений для поиска
        self.plant_mapping = {
            'sunflower': ['sunflower', '🌻'],
            'pumpkin': ['pumpkin', '🎃'],
            'dragon_fruit': ['dragon fruit', 'dragon', '🐉'],
            'eggplant': ['eggplant', '🍆'],
            'cactus': ['cactus', '🌵'],
            'strawberry': ['strawberry', '🍓'],
            'corn': ['corn', '🌽'],
            'tomato': ['tomato', '🍅'],
            'carrot': ['carrot', '🥕'],
            'pepper': ['pepper', '🌶️', '🌶'],
            "mango": ["mango", "🥭"],
            "starfruit": ["starfruit", "🌟"]
        }
        
    async def init(self):
        """Инициализация подключений"""
        self.db = get_db()
        self.collection = self.db.stock
        self.subscriptions_collection = self.db.plant_subscriptions
        self.session = aiohttp.ClientSession()
        
        # Инициализация телеграм бота для отправки уведомлений
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if bot_token:
            self.bot = Bot(token=bot_token)
            logger.info("Telegram bot initialized for notifications")
        else:
            logger.warning("TELEGRAM_BOT_TOKEN not set, notifications disabled")
            
        logger.info("Parser initialized successfully")
        
    async def close(self):
        """Закрытие подключений"""
        if self.session:
            await self.session.close()
            
    async def fetch_stocks(self) -> List[Dict[str, Any]]:
        """Получение данных с API"""
        try:
            async with self.session.get(API_URL, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Fetched {len(data)} stock updates")
                    return data
                else:
                    logger.error(f"API returned status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching stocks: {e}")
            return []
            
    async def process_stock(self, stock_data: Dict[str, Any], is_active: bool = False):
        """Обработка и сохранение одного стока"""
        stock_id = stock_data.get('id')
        if not stock_id:
            logger.warning("Stock without ID skipped")
            return
            
        # Проверяем существование стока
        existing_stock = await self.collection.find_one({'id': stock_id})
        if existing_stock:
            # Если сток уже существует, обновляем только флаг active если нужно
            if is_active and not existing_stock.get('active', False):
                await self.collection.update_one(
                    {'id': stock_id},
                    {'$set': {'active': True}}
                )
                logger.info(f"Updated stock {stock_id} as active")
            return
            
        # Подготавливаем данные для сохранения
        stock_document = {
            'id': stock_id,
            'content': stock_data.get('content', ''),
            'createdAt': stock_data.get('createdAt'),
            'embeds': stock_data.get('embeds', []),
            'active': is_active,
            'parsed_at': datetime.now(timezone.utc)
        }
        
        # Парсим поля из embeds для удобства
        plants_data = []
        
        if stock_document['embeds'] and len(stock_document['embeds']) > 0:
            embed = stock_document['embeds'][0]
            fields = embed.get('fields', [])
            
            # Извлекаем информацию о растениях и изменениях стока
            for field in fields:
                plant_info = {
                    'name': field.get('name', ''),
                    'value': field.get('value', '')
                }
                plants_data.append(plant_info)
            
            stock_document['timestamp'] = embed.get('timestamp')
            stock_document['title'] = embed.get('title')
        
        # Добавляем фиксированные растения - 4 кактуса и 3 клубники (всегда)
        plants_data.append({
            'name': '🌵 🌵 🌵 🌵 Cactus',
            'value': '+4 stock'
        })
        plants_data.append({
            'name': '🍓 🍓 🍓 Strawberry',
            'value': '+3 stock'
        })
        
        stock_document['plants_data'] = plants_data
        
        # Сохраняем в базу
        await self.collection.insert_one(stock_document)
        logger.info(f"Saved new stock {stock_id} (active={is_active})")
        
        # Если это новый активный сток и есть бот, отправляем уведомления
        if is_active and self.bot:
            await self.send_plant_notifications(stock_document)
    
    async def send_plant_notifications(self, stock: Dict[str, Any]):
        """Отправка уведомлений пользователям о растениях в стоке"""
        # Получаем все растения из стока
        plants_in_stock = self.extract_plants_from_stock(stock)
        
        if not plants_in_stock:
            logger.info("No plants found in stock for notifications")
            return
        
        logger.info(f"Plants in stock: {plants_in_stock}")
        
        # Получаем всех пользователей с подписками
        subscribers = await self.subscriptions_collection.find({'plants': {'$exists': True, '$ne': []}}).to_list(length=None)
        
        if not subscribers:
            logger.info("No subscribers found")
            return
        
        # Для каждого подписчика проверяем, есть ли его растения в стоке
        notifications_sent = 0
        for subscriber in subscribers:
            user_id = subscriber.get('user_id')
            subscribed_plants = subscriber.get('plants', [])
            
            if not user_id or not subscribed_plants:
                continue
            
            # Находим пересечение подписок и растений в стоке
            matched_plants = [plant for plant in subscribed_plants if plant in plants_in_stock]
            
            if matched_plants:
                # Формируем и отправляем уведомление
                message = self.format_plant_notification(stock, matched_plants, plants_in_stock)
                
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    notifications_sent += 1
                    logger.info(f"Sent notification to user {user_id} about plants: {matched_plants}")
                except TelegramError as e:
                    logger.error(f"Failed to send notification to user {user_id}: {e}")
                    
                    # Если пользователь заблокировал бота, удаляем его подписки
                    if "blocked" in str(e).lower() or "user not found" in str(e).lower():
                        await self.subscriptions_collection.delete_one({'user_id': user_id})
                        logger.info(f"Removed subscriptions for blocked user {user_id}")
        
        logger.info(f"Sent {notifications_sent} plant notifications")
    
    def extract_plants_from_stock(self, stock: Dict[str, Any]) -> List[str]:
        """Извлечь список растений из стока"""
        found_plants = set()
        
        # Проверяем plants_data
        plants_data = stock.get('plants_data', [])
        for plant_info in plants_data:
            plant_name = plant_info.get('name', '').lower()
            
            # Проверяем каждое известное растение
            for plant_id, keywords in self.plant_mapping.items():
                for keyword in keywords:
                    if keyword.lower() in plant_name:
                        found_plants.add(plant_id)
                        break
        
        return list(found_plants)
    
    def format_plant_notification(self, stock: Dict[str, Any], matched_plants: List[str], all_plants: List[str]) -> str:
        """Форматировать уведомление о растениях"""
        # Получаем информацию о растениях
        plant_emojis = {
            'sunflower': '🌻',
            'pumpkin': '🎃',
            'dragon_fruit': '🐉',
            'eggplant': '🍆',
            'cactus': '🌵',
            'strawberry': '🍓',
            'corn': '🌽',
            'tomato': '🍅',
            'carrot': '🥕',
            'pepper': '🌶️',
            'mango': '🥭'
        }
        
        message_parts = ["🎯 <b>ВАШИ РАСТЕНИЯ В СТОКЕ!</b>\n"]
        
        # Дата
        created_at = stock.get('createdAt', '')
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                formatted_date = dt.strftime('%d.%m.%Y %H:%M UTC')
                message_parts.append(f"📅 {formatted_date}\n")
            except:
                pass
        
        # Показываем растения, на которые подписан пользователь
        message_parts.append("<b>Ваши растения:</b>")
        for plant_id in matched_plants:
            emoji = plant_emojis.get(plant_id, '🌱')
            # Находим информацию о стоке для этого растения
            plants_data = stock.get('plants_data', [])
            for plant_info in plants_data:
                plant_name = plant_info.get('name', '').lower()
                if any(keyword.lower() in plant_name for keyword in self.plant_mapping.get(plant_id, [])):
                    value = plant_info.get('value', '')
                    message_parts.append(f"{emoji} {plant_info.get('name', '')}: <b>{value}</b>")
                    break
        
        message_parts.append("\n<b>Весь сток:</b>")
        # Показываем все растения в стоке
        plants_data = stock.get('plants_data', [])
        for plant_info in plants_data:
            name = plant_info.get('name', '')
            value = plant_info.get('value', '')
            message_parts.append(f"{name}: {value}")
        
        return "\n".join(message_parts)
            
    async def deactivate_old_stocks(self):
        """Деактивация всех старых активных стоков"""
        result = await self.collection.update_many(
            {'active': True},
            {'$set': {'active': False}}
        )
        if result.modified_count > 0:
            logger.info(f"Deactivated {result.modified_count} old active stocks")
            
    async def run_parser(self):
        """Основной цикл парсера"""
        while True:
            try:
                # Получаем данные с API
                stocks = await self.fetch_stocks()
                
                if stocks:
                    # Сначала деактивируем все старые активные стоки
                    await self.deactivate_old_stocks()
                    
                    # Обрабатываем стоки
                    for index, stock in enumerate(stocks):
                        # Первый элемент - текущий активный сток
                        is_active = (index == 0)
                        await self.process_stock(stock, is_active)
                        
                logger.info(f"Parser cycle completed. Next run in {REQUEST_INTERVAL} seconds")
                
            except Exception as e:
                logger.error(f"Error in parser cycle: {e}")
                
            # Ждем перед следующим запросом
            await asyncio.sleep(REQUEST_INTERVAL)
            
    async def create_indexes(self):
        """Создание индексов для оптимизации"""
        # Индекс по id для быстрого поиска
        await self.collection.create_index('id', unique=True)
        # Индекс по active для быстрого поиска активных стоков
        await self.collection.create_index('active')
        # Составной индекс для сортировки по дате создания
        await self.collection.create_index([('createdAt', -1)])
        
        # Индексы для коллекции подписок
        await self.subscriptions_collection.create_index('user_id', unique=True)
        await self.subscriptions_collection.create_index('plants')
        
        logger.info("Database indexes created")


async def main():
    """Главная функция"""
    parser = StockParser()
    
    try:
        # Инициализация
        await parser.init()
        
        # Создаем индексы
        await parser.create_indexes()
        
        # Запускаем парсер
        logger.info("Starting stock parser...")
        await parser.run_parser()
        
    except KeyboardInterrupt:
        logger.info("Parser stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await parser.close()


if __name__ == "__main__":
    asyncio.run(main())
