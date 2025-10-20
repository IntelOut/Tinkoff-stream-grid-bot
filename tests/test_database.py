import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Добавляем src в путь для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.database import get_redis_connection, get_db_connection, create_database_if_not_exists, create_tables

class TestDatabase(unittest.TestCase):
    
    @patch('src.database.redis.Redis')
    def test_get_redis_connection_without_auth(self, mock_redis):
        """Тест подключения к Redis без аутентификации"""
        # Мокаем переменные окружения
        with patch('src.config.REDIS_USER', None), \
             patch('src.config.REDIS_PASSWORD', None), \
             patch('src.config.REDIS_HOST', 'localhost'), \
             patch('src.config.REDIS_PORT', 6379):
            
            redis_client = get_redis_connection()
            
            # Проверяем, что Redis был вызван с правильными параметрами
            mock_redis.assert_called_with(
                host='localhost',
                port=6379,
                db=0,
                decode_responses=True
            )
    
    @patch('src.database.redis.Redis')
    def test_get_redis_connection_with_auth(self, mock_redis):
        """Тест подключения к Redis с аутентификацией"""
        # Мокаем переменные окружения
        with patch('src.config.REDIS_USER', 'test_user'), \
             patch('src.config.REDIS_PASSWORD', 'test_password'), \
             patch('src.config.REDIS_HOST', 'localhost'), \
             patch('src.config.REDIS_PORT', 6379):
            
            redis_client = get_redis_connection()
            
            # Проверяем, что Redis был вызван с правильными параметрами
            mock_redis.assert_called_with(
                host='localhost',
                port=6379,
                username='test_user',
                password='test_password',
                db=0,
                decode_responses=True
            )
    
    @patch('src.database.psycopg2.connect')
    def test_get_db_connection(self, mock_connect):
        """Тест подключения к PostgreSQL"""
        # Мокаем переменные окружения
        with patch('src.config.DB_HOST', 'localhost'), \
             patch('src.config.DB_NAME', 'test_db'), \
             patch('src.config.DB_USER', 'test_user'), \
             patch('src.config.DB_PASSWORD', 'test_password'):
            
            conn = get_db_connection()
            
            # Проверяем, что psycopg2.connect был вызван с правильными параметрами
            mock_connect.assert_called_with(
                host='localhost',
                database='test_db',
                user='test_user',
                password='test_password'
            )

if __name__ == '__main__':
    unittest.main()