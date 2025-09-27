import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
import aiohttp
from motor.motor_asyncio import AsyncIOMotorDatabase
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mongo_init import get_db

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
        self.session: aiohttp.ClientSession = None
        
    async def init(self):
        """Инициализация подключений"""
        self.db = get_db()
        self.collection = self.db.stock
        self.session = aiohttp.ClientSession()
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
        if stock_document['embeds'] and len(stock_document['embeds']) > 0:
            embed = stock_document['embeds'][0]
            fields = embed.get('fields', [])
            
            # Извлекаем информацию о растениях и изменениях стока
            plants_data = []
            for field in fields:
                plant_info = {
                    'name': field.get('name', ''),
                    'value': field.get('value', '')
                }
                plants_data.append(plant_info)
            
            stock_document['plants_data'] = plants_data
            stock_document['timestamp'] = embed.get('timestamp')
            stock_document['title'] = embed.get('title')
        
        # Сохраняем в базу
        await self.collection.insert_one(stock_document)
        logger.info(f"Saved new stock {stock_id} (active={is_active})")
        
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
