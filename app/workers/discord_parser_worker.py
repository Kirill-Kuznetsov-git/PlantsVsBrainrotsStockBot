import discord
from discord.ext import commands
import asyncio
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorDatabase
import sys

# Добавляем путь к корневой директории
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_init import get_db

# Загружаем переменные окружения
load_dotenv()

# Настройки Discord
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '1421601402425311362'))

# Включаем intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB collections
db: AsyncIOMotorDatabase = None
stocks_collection = None

# Маппинг эмодзи к названиям
SEED_EMOJIS = {
    '🌻': 'Sunflower',
    '🎃': 'Pumpkin',
    '🐉': 'Dragon Fruit',
    '🍆': 'Eggplant',
    '🌵': 'Cactus',
    '🍓': 'Strawberry',
    '🌽': 'Corn',
    '🍅': 'Tomato',
    '🥕': 'Carrot',
    '🌶️': 'Pepper',
    '🌶': 'Pepper',
    '🍄': 'Mushroom',
    '🥔': 'Potato',
    '🧅': 'Onion',
    '🥒': 'Cucumber',
    '🥬': 'Lettuce',
    '🫑': 'Bell Pepper'
}

GEAR_KEYWORDS = ['gear', 'equipment', 'weapon', 'armor', 'tool', 'item']

def extract_timestamp_from_title(title):
    """Извлекает timestamp из заголовка вида 'Plants vs Brainrots Stock - <t:1759061404:t>'"""
    match = re.search(r'<t:(\d+):t>', title)
    if match:
        return int(match.group(1))
    return None

async def parse_stock_message(message):
    """Парсит сообщение со стоком"""
    stock_info = {
        'discord_message_id': str(message.id),
        'timestamp': message.created_at,
        'author': message.author.name,
        'channel': message.channel.name,
        'channel_id': str(message.channel.id),
        'seed_stocks': {},
        'gear_stocks': {},
        'other_items': [],
        'raw_data': [],
        'active': True  # Помечаем как активный сток
    }
    
    # Проверяем embeds
    for embed in message.embeds:
        # Проверяем заголовок
        if embed.title and "Plants vs Brainrots Stock" in embed.title:
            stock_info['title'] = embed.title
            
            # Извлекаем timestamp из заголовка
            game_timestamp = extract_timestamp_from_title(embed.title)
            if game_timestamp:
                stock_info['game_timestamp'] = game_timestamp
                stock_info['game_time'] = datetime.fromtimestamp(game_timestamp)
                stock_info['id'] = f"discord_{game_timestamp}"  # Уникальный ID
            else:
                stock_info['id'] = f"discord_{message.id}"
            
            # Сохраняем embed
            stock_info['embed'] = {
                'title': embed.title,
                'description': embed.description,
                'timestamp': embed.timestamp.isoformat() if embed.timestamp else None,
                'color': embed.color.value if embed.color else None
            }
            
            # Парсим поля
            plants_data = []  # Для совместимости с основным ботом
            
            for field in embed.fields:
                field_name = field.name.strip()
                field_value = field.value.strip()
                
                # Сохраняем сырые данные
                stock_info['raw_data'].append({
                    'name': field_name,
                    'value': field_value
                })
                
                # Определяем тип стока
                is_seed = False
                is_gear = False
                
                # Проверяем на seed по эмодзи
                for emoji, seed_name in SEED_EMOJIS.items():
                    if emoji in field_name:
                        is_seed = True
                        # Извлекаем количество
                        quantity_match = re.search(r'[+-]?\d+', field_value)
                        quantity = int(quantity_match.group()) if quantity_match else 0
                        
                        stock_info['seed_stocks'][seed_name] = {
                            'emoji': emoji,
                            'full_name': field_name,
                            'quantity': quantity,
                            'value': field_value
                        }
                        
                        # Добавляем в plants_data для совместимости
                        plants_data.append({
                            'name': field_name,
                            'value': field_value
                        })
                        break
                
                # Проверяем на gear
                if not is_seed:
                    for keyword in GEAR_KEYWORDS:
                        if keyword.lower() in field_name.lower() or keyword.lower() in field_value.lower():
                            is_gear = True
                            stock_info['gear_stocks'][field_name] = {
                                'name': field_name,
                                'value': field_value
                            }
                            break
                
                # Если не seed и не gear
                if not is_seed and not is_gear:
                    stock_info['other_items'].append({
                        'name': field_name,
                        'value': field_value
                    })
            
            # Добавляем фиксированные растения (кактусы и клубнику)
            plants_data.append({
                'name': '🌵 🌵 🌵 🌵 Cactus',
                'value': '+4 stock'
            })
            plants_data.append({
                'name': '🍓 🍓 🍓 Strawberry',
                'value': '+3 stock'
            })
            
            stock_info['plants_data'] = plants_data
            
            # Добавляем к seed_stocks для статистики
            stock_info['seed_stocks']['Cactus'] = {
                'emoji': '🌵',
                'full_name': '🌵 🌵 🌵 🌵 Cactus',
                'quantity': 4,
                'value': '+4 stock'
            }
            stock_info['seed_stocks']['Strawberry'] = {
                'emoji': '🍓',
                'full_name': '🍓 🍓 🍓 Strawberry',
                'quantity': 3,
                'value': '+3 stock'
            }
    
    return stock_info

@bot.event
async def on_ready():
    global db, stocks_collection
    
    print(f"✅ Бот {bot.user} онлайн!")
    print(f"📍 Мониторинг канала ID: {CHANNEL_ID}")
    
    # Подключаемся к MongoDB
    db = get_db()
    stocks_collection = db.stock
    
    # Создаем индексы
    await stocks_collection.create_index('discord_message_id', unique=True, sparse=True)
    await stocks_collection.create_index('game_timestamp', sparse=True)
    await stocks_collection.create_index('active')
    await stocks_collection.create_index([('timestamp', -1)])
    
    print("✅ MongoDB подключена")
    print("=" * 60)
    print("🔍 Ожидаю сообщения с 'Plants vs Brainrots Stock' в заголовке...")
    print("-" * 60)
    
    # Загружаем статистику
    total_stocks = await stocks_collection.count_documents({'source': 'discord'})
    print(f"📂 В базе {total_stocks} стоков из Discord")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Проверяем канал
    if message.channel.id != CHANNEL_ID:
        return
    
    # Проверяем наличие embeds с нужным заголовком
    has_stock_embed = False
    for embed in message.embeds:
        if embed.title and "Plants vs Brainrots Stock" in embed.title:
            has_stock_embed = True
            break
    
    if not has_stock_embed:
        return
    
    # Проверяем, не обработано ли уже это сообщение
    existing = await stocks_collection.find_one({'discord_message_id': str(message.id)})
    if existing:
        print(f"⏭️ Сообщение {message.id} уже обработано")
        return
    
    # Парсим сообщение
    print(f"\n🆕 Новое сообщение со стоком!")
    print("message", message, type(message))
    stock_info = await parse_stock_message(message)
    
    # Выводим информацию
    print(f"📅 Время: {stock_info['timestamp']}")
    print(f"👤 Автор: {stock_info['author']}")
    
    if 'game_timestamp' in stock_info:
        print(f"🎮 Игровое время: {stock_info['game_time']}")
        print(f"🆔 ID из заголовка: {stock_info['game_timestamp']}")
    
    # Seed стоки
    if stock_info['seed_stocks']:
        print(f"\n🌱 SEED СТОКИ ({len(stock_info['seed_stocks'])}):")
        for seed, data in stock_info['seed_stocks'].items():
            print(f"   {data['emoji']} {seed}: {data['value']}")
    
    # Gear стоки
    if stock_info['gear_stocks']:
        print(f"\n⚙️ GEAR СТОКИ ({len(stock_info['gear_stocks'])}):")
        for gear, data in stock_info['gear_stocks'].items():
            print(f"   • {data['name']}: {data['value']}")
    
    # Другие предметы
    if stock_info['other_items']:
        print(f"\n📦 ДРУГИЕ ПРЕДМЕТЫ ({len(stock_info['other_items'])}):")
        for item in stock_info['other_items']:
            print(f"   • {item['name']}: {item['value']}")
    
    # Деактивируем старые активные стоки
    await stocks_collection.update_many(
        {'active': True},
        {'$set': {'active': False}}
    )
    
    # Сохраняем в MongoDB
    try:
        result = await stocks_collection.insert_one(stock_info)
        print(f"\n💾 Сохранено в MongoDB с ID: {result.inserted_id}")
        
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
    
    print("-" * 60)
    
    # Обрабатываем команды
    await bot.process_commands(message)

# Запуск бота
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: DISCORD_BOT_TOKEN не установлен!")
    else:
        print("🚀 Запускаю Plants vs Brainrots Stock Monitor (MongoDB)...")
        bot.run(DISCORD_TOKEN)
