import os
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# Получение переменных окружения
TOKEN = os.getenv('TINKOFF_TOKEN')
ACCID = os.getenv('ACCOUNT_ID')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
REDIS_HOST = os.getenv('REDIS_HOST', DB_HOST)
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_USER = os.getenv('REDIS_USER', None)
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)