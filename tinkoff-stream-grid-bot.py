#!/usr/bin/env python3
"""
Торговый бот для Тинькофф Инвестиции - Grid Trading стратегия
Асинхронная версия с использованием библиотеки t-tech-investments
"""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any

import aiosqlite
from dotenv import load_dotenv
from tinkoff.invest import (
    Client,
    OrderType,
    OrderDirection,
    Quotation,
    OrderExecutionReportStatus,
    RequestError,
)
from tinkoff.invest.schemas import OrderState

# Загружаем переменные окружения из файла .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),  # Логи в файл
        logging.StreamHandler()  # Логи в консоль
    ]
)
logger = logging.getLogger(__name__)


class GridBotConfig:
    """Класс конфигурации для сеточного бота"""
    
    def __init__(self):
        # Получаем основные настройки из переменных окружения
        self.token = self._get_env('TINKOFF_TOKEN')  # API токен Тинькофф
        self.account_id = self._get_env('TINKOFF_ACCOUNT_ID', required=False)  # ID счета (опционально)
        self.db_path = self._get_env('DATABASE_PATH', 'sqlite_bot.db')  # Путь к файлу БД
        self.order_check_interval = int(self._get_env('ORDER_CHECK_INTERVAL', '60'))  # Интервал проверки ордеров (сек)
        
        # Настройки сетки по умолчанию
        self.default_grid_levels = int(self._get_env('GRID_LEVELS', '6'))  # Количество уровней сетки
        self.default_price_step = float(self._get_env('PRICE_STEP', '0.01'))  # Шаг цены (1%)
        self.default_quantity = int(self._get_env('QUANTITY', '1'))  # Количество лотов
        
        # Конфигурация торгуемых инструментов
        # Здесь можно добавить любые акции из Тинькофф Инвестиций
        self.shares_config = {
            "UWGN": {  # Тикер акции
                "levels": 6,  # Количество уровней сетки (переопределяет default)
                "price_step": 0.01,  # Шаг цены (1%)
                "quantity": 1,  # Количество лотов
                "start_price": 0,  # Начальная цена (0 - использовать текущую)
            },
            # Раскомментируйте для добавления других инструментов
            # "SBER": {
            #     "levels": 6,
            #     "price_step": 0.03,
            #     "quantity": 1,
            #     "start_price": 0,
            # },
            # "T": {  # Акции Т-Телеком
            #     "levels": 4,
            #     "price_step": 0.02,
            #     "quantity": 10,
            #     "start_price": 0,
            # },
        }
    
    def _get_env(self, key: str, required: bool = True, default: str = None) -> str:
        """Безопасное получение переменной окружения"""
        value = os.getenv(key)
        
        if required and not value:
            raise ValueError(f"Переменная окружения {key} обязательна для заполнения")
        return value or default


class DatabaseManager:
    """Асинхронный менеджер базы данных SQLite"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None
    
    async def __aenter__(self):
        """Контекстный менеджер для входа"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер для выхода"""
        await self.disconnect()
    
    async def connect(self):
        """Подключение к базе данных"""
        self.connection = await aiosqlite.connect(self.db_path)
        await self.connection.execute("PRAGMA foreign_keys = ON")  # Включаем поддержку внешних ключей
        await self._init_tables()  # Создаем таблицы, если их нет
    
    async def disconnect(self):
        """Отключение от базы данных"""
        if self.connection:
            await self.connection.close()
    
    async def _init_tables(self):
        """Инициализация структуры таблиц в БД"""
        
        # Таблица с информацией об акциях
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS share (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker VARCHAR(50) NOT NULL UNIQUE,      -- Тикер акции (например, UWGN)
                figi VARCHAR(50),                         -- FIGI идентификатор инструмента
                levels INTEGER,                           -- Количество уровней сетки
                price_step DECIMAL(20,10),               -- Шаг цены в процентах
                quantity INTEGER                          -- Количество лотов в ордере
            )
        """)
        
        # Таблица с ценовыми уровнями сетки
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS price (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                share_id INTEGER NOT NULL,                -- ID акции из таблицы share
                ticker VARCHAR(50) NOT NULL,              -- Тикер акции
                price DECIMAL(20,10) NOT NULL,           -- Цена уровня
                FOREIGN KEY (share_id) REFERENCES share(id)
            )
        """)
        
        # Таблица с активными ордерами
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS order_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                share_id INTEGER NOT NULL,                -- ID акции
                ticker VARCHAR(50) NOT NULL,              -- Тикер акции
                order_id VARCHAR(64) UNIQUE,             -- ID ордера в Тинькофф
                price DECIMAL(20,10) NOT NULL,           -- Цена ордера
                direction INTEGER,                        -- Направление (1 - покупка, 2 - продажа)
                status VARCHAR(20),                      -- Статус ордера (ACTIVE, FILLED, CANCELLED)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Время создания
                FOREIGN KEY (share_id) REFERENCES share(id)
            )
        """)
        
        await self.connection.commit()
        logger.info("База данных инициализирована")
    
    async def insert_share(self, ticker: str, figi: str, levels: int, price_step: float, quantity: int) -> int:
        """
        Добавление или получение информации об акции
        
        Args:
            ticker: Тикер акции
            figi: FIGI идентификатор
            levels: Количество уровней сетки
            price_step: Шаг цены
            quantity: Количество лотов
        
        Returns:
            ID записи в таблице share
        """
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO share (ticker, figi, levels, price_step, quantity) VALUES (?, ?, ?, ?, ?)",
            (ticker, figi, levels, price_step, quantity)
        )
        await self.connection.commit()
        
        # Если запись только что создана, возвращаем её ID
        if cursor.lastrowid:
            return cursor.lastrowid
        
        # Иначе получаем существующий ID
        cursor = await self.connection.execute(
            "SELECT id FROM share WHERE ticker = ?",
            (ticker,)
        )
        result = await cursor.fetchone()
        return result[0] if result else 0
    
    async def insert_prices(self, share_id: int, ticker: str, prices: List[float]):
        """
        Сохранение ценовых уровней сетки в БД
        
        Args:
            share_id: ID акции
            ticker: Тикер акции
            prices: Список ценовых уровней
        """
        # Сначала удаляем старые уровни
        await self.connection.execute("DELETE FROM price WHERE share_id = ?", (share_id,))
        
        # Добавляем новые уровни
        for price in prices:
            await self.connection.execute(
                "INSERT INTO price (share_id, ticker, price) VALUES (?, ?, ?)",
                (share_id, ticker, price)
            )
        await self.connection.commit()
        logger.info(f"Сохранено {len(prices)} ценовых уровней для {ticker}")
    
    async def get_prices(self, share_id: int) -> List[float]:
        """
        Получение ценовых уровней из БД
        
        Args:
            share_id: ID акции
        
        Returns:
            Список цен, отсортированный по возрастанию
        """
        cursor = await self.connection.execute(
            "SELECT price FROM price WHERE share_id = ? ORDER BY price",
            (share_id,)
        )
        results = await cursor.fetchall()
        return [row[0] for row in results]
    
    async def insert_order(self, share_id: int, ticker: str, order_id: str, price: float, direction: int):
        """
        Сохранение информации о выставленном ордере
        
        Args:
            share_id: ID акции
            ticker: Тикер акции
            order_id: ID ордера в Тинькофф
            price: Цена ордера
            direction: Направление (1 - покупка, 2 - продажа)
        """
        await self.connection.execute(
            "INSERT INTO order_table (share_id, ticker, order_id, price, direction, status) VALUES (?, ?, ?, ?, ?, ?)",
            (share_id, ticker, order_id, price, direction, 'ACTIVE')
        )
        await self.connection.commit()
    
    async def update_order(self, order_id: str, new_order_id: str = None, price: float = None, 
                          direction: int = None, status: str = None):
        """
        Обновление информации об ордере
        
        Args:
            order_id: Старый ID ордера
            new_order_id: Новый ID ордера (при перевыставлении)
            price: Новая цена
            direction: Новое направление
            status: Новый статус
        """
        updates = []
        params = []
        
        if new_order_id:
            updates.append("order_id = ?")
            params.append(new_order_id)
        if price is not None:
            updates.append("price = ?")
            params.append(price)
        if direction is not None:
            updates.append("direction = ?")
            params.append(direction)
        if status:
            updates.append("status = ?")
            params.append(status)
        
        if updates:
            params.append(order_id)
            await self.connection.execute(
                f"UPDATE order_table SET {', '.join(updates)} WHERE order_id = ?",
                params
            )
            await self.connection.commit()
    
    async def get_order(self, order_id: str) -> Optional[tuple]:
        """
        Получение информации об ордере по его ID
        
        Args:
            order_id: ID ордера
        
        Returns:
            Кортеж (id, share_id, price) или None
        """
        cursor = await self.connection.execute(
            "SELECT id, share_id, price FROM order_table WHERE order_id = ?",
            (order_id,)
        )
        return await cursor.fetchone()
    
    async def delete_order(self, order_id: int):
        """Удаление ордера из БД"""
        await self.connection.execute("DELETE FROM order_table WHERE id = ?", (order_id,))
        await self.connection.commit()
    
    async def get_active_orders_count(self, share_id: int) -> int:
        """
        Получение количества активных ордеров для акции
        
        Args:
            share_id: ID акции
        
        Returns:
            Количество активных ордеров
        """
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM order_table WHERE share_id = ? AND status = 'ACTIVE'",
            (share_id,)
        )
        result = await cursor.fetchone()
        return result[0] if result else 0


class GridTradingBot:
    """Основной класс сеточного торгового бота"""
    
    def __init__(self, config: GridBotConfig, db: DatabaseManager):
        self.config = config  # Конфигурация бота
        self.db = db  # Менеджер базы данных
        self.client = None  # Клиент API Тинькофф
        self.is_running = False  # Флаг работы бота
        self.shares_info: Dict[str, Dict[str, Any]] = {}  # Информация по всем акциям
    
    def _quotation_to_float(self, quotation: Quotation) -> float:
        """
        Конвертация Quotation в float
        
        Args:
            quotation: Объект Quotation из API Тинькофф
        
        Returns:
            Число с плавающей точкой
        """
        return float(quotation.units) + float(quotation.nano) / 1e9
    
    def _float_to_quotation(self, value: float) -> Quotation:
        """
        Конвертация float в Quotation
        
        Args:
            value: Число с плавающей точкой
        
        Returns:
            Объект Quotation для API Тинькофф
        """
        units = int(value)
        nano = int((value - units) * 1e9)
        return Quotation(units=units, nano=nano)
    
    async def init_shares(self):
        """Инициализация информации по торгуемым акциям"""
        async with Client(self.config.token) as client:
            # Получаем список всех акций от API
            response = await client.instruments.shares()
            
            for ticker, share_config in self.config.shares_config.items():
                # Ищем нужную акцию по тикеру
                instrument = next(
                    (inst for inst in response.instruments if inst.ticker == ticker),
                    None
                )
                
                if not instrument:
                    logger.error(f"Инструмент {ticker} не найден в API")
                    continue
                
                # Получаем минимальный шаг цены для инструмента
                min_price_step = self._quotation_to_float(instrument.min_price_increment)
                
                # Собираем информацию об акции
                share_info = {
                    'ticker': ticker,
                    'figi': instrument.figi,
                    'min_price_step': min_price_step,
                    'levels': share_config.get('levels', self.config.default_grid_levels),
                    'price_step': share_config.get('price_step', self.config.default_price_step),
                    'quantity': share_config.get('quantity', self.config.default_quantity),
                    'start_price': share_config.get('start_price', 0),
                    'account_id': self.config.account_id,
                }
                
                # Получаем текущую рыночную цену
                last_price_response = await client.market_data.get_last_prices(figi=[instrument.figi])
                last_price = self._quotation_to_float(last_price_response.last_prices[0].price)
                share_info['last_price'] = last_price
                
                # Если начальная цена не задана, используем текущую
                if share_info['start_price'] == 0:
                    share_info['start_price'] = last_price
                
                # Сохраняем в базу данных
                share_id = await self.db.insert_share(
                    ticker, instrument.figi, 
                    share_info['levels'], 
                    share_info['price_step'], 
                    share_info['quantity']
                )
                share_info['id'] = share_id
                
                # Генерируем ценовую сетку
                prices = self._generate_price_grid(share_info)
                await self.db.insert_prices(share_id, ticker, prices)
                share_info['prices'] = prices
                
                self.shares_info[ticker] = share_info
                logger.info(f"Инициализирована акция {ticker}: цена={last_price}, мин.шаг={min_price_step}, уровней сетки={len(prices)}")
    
    def _generate_price_grid(self, share_info: Dict) -> List[float]:
        """
        Генерация ценовых уровней сетки
        
        Формула: цена = стартовая_цена + стартовая_цена * шаг_цены * (i - количество_уровней/2)
        Это создает сетку цен, симметричную относительно стартовой цены
        
        Args:
            share_info: Информация об акции
        
        Returns:
            Отсортированный список ценовых уровней
        """
        start_price = share_info['start_price']
        price_step = share_info['price_step']
        levels = share_info['levels']
        min_price_step = share_info['min_price_step']
        
        prices = []
        for i in range(levels + 1):
            # Вычисляем цену по формуле сетки
            price = start_price + start_price * price_step * (i - levels / 2)
            # Округляем до минимального шага цены инструмента
            price = round(price / min_price_step) * min_price_step
            price = float(format(price, '.9f'))  # Ограничиваем точность
            prices.append(price)
        
        return sorted(prices)
    
    async def cancel_all_orders(self, share_info: Dict):
        """
        Отмена всех активных ордеров по акции
        
        Args:
            share_info: Информация об акции
        """
        try:
            async with Client(self.config.token) as client:
                account_id = share_info['account_id'] or await self._get_account_id()
                await client.orders.cancel_all_orders(account_id=account_id)
                logger.info(f"Отменены все ордера для {share_info['ticker']}")
        except Exception as e:
            logger.error(f"Ошибка при отмене ордеров для {share_info['ticker']}: {e}")
    
    async def _get_account_id(self) -> str:
        """
        Получение ID первого доступного счета, если не указан в конфиге
        
        Returns:
            ID счета
        """
        if self.config.account_id:
            return self.config.account_id
        
        async with Client(self.config.token) as client:
            accounts = await client.users.get_accounts()
            if accounts.accounts:
                return accounts.accounts[0].id
        raise ValueError("Не найдено ни одного счета в API Тинькофф")
    
    async def create_order(self, share_info: Dict, price: float) -> Optional[str]:
        """
        Создание лимитного ордера
        
        Args:
            share_info: Информация об акции
            price: Цена ордера
        
        Returns:
            ID созданного ордера или None при ошибке
        """
        try:
            account_id = share_info['account_id'] or await self._get_account_id()
            
            # Определяем направление ордера относительно текущей цены
            # Выше текущей цены - продажа (SELL), ниже - покупка (BUY)
            async with Client(self.config.token) as client:
                last_price_response = await client.market_data.get_last_prices(figi=[share_info['figi']])
                last_price = self._quotation_to_float(last_price_response.last_prices[0].price)
            
            direction = OrderDirection.ORDER_DIRECTION_SELL if price > last_price else OrderDirection.ORDER_DIRECTION_BUY
            
            # Генерируем уникальный ID ордера на основе времени
            order_id = str(int(asyncio.get_event_loop().time() * 1e9))
            
            async with Client(self.config.token) as client:
                order = await client.orders.post_order(
                    account_id=account_id,
                    figi=share_info['figi'],
                    quantity=share_info['quantity'],
                    price=self._float_to_quotation(price),
                    direction=direction,
                    order_type=OrderType.ORDER_TYPE_LIMIT,  # Лимитный ордер
                    order_id=order_id
                )
                
                # Сохраняем информацию об ордере в БД
                await self.db.insert_order(
                    share_info['id'],
                    share_info['ticker'],
                    order.order_id,
                    price,
                    direction
                )
                
                logger.info(f"Создан ордер: {share_info['ticker']} цена={price} направление={direction}")
                return order.order_id
                
        except RequestError as e:
            logger.error(f"Ошибка при создании ордера для {share_info['ticker']} по цене {price}: {e}")
            # Ошибка 30079 означает, что торги по инструменту приостановлены
            if hasattr(e, 'details') and e.details == '30079':
                logger.warning(f"Торги по {share_info['ticker']} приостановлены")
            return None
    
    async def recreate_orders(self, share_info: Dict):
        """
        Пересоздание всех ордеров для акции
        
        Args:
            share_info: Информация об акции
        """
        logger.info(f"Пересоздание ордеров для {share_info['ticker']}")
        
        # Отменяем все существующие ордера
        await self.cancel_all_orders(share_info)
        
        # Получаем текущую рыночную цену
        async with Client(self.config.token) as client:
            last_price_response = await client.market_data.get_last_prices(figi=[share_info['figi']])
            last_price = self._quotation_to_float(last_price_response.last_prices[0].price)
        
        # Находим цену для пропуска (ближайшую к текущей)
        prices = await self.db.get_prices(share_info['id'])
        skip_price = min(prices, key=lambda x: abs(x - last_price))
        
        # Создаем ордера для всех ценовых уровней, кроме пропущенного
        for price in prices:
            if price == skip_price:
                continue
            
            # Проверяем, нет ли уже активного ордера на этот уровень
            # (упрощенная проверка, в реальности нужно проверять по price)
            existing_order = await self.db.get_order(str(int(price * 1000)))
            if not existing_order:
                await self.create_order(share_info, price)
    
    async def handle_order_fill(self, order_id: str, share_info: Dict):
        """
        Обработка исполненного ордера
        
        Принцип сеточной торговли:
        - Если исполнился ордер на продажу, выставляем ордер на покупку на уровень ниже
        - Если исполнился ордер на покупку, выставляем ордер на продажу на уровень выше
        
        Args:
            order_id: ID исполнившегося ордера
            share_info: Информация об акции
        """
        order = await self.db.get_order(order_id)
        if not order:
            logger.warning(f"Ордер {order_id} не найден в базе данных")
            return
        
        order_db_id, share_id, price = order
        
        # Получаем состояние ордера из API, чтобы узнать направление
        async with Client(self.config.token) as client:
            account_id = share_info['account_id'] or await self._get_account_id()
            order_state = await client.orders.get_order_state(
                account_id=account_id,
                order_id=order_id
            )
        
        if not order_state:
            logger.warning(f"Состояние ордера {order_id} не получено")
            return
        
        # Получаем все ценовые уровни для этой акции
        prices = await self.db.get_prices(share_info['id'])
        price_index = prices.index(price)
        
        # Определяем новый ордер (противоположное направление)
        if order_state.direction == OrderDirection.ORDER_DIRECTION_SELL:
            # Был продан - теперь покупаем на уровень ниже
            new_direction = OrderDirection.ORDER_DIRECTION_BUY
            new_price_index = price_index - 1
            action = "покупку"
        else:
            # Был куплен - теперь продаем на уровень выше
            new_direction = OrderDirection.ORDER_DIRECTION_SELL
            new_price_index = price_index + 1
            action = "продажу"
        
        # Проверяем, не вышли ли за границы сетки
        if 0 <= new_price_index < len(prices):
            new_price = prices[new_price_index]
            
            try:
                async with Client(self.config.token) as client:
                    # Создаем новый ордер
                    new_order_id = str(int(asyncio.get_event_loop().time() * 1e9))
                    new_order = await client.orders.post_order(
                        account_id=share_info['account_id'] or await self._get_account_id(),
                        figi=share_info['figi'],
                        quantity=share_info['quantity'],
                        price=self._float_to_quotation(new_price),
                        direction=new_direction,
                        order_type=OrderType.ORDER_TYPE_LIMIT,
                        order_id=new_order_id
                    )
                    
                    # Обновляем запись в БД (меняем ID ордера, цену и направление)
                    await self.db.update_order(
                        order_id,
                        new_order_id=new_order.order_id,
                        price=new_price,
                        direction=new_direction,
                        status='ACTIVE'
                    )
                    
                    logger.info(f"Ордер {order_id} исполнен. Выставлен новый ордер на {action} {share_info['ticker']} по цене {new_price}")
                    
            except RequestError as e:
                logger.error(f"Ошибка при создании замещающего ордера: {e}")
        else:
            logger.warning(f"Новый ценовой индекс {new_price_index} вышел за границы сетки для {share_info['ticker']}")
    
    async def process_trade_stream(self):
        """
        Обработка потока торговых событий
        
        Подписываемся на стрим исполненных ордеров и обрабатываем их
        """
        async with Client(self.config.token) as client:
            async for response in client.orders_stream.trades_stream():
                if not response.order_trades:
                    continue
                
                order_id = response.order_trades.order_id
                logger.info(f"Получено торговое событие по ордеру {order_id}")
                
                # Определяем, для какой акции этот ордер
                for ticker, share_info in self.shares_info.items():
                    order = await self.db.get_order(order_id)
                    if order:
                        await self.handle_order_fill(order_id, share_info)
                        break
    
    async def periodic_order_check(self):
        """
        Периодическая проверка ордеров
        
        Если количество активных ордеров меньше ожидаемого, пересоздаем их
        """
        while self.is_running:
            await asyncio.sleep(self.config.order_check_interval)
            
            for ticker, share_info in self.shares_info.items():
                active_orders = await self.db.get_active_orders_count(share_info['id'])
                expected_orders = len(share_info['prices']) - 1  # Минус пропущенный уровень
                
                if active_orders < expected_orders:
                    logger.info(f"Обнаружены пропущенные ордера для {ticker}. Активных: {active_orders}, Ожидалось: {expected_orders}")
                    await self.recreate_orders(share_info)
    
    async def start(self):
        """Запуск бота"""
        self.is_running = True
        
        # Инициализируем информацию по акциям
        await self.init_shares()
        
        # Отменяем существующие ордера и создаем новые
        for share_info in self.shares_info.values():
            await self.cancel_all_orders(share_info)
            await self.recreate_orders(share_info)
        
        # Запускаем фоновые задачи
        tasks = [
            asyncio.create_task(self.process_trade_stream()),  # Обработка исполненных ордеров
            asyncio.create_task(self.periodic_order_check()),  # Периодическая проверка
        ]
        
        # Настройка обработки сигналов остановки
        stop_event = asyncio.Event()
        
        def signal_handler():
            """Обработчик сигналов завершения"""
            logger.info("Получен сигнал завершения. Останавливаем бота...")
            stop_event.set()
        
        # Регистрируем обработчики для Ctrl+C и SIGTERM
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
        
        try:
            # Ждем сигнала остановки
            await stop_event.wait()
        finally:
            self.is_running = False
            # Отменяем все задачи
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            logger.info("Бот остановлен")


async def main():
    """Главная функция запуска бота"""
    try:
        # Загружаем конфигурацию
        config = GridBotConfig()
        
        # Инициализируем базу данных
        async with DatabaseManager(config.db_path) as db:
            # Создаем и запускаем бота
            bot = GridTradingBot(config, db)
            await bot.start()
            
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
