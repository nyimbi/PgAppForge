"""
Export Manager for coordinating different export formats.

Provides a unified interface for exporting data in various formats (CSV, Excel, PDF)
with customizable formatting and metadata options.
"""

import logging
from enum import Enum
from typing import List, Dict, Any, Optional, Union, IO
from datetime import datetime
from io import BytesIO, StringIO

from flask import current_app
from flask_login import current_user

log = logging.getLogger(__name__)


class ExportFormat(Enum):
    """Supported export formats."""
    CSV = "csv"
    EXCEL = "xlsx" 
    PDF = "pdf"
    JSON = "json"


class ExportManager:
    """
    Central manager for coordinating data exports.
    
    Handles export requests, format selection, and delegates to specific
    exporter implementations while maintaining consistent metadata and formatting.
    """
    
    def __init__(self, app=None):
        """
        Initialize the export manager.
        
        Args:
            app: Flask application instance (optional)
        """
        self.app = app
        self._exporters = {}
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """
        Initialize the export manager with Flask app.
        
        Args:
            app: Flask application instance
        """
        self.app = app
        
        # Register default exporters
        self._register_default_exporters()
        
        # Store reference in app
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['export_manager'] = self
    
    def _register_default_exporters(self):
        """Register default exporter implementations."""
        from .csv_exporter import CSVExporter
        from .excel_exporter import ExcelExporter
        from .pdf_exporter import PDFExporter
        
        self._exporters[ExportFormat.CSV] = CSVExporter()
        self._exporters[ExportFormat.EXCEL] = ExcelExporter()
        self._exporters[ExportFormat.PDF] = PDFExporter()
    
    def register_exporter(self, format_type: ExportFormat, exporter):
        """
        Register a custom exporter for a specific format.
        
        Args:
            format_type: Export format enum
            exporter: Exporter implementation
        """
        self._exporters[format_type] = exporter
        log.info(f"Registered custom exporter for {format_type.value}")
    
    def export_data(self, 
                    data: List[Dict[str, Any]], 
                    format_type: ExportFormat,
                    filename: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None,
                    options: Optional[Dict[str, Any]] = None) -> Union[str, bytes, IO]:
        """
        Export data in the specified format.
        
        Args:
            data: List of dictionaries containing the data to export
            format_type: Target export format
            filename: Optional filename (will be generated if not provided)
            metadata: Optional metadata to include in export
            options: Format-specific export options
            
        Returns:
            Exported data as string, bytes, or IO object depending on format
            
        Raises:
            ValueError: If format is not supported
            Exception: If export fails
        """
        try:
            # Validate format
            if format_type not in self._exporters:
                raise ValueError(f"Export format {format_type.value} is not supported")
            
            # Prepare metadata
            export_metadata = self._prepare_metadata(metadata, format_type)
            
            # Generate filename if not provided
            if not filename:
                filename = self._generate_filename(format_type, export_metadata)
            
            # Get exporter and perform export
            exporter = self._exporters[format_type]
            
            log.info(f"Starting export to {format_type.value} format: {filename}")
            
            result = exporter.export(
                data=data,
                filename=filename,
                metadata=export_metadata,
                options=options or {}
            )
            
            log.info(f"Export completed successfully: {filename}")
            return result
            
        except Exception as e:
            log.error(f"Export failed for format {format_type.value}: {e}")
            raise
    
    def export_query_result(self,
                           query_result,
                           format_type: ExportFormat,
                           filename: Optional[str] = None,
                           column_labels: Optional[Dict[str, str]] = None,
                           metadata: Optional[Dict[str, Any]] = None,
                           options: Optional[Dict[str, Any]] = None) -> Union[str, bytes, IO]:
        """
        Export SQLAlchemy query result in the specified format.
        
        Args:
            query_result: SQLAlchemy query result or list of model instances
            format_type: Target export format
            filename: Optional filename
            column_labels: Optional mapping of column names to display labels
            metadata: Optional metadata to include
            options: Format-specific options
            
        Returns:
            Exported data
        """
        try:
            # Convert query result to dictionary format
            data = self._convert_query_result_to_dict(query_result, column_labels)
            
            # Add query metadata
            if metadata is None:
                metadata = {}
            
            metadata.update({
                'record_count': len(data),
                'query_executed_at': datetime.now().isoformat(),
                'exported_by': getattr(current_user, 'username', 'system') if current_user.is_authenticated else 'anonymous'
            })
            
            return self.export_data(data, format_type, filename, metadata, options)
            
        except Exception as e:
            log.error(f"Query result export failed: {e}")
            raise
    
    def get_supported_formats(self) -> List[str]:
        """
        Get list of supported export formats.
        
        Returns:
            List of supported format strings
        """
        return [fmt.value for fmt in self._exporters.keys()]
    
    def is_format_supported(self, format_type: Union[str, ExportFormat]) -> bool:
        """
        Check if a format is supported.
        
        Args:
            format_type: Format to check (string or enum)
            
        Returns:
            True if format is supported
        """
        if isinstance(format_type, str):
            try:
                format_type = ExportFormat(format_type)
            except ValueError:
                return False
        
        return format_type in self._exporters
    
    def _prepare_metadata(self, metadata: Optional[Dict[str, Any]], 
                         format_type: ExportFormat) -> Dict[str, Any]:
        """
        Prepare metadata for export.
        
        Args:
            metadata: User-provided metadata
            format_type: Export format
            
        Returns:
            Complete metadata dictionary
        """
        export_metadata = {
            'export_timestamp': datetime.now().isoformat(),
            'export_format': format_type.value,
            'exported_by': getattr(current_user, 'username', 'system') if current_user.is_authenticated else 'anonymous',
            'application': current_app.config.get('APP_NAME', 'PgForge'),
            'version': '1.0.0'
        }
        
        if metadata:
            export_metadata.update(metadata)
        
        return export_metadata
    
    def _generate_filename(self, format_type: ExportFormat, 
                          metadata: Dict[str, Any]) -> str:
        """
        Generate a filename for export.
        
        Args:
            format_type: Export format
            metadata: Export metadata
            
        Returns:
            Generated filename
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = metadata.get('title', 'export')
        
        # Sanitize base name
        base_name = ''.join(c for c in base_name if c.isalnum() or c in (' ', '-', '_')).strip()
        base_name = base_name.replace(' ', '_')
        
        return f"{base_name}_{timestamp}.{format_type.value}"
    
    def _convert_query_result_to_dict(self, query_result, 
                                    column_labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Convert SQLAlchemy query result to list of dictionaries.
        
        Args:
            query_result: Query result to convert
            column_labels: Optional column label mapping
            
        Returns:
            List of dictionaries representing the data
        """
        data = []
        
        try:
            for row in query_result:
                row_dict = {}
                
                # Handle different types of query results
                if hasattr(row, '__table__'):
                    # SQLAlchemy model instance
                    for column in row.__table__.columns:
                        value = getattr(row, column.name)
                        
                        # Convert datetime to string
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        
                        # Use label if provided, otherwise use column name
                        key = column_labels.get(column.name, column.name) if column_labels else column.name
                        row_dict[key] = value
                        
                elif hasattr(row, '_asdict'):
                    # Named tuple (from query with specific columns)
                    row_dict = row._asdict()
                    
                    # Apply column labels if provided
                    if column_labels:
                        labeled_dict = {}
                        for key, value in row_dict.items():
                            labeled_key = column_labels.get(key, key)
                            labeled_dict[labeled_key] = value
                        row_dict = labeled_dict
                        
                elif isinstance(row, dict):
                    # Already a dictionary
                    row_dict = row.copy()
                    
                else:
                    # Try to convert to dict
                    row_dict = dict(row) if hasattr(row, 'keys') else {'value': str(row)}
                
                data.append(row_dict)
                
        except Exception as e:
            log.warning(f"Error converting query result row: {e}")
            # Fallback: try to convert entire result to string representation
            data.append({'data': str(query_result)})
        
        return data
    
    def get_export_statistics(self) -> Dict[str, Any]:
        """
        Get export usage statistics.
        
        Returns:
            Dictionary with export statistics
        """
        # This could be enhanced to track actual usage statistics
        return {
            'supported_formats': self.get_supported_formats(),
            'total_exporters': len(self._exporters),
            'last_updated': datetime.now().isoformat()
        }