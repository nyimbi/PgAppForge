"""
Export Views for PgAppForge Integration.

Provides web interface views for configuring and executing data exports
in various formats (CSV, Excel, PDF).
"""

import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from io import BytesIO

from flask import request, jsonify, send_file, flash, redirect, url_for, Response
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.forms import DynamicForm
from pgappforge.widgets import FormWidget
from flask_login import current_user
from wtforms import SelectField, StringField, TextAreaField, BooleanField, IntegerField
from wtforms.validators import DataRequired, Optional as OptionalValidator, NumberRange

from .export_manager import ExportManager, ExportFormat

log = logging.getLogger(__name__)


class ExportConfigForm(DynamicForm):
    """
    Form for configuring export options.
    
    Allows users to select format, configure options, and customize output.
    """
    
    export_format = SelectField(
        'Export Format',
        choices=[
            ('csv', 'CSV - Comma Separated Values'),
            ('xlsx', 'Excel - Spreadsheet'),
            ('pdf', 'PDF - Portable Document'),
            ('json', 'JSON - JavaScript Object Notation')
        ],
        validators=[DataRequired()],
        default='csv'
    )
    
    filename = StringField(
        'Filename',
        validators=[OptionalValidator()],
        description='Leave empty for auto-generated filename'
    )
    
    title = StringField(
        'Export Title',
        validators=[OptionalValidator()],
        description='Title to include in the export'
    )
    
    include_metadata = BooleanField(
        'Include Metadata',
        default=True,
        description='Include export information (timestamp, user, etc.)'
    )
    
    # Format-specific options
    csv_delimiter = SelectField(
        'CSV Delimiter',
        choices=[
            (',', 'Comma (,)'),
            (';', 'Semicolon (;)'),
            ('\t', 'Tab'),
            ('|', 'Pipe (|)')
        ],
        default=','
    )
    
    csv_encoding = SelectField(
        'CSV Encoding',
        choices=[
            ('utf-8', 'UTF-8'),
            ('utf-16', 'UTF-16'),
            ('latin-1', 'Latin-1'),
            ('cp1252', 'Windows-1252')
        ],
        default='utf-8'
    )
    
    excel_auto_filter = BooleanField(
        'Excel Auto Filter',
        default=True,
        description='Add auto-filter to Excel headers'
    )
    
    excel_freeze_headers = BooleanField(
        'Excel Freeze Headers',
        default=True,
        description='Freeze header row in Excel'
    )
    
    excel_add_charts = BooleanField(
        'Excel Add Charts',
        default=False,
        description='Add charts based on numeric data'
    )
    
    pdf_page_size = SelectField(
        'PDF Page Size',
        choices=[
            ('letter', 'Letter (8.5" x 11")'),
            ('a4', 'A4'),
            ('legal', 'Legal (8.5" x 14")')
        ],
        default='letter'
    )
    
    pdf_table_style = SelectField(
        'PDF Table Style',
        choices=[
            ('default', 'Default'),
            ('minimal', 'Minimal'),
            ('professional', 'Professional'),
            ('colorful', 'Colorful')
        ],
        default='default'
    )
    
    pdf_add_charts = BooleanField(
        'PDF Add Charts',
        default=False,
        description='Add charts to PDF'
    )
    
    max_records = IntegerField(
        'Maximum Records',
        validators=[OptionalValidator(), NumberRange(min=1, max=100000)],
        description='Limit number of records to export (leave empty for all)'
    )
    
    advanced_options = TextAreaField(
        'Advanced Options (JSON)',
        validators=[OptionalValidator()],
        description='Advanced configuration in JSON format'
    )


class ExportView(BaseView):
    """
    Main export configuration and execution view.
    
    Provides interface for users to configure export options and download
    exports in various formats.
    """
    
    route_base = '/export'
    default_view = 'index'
    
    def __init__(self):
        """Initialize export view."""
        super().__init__()
        self.export_manager = None
    
    def _get_export_manager(self) -> ExportManager:
        """Get or create export manager instance."""
        if not self.export_manager:
            self.export_manager = ExportManager(self.appbuilder.app)
        return self.export_manager
    
    @expose('/')
    @has_access
    def index(self):
        """
        Main export configuration page.
        
        Returns:
            Rendered export configuration template
        """
        try:
            form = ExportConfigForm()
            export_manager = self._get_export_manager()
            
            # Get supported formats
            supported_formats = export_manager.get_supported_formats()
            
            return self.render_template(
                'export/export_config.html',
                form=form,
                supported_formats=supported_formats,
                form_widget=FormWidget(form)
            )
            
        except Exception as e:
            log.error(f"Error rendering export configuration: {e}")
            flash(f"Error loading export page: {str(e)}", 'error')
            return self.render_template('export/export_error.html', error=str(e))
    
    @expose('/configure', methods=['GET', 'POST'])
    @has_access
    def configure(self):
        """
        Export configuration endpoint.
        
        Handles both GET (show form) and POST (process form) requests.
        """
        form = ExportConfigForm()
        
        if request.method == 'POST' and form.validate_on_submit():
            try:
                # Process export configuration
                export_config = self._process_export_form(form)
                
                # Store configuration in session for download
                session_key = f"export_config_{datetime.now().timestamp()}"
                # In a real implementation, you'd store this in a database or cache
                # For now, we'll pass it directly to the download endpoint
                
                return redirect(url_for('ExportView.download', config=json.dumps(export_config)))
                
            except Exception as e:
                log.error(f"Error processing export configuration: {e}")
                flash(f"Export configuration error: {str(e)}", 'error')
        
        return self.render_template(
            'export/export_configure.html',
            form=form,
            form_widget=FormWidget(form)
        )
    
    @expose('/download')
    @has_access
    def download(self):
        """
        Export download endpoint.
        
        Generates and returns the export file based on configuration.
        """
        try:
            # Get export configuration
            config_json = request.args.get('config')
            if not config_json:
                flash('No export configuration provided', 'error')
                return redirect(url_for('ExportView.index'))
            
            export_config = json.loads(config_json)
            
            # Get sample data (in real implementation, this would be actual data)
            sample_data = self._get_sample_export_data()
            
            # Perform export
            export_manager = self._get_export_manager()
            export_format = ExportFormat(export_config['format'])
            
            exported_content = export_manager.export_data(
                data=sample_data,
                format_type=export_format,
                filename=export_config.get('filename'),
                metadata=export_config.get('metadata', {}),
                options=export_config.get('options', {})
            )
            
            # Determine content type and filename
            content_type, filename = self._get_download_params(export_format, export_config)
            
            # Return file response
            if isinstance(exported_content, str):
                # String content (CSV, JSON)
                response = Response(
                    exported_content,
                    mimetype=content_type,
                    headers={'Content-Disposition': f'attachment; filename={filename}'}
                )
                return response
            else:
                # Binary content (Excel, PDF)
                return send_file(
                    BytesIO(exported_content),
                    as_attachment=True,
                    download_name=filename,
                    mimetype=content_type
                )
                
        except Exception as e:
            log.error(f"Error generating export download: {e}")
            flash(f"Export failed: {str(e)}", 'error')
            return redirect(url_for('ExportView.index'))
    
    @expose('/api/formats')
    @has_access
    def api_formats(self):
        """
        API endpoint to get supported export formats.
        
        Returns:
            JSON response with supported formats and their options
        """
        try:
            export_manager = self._get_export_manager()
            
            # Get format information
            formats_info = {}
            for format_name in export_manager.get_supported_formats():
                format_enum = ExportFormat(format_name)
                exporter = export_manager._exporters[format_enum]
                
                if hasattr(exporter, 'get_sample_options'):
                    formats_info[format_name] = {
                        'name': format_name.upper(),
                        'description': f'{format_name.upper()} export format',
                        'options': exporter.get_sample_options()
                    }
                else:
                    formats_info[format_name] = {
                        'name': format_name.upper(),
                        'description': f'{format_name.upper()} export format',
                        'options': {}
                    }
            
            return jsonify({
                'status': 'success',
                'formats': formats_info
            })
            
        except Exception as e:
            log.error(f"Error getting formats API data: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @expose('/api/preview')
    @has_access
    def api_preview(self):
        """
        API endpoint to preview export configuration.
        
        Returns:
            JSON response with preview of the export
        """
        try:
            # Get preview parameters
            format_type = request.args.get('format', 'csv')
            max_rows = int(request.args.get('max_rows', '10'))
            
            # Get sample data
            sample_data = self._get_sample_export_data()[:max_rows]
            
            # Generate preview
            export_manager = self._get_export_manager()
            
            if format_type in ['csv', 'json']:
                preview_content = export_manager.export_data(
                    data=sample_data,
                    format_type=ExportFormat(format_type),
                    filename=f"preview.{format_type}",
                    options={'include_metadata': False}
                )
                
                if format_type == 'csv':
                    # Return first few lines for CSV preview
                    lines = preview_content.split('\n')[:max_rows + 2]  # +2 for headers
                    preview_content = '\n'.join(lines)
            else:
                # For binary formats, return metadata only
                preview_content = f"Preview not available for {format_type.upper()} format. Export will contain {len(sample_data)} records."
            
            return jsonify({
                'status': 'success',
                'preview': preview_content,
                'record_count': len(sample_data),
                'format': format_type
            })
            
        except Exception as e:
            log.error(f"Error generating export preview: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    def _process_export_form(self, form: ExportConfigForm) -> Dict[str, Any]:
        """
        Process export configuration form data.
        
        Args:
            form: Validated form instance
            
        Returns:
            Export configuration dictionary
        """
        export_config = {
            'format': form.export_format.data,
            'filename': form.filename.data,
            'metadata': {
                'title': form.title.data or 'Data Export',
                'exported_by': getattr(current_user, 'username', 'anonymous'),
                'export_timestamp': datetime.now().isoformat(),
                'include_metadata': form.include_metadata.data
            },
            'options': {}
        }
        
        # Add format-specific options
        if form.export_format.data == 'csv':
            export_config['options'] = {
                'delimiter': form.csv_delimiter.data,
                'encoding': form.csv_encoding.data,
                'include_metadata': form.include_metadata.data
            }
        elif form.export_format.data == 'xlsx':
            export_config['options'] = {
                'auto_filter': form.excel_auto_filter.data,
                'freeze_headers': form.excel_freeze_headers.data,
                'add_charts': form.excel_add_charts.data,
                'include_metadata': form.include_metadata.data
            }
        elif form.export_format.data == 'pdf':
            export_config['options'] = {
                'page_size': form.pdf_page_size.data,
                'table_style': form.pdf_table_style.data,
                'add_charts': form.pdf_add_charts.data,
                'title': form.title.data or 'Data Export Report',
                'include_metadata': form.include_metadata.data
            }
        
        # Add advanced options if provided
        if form.advanced_options.data:
            try:
                advanced = json.loads(form.advanced_options.data)
                export_config['options'].update(advanced)
            except json.JSONDecodeError:
                log.warning("Invalid JSON in advanced options, ignoring")
        
        # Add record limit
        if form.max_records.data:
            export_config['max_records'] = form.max_records.data
        
        return export_config
    
    def _get_sample_export_data(self) -> List[Dict[str, Any]]:
        """
        Get sample data for export.
        
        In a real implementation, this would query actual application data.
        """
        return [
            {
                'id': 1,
                'name': 'John Doe',
                'email': 'john.doe@example.com',
                'department': 'Engineering',
                'salary': 75000.00,
                'start_date': datetime(2022, 1, 15),
                'active': True
            },
            {
                'id': 2,
                'name': 'Jane Smith',
                'email': 'jane.smith@example.com',
                'department': 'Marketing',
                'salary': 65000.00,
                'start_date': datetime(2022, 3, 1),
                'active': True
            },
            {
                'id': 3,
                'name': 'Bob Johnson',
                'email': 'bob.johnson@example.com',
                'department': 'Sales',
                'salary': 55000.00,
                'start_date': datetime(2021, 11, 10),
                'active': False
            },
            {
                'id': 4,
                'name': 'Alice Brown',
                'email': 'alice.brown@example.com',
                'department': 'HR',
                'salary': 60000.00,
                'start_date': datetime(2023, 2, 20),
                'active': True
            },
            {
                'id': 5,
                'name': 'Charlie Wilson',
                'email': 'charlie.wilson@example.com',
                'department': 'Engineering',
                'salary': 80000.00,
                'start_date': datetime(2020, 8, 5),
                'active': True
            }
        ]
    
    def _get_download_params(self, export_format: ExportFormat, 
                           export_config: Dict[str, Any]) -> tuple:
        """
        Get content type and filename for download.
        
        Args:
            export_format: Export format enum
            export_config: Export configuration
            
        Returns:
            Tuple of (content_type, filename)
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_filename = export_config.get('filename') or f"export_{timestamp}"
        
        # Remove extension if already present
        if '.' in base_filename:
            base_filename = base_filename.rsplit('.', 1)[0]
        
        content_types = {
            ExportFormat.CSV: 'text/csv',
            ExportFormat.EXCEL: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ExportFormat.PDF: 'application/pdf',
            ExportFormat.JSON: 'application/json'
        }
        
        extensions = {
            ExportFormat.CSV: 'csv',
            ExportFormat.EXCEL: 'xlsx',
            ExportFormat.PDF: 'pdf',
            ExportFormat.JSON: 'json'
        }
        
        content_type = content_types.get(export_format, 'application/octet-stream')
        extension = extensions.get(export_format, 'bin')
        filename = f"{base_filename}.{extension}"
        
        return content_type, filename


class DataExportView(BaseView):
    """
    Data-specific export view for integration with ModelViews.
    
    Provides methods for exporting data from specific models or queries
    with contextual export options.
    """
    
    route_base = '/data-export'
    
    @expose('/model/<model_name>')
    @has_access
    def export_model(self, model_name: str):
        """
        Export data from a specific model.
        
        Args:
            model_name: Name of the model to export
            
        Returns:
            Export configuration page for the model
        """
        try:
            # Get export format from query parameters
            export_format = request.args.get('format', 'csv')
            max_records = request.args.get('max_records', type=int)
            
            # In a real implementation, you would:
            # 1. Get the model class from model_name
            # 2. Query the data based on filters
            # 3. Apply permissions checking
            # 4. Generate the export
            
            flash(f"Model export for '{model_name}' in {export_format.upper()} format would be generated here.", 'info')
            return redirect(url_for('ExportView.index'))
            
        except Exception as e:
            log.error(f"Error exporting model {model_name}: {e}")
            flash(f"Export failed: {str(e)}", 'error')
            return redirect(url_for('ExportView.index'))
    
    @expose('/query', methods=['POST'])
    @has_access
    def export_query(self):
        """
        Export results from a custom query.
        
        Accepts POST data with query parameters and export configuration.
        """
        try:
            # Get query and export parameters from POST data
            query_sql = request.form.get('query')
            export_format = request.form.get('format', 'csv')
            
            if not query_sql:
                flash('No query provided for export', 'error')
                return redirect(url_for('ExportView.index'))
            
            # In a real implementation, you would:
            # 1. Validate and sanitize the SQL query
            # 2. Execute the query with proper permissions
            # 3. Convert results to export format
            # 4. Return the exported file
            
            flash(f"Query export in {export_format.upper()} format would be generated here.", 'info')
            return redirect(url_for('ExportView.index'))
            
        except Exception as e:
            log.error(f"Error exporting query results: {e}")
            flash(f"Query export failed: {str(e)}", 'error')
            return redirect(url_for('ExportView.index'))