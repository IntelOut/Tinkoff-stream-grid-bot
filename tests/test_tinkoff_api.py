import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Добавляем src в путь для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.tinkoff_api import makefloat, makequotation

class TestTinkoffAPI(unittest.TestCase):
    
    def test_makefloat(self):
        """Тест функции makefloat"""
        # Создаем мок объект с units и nano
        mock_quotation = MagicMock()
        mock_quotation.units = 10
        mock_quotation.nano = 500000000  # 0.5 в наноединицах
        
        result = makefloat(mock_quotation)
        expected = 10.5
        self.assertEqual(result, expected)
    
    def test_makequotation_from_number(self):
        """Тест функции makequotation с числового значения"""
        from tinkoff.invest import Quotation
        
        price = 10.5
        result = makequotation(price)
        
        self.assertIsInstance(result, Quotation)
        self.assertEqual(result.units, 10)
        self.assertEqual(result.nano, 500000000)  # 0.5 в наноединицах
    
    def test_makequotation_from_quotation(self):
        """Тест функции makequotation с объекта Quotation"""
        from tinkoff.invest import Quotation
        
        # Создаем исходный объект Quotation
        original = Quotation(units=10, nano=500000000)
        result = makequotation(original)
        
        # Результат должен быть тем же объектом
        self.assertIs(result, original)

if __name__ == '__main__':
    unittest.main()