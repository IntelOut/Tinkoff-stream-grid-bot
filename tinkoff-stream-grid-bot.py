#!/usr/bin/env python3
"""
Торговый бот для Тинькофф Инвестиции - Grid Trading стратегия
Асинхронная версия с использованием библиотеки t-tech-investments
"""
import asyncio
import logging
import os
import signal
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import aiosqlite
from dotenv import load_dotenv
from t_tech.invest import (
    AsyncClient,
    OrderType,
    OrderDirection,
    OrderExecutionReportStatus,
    Quotation,
    RequestError,
    AioRequestError,
)

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

API_ERRORS = (RequestError, AioRequestError)


class GridBotConfig:
    """Класс конфигурации для сеточного бота"""

    def __init__(self):
        # Получаем основные настройки из переменных окружения
        self.token = self._get_env('TINKOFF_TOKEN')  # API токен Тинькофф
        self.account_id = self._get_env('TINKOFF_ACCOUNT_ID', required=False)  # ID счета (опционально)
        self.db_path = self._get_env('DATABASE_PATH')  # Путь к файлу БД
        self.order_check_interval = int(self._get_env('ORDER_CHECK_INTERVAL', '60'))  # Интервал проверки ордеров (сек)

        # Настройки сетки по умолчанию
        self.default_grid_levels = int(self._get_env('GRID_LEVELS', '6'))  # Количество уровней сетки
        self.default_price_step = float(self._get_env('PRICE_STEP', '0.01'))  # Шаг цены (1%)
        self.default_quantity = int(self._get_env('QUANTITY', '1'))  # Количество лотов

        # Конфигурация торгуемых инструментов
        # Здесь можно добавить любые акции из Тинькофф Инвестиций
        self.shares_config = {
            "BTCUSDperpA": {  # Тикер инструмента
                "levels": 3,  # Количество уровней сетки (переопределяет default)
                "price_step": 0.0001,  # Шаг цены в долях цены
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
 

        Returns:
            Список цен, отсортированный по возрастанию
        """
        cursor = await self.connection.execute(
            "SELECT price FROM price WHERE share_id = ? ORDER BY price",
            (share_id,)
        )
        results = await cursor.fetchall()
        return [float(row[0]) for row in results]

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
            (share_id, ticker, order_id, price, int(direction), 'ACTIVE')
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
            params.append(int(direction))
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

    async def get_order(self, order_id: str) -> Optional[Tuple[int, int, float]]:
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
        result = await cursor.fetchone()
        if not result:
            return None
        return result[0], result[1], float(result[2])

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

    async def get_active_orders(self, share_id: int) -> List[Tuple[int, str, float, int]]:
        """
        Получение активных ордеров для акции

        Args:
            share_id: ID акции

        Returns:
            Список кортежей (id, order_id, price, direction)
        """
        cursor = await self.connection.execute(
            "SELECT id, order_id, price, direction FROM order_table WHERE share_id = ? AND status = 'ACTIVE'",
            (share_id,)
        )
        results = await cursor.fetchall()
        return [(row[0], row[1], float(row[2]), int(row[3])) for row in results]


class GridTradingBot:
    """Основной класс сеточного торгового бота"""

    def __init__(self, config: GridBotConfig, db: DatabaseManager):
        self.config = config  # Конфигурация бота
        self.db = db  # Менеджер базы данных
        self.client: Optional[Any] = None  # Клиент API Тинькофф (общий на время жизни бота)
        self.is_running = False  # Флаг работы бота
        self._account_id: Optional[str] = None  # Кэшированный ID счета
        self.shares_info: Dict[str, Dict[str, Any]] = {}  # Информация по всем акциям

    @staticmethod
    def _quotation_to_decimal(quotation: Quotation) -> Decimal:
        """
        Конвертация Quotation в Decimal

        Args:
            quotation: Объект Quotation из API Тинькофф

        Returns:
            Точное десятичное число
        """
        return Decimal(quotation.units) + Decimal(quotation.nano) / Decimal(1_000_000_000)

    def _quotation_to_float(self, quotation: Quotation) -> float:
        """Конвертация Quotation в float"""
        return float(self._quotation_to_decimal(quotation))

    @staticmethod
    def _decimal_to_quotation(value: Decimal) -> Quotation:
        """
        Конвертация Decimal в Quotation с корректной нормализацией nano

        Args:
            value: Точное десятичное число

        Returns:
            Объект Quotation для API Тинькофф
        """
        units = int(value)
        nano = int((value - Decimal(units)) * Decimal(1_000_000_000))
        if nano < 0:
            units -= 1
            nano += 1_000_000_000
        return Quotation(units=units, nano=nano)

    def _float_to_quotation(self, value: float) -> Quotation:
        """Конвертация float в Quotation без потери точности через Decimal"""
        return self._decimal_to_quotation(Decimal(str(value)))

    async def _get_account_id(self) -> str:
        """
        Получение ID счета. Результат кэшируется.

        Returns:
            ID счета
        """
        if self._account_id:
            return self._account_id
        if self.config.account_id:
            self._account_id = self.config.account_id
            return self._account_id

        accounts = await self.client.users.get_accounts()
        if accounts.accounts:
            self._account_id = accounts.accounts[0].id
            return self._account_id
        raise ValueError("Не найдено ни одного счета в API Тинькофф")

    async def _get_last_price(self, share_info: Dict) -> Optional[float]:
        """Получение текущей рыночной цены инструмента"""
        try:
            response = await self.client.market_data.get_last_prices(figi=[share_info['figi']])
            if response.last_prices:
                return self._quotation_to_float(response.last_prices[0].price)
        except API_ERRORS as e:
            logger.error("Ошибка при получении цены для %s: %s", share_info['ticker'], e)
        return None

    async def init_shares(self):
        """Инициализация информации по торгуемым инструментам.

        Поиск ведется по всем типам инструментов: акции, облигации, ETF,
        валюты и фьючерсы. При совпадении тикеров приоритет отдается первому
        найденному типу в порядке списка ниже.
        """
        # Порядок определяет приоритет при одинаковых тикерах
        catalog_methods = [
            ("shares", "акции"),
            ("bonds", "облигации"),
            ("etfs", "ETF"),
            ("currencies", "валюты"),
            ("futures", "фьючерсы"),
        ]

        instruments = {}
        instrument_types = {}
        for method, label in catalog_methods:
            try:
                response = await getattr(self.client.instruments, method)()
            except API_ERRORS as e:
                logger.error("Ошибка при загрузке каталога %s: %s", label, e)
                continue
            for inst in response.instruments:
                if inst.ticker not in instruments:
                    instruments[inst.ticker] = inst
                    instrument_types[inst.ticker] = label

        for ticker, share_config in self.config.shares_config.items():
            try:
                instrument = instruments.get(ticker)
                if not instrument:
                    logger.error(
                        f"Инструмент {ticker} не найден в API "
                        "(искали среди: акции, облигации, ETF, валюты, фьючерсы)"
                    )
                    continue

                # Получаем минимальный шаг цены для инструмента
                min_price_step = self._quotation_to_float(instrument.min_price_increment)

                # Собираем информацию об инструменте
                share_info = {
                    'ticker': ticker,
                    'figi': instrument.figi,
                    'instrument_type': instrument_types.get(ticker, 'unknown'),
                    'min_price_step': min_price_step,
                    'levels': share_config.get('levels', self.config.default_grid_levels),
                    'price_step': share_config.get('price_step', self.config.default_price_step),
                    'quantity': share_config.get('quantity', self.config.default_quantity),
                    'start_price': share_config.get('start_price', 0),
                }

                # Получаем текущую рыночную цену
                last_price = await self._get_last_price(share_info)
                if last_price is None:
                    logger.error("Не удалось получить цену для %s, инструмент пропущен", ticker)
                    continue
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
                logger.info(
                    f"Инициализирован инструмент {ticker} ({share_info['instrument_type']}): "
                    f"цена={last_price}, мин.шаг={min_price_step}, уровней сетки={len(prices)}"
                )
            except Exception as e:
                # Сбой по одному инструменту не должен останавливать инициализацию остальных
                logger.error("Ошибка инициализации инструмента %s: %s", ticker, e)
                continue

    def _generate_price_grid(self, share_info: Dict) -> List[float]:
        """
        Генерация ценовых уровней сетки

        Формула: цена = стартовая_цена + стартовая_цена * шаг_цены * (i - количество_уровней/2)
        Это создает сетку цен, симметричную относительно стартовой цены

        Args:
            share_info: Информация об инструменте

        Returns:
            Отсортированный список ценовых уровней
        """
        start_price = Decimal(str(share_info['start_price']))
        price_step = Decimal(str(share_info['price_step']))
        levels = share_info['levels']
        min_price_step = Decimal(str(share_info['min_price_step']))
        half = Decimal(levels) / 2

        prices = []
        for i in range(levels + 1):
            # Вычисляем цену по формуле сетки
            price = start_price + start_price * price_step * (Decimal(i) - half)
            # Округляем до минимального шага цены инструмента
            price = (price / min_price_step).to_integral_value(rounding=ROUND_HALF_UP) * min_price_step
            prices.append(float(price))

        return sorted(prices)

    @staticmethod
    def _nearest_index(prices: List[float], price: float) -> int:
        """Индекс ближайшего ценового уровня сетки к заданной цене"""
        return min(range(len(prices)), key=lambda i: abs(prices[i] - price))

    async def _order_is_live(self, account_id: str, order_id: str) -> bool:
        """
        Проверка, что ордер все еще активен на бирже.

        При ошибке API исключение пробрасывается наверх: состояние ордера
        неизвестно, и удалять его строку из БД нельзя.

        Returns:
            True, если ордер в статусе NEW или PARTIALLYFILL
        """
        state = await self.client.orders.get_order_state(
            account_id=account_id,
            order_id=order_id,
        )
        return state.execution_report_status in (
            OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_NEW,
            OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_PARTIALLYFILL,
        )

    async def cancel_share_orders(self, share_info: Dict) -> bool:
        """
        Точечная отмена активных ордеров только по данному инструменту.

        Отменяются только ордера из БД для конкретного инструмента (а не по всему счету),
        чтобы не задеть ордера других инструментов.

        Args:
            share_info: Информация об инструменте

        Returns:
            True, если все ордера отменены или их не было, иначе False
        """
        account_id = await self._get_account_id()
        active_orders = await self.db.get_active_orders(share_info['id'])
        if not active_orders:
            return True

        ok = True
        for row_id, order_id, price, _ in active_orders:
            try:
                await self.client.orders.cancel_order(account_id=account_id, order_id=order_id)
                await self.db.delete_order(row_id)
                logger.info("Отменён ордер %s для %s по цене %s", order_id, share_info['ticker'], price)
            except API_ERRORS as e:
                try:
                    is_live = await self._order_is_live(account_id, order_id)
                except API_ERRORS:
                    # Состояние ордера не определено (таймаут/сеть): не удаляем строку,
                    # чтобы не выставить дубль поверх живого ордера
                    logger.error(
                        "Не удалось проверить состояние ордера %s для %s: %s. "
                        "Перевыставление прервано.",
                        order_id, share_info['ticker'], e
                    )
                    ok = False
                    break

                if is_live:
                    logger.error(
                        "Не удалось отменить активный ордер %s для %s: %s. Перевыставление прервано.",
                        order_id, share_info['ticker'], e
                    )
                    ok = False
                else:
                    await self.db.delete_order(row_id)
                    logger.info("Ордер %s для %s уже не активен на бирже, удалён из БД", order_id, share_info['ticker'])
        return ok

    async def _place_order(self, share_info: Dict, price: float, direction: OrderDirection) -> Optional[Any]:
        """
        Выставление лимитного ордера в API.

        Args:
            share_info: Информация об инструменте
            price: Цена ордера
            direction: Направление ордера

        Returns:
            Ответ API (PostOrderResponse) или None при ошибке
        """
        account_id = await self._get_account_id()
        # Уникальный ID ордера должен быть валидным UUID (требование API)
        order_id = uuid4().hex

        try:
            return await self.client.orders.post_order(
                account_id=account_id,
                figi=share_info['figi'],
                quantity=share_info['quantity'],
                price=self._float_to_quotation(price),
                direction=direction,
                order_type=OrderType.ORDER_TYPE_LIMIT,  # Лимитный ордер
                order_id=order_id,
            )
        except API_ERRORS as e:
            logger.error("Ошибка при создании ордера для %s по цене %s: %s", share_info['ticker'], price, e)
            return None

    async def create_order(self, share_info: Dict, price: float, last_price: Optional[float] = None) -> Optional[str]:
        """
        Создание лимитного ордера

        Args:
            share_info: Информация об инструменте
            price: Цена ордера
            last_price: Текущая цена инструмента (если уже известна, избегаем лишнего запроса)

        Returns:
            ID созданного ордера или None при ошибке
        """
        account_id = await self._get_account_id()

        # Определяем направление ордера относительно текущей цены
        # Выше текущей цены - продажа (SELL), ниже - покупка (BUY)
        if last_price is None:
            last_price = await self._get_last_price(share_info)
            if last_price is None:
                logger.warning("Не удалось получить цену для %s, ордер по цене %s не выставлен", share_info['ticker'], price)
                return None

        direction = OrderDirection.ORDER_DIRECTION_SELL if price > last_price else OrderDirection.ORDER_DIRECTION_BUY

        order = await self._place_order(share_info, price, direction)
        if order is None:
            return None

        try:
            # Сохраняем информацию об ордере в БД
            await self.db.insert_order(
                share_info['id'],
                share_info['ticker'],
                order.order_id,
                price,
                direction,
            )
        except Exception as e:
            # Если не удалось сохранить - отменяем ордер, чтобы он не оставался бесконтрольным
            logger.error("Не удалось сохранить ордер %s в БД: %s. Отменяем ордер.", order.order_id, e)
            try:
                await self.client.orders.cancel_order(account_id=account_id, order_id=order.order_id)
            except API_ERRORS:
                pass
            return None

        logger.info("Создан ордер: %s цена=%s направление=%s id=%s", share_info['ticker'], price, direction.name, order.order_id)
        return order.order_id

    async def recreate_orders(self, share_info: Dict):
        """
        Восстановление недостающих ордеров для инструмента.

        Выставляет ордера только на те уровни сетки, где их сейчас нет.
        Уровень, ближайший к текущей цене, пропускается.

        Args:
            share_info: Информация об инструменте
        """
        prices = await self.db.get_prices(share_info['id'])
        if not prices:
            return

        active_orders = await self.db.get_active_orders(share_info['id'])
        covered = {round(row[2], 6) for row in active_orders}

        last_price = await self._get_last_price(share_info)
        if last_price is None:
            last_price = share_info.get('last_price')
        skip_price = min(prices, key=lambda x: abs(x - last_price)) if last_price else None

        for price in prices:
            if skip_price is not None and price == skip_price:
                continue
            if round(price, 6) in covered:
                continue
            await self.create_order(share_info, price, last_price)

    async def handle_order_fill(self, order_id: str, share_info: Dict, direction: OrderDirection):
        """
        Обработка исполненного ордера

        Принцип сеточной торговли:
        - Если исполнился ордер на продажу, выставляем ордер на покупку на уровень ниже
        - Если исполнился ордер на покупку, выставляем ордер на продажу на уровень выше

        Args:
            order_id: ID исполнившегося ордера
            share_info: Информация об инструменте
            direction: Направление исполненного ордера
        """
        order = await self.db.get_order(order_id)
        if not order:
            logger.warning(f"Ордер {order_id} не найден в базе данных")
            return

        # Получаем все ценовые уровни для этого инструмента
        prices = await self.db.get_prices(share_info['id'])
        price_index = self._nearest_index(prices, order[2])

        # Определяем новый ордер (противоположное направление)
        if direction == OrderDirection.ORDER_DIRECTION_SELL:
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
        if not (0 <= new_price_index < len(prices)):
            logger.warning(
                f"Новый ценовой индекс {new_price_index} вышел за границы сетки для {share_info['ticker']}. "
                "Ордер помечен исполненным, уровень будет восстановлен проверкой ордеров."
            )
            await self.db.update_order(order_id, status='FILLED')
            return

        new_price = prices[new_price_index]

        # Не выставляем дубликат, если целевой уровень уже занят активным ордером
        active_orders = await self.db.get_active_orders(share_info['id'])
        target_rounded = round(new_price, 6)
        if any(round(row[2], 6) == target_rounded for row in active_orders):
            logger.info(
                f"Уровень {new_price} для {share_info['ticker']} уже занят активным ордером, "
                "замещающий ордер не требуется"
            )
            await self.db.update_order(order_id, status='FILLED')
            return

        # Создаем новый ордер
        new_order = await self._place_order(share_info, new_price, new_direction)
        if new_order is None:
            # Помечаем ордер исполненным, чтобы проверка ордеров восстановила уровень
            await self.db.update_order(order_id, status='FILLED')
            return

        # Обновляем запись в БД (меняем ID ордера, цену и направление)
        await self.db.update_order(
            order_id,
            new_order_id=new_order.order_id,
            price=new_price,
            direction=new_direction,
            status='ACTIVE',
        )

        logger.info(
            f"Ордер {order_id} исполнен. Выставлен новый ордер на {action} {share_info['ticker']} "
            f"по цене {new_price} (id={new_order.order_id})"
        )

    async def handle_trade_event(self, order_trades: Any):
        """
        Обработка события торгового стрима

        Args:
            order_trades: Сообщение OrderTrades из стрима
        """
        order_id = order_trades.order_id

        order = await self.db.get_order(order_id)
        if not order:
            logger.warning(f"Событие по неизвестному ордеру {order_id}")
            return

        # Находим инструмент по share_id из записи об ордере
        _, share_id, _ = order
        share_info = next(
            (info for info in self.shares_info.values() if info['id'] == share_id),
            None
        )
        if not share_info:
            logger.warning(f"Не найден инструмент для ордера {order_id} (share_id={share_id})")
            return

        # Дополнительная проверка по FIGI из сообщения стрима
        message_figi = getattr(order_trades, 'figi', None)
        if message_figi and message_figi != share_info['figi']:
            logger.warning(f"FIGI события не совпадает для ордера {order_id}")
            return

        logger.info(f"Получено торговое событие по ордеру {order_id} ({share_info['ticker']})")
        await self.handle_order_fill(order_id, share_info, order_trades.direction)

    async def process_trade_stream(self):
        """
        Обработка потока торговых событий.

        Стрим требует список счетов, при разрыве соединения переподключается
        с увеличивающейся паузой.
        """
        account_id = await self._get_account_id()
        backoff = 1

        while self.is_running:
            try:
                async with AsyncClient(self.config.token) as client:
                    logger.info("Подключение к потоку торговых событий...")
                    async for response in client.orders_stream.trades_stream(accounts=[account_id]):
                        if not response.order_trades:
                            continue
                        order_id = response.order_trades.order_id
                        try:
                            await self.handle_trade_event(response.order_trades)
                        except Exception as e:
                            # Сбой обработки события не должен ронять стрим:
                            # помечаем ордер исполненным, проверка ордеров восстановит уровень
                            logger.error(f"Ошибка обработки торгового события по ордеру {order_id}: {e}")
                            try:
                                await self.db.update_order(order_id, status='FILLED')
                            except Exception:
                                logger.error(f"Не удалось обновить статус ордера {order_id} после сбоя обработки")
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка торгового стрима: {e}. Повторное подключение через {backoff} сек.")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def periodic_order_check(self):
        """
        Периодическая проверка ордеров

        Если количество активных ордеров меньше ожидаемого, восстанавливаем их
        """
        while self.is_running:
            await asyncio.sleep(self.config.order_check_interval)

            for ticker, share_info in self.shares_info.items():
                try:
                    active_orders = await self.db.get_active_orders_count(share_info['id'])
                    expected_orders = len(share_info['prices']) - 1  # Минус пропущенный уровень

                    if active_orders < expected_orders:
                        logger.info(
                            f"Обнаружены пропущенные ордера для {ticker}. "
                            f"Активных: {active_orders}, ожидалось: {expected_orders}"
                        )
                        await self.recreate_orders(share_info)
                except Exception as e:
                    logger.error(f"Ошибка при проверке ордеров для {ticker}: {e}")

    async def start(self):
        """Запуск бота"""
        self.is_running = True

        # Единый клиент на все время жизни бота
        async with AsyncClient(self.config.token) as self.client:
            # Инициализируем информацию по инструментам
            await self.init_shares()
            if not self.shares_info:
                logger.error("Не удалось инициализировать ни одного инструмента, бот остановлен")
                self.is_running = False
                return

            account_id = await self._get_account_id()
            logger.info("Аккаунт для торговли: %s", account_id)

            # Очищаем старые ордера и выставляем сетку заново
            for share_info in self.shares_info.values():
                if not await self.cancel_share_orders(share_info):
                    logger.error(
                        f"Не удалось отменить старые ордера для {share_info['ticker']}. "
                        "Старт прерван, чтобы избежать двойных ордеров."
                    )
                    self.is_running = False
                    return
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

            loop = asyncio.get_running_loop()
            registered = False
            for sig in (signal.SIGINT, getattr(signal, 'SIGTERM', signal.SIGINT)):
                try:
                    loop.add_signal_handler(sig, signal_handler)
                    registered = True
                except (NotImplementedError, ValueError, RuntimeError):
                    # На Windows обработчики сигналов не поддерживаются
                    break
            if not registered:
                logger.info("Обработчики сигналов недоступны на этой платформе, остановка через Ctrl+C")

            try:
                # Ждем сигнала остановки
                await stop_event.wait()
            except KeyboardInterrupt:
                logger.info("Получен Ctrl+C")
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

        self.client = None


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
