import time
import sys
from tinkoff.invest import OrderDirection, OrderExecutionReportStatus
from src.tinkoff_api import get_instruments, get_last_prices, cancel_all_orders, post_order, get_order_state
from src.database import get_db_connection, get_config, create_tables
from src.config import ACCID

logger = open('bot_stat.log', 'a')

def log(*args):
    message = ' '.join(map(str, args))
    print(message)
    logger.write(message + "\n")
    logger.flush()

def initialize_shares():
    # Создание таблиц в базе данных
    create_tables()
    
    # Получение конфигурации
    config = get_config()
    shares_config = config.get('shares', {})
    
    # Получение инструментов
    instruments = get_instruments()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    shares = {}
    for instrument_data in instruments:
        ticker = instrument_data.get('ticker')
        figi = instrument_data.get('figi')
        min_price_step = instrument_data.get('min_price_increment')
        
        if not ticker or not figi or not min_price_step:
            continue
            
        if ticker in shares_config:
            share = shares_config[ticker].copy()
            share['ticker'] = ticker
            share['figi'] = figi
            share['min_price_step'] = min_price_step
            
            # Вставка или игнорирование инструмента в базу
            cur.execute("INSERT INTO share (ticker, figi) VALUES (%s, %s) ON CONFLICT (ticker) DO NOTHING", (ticker, figi))
            conn.commit()
            
            # Получение ID инструмента
            cur.execute("SELECT id FROM share WHERE ticker = %s", (ticker, ))
            share_id = cur.fetchone()[0]
            share['id'] = share_id
            
            shares[ticker] = share
    
    cur.close()
    conn.close()
    
    return shares

def initialize_prices(shares):
    conn = get_db_connection()
    cur = conn.cursor()
    
    for ticker, share in shares.items():
        # Проверка наличия цен в базе
        cur.execute("SELECT COUNT(*) FROM price WHERE share_id = %s", (share['id'], ))
        count = cur.fetchone()[0]
        
        if count > 0:
            continue
        
        # Получение последней цены
        last_prices = get_last_prices([share['figi']])
        if not last_prices:
            continue
            
        last_price = last_prices[0]['price']
        print(ticker, share['figi'], "last price", last_price, "min step", share['min_price_step'])
        
        if share['start_price'] == 0:
            share['start_price'] = last_price
        
        # Удаление всех открытых ордеров
        cancel_all_orders()
        
        # Заполнение цен
        for i in range(share['number'] + 1):
            price = share['start_price'] + share['start_price'] * share['price_step'] * (i - share['number'] / 2)
            price = round(price / share['min_price_step']) * share['min_price_step']
            price = float(format(price, '.9f'))
            
            cur.execute("INSERT INTO price (share_id, ticker, price) VALUES (%s, %s, %s)", (share['id'], ticker, price))
            conn.commit()
    
    cur.close()
    conn.close()

def create_orders(share):
    conn = get_db_connection()
    cur = conn.cursor()
    
    share_id = share['id']
    figi = share['figi']
    quantity = share['quantity']
    
    # Получение цен из базы
    cur.execute("SELECT price FROM price WHERE share_id = %s ORDER BY price", (share_id, ))
    prices = [row[0] for row in cur.fetchall()]
    
    # Получение последних цен
    last_prices = get_last_prices([figi])
    if not last_prices:
        cur.close()
        conn.close()
        return
        
    last_price = last_prices[0]['price']
    
    skip_price = 0
    for price in prices:
        if abs(price - last_price) < abs(price - skip_price):
            skip_price = price
    
    # Пробуем найти цену под sell
    try:
        cur.execute(
            "SELECT MAX(price) FROM price P WHERE share_id = %s AND price < (SELECT MIN(price) FROM \"order\" WHERE direction = %s AND share_id = P.share_id)",
            (share_id, OrderDirection.ORDER_DIRECTION_SELL.value)
        )
        new_skip_price_result = cur.fetchone()
        new_skip_price = new_skip_price_result[0] if new_skip_price_result and new_skip_price_result[0] else None
        print(time.asctime(), 'new_skip_price sell', new_skip_price)
    except Exception as e:
        print(time.asctime(), 'Ошибка при поиске цены sell:', e)
        new_skip_price = None
    
    if not new_skip_price:
        # Пробуем найти цену над buy
        try:
            cur.execute(
                "SELECT MIN(price) FROM price P WHERE share_id = %s AND price > (SELECT MAX(price) FROM \"order\" WHERE direction = %s AND share_id = P.share_id)",
                (share_id, OrderDirection.ORDER_DIRECTION_BUY.value)
            )
            new_skip_price_result = cur.fetchone()
            new_skip_price = new_skip_price_result[0] if new_skip_price_result and new_skip_price_result[0] else None
            print(time.asctime(), 'new_skip_price buy', new_skip_price)
        except Exception as e:
            print(time.asctime(), 'Ошибка при поиске цены buy:', e)
            new_skip_price = None
    
    if new_skip_price:
        print(time.asctime(), 'new_skip_price', new_skip_price)
        skip_price = new_skip_price
    
    print(time.asctime(), 'last', last_price, 'skip', skip_price)
    
    # Создание ордеров
    for price in prices:
        # Достаем ордер из базы
        try:
            cur.execute("SELECT order_id FROM \"order\" WHERE share_id = %s AND price = %s", (share_id, price))
            order_result = cur.fetchone()
            if order_result:
                order_id = order_result[0]
                handle_order(order_id)
                continue
        except Exception as e:
            print(time.asctime(), 'Ошибка при поиске ордера в БД:', e)
            continue
        
        if price == skip_price:
            continue
        
        # Создание ордера
        direction = OrderDirection.ORDER_DIRECTION_SELL if price > last_price else OrderDirection.ORDER_DIRECTION_BUY
        try:
            order = post_order(figi, quantity, price, direction)
            if order:
                cur.execute("INSERT INTO \"order\" (share_id, ticker, order_id, price, direction) VALUES (%s, %s, %s, %s, %s)",
                           [share_id, share['ticker'], order.order_id, price, direction.value])
                conn.commit()
                print(time.asctime(), "Выставил ордер: ", share['ticker'], price, direction)
        except Exception as e:
            print(time.asctime(), "Ошибка при выставлении ордера:", e)
    
    cur.close()
    conn.close()

def handle_order(order_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT id, share_id, price FROM \"order\" WHERE order_id = %s", (order_id, ))
    order = cur.fetchone()
    if not order:
        print(time.asctime(), "not order: ", order)
        cur.close()
        conn.close()
        return
    id = order[0]
    share_id = order[1]
    price = order[2]
    
    # Получение информации об акции
    shares = initialize_shares()
    share = None
    for tmp in shares.values():
        if tmp['id'] == share_id:
            share = tmp
            break
    if not share:
        print("share not found")
        cur.close()
        conn.close()
        return
    figi = share['figi']
    quantity = share['quantity']
    
    order_state = get_order_state(order_id)
    if not order_state:
        print(time.asctime(), "not order_state: ", order)
        cur.close()
        conn.close()
        return
    print(time.asctime(), order_state.execution_report_status)
    
    # Проверяем наличие необходимых атрибутов более надежным способом
    if not hasattr(order_state, 'execution_report_status'):
        print(time.asctime(), "execution_report_status not found in order_state")
        cur.close()
        conn.close()
        return
        
    bad_statuses = [
        OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_UNSPECIFIED,
        OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_REJECTED,
        OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_CANCELLED
    ]
    
    if (order_state.execution_report_status in bad_statuses):
        print(time.asctime(), " ORDER ", order_state.execution_report_status, order_id, price)
        cur.execute("DELETE FROM \"order\" WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return
    
    # Проверяем статус исполнения
    if not hasattr(order_state, 'execution_report_status') or \
       order_state.execution_report_status != OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_FILL:
        # Ордер еще не исполнен, ничего не делаем
        cur.close()
        conn.close()
        return
        
    print(time.asctime(), " ORDER FILLED ", order_id, price)
    log(time.asctime(), " ORDER FILLED ", order_id, price, order_state.direction)
    
    # Получение цен из базы
    cur.execute("SELECT price FROM price WHERE share_id = %s ORDER BY price", (share_id, ))
    prices = [row[0] for row in cur.fetchall()]
    
    # Проверяем наличие направления
    if not hasattr(order_state, 'direction'):
        print(time.asctime(), "direction not found in order_state")
        cur.close()
        conn.close()
        return
        
    direction = order_state.direction
    price_index = prices.index(price)
    
    if (direction == OrderDirection.ORDER_DIRECTION_SELL):
        direction = OrderDirection.ORDER_DIRECTION_BUY
        price_index -= 1
    else:
        direction = OrderDirection.ORDER_DIRECTION_SELL
        price_index += 1
    
    price = prices[price_index]
    
    try:
        order = post_order(figi, quantity, price, direction)
        if order:
            cur.execute("UPDATE \"order\" SET order_id = %s, price = %s, direction = %s WHERE id = %s",
                       [order.order_id, price, direction.value, id])
            conn.commit()
            print(time.asctime(), " NEW ORDER ", order.order_id, direction, price)
    except Exception as err:
        print(time.asctime(), " ERROR ", err)
    
    cur.close()
    conn.close()

def main():
    # Инициализация акций
    shares = initialize_shares()
    
    # Инициализация цен
    initialize_prices(shares)
    
    # Создание ордеров
    for share in shares.values():
        create_orders(share)
    
    # Засечь время
    orders_time = time.time()
    
    # Основной цикл обработки сделок
    while True:
        try:
            # Здесь должна быть логика обработки потока сделок
            # Пока просто засыпаем
            time.sleep(60)
            
            # Если прошла минута, пытаемся перевыставить ордера
            if time.time() - orders_time >= 1 * 60:
                for share in shares.values():
                    create_orders(share)
                orders_time = time.time()
        except Exception as err:
            # Другие возможные ошибки
            print(time.asctime(), "другая ошибка", err)
    
    return 0