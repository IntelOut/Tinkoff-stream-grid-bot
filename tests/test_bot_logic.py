import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Добавляем src в путь для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.bot_logic import log, initialize_shares, initialize_prices, create_orders, handle_order

class TestBotLogic(unittest.TestCase):
    
    def test_log_function(self):
        """Тест функции логирования"""
        # Проверяем, что функция не вызывает исключений
        try:
            log("Test message")
            result = True
        except Exception:
            result = False
        
        self.assertTrue(result)
    
    @patch('src.bot_logic.get_config')
    @patch('src.bot_logic.get_instruments')
    @patch('src.bot_logic.create_tables')
    @patch('src.bot_logic.get_db_connection')
    def test_initialize_shares(self, mock_get_db_connection, mock_create_tables, mock_get_instruments, mock_get_config):
        """Тест инициализации акций"""
        # Мокаем конфигурацию
        mock_get_config.return_value = {
            'shares': {
                'TEST': {
                    'number': 10,
                    'price_step': 0.03,
                    'quantity': 1,
                    'start_price': 0
                }
            }
        }
        
        # Мокаем инструменты
        mock_get_instruments.return_value = [
            {
                'ticker': 'TEST',
                'figi': 'TEST_FIGI',
                'min_price_increment': 0.01
            }
        ]
        
        # Мокаем подключение к БД
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = [1]  # ID акции
        
        # Вызываем тестируемую функцию
        shares = initialize_shares()
        
        # Проверяем результаты
        self.assertIn('TEST', shares)
        self.assertEqual(shares['TEST']['ticker'], 'TEST')
        self.assertEqual(shares['TEST']['figi'], 'TEST_FIGI')
        self.assertEqual(shares['TEST']['min_price_step'], 0.01)
        self.assertEqual(shares['TEST']['id'], 1)
        
        # Проверяем вызовы
        mock_create_tables.assert_called_once()
        mock_get_config.assert_called_once()
        mock_get_instruments.assert_called_once()
        mock_conn.cursor.assert_called_once()
        mock_cur.execute.assert_called()
        mock_conn.commit.assert_called()
    
    @patch('src.bot_logic.get_last_prices')
    @patch('src.bot_logic.cancel_all_orders')
    @patch('src.bot_logic.get_db_connection')
    def test_initialize_prices(self, mock_get_db_connection, mock_cancel_all_orders, mock_get_last_prices):
        """Тест инициализации цен"""
        # Создаем тестовые данные
        shares = {
            'TEST': {
                'id': 1,
                'ticker': 'TEST',
                'figi': 'TEST_FIGI',
                'min_price_step': 0.01,
                'start_price': 0,
                'number': 5,
                'price_step': 0.02,
                'quantity': 1
            }
        }
        
        # Мокаем подключение к БД
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = [0]  # Нет цен в БД
        
        # Мокаем получение последних цен
        mock_get_last_prices.return_value = [
            {
                'figi': 'TEST_FIGI',
                'price': 100.0
            }
        ]
        
        # Вызываем тестируемую функцию
        try:
            initialize_prices(shares)
            result = True
        except Exception as e:
            print(f"Ошибка в тесте: {e}")
            result = False
        
        # Проверяем результат
        self.assertTrue(result)
        
        # Проверяем вызовы
        mock_get_db_connection.assert_called()
        mock_get_last_prices.assert_called_with(['TEST_FIGI'])
        mock_cancel_all_orders.assert_called_once()

if __name__ == '__main__':
    unittest.main()