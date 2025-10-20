import unittest
import sys
import os

# Добавляем src и tests в путь для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Импортируем тесты
from test_config import TestConfig
from test_database import TestDatabase
from test_tinkoff_api import TestTinkoffAPI
from test_bot_logic import TestBotLogic

if __name__ == '__main__':
    # Создаем тестовый набор
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Добавляем тесты в набор
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabase))
    suite.addTests(loader.loadTestsFromTestCase(TestTinkoffAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestBotLogic))
    
    # Запускаем тесты
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Возвращаем код выхода в зависимости от результата тестов
    sys.exit(0 if result.wasSuccessful() else 1)