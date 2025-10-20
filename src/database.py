import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import redis
import json
import os
from src.config import DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, REDIS_HOST, REDIS_PORT, REDIS_USER, REDIS_PASSWORD

# Подключение к Redis
def get_redis_connection():
    if REDIS_USER and REDIS_PASSWORD:
        redis_client = redis.Redis(
            host=REDIS_HOST, 
            port=REDIS_PORT, 
            username=REDIS_USER,
            password=REDIS_PASSWORD,
            db=0, 
            decode_responses=True
        )
    else:
        redis_client = redis.Redis(
            host=REDIS_HOST, 
            port=REDIS_PORT, 
            db=0, 
            decode_responses=True
        )
    return redis_client

# Подключение к PostgreSQL
def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    return conn

# Подключение к tinkoff_bd (для кэширования инструментов)
def get_tinkoff_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database='tinkoff_bd',
        user=DB_USER,
        password=DB_PASSWORD
    )
    return conn

# Создание базы данных, если она не существует
def create_database_if_not_exists():
    # Подключение к PostgreSQL без указания базы данных
    conn = psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database='postgres'  # Подключаемся к стандартной базе
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    # Проверка существования базы данных stream_grid_bot
    cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (DB_NAME,))
    exists = cur.fetchone()
    
    if not exists:
        # Создание базы данных stream_grid_bot
        cur.execute(f'CREATE DATABASE {DB_NAME}')
        print(f"База данных {DB_NAME} создана")
    else:
        print(f"База данных {DB_NAME} уже существует")
    
    # Проверка существования базы данных tinkoff_bd
    cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'tinkoff_bd'")
    exists = cur.fetchone()
    
    if not exists:
        # Создание базы данных tinkoff_bd
        cur.execute('CREATE DATABASE tinkoff_bd')
        print("База данных tinkoff_bd создана")
    else:
        print("База данных tinkoff_bd уже существует")
    
    cur.close()
    conn.close()

# Создание таблиц в базе данных
def create_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Создание таблицы share
    cur.execute('''
        CREATE TABLE IF NOT EXISTS share (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(50) NOT NULL UNIQUE,
            figi VARCHAR(50)
        )
    ''')
    
    # Создание таблицы price
    cur.execute('''
        CREATE TABLE IF NOT EXISTS price (
            id SERIAL PRIMARY KEY,
            share_id INTEGER NOT NULL,
            ticker VARCHAR(50) NOT NULL,
            price DECIMAL(20,10) NOT NULL
        )
    ''')
    
    # Создание таблицы order
    cur.execute('''
        CREATE TABLE IF NOT EXISTS "order" (
            id SERIAL PRIMARY KEY,
            share_id INTEGER NOT NULL,
            ticker VARCHAR(50) NOT NULL,
            order_id VARCHAR(64) UNIQUE,
            price DECIMAL(20,10) NOT NULL,
            direction INTEGER
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# Получение конфигурации из Redis или файла
def get_config():
    redis_client = get_redis_connection()
    
    # Попытка получить конфигурацию из Redis
    config_json = redis_client.get('bot_config')
    if config_json:
        return json.loads(config_json)
    
    # Если в Redis нет, читаем из файла
    config_file = "config.json"
    if os.path.isfile(config_file):
        with open(file=config_file) as config_file_handle:
            config = json.load(config_file_handle)
            # Сохраняем в Redis для следующего использования
            redis_client.set('bot_config', json.dumps(config))
            return config
    else:
        print("No " + config_file + " exists.")
        exit(0)

# Получение списка инструментов из кэша (tinkoff_bd) или API
def get_instruments_cache():
    redis_client = get_redis_connection()
    instruments_json = redis_client.get('instruments_cache')
    if instruments_json:
        return json.loads(instruments_json)
    return None

def set_instruments_cache(instruments):
    redis_client = get_redis_connection()
    redis_client.setex('instruments_cache', 3600, json.dumps(instruments))  # Кэш на 1 час

# Получение инструментов из tinkoff_bd
def get_instruments_from_tinkoff_db():
    try:
        conn = get_tinkoff_db_connection()
        cur = conn.cursor()
        
        # Получение инструментов из tinkoff_bd
        cur.execute("SELECT ticker, figi, min_price_increment FROM instruments")
        instruments = cur.fetchall()
        
        instruments_data = []
        for instrument in instruments:
            instruments_data.append({
                'ticker': instrument[0],
                'figi': instrument[1],
                'min_price_increment': float(instrument[2]) if instrument[2] else None
            })
        
        cur.close()
        conn.close()
        
        return instruments_data
    except Exception as e:
        print(f"Ошибка при получении инструментов из tinkoff_bd: {e}")
        return None