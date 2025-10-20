# Tinkoff Stream Grid Bot

Бот для автоматической торговли на бирже Тинькофф по сеточному принципу.

## Описание

Этот бот реализует стратегию сеточной торговли на бирже Тинькофф. Он автоматически выставляет ордера на покупку и продажу акций по заранее заданным уровням цен, адаптируясь к рыночным колебаниям.

## Требования

- Python 3.7+
- Аккаунт Тинькофф Инвестиции
- Токен доступа к Tinkoff Invest API
- PostgreSQL
- Redis

## Установка

1. Клонируйте репозиторий:
   ```
   git clone <repository-url>
   cd tinkoff-stream-grid-bot
   ```

2. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```

3. Создайте файл `.env` на основе `.env.example` и заполните его:
   ```
   cp .env.example .env
   ```

4. Настройте параметры в `.env`:
   ```
   TINKOFF_TOKEN=your_tinkoff_token_here
   ACCOUNT_ID=your_account_id_here
   DB_HOST=localhost
   DB_NAME=stream_grid_bot
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   REDIS_HOST=localhost
   REDIS_PORT=6379
   REDIS_USER=
   REDIS_PASSWORD=
   ```

5. Создайте файл `config.json` на основе `config_example.json` и настройте под себя:
   ```
   cp config_example.json config.json
   ```

## Настройка config.json

В файле `config.json` настраиваются параметры торговых инструментов:

```json
{
  "shares": {
    "IRAO": {
      "number": 10,
      "price_step": 0.03,
      "quantity": 1,
      "start_price": 0
    }
  }
}
```

Где:
- `number` - количество линий сетки
- `price_step` - шаг построения сетки (в процентах)
- `quantity` - количество бумаг в одном ордере
- `start_price` - начальная цена (0 для автоматического определения)

## Запуск

Для запуска бота выполните:

```
python -m src.main
```

## Тестирование

Для запуска тестов выполните:

```
python -m tests.run_tests
```

## Архитектура

Проект разделен на несколько модулей:

- `src/config.py` - конфигурация и переменные окружения
- `src/database.py` - работа с базами данных PostgreSQL и Redis
- `src/tinkoff_api.py` - взаимодействие с Tinkoff Invest API
- `src/bot_logic.py` - бизнес-логика бота
- `src/main.py` - точка входа

## Приоритет получения данных

При получении списка инструментов бот использует следующий приоритет:
1. Кэш Redis (на 1 час)
2. База данных tinkoff_bd (заполняется другим проектом)
3. API Тинькофф

## Лицензия

MIT
