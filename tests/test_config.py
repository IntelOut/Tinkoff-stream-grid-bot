import unittest
import os
from src.config import TOKEN, ACCID, DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, REDIS_HOST, REDIS_PORT, REDIS_USER, REDIS_PASSWORD

class TestConfig(unittest.TestCase):
    
    def test_env_variables_loaded(self):
        """Тест проверяет, что переменные окружения загружены"""
        # Проверяем, что переменные существуют (могут быть None или иметь значения по умолчанию)
        self.assertIsNotNone(DB_HOST)
        self.assertIsNotNone(DB_NAME)
        self.assertIsNotNone(DB_USER)
        self.assertIsNotNone(REDIS_HOST)
        self.assertIsNotNone(REDIS_PORT)
        
    def test_default_values(self):
        """Тест проверяет значения по умолчанию"""
        # REDIS_PORT должен быть числом (по умолчанию 6379)
        self.assertEqual(REDIS_PORT, 6379)
        
    def test_optional_variables(self):
        """Тест проверяет необязательные переменные"""
        # Эти переменные могут быть None
        # Проверяем, что они существуют
        self.assertTrue(hasattr(os.environ, 'REDIS_USER') or REDIS_USER is None)
        self.assertTrue(hasattr(os.environ, 'REDIS_PASSWORD') or REDIS_PASSWORD is None)

if __name__ == '__main__':
    unittest.main()