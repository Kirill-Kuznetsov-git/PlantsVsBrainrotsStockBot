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

@bot.event
async def on_ready():
    global db
    
    print(f"✅ Бот {bot.user} онлайн!")
    print(f"📍 Мониторинг канала ID: {CHANNEL_ID}")
    
    # Подключаемся к MongoDB
    db = get_db()
    
    print("✅ MongoDB подключена")
    print("=" * 60)
    print("🔍 Ожидаю сообщения с 'Plants vs Brainrots Stock' в заголовке...")
    print("-" * 60)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Проверяем канал
    if message.channel.id != CHANNEL_ID:
        return
    
    if 'PVB Stock Alerts' not in message.author.name:
        return

    embed = message.embeds[0]
    seeds_stock = embed.fields[0].value
    gear_stock = embed.fields[1].value

    seeds_stock_list = seeds_stock.split("\n")
    seeds_stock = {}
    for seed in seeds_stock_list:
        seed_name = seed.split(">")[1].split("*")[0].strip().lower().replace(" ", "_")
        seed_value = int(seed.split("**x")[1][0])
        seeds_stock[seed_name] = seed_value

    gear_stock_list = gear_stock.split("\n")
    gear_stock = {}
    for gear in gear_stock_list:
        gear_name = gear.split(">")[1].split("*")[0].strip().lower().replace(" ", "_")
        gear_value = int(gear.split("**x")[1][0])
        gear_stock[gear_name] = gear_value

    await db.stocks.insert_one({
        "created_at": message.created_at,
        "seeds_stock": seeds_stock,
        "gear_stock": gear_stock
    })

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: DISCORD_BOT_TOKEN не установлен!")
    else:
        print("🚀 Запускаю Plants vs Brainrots Stock Monitor (MongoDB)...")
        bot.run(DISCORD_TOKEN)
