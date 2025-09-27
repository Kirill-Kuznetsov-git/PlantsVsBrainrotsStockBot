import os

from motor.motor_asyncio import AsyncIOMotorClient as MotorClient
from motor.motor_asyncio import AsyncIOMotorDatabase as MotorDatabase

mongo_client: MotorClient | None = None
mongo_db: MotorDatabase | None = None


def get_client() -> MotorClient:
    global mongo_client, mongo_db
    if mongo_client is None:
        # Оптимизированный пул соединений для высокой нагрузки
        mongo_client = MotorClient(
            os.getenv('MONGO_DB_URL'),
            maxPoolSize=int(os.getenv('MONGO_MAX_POOL_SIZE', '1000')),  # Увеличено с 200
            minPoolSize=int(os.getenv('MONGO_MIN_POOL_SIZE', '50')),   # Увеличено с 10
            maxIdleTimeMS=60000,  # Увеличено до 60 сек для снижения overhead
            serverSelectionTimeoutMS=10000,  # Увеличено до 10 сек
            connectTimeoutMS=20000,  # Добавлен timeout подключения
            socketTimeoutMS=30000,   # Добавлен socket timeout
            waitQueueTimeoutMS=5000, # Timeout ожидания соединения из пула
            retryWrites=True,        # Автоматический retry записей
            readPreference="primary",
        )
    return mongo_client


def get_db() -> MotorDatabase:
    global mongo_client, mongo_db
    if mongo_client is None:
        mongo_client = MotorClient(
            os.getenv('MONGO_DB_URL'),
            maxPoolSize=int(os.getenv('MONGO_MAX_POOL_SIZE', '1000')),  # Увеличено с 200
            minPoolSize=int(os.getenv('MONGO_MIN_POOL_SIZE', '50')),   # Увеличено с 10
            maxIdleTimeMS=60000,  # Увеличено до 60 сек для снижения overhead
            serverSelectionTimeoutMS=10000,  # Увеличено до 10 сек
            retryWrites=True,        # Автоматический retry записей
            readPreference="primary",
        )
    if mongo_db is None:
        mongo_db = mongo_client.get_database(os.getenv('MONGO_DB_NAME'))
    return mongo_db
