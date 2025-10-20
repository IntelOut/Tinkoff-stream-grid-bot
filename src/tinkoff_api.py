import time
from tinkoff.invest import Client, RequestError
from tinkoff.invest import OrderType, OrderDirection, Quotation
from src.config import TOKEN, ACCID
from src.database import get_config, get_instruments_cache, set_instruments_cache, get_instruments_from_tinkoff_db

def makefloat(m) -> float:
    return float(format(m.units + m.nano / 10 ** 9, '.9f'))

def makequotation(m) -> Quotation:
    # Проверяем, является ли m уже объектом Quotation
    if isinstance(m, Quotation):
        return m
    # Если m - число, создаем Quotation
    units = int(m)
    nano = int((m - units) * 10**9)
    return Quotation(units=units, nano=nano)

def get_instruments():
    # Попытка получить инструменты из кэша Redis
    instruments_cache = get_instruments_cache()
    if instruments_cache:
        print("Инструменты получены из кэша Redis")
        return instruments_cache
    
    # Попытка получить инструменты из tinkoff_bd
    instruments_db = get_instruments_from_tinkoff_db()
    if instruments_db:
        print("Инструменты получены из базы tinkoff_bd")
        # Сохраняем в Redis кэш
        set_instruments_cache(instruments_db)
        return instruments_db
    
    # Если нигде нет, получаем из API
    print("Инструменты получены из API Тинькофф")
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            # Получаем список инструментов с обработкой ошибок
            shares_response = client.instruments.shares()
            if not hasattr(shares_response, 'instruments'):
                print(time.asctime(), "Не удалось получить список инструментов")
                return []
                
            instruments = shares_response.instruments
            
            # Сохраняем в структурированный формат
            instruments_data = []
            for instrument in instruments:
                instruments_data.append({
                    'ticker': instrument.ticker if hasattr(instrument, 'ticker') else None,
                    'figi': instrument.figi if hasattr(instrument, 'figi') else None,
                    'min_price_increment': makefloat(instrument.min_price_increment) if hasattr(instrument, 'min_price_increment') else None
                })
            
            # Сохраняем в Redis кэш
            set_instruments_cache(instruments_data)
            
            return instruments_data
        except Exception as e:
            print(time.asctime(), "Ошибка при получении списка инструментов:", e)
            return []

def get_last_prices(figi_list):
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            # Получаем последние цены с обработкой ошибок
            last_prices_response = client.market_data.get_last_prices(figi=figi_list)
            if not hasattr(last_prices_response, 'last_prices') or not last_prices_response.last_prices:
                print(time.asctime(), "Не удалось получить последние цены")
                return []
                
            prices = []
            for last_price_obj in last_prices_response.last_prices:
                if hasattr(last_price_obj, 'price') and hasattr(last_price_obj, 'figi'):
                    prices.append({
                        'figi': last_price_obj.figi,
                        'price': makefloat(last_price_obj.price)
                    })
            
            return prices
        except Exception as e:
            print(time.asctime(), "Ошибка при получении последних цен:", e)
            return []

def cancel_all_orders():
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            client.cancel_all_orders(account_id=ACCID)
        except Exception as e:
            print(time.asctime(), "Ошибка при отмене всех ордеров:", e)

def post_order(figi, quantity, price, direction):
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            price_quotation = makequotation(price)
            order = client.orders.post_order(
                account_id=ACCID, 
                figi=figi, 
                quantity=quantity,
                price=price_quotation, 
                direction=direction,
                order_type=OrderType.ORDER_TYPE_LIMIT,
                order_id=str(time.time_ns())
            )
            return order
        except RequestError as err:
            # попробовать поймать ошибку что нет торгов сейчас, например 30079. Все ошибки тут: https://tinkoff.github.io/investAPI/errors/
            print(time.asctime(), "Ошибка при выставлении ордера: ", figi, price, direction, err)
            # Проверяем код ошибки более надежным способом
            if hasattr(err, 'details') and err.details == '30079':
                return None
            # Также проверяем через metadata если она доступна
            elif hasattr(err, 'metadata') and hasattr(err.metadata, 'message') and '30079' in str(err.metadata.message):
                return None
            raise err
        except Exception as e:
            print(time.asctime(), "Другая ошибка при выставлении ордера:", e)
            raise e

def get_order_state(order_id):
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            order_state = client.orders.get_order_state(account_id=ACCID, order_id=order_id)
            return order_state
        except Exception as e:
            print(time.asctime(), "Ошибка при получении статуса ордера:", e)
            return None

def trades_stream():
    with Client(token=TOKEN, app_name="nazmiev.Tinkoff-stream-grid-bot") as client:
        try:
            for response in client.orders_stream.trades_stream([ACCID]):
                yield response
        except RequestError as err:
            # неведомая ошибка
            print(time.asctime(), "неведомая ошибка", err)
        except Exception as err:
            # Другие возможные ошибки
            print(time.asctime(), "другая ошибка", err)