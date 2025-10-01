import discord
from discord.ext import commands
import asyncio
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorDatabase
import sys
from telegram import Bot

# Добавляем путь к корневой директории
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_init import get_db

# Загружаем переменные окружения
load_dotenv()

# Настройки Discord
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '1421601402425311362'))

# Настройки Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
NOTIFICATION_CHANNEL_ID = os.getenv('NOTIFICATION_CHANNEL_ID')  # ID канала для уведомлений о редких предметах

# Включаем intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB collections
db: AsyncIOMotorDatabase = None

async def send_notifications(stock_data):
    """Отправляет уведомления подписчикам"""
    if not telegram_bot:
        return
    
    # Получаем подписчиков
    subscriptions = await db.plant_subscriptions.find({}).to_list(length=None)
    
    # Отладка - выводим что пришло в стоке
    print("\n=== НОВЫЙ СТОК ===")
    print("Семена:", stock_data.get('seeds_stock', {}))
    print("Снаряжение:", stock_data.get('gear_stock', {}))
    
    for subscription in subscriptions:
        user_id = subscription.get('user_id')
        subscribed_items = subscription.get('items', [])
        
        if not subscribed_items:
            continue
            
        print(f"\nПроверяем подписки пользователя {user_id}: {subscribed_items}")
        
        # Проверяем совпадения
        matched_items = []
        
        # Проверяем семена
        for seed_name, quantity in stock_data.get('seeds_stock', {}).items():
            # Нормализуем название для сравнения
            normalized = seed_name.lower().replace(' ', '_')
            seed_key = f"{normalized}_seed" if not normalized.endswith('_seed') else normalized
            
            # Проверяем различные варианты
            if (normalized in subscribed_items or 
                seed_key in subscribed_items or
                f"{normalized.replace('_', '')}_seed" in subscribed_items):
                matched_items.append(f"🌱 {seed_name}: {quantity}")
                print(f"  ✅ Найдено совпадение для семени: {seed_name} -> {seed_key}")
        
        # Проверяем снаряжение  
        for gear_name, quantity in stock_data.get('gear_stock', {}).items():
            normalized = gear_name.lower().replace(' ', '_')
            
            if normalized in subscribed_items:
                matched_items.append(f"⚔️ {gear_name}: {quantity}")
                print(f"  ✅ Найдено совпадение для снаряжения: {gear_name} -> {normalized}")
        
        if matched_items:
            print(f"  📨 Отправляем уведомление с {len(matched_items)} предметами")
            message = "🔔 <b>Автосток уведомление!</b>\n\n"
            message += "В новом стоке появились ваши предметы:\n\n"
            message += "\n".join(matched_items)
            message += "\n\n/current - посмотреть полный сток"
            
            try:
                await telegram_bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML'
                )
                print(f"  ✅ Уведомление отправлено")
            except Exception as e:
                print(f"  ❌ Ошибка отправки: {e}")

async def check_rare_items(stock_data):
    """Проверяет наличие редких предметов и отправляет в канал"""
    if not telegram_bot or not NOTIFICATION_CHANNEL_ID:
        return
    
    # Список редких предметов
    rare_seeds = [
        'grape_seed', 
        'cocotank_seed',
        'mr_carrot_seed',
        'tomatrio_seed',
        'carnivorous_plant_seed',
        "shroombino_seed"
    ]
    
    found_rare = []
    
    # Проверяем семена
    for seed_name, quantity in stock_data.get('seeds_stock', {}).items():
        # Нормализуем название для сравнения
        normalized = seed_name.lower().replace(' ', '_').strip()
        if not normalized.endswith('_seed'):
            normalized = f"{normalized}_seed"
        
        # Проверяем, является ли семя редким
        if normalized in rare_seeds:
            found_rare.append(f"💎 {seed_name}: {quantity}")
            print(f"  🎯 Найден редкий предмет: {seed_name}")
    
    # Если нашли редкие предметы, отправляем в канал
    if found_rare:
        print(f"\n🎉 Найдено {len(found_rare)} редких предметов!")
        
        message = "🚨 <b>РЕДКИЕ ПРЕДМЕТЫ В НОВОМ СТОКЕ!</b> 🚨\n\n"
        message += "\n".join(found_rare)
        
        # Добавляем московское время
        from datetime import timezone, timedelta
        moscow_tz = timezone(timedelta(hours=3))
        moscow_time = stock_data['created_at'].astimezone(moscow_tz)
        message += f"\n\n📅 Время: {moscow_time.strftime('%H:%M МСК')}"
        message += f"\n\n🎉 Наш бот с кастомными стоками: https://t.me//plantsvsbrainrot_stock_bot"
        
        try:
            await telegram_bot.send_message(
                chat_id=NOTIFICATION_CHANNEL_ID,
                text=message,
                parse_mode='HTML'
            )
            print("  ✅ Уведомление о редких предметах отправлено в канал")
        except Exception as e:
            print(f"  ❌ Ошибка отправки в канал: {e}")

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
        seed_name = seed.split(">")[1].split("**x")[0].strip().replace("*", "")
        seed_value = int(seed.split("**x")[1][0])
        seeds_stock[seed_name] = seed_value

    gear_stock_list = gear_stock.split("\n")
    gear_stock = {}
    for gear in gear_stock_list:
        gear_name = gear.split(">")[1].split("**x")[0].strip().replace("*", "")
        gear_value = int(gear.split("**x")[1][0])
        gear_stock[gear_name] = gear_value

    stock_data = {
        "created_at": message.created_at,
        "seeds_stock": seeds_stock,
        "gear_stock": gear_stock
    }

    await db.stocks.insert_one(stock_data)
    
    # Отправляем уведомления
    await send_notifications(stock_data)
    await check_rare_items(stock_data)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Ошибка: DISCORD_BOT_TOKEN не установлен!")
    else:
        print("🚀 Запускаю Plants vs Brainrots Stock Monitor (MongoDB)...")
        bot.run(DISCORD_TOKEN)
