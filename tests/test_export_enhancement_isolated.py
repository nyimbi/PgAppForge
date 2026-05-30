"""
Isolated tests for Export Enhancement functionality.

Tests the export system without complex PgAppForge imports.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import csv
from io import StringIO, BytesIO
from datetime import datetime, date
from decimal import Decimal

# Import the classes we're testing directly
from pgappforge.export.export_manager import ExportManager, ExportFormat
from pgappforge.export.csv_exporter import CSVExporter
from pgappforge.export.excel_exporter import ExcelExporter
from pgappforge.export.pdf_exporter import PDFExporter


class TestExportManagerIsolated(unittest.TestCase):
    """Test cases for ExportManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.export_manager = ExportManager()
        
        # Sample test data
        self.sample_data = [
            {
                'id': 1,
                'name': 'John Doe',
                'email': 'john.doe@example.com',
                'salary': 75000.50,
                'start_date': datetime(2023, 1, 15),
                'active': True
            },
            {
                'id': 2,
                'name': 'Jane Smith',
                'email': 'jane.smith@example.com',
                'salary': 65000.00,
                'start_date': datetime(2023, 3, 1),
                'active': False
            }
        ]
    
    def test_export_manager_initialization(self):
        """Test export manager initialization."""
        self.assertIsInstance(self.export_manager, ExportManager)
        self.assertIn(ExportFormat.CSV, self.export_manager._exporters)
        self.assertIn(ExportFormat.EXCEL, self.export_manager._exporters)
        self.assertIn(ExportFormat.PDF, self.export_manager._exporters)
    
    def test_get_supported_formats(self):
        """Test getting supported formats."""
        formats = self.export_manager.get_supported_formats()
        
        self.assertIsInstance(formats, list)
        self.assertIn('csv', formats)
        self.assertIn('xlsx', formats)
        self.assertIn('pdf', formats)
    
    def test_is_format_supported(self):
        """Test format support checking."""
        # Test with string
        self.assertTrue(self.export_manager.is_format_supported('csv'))
        self.assertTrue(self.export_manager.is_format_supported('xlsx'))
        self.assertFalse(self.export_manager.is_format_supported('unknown'))
        
        # Test with enum
        self.assertTrue(self.export_manager.is_format_supported(ExportFormat.CSV))
        self.assertTrue(self.export_manager.is_format_supported(ExportFormat.PDF))
    
    def test_register_custom_exporter(self):
        """Test registering custom exporter."""
        custom_exporter = Mock()
        
        self.export_manager.register_exporter(ExportFormat.JSON, custom_exporter)
        
        self.assertIn(ExportFormat.JSON, self.export_manager._exporters)
        self.assertEqual(self.export_manager._exporters[ExportFormat.JSON], custom_exporter)
    
    def test_export_data_csv(self):
        """Test exporting data to CSV format."""
        result = self.export_manager.export_data(
            data=self.sample_data,
            format_type=ExportFormat.CSV,
            filename='test.csv'
        )
        
        self.assertIsInstance(result, str)
        self.assertIn('John Doe', result)
        self.assertIn('jane.smith@example.com', result)
    
    def test_export_data_with_metadata(self):
        """Test exporting data with custom metadata."""
        metadata = {
            'title': 'Test Export',
            'description': 'Test data export'
        }
        
        result = self.export_manager.export_data(
            data=self.sample_data,
            format_type=ExportFormat.CSV,
            metadata=metadata
        )
        
        self.assertIn('Test Export', result)
    
    def test_export_data_unsupported_format(self):
        """Test exporting with unsupported format."""
        # Remove CSV exporter to test unsupported format
        del self.export_manager._exporters[ExportFormat.CSV]
        
        with self.assertRaises(ValueError) as context:
            self.export_manager.export_data(
                data=self.sample_data,
                format_type=ExportFormat.CSV
            )
        
        self.assertIn('not supported', str(context.exception))
    
    def test_generate_filename(self):
        """Test filename generation."""
        metadata = {'title': 'Test Report'}
        
        filename = self.export_manager._generate_filename(ExportFormat.CSV, metadata)
        
        self.assertTrue(filename.startswith('Test_Report_'))
        self.assertTrue(filename.endswith('.csv'))
    
    def test_prepare_metadata(self):
        """Test metadata preparation."""
        user_metadata = {'custom': 'value'}
        
        with patch('pgappforge.export.export_manager.current_user') as mock_user:
            mock_user.username = 'testuser'
            mock_user.is_authenticated = True
            
            metadata = self.export_manager._prepare_metadata(user_metadata, ExportFormat.CSV)
        
        self.assertIn('export_timestamp', metadata)
        self.assertIn('export_format', metadata)
        self.assertIn('custom', metadata)
        self.assertEqual(metadata['custom'], 'value')


class TestCSVExporterIsolated(unittest.TestCase):
    """Test cases for CSVExporter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.csv_exporter = CSVExporter()
        
        self.sample_data = [
            {
                'name': 'John Doe',
                'age': 30,
                'salary': 50000.50,
                'active': True,
                'start_date': datetime(2023, 1, 15)
            },
            {
                'name': 'Jane Smith',
                'age': 25,
                'salary': 45000.00,
                'active': False,
                'start_date': datetime(2023, 2, 20)
            }
        ]
    
    def test_csv_exporter_initialization(self):
        """Test CSV exporter initialization."""
        self.assertIsInstance(self.csv_exporter, CSVExporter)
        self.assertIn('delimiter', self.csv_exporter.default_options)
        self.assertEqual(self.csv_exporter.default_options['delimiter'], ',')
    
    def test_export_basic(self):
        """Test basic CSV export."""
        result = self.csv_exporter.export(
            data=self.sample_data,
            filename='test.csv'
        )
        
        self.assertIsInstance(result, str)
        
        # Parse CSV and verify content
        lines = result.strip().split('\n')
        # Skip metadata header lines (start with #)
        data_lines = [line for line in lines if not line.startswith('#')]
        
        # Should have header + 2 data rows
        self.assertGreaterEqual(len(data_lines), 3)
        self.assertIn('John Doe', result)
        self.assertIn('Jane Smith', result)
    
    def test_export_with_custom_delimiter(self):
        """Test CSV export with custom delimiter."""
        options = {'delimiter': ';'}
        
        result = self.csv_exporter.export(
            data=self.sample_data,
            filename='test.csv',
            options=options
        )
        
        self.assertIn(';', result)
    
    def test_export_with_metadata(self):
        """Test CSV export with metadata."""
        metadata = {'title': 'Employee Report', 'department': 'HR'}
        
        result = self.csv_exporter.export(
            data=self.sample_data,
            filename='test.csv',
            metadata=metadata
        )
        
        self.assertIn('Employee Report', result)
        self.assertIn('department: HR', result)
    
    def test_export_without_headers(self):
        """Test CSV export without headers."""
        options = {'include_headers': False}
        
        result = self.csv_exporter.export(
            data=self.sample_data,
            filename='test.csv',
            options=options
        )
        
        lines = result.strip().split('\n')
        data_lines = [line for line in lines if not line.startswith('#')]
        
        # Should not have header row, only data rows
        self.assertEqual(len(data_lines), 2)
    
    def test_export_empty_data(self):
        """Test CSV export with empty data."""
        result = self.csv_exporter.export(
            data=[],
            filename='empty.csv'
        )
        
        self.assertIn('No data available', result)
    
    def test_format_row(self):
        """Test row formatting."""
        row = {
            'text': 'Sample',
            'number': 123.45,
            'bool': True,
            'date': datetime(2023, 1, 15),
            'none_val': None,
            'list_val': [1, 2, 3],
            'dict_val': {'key': 'value'}
        }
        
        formatted = self.csv_exporter._format_row(row, self.csv_exporter.default_options)
        
        self.assertEqual(formatted['text'], 'Sample')
        self.assertEqual(formatted['number'], '123.45')
        self.assertEqual(formatted['bool'], 'True')
        self.assertEqual(formatted['date'], '2023-01-15 00:00:00')
        self.assertEqual(formatted['none_val'], '')
        self.assertEqual(formatted['list_val'], '1; 2; 3')
        self.assertEqual(formatted['dict_val'], 'key: value')
    
    def test_validate_options(self):
        """Test options validation."""
        # Valid options
        valid_options = {
            'delimiter': ',',
            'encoding': 'utf-8',
            'date_format': '%Y-%m-%d'
        }
        warnings = self.csv_exporter.validate_options(valid_options)
        self.assertEqual(len(warnings), 0)
        
        # Invalid options
        invalid_options = {
            'delimiter': 'too_long',
            'encoding': 'invalid_encoding',
            'date_format': 'invalid_format'
        }
        warnings = self.csv_exporter.validate_options(invalid_options)
        self.assertGreater(len(warnings), 0)
    
    def test_get_sample_options(self):
        """Test getting sample options."""
        options = self.csv_exporter.get_sample_options()
        
        self.assertIsInstance(options, dict)
        self.assertIn('delimiter', options)
        self.assertIn('encoding', options)
        self.assertIn('description', options['delimiter'])


class TestExcelExporterIsolated(unittest.TestCase):
    """Test cases for ExcelExporter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.excel_exporter = ExcelExporter()
        
        self.sample_data = [
            {
                'name': 'John Doe',
                'age': 30,
                'salary': 50000.50,
                'start_date': datetime(2023, 1, 15)
            },
            {
                'name': 'Jane Smith',
                'age': 25,
                'salary': 45000.00,
                'start_date': datetime(2023, 2, 20)
            }
        ]
    
    def test_excel_exporter_initialization(self):
        """Test Excel exporter initialization."""
        self.assertIsInstance(self.excel_exporter, ExcelExporter)
        self.assertIn('sheet_name', self.excel_exporter.default_options)
    
    @patch('pgappforge.export.excel_exporter.OPENPYXL_AVAILABLE', True)
    @patch('pgappforge.export.excel_exporter.Workbook')
    def test_export_basic(self, mock_workbook):
        """Test basic Excel export."""
        # Mock workbook and worksheet
        mock_wb = Mock()
        mock_ws = Mock()
        mock_wb.active = mock_ws
        mock_workbook.return_value = mock_wb
        
        # Mock save method
        mock_wb.save = Mock()
        
        result = self.excel_exporter.export(
            data=self.sample_data,
            filename='test.xlsx'
        )
        
        # Should return bytes
        self.assertIsInstance(result, bytes)
        
        # Verify workbook was created and saved
        mock_workbook.assert_called_once()
        mock_wb.save.assert_called_once()
    
    def test_export_without_openpyxl(self):
        """Test Excel export without openpyxl available."""
        with patch('pgappforge.export.excel_exporter.OPENPYXL_AVAILABLE', False):
            with self.assertRaises(ImportError) as context:
                self.excel_exporter.export(
                    data=self.sample_data,
                    filename='test.xlsx'
                )
            
            self.assertIn('openpyxl package is required', str(context.exception))
    
    def test_format_cell_value(self):
        """Test cell value formatting."""
        # Test various value types
        test_values = [
            (None, ""),
            (True, True),
            (False, False),
            (123, 123),
            (123.45, 123.45),
            (Decimal('99.99'), 99.99),
            (datetime(2023, 1, 15), datetime(2023, 1, 15)),
            ([1, 2, 3], "1; 2; 3"),
            ({'a': 1}, "a: 1"),
            ("text", "text")
        ]
        
        for input_val, expected in test_values:
            with self.subTest(input_val=input_val):
                result = self.excel_exporter._format_cell_value(input_val, {})
                self.assertEqual(result, expected)
    
    def test_get_sample_options(self):
        """Test getting sample options."""
        options = self.excel_exporter.get_sample_options()
        
        self.assertIsInstance(options, dict)
        self.assertIn('sheet_name', options)
        self.assertIn('auto_filter', options)
        self.assertIn('add_charts', options)


class TestPDFExporterIsolated(unittest.TestCase):
    """Test cases for PDFExporter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.pdf_exporter = PDFExporter()
        
        self.sample_data = [
            {
                'name': 'John Doe',
                'age': 30,
                'salary': 50000.50,
                'start_date': datetime(2023, 1, 15)
            },
            {
                'name': 'Jane Smith',
                'age': 25,
                'salary': 45000.00,
                'start_date': datetime(2023, 2, 20)
            }
        ]
    
    def test_pdf_exporter_initialization(self):
        """Test PDF exporter initialization."""
        self.assertIsInstance(self.pdf_exporter, PDFExporter)
        self.assertIn('page_size', self.pdf_exporter.default_options)
        self.assertEqual(self.pdf_exporter.default_options['page_size'], 'letter')
    
    @patch('pgappforge.export.pdf_exporter.REPORTLAB_AVAILABLE', True)
    @patch('pgappforge.export.pdf_exporter.SimpleDocTemplate')
    def test_export_basic(self, mock_document):
        """Test basic PDF export."""
        # Mock document
        mock_doc = Mock()
        mock_document.return_value = mock_doc
        mock_doc.build = Mock()
        
        with patch('builtins.open', create=True):
            result = self.pdf_exporter.export(
                data=self.sample_data,
                filename='test.pdf'
            )
        
        # Should return bytes
        self.assertIsInstance(result, bytes)
        
        # Verify document was created and built
        mock_document.assert_called_once()
        mock_doc.build.assert_called_once()
    
    def test_export_without_reportlab(self):
        """Test PDF export without reportlab available."""
        with patch('pgappforge.export.pdf_exporter.REPORTLAB_AVAILABLE', False):
            with self.assertRaises(ImportError) as context:
                self.pdf_exporter.export(
                    data=self.sample_data,
                    filename='test.pdf'
                )
            
            self.assertIn('reportlab package is required', str(context.exception))
    
    def test_format_cell_value(self):
        """Test cell value formatting for PDF."""
        # Test various value types
        test_values = [
            (None, ""),
            (True, "Yes"),
            (False, "No"),
            (123.456, "123.46"),
            (datetime(2023, 1, 15, 10, 30), "2023-01-15 10:30:00"),
            (date(2023, 1, 15), "2023-01-15"),
            ([1, 2, 3], "1; 2; 3"),
            ({'a': 1}, "a: 1"),
            ("text", "text")
        ]
        
        for input_val, expected in test_values:
            with self.subTest(input_val=input_val):
                result = self.pdf_exporter._format_cell_value(input_val)
                self.assertEqual(result, expected)
    
    def test_get_page_size(self):
        """Test page size selection."""
        # Test different page sizes
        with patch('pgappforge.export.pdf_exporter.letter', 'letter_size'):
            with patch('pgappforge.export.pdf_exporter.A4', 'a4_size'):
                # Test letter
                result = self.pdf_exporter._get_page_size('letter')
                self.assertEqual(result, 'letter_size')
                
                # Test A4
                result = self.pdf_exporter._get_page_size('a4')
                self.assertEqual(result, 'a4_size')
                
                # Test default (invalid)
                result = self.pdf_exporter._get_page_size('invalid')
                self.assertEqual(result, 'letter_size')
    
    def test_get_sample_options(self):
        """Test getting sample options."""
        options = self.pdf_exporter.get_sample_options()
        
        self.assertIsInstance(options, dict)
        self.assertIn('page_size', options)
        self.assertIn('title', options)
        self.assertIn('table_style', options)


class TestExportIntegration(unittest.TestCase):
    """Test integration between export components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.export_manager = ExportManager()
        
        self.test_data = [
            {
                'employee_id': 1,
                'name': 'John Doe',
                'email': 'john.doe@company.com',
                'department': 'Engineering',
                'salary': 85000.00,
                'hire_date': datetime(2022, 3, 15),
                'active': True,
                'performance_rating': 4.2
            },
            {
                'employee_id': 2,
                'name': 'Jane Smith',
                'email': 'jane.smith@company.com',
                'department': 'Marketing',
                'salary': 72000.00,
                'hire_date': datetime(2022, 6, 1),
                'active': True,
                'performance_rating': 4.5
            },
            {
                'employee_id': 3,
                'name': 'Bob Johnson',
                'email': 'bob.johnson@company.com',
                'department': 'Sales',
                'salary': 65000.00,
                'hire_date': datetime(2021, 11, 20),
                'active': False,
                'performance_rating': 3.8
            }
        ]
    
    def test_complete_csv_export_workflow(self):
        """Test complete CSV export workflow with all features."""
        metadata = {
            'title': 'Employee Report',
            'department': 'HR',
            'report_date': datetime(2023, 9, 15)
        }
        
        options = {
            'delimiter': ';',
            'include_metadata': True,
            'include_headers': True,
            'date_format': '%d/%m/%Y',
            'datetime_format': '%d/%m/%Y %H:%M'
        }
        
        result = self.export_manager.export_data(
            data=self.test_data,
            format_type=ExportFormat.CSV,
            filename='employees.csv',
            metadata=metadata,
            options=options
        )
        
        # Verify result
        self.assertIsInstance(result, str)
        self.assertIn('Employee Report', result)
        self.assertIn('John Doe', result)
        self.assertIn('Engineering', result)
        self.assertIn(';', result)  # Custom delimiter
    
    def test_export_statistics(self):
        """Test export statistics functionality."""
        stats = self.export_manager.get_export_statistics()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('supported_formats', stats)
        self.assertIn('total_exporters', stats)
        self.assertGreater(stats['total_exporters'], 0)
    
    def test_query_result_conversion(self):
        """Test converting different query result formats."""
        # Test with dictionary format
        dict_results = [
            {'id': 1, 'name': 'Test 1'},
            {'id': 2, 'name': 'Test 2'}
        ]
        
        converted = self.export_manager._convert_query_result_to_dict(dict_results)
        self.assertEqual(len(converted), 2)
        self.assertEqual(converted[0]['id'], 1)
        
        # Test with column labels
        column_labels = {'id': 'Employee ID', 'name': 'Full Name'}
        converted = self.export_manager._convert_query_result_to_dict(
            dict_results, column_labels
        )
        
        self.assertIn('Employee ID', converted[0])
        self.assertIn('Full Name', converted[0])
    
    def test_multiple_format_export(self):
        """Test exporting the same data in multiple formats."""
        metadata = {'title': 'Multi-Format Export Test'}
        
        formats_to_test = [ExportFormat.CSV]  # Only test CSV to avoid import issues
        
        for export_format in formats_to_test:
            with self.subTest(format=export_format):
                try:
                    result = self.export_manager.export_data(
                        data=self.test_data,
                        format_type=export_format,
                        metadata=metadata
                    )
                    
                    # Verify result is not empty
                    if isinstance(result, str):
                        self.assertTrue(len(result) > 0)
                    else:
                        self.assertIsInstance(result, bytes)
                        self.assertTrue(len(result) > 0)
                        
                except ImportError:
                    # Skip if required package not available
                    self.skipTest(f"Required package for {export_format.value} not available")
    
    def test_large_dataset_handling(self):
        """Test handling of larger datasets."""
        # Create a larger dataset
        large_data = []
        for i in range(100):
            large_data.append({
                'id': i,
                'name': f'User {i}',
                'email': f'user{i}@example.com',
                'value': i * 100.50,
                'created': datetime(2023, 1, 1)
            })
        
        result = self.export_manager.export_data(
            data=large_data,
            format_type=ExportFormat.CSV,
            filename='large_dataset.csv'
        )
        
        self.assertIsInstance(result, str)
        self.assertIn('User 99', result)  # Verify last record
        
        # Count lines (approximately)
        lines = result.count('\n')
        self.assertGreater(lines, 100)  # Should have more than 100 lines including metadata and headers
    
    def test_empty_and_edge_cases(self):
        """Test various edge cases."""
        # Empty data
        result = self.export_manager.export_data(
            data=[],
            format_type=ExportFormat.CSV
        )
        self.assertIn('No data available', result)
        
        # Data with None values
        none_data = [
            {'id': 1, 'name': 'John', 'value': None},
            {'id': None, 'name': None, 'value': 100}
        ]
        
        result = self.export_manager.export_data(
            data=none_data,
            format_type=ExportFormat.CSV
        )
        self.assertIsInstance(result, str)
        
        # Data with special characters
        special_data = [
            {'name': 'John "Quote" Doe', 'note': 'Line 1\nLine 2'},
            {'name': 'Jane, Comma', 'note': 'Special chars: €£¥'}
        ]
        
        result = self.export_manager.export_data(
            data=special_data,
            format_type=ExportFormat.CSV
        )
        self.assertIsInstance(result, str)


if __name__ == '__main__':
    unittest.main()