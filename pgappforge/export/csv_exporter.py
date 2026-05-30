"""
CSV Export Implementation.

Provides comprehensive CSV export functionality with customizable formatting,
encoding, and delimiter options.
"""

import csv
import logging
from io import StringIO
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, date

log = logging.getLogger(__name__)


class CSVExporter:
    """
    CSV format exporter with advanced formatting options.
    
    Supports customizable delimiters, encoding, quoting, and metadata inclusion.
    """
    
    def __init__(self):
        """Initialize CSV exporter with default settings."""
        self.default_options = {
            'delimiter': ',',
            'quotechar': '"',
            'quoting': csv.QUOTE_MINIMAL,
            'encoding': 'utf-8',
            'include_metadata': True,
            'include_headers': True,
            'date_format': '%Y-%m-%d',
            'datetime_format': '%Y-%m-%d %H:%M:%S',
            'null_value': '',
            'boolean_format': {'true': 'True', 'false': 'False'}
        }
    
    def export(self, 
               data: List[Dict[str, Any]],
               filename: str,
               metadata: Optional[Dict[str, Any]] = None,
               options: Optional[Dict[str, Any]] = None) -> str:
        """
        Export data to CSV format.
        
        Args:
            data: List of dictionaries containing the data
            filename: Target filename
            metadata: Export metadata
            options: CSV-specific export options
            
        Returns:
            CSV content as string
        """
        try:
            # Merge options with defaults
            export_options = {**self.default_options, **(options or {})}
            
            # Create string buffer
            output = StringIO()
            
            # Add metadata header if requested
            if export_options.get('include_metadata', True) and metadata:
                self._write_metadata_header(output, metadata, export_options)
            
            # Write CSV data
            if data:
                self._write_csv_data(output, data, export_options)
            else:
                # Handle empty data case
                output.write("# No data available for export\n")
            
            csv_content = output.getvalue()
            output.close()
            
            log.info(f"CSV export completed: {len(data)} records, {len(csv_content)} characters")
            return csv_content
            
        except Exception as e:
            log.error(f"CSV export failed: {e}")
            raise
    
    def _write_metadata_header(self, output: StringIO, 
                              metadata: Dict[str, Any], 
                              options: Dict[str, Any]) -> None:
        """
        Write metadata header to CSV output.
        
        Args:
            output: StringIO output buffer
            metadata: Metadata to write
            options: Export options
        """
        try:
            output.write("# Export Metadata\n")
            
            for key, value in metadata.items():
                if value is not None:
                    # Format value appropriately
                    if isinstance(value, (datetime, date)):
                        if isinstance(value, datetime):
                            formatted_value = value.strftime(options['datetime_format'])
                        else:
                            formatted_value = value.strftime(options['date_format'])
                    else:
                        formatted_value = str(value)
                    
                    output.write(f"# {key}: {formatted_value}\n")
            
            output.write("#\n")  # Separator line
            
        except Exception as e:
            log.warning(f"Error writing CSV metadata header: {e}")
    
    def _write_csv_data(self, output: StringIO, 
                       data: List[Dict[str, Any]], 
                       options: Dict[str, Any]) -> None:
        """
        Write actual CSV data.
        
        Args:
            output: StringIO output buffer
            data: Data to write
            options: Export options
        """
        try:
            # Get all unique keys from data for headers
            headers = set()
            for row in data:
                headers.update(row.keys())
            
            headers = sorted(list(headers))  # Sort for consistent output
            
            # Create CSV writer
            writer = csv.DictWriter(
                output,
                fieldnames=headers,
                delimiter=options['delimiter'],
                quotechar=options['quotechar'],
                quoting=options['quoting'],
                restval=options['null_value']
            )
            
            # Write headers if requested
            if options.get('include_headers', True):
                writer.writeheader()
            
            # Write data rows with formatting
            for row in data:
                formatted_row = self._format_row(row, options)
                writer.writerow(formatted_row)
                
        except Exception as e:
            log.error(f"Error writing CSV data: {e}")
            raise
    
    def _format_row(self, row: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format a single row for CSV output.
        
        Args:
            row: Row data dictionary
            options: Export options
            
        Returns:
            Formatted row dictionary
        """
        formatted_row = {}
        
        for key, value in row.items():
            if value is None:
                formatted_value = options['null_value']
                
            elif isinstance(value, bool):
                boolean_format = options.get('boolean_format', {})
                formatted_value = boolean_format.get('true' if value else 'false', str(value))
                
            elif isinstance(value, datetime):
                formatted_value = value.strftime(options['datetime_format'])
                
            elif isinstance(value, date):
                formatted_value = value.strftime(options['date_format'])
                
            elif isinstance(value, (list, tuple)):
                # Convert lists/tuples to comma-separated strings
                formatted_value = '; '.join(str(item) for item in value)
                
            elif isinstance(value, dict):
                # Convert dictionaries to JSON-like string
                formatted_value = '; '.join(f"{k}: {v}" for k, v in value.items())
                
            else:
                formatted_value = str(value)
            
            formatted_row[key] = formatted_value
        
        return formatted_row
    
    def export_to_file(self, 
                       data: List[Dict[str, Any]],
                       filepath: str,
                       metadata: Optional[Dict[str, Any]] = None,
                       options: Optional[Dict[str, Any]] = None) -> None:
        """
        Export data directly to a CSV file.
        
        Args:
            data: Data to export
            filepath: File path to write to
            metadata: Export metadata
            options: Export options
        """
        try:
            csv_content = self.export(data, filepath, metadata, options)
            
            # Get encoding from options
            encoding = options.get('encoding', 'utf-8') if options else 'utf-8'
            
            # Write to file
            with open(filepath, 'w', encoding=encoding, newline='') as f:
                f.write(csv_content)
            
            log.info(f"CSV file written successfully: {filepath}")
            
        except Exception as e:
            log.error(f"Error writing CSV file {filepath}: {e}")
            raise
    
    def validate_options(self, options: Dict[str, Any]) -> List[str]:
        """
        Validate export options and return any warnings.
        
        Args:
            options: Options to validate
            
        Returns:
            List of warning messages
        """
        warnings = []
        
        # Check delimiter
        delimiter = options.get('delimiter', ',')
        if len(delimiter) != 1:
            warnings.append(f"Delimiter should be a single character, got: '{delimiter}'")
        
        # Check quote character
        quotechar = options.get('quotechar', '"')
        if len(quotechar) != 1:
            warnings.append(f"Quote character should be a single character, got: '{quotechar}'")
        
        # Check encoding
        encoding = options.get('encoding', 'utf-8')
        try:
            'test'.encode(encoding)
        except LookupError:
            warnings.append(f"Unknown encoding: {encoding}")
        
        # Check date formats
        for format_key in ['date_format', 'datetime_format']:
            format_str = options.get(format_key)
            if format_str:
                try:
                    datetime.now().strftime(format_str)
                except ValueError:
                    warnings.append(f"Invalid {format_key}: {format_str}")
        
        return warnings
    
    def get_sample_options(self) -> Dict[str, Any]:
        """
        Get sample configuration options with explanations.
        
        Returns:
            Dictionary with sample options and their descriptions
        """
        return {
            'delimiter': {
                'value': ',',
                'description': 'Field delimiter character (comma, semicolon, tab, etc.)',
                'examples': [',', ';', '\t', '|']
            },
            'quotechar': {
                'value': '"',
                'description': 'Character used to quote fields containing special characters',
                'examples': ['"', "'"]
            },
            'encoding': {
                'value': 'utf-8',
                'description': 'Character encoding for the output file',
                'examples': ['utf-8', 'utf-16', 'latin-1', 'cp1252']
            },
            'include_metadata': {
                'value': True,
                'description': 'Include export metadata as comments at the top of the file'
            },
            'include_headers': {
                'value': True,
                'description': 'Include column headers as the first row'
            },
            'date_format': {
                'value': '%Y-%m-%d',
                'description': 'Format string for date values',
                'examples': ['%Y-%m-%d', '%d/%m/%Y', '%m-%d-%Y']
            },
            'datetime_format': {
                'value': '%Y-%m-%d %H:%M:%S',
                'description': 'Format string for datetime values',
                'examples': ['%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %I:%M %p']
            },
            'null_value': {
                'value': '',
                'description': 'String representation of null/None values',
                'examples': ['', 'NULL', 'N/A', '-']
            }
        }