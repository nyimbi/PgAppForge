"""
Wizard Migration Management Views

Web interface for migrating, importing, and exporting wizard forms
with comprehensive validation and monitoring capabilities.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, send_file, flash, redirect, url_for
from flask.views import MethodView
from werkzeug.utils import secure_filename
import tempfile
import os
from pathlib import Path

from ..migration.wizard_migration import (
    wizard_migration_manager,
    WizardExportData,
    MigrationMetadata
)
from ..utils.error_handling import wizard_error_handler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class WizardMigrationView(MethodView):
    """Main view for wizard migration operations"""
    
    def __init__(self):
        self.migration_manager = wizard_migration_manager
        self.allowed_extensions = {'.json', '.zip'}
        self.max_file_size = 50 * 1024 * 1024  # 50MB
    
    def get(self):
        """Display migration dashboard"""
        try:
            # Get migration status
            status = self.migration_manager.get_migration_status()
            
            # Get available wizards from database
            available_wizards = self._get_available_wizards()
            
            # Get recent migrations
            recent_migrations = self._get_recent_migrations()
            
            return render_template(
                'migration/dashboard.html',
                status=status,
                wizards=available_wizards,
                recent_migrations=recent_migrations,
                page_title="Wizard Migration Dashboard"
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Error loading migration dashboard: {error.user_friendly_message}", 'error')
            return render_template('migration/error.html', error=error)


class WizardExportView(MethodView):
    """Handle wizard export operations"""
    
    def __init__(self):
        self.migration_manager = wizard_migration_manager
    
    def get(self):
        """Display export form"""
        try:
            available_wizards = self._get_available_wizards()
            export_formats = ['json', 'zip']
            
            return render_template(
                'migration/export.html',
                wizards=available_wizards,
                formats=export_formats,
                page_title="Export Wizards"
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Error loading export form: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_migration.index'))
    
    def post(self):
        """Execute wizard export"""
        try:
            # Get form data
            wizard_ids = request.form.getlist('wizard_ids')
            export_format = request.form.get('format', 'json')
            include_data = request.form.get('include_data') == 'on'
            include_analytics = request.form.get('include_analytics') == 'on'
            include_themes = request.form.get('include_themes') == 'on'
            include_collaboration = request.form.get('include_collaboration') == 'on'
            compress_output = request.form.get('compress') == 'on'
            
            if not wizard_ids:
                flash("Please select at least one wizard to export", 'warning')
                return redirect(url_for('wizard_export.index'))
            
            # Create temporary export file
            with tempfile.NamedTemporaryFile(
                suffix='.zip' if compress_output else '.json',
                delete=False
            ) as temp_file:
                export_file = self.migration_manager.exporter.export_to_file(
                    wizard_ids=wizard_ids,
                    file_path=temp_file.name,
                    format=export_format,
                    compress=compress_output,
                    include_data=include_data,
                    include_analytics=include_analytics,
                    include_themes=include_themes,
                    include_collaboration=include_collaboration
                )
            
            # Return file for download
            filename = f"wizard_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            filename += '.zip' if compress_output else '.json'
            
            return send_file(
                export_file,
                as_attachment=True,
                download_name=filename,
                mimetype='application/zip' if compress_output else 'application/json'
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Export failed: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_export.index'))
    
    def _get_available_wizards(self) -> List[Dict[str, Any]]:
        """Get list of available wizards"""
        # Query database for available wizards
        try:
            from flask import current_app
            from flask_login import current_user
            
            # Check if SQLAlchemy is available
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                from flask_sqlalchemy import SQLAlchemy
                from sqlalchemy import text
                
                db = current_app.extensions['sqlalchemy'].db
                
                try:
                    current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                    
                    # Query available wizards
                    wizards_query = text("""
                        SELECT id, title, description, status, created_date
                        FROM wizard_forms 
                        WHERE (is_public = true OR user_id = :user_id OR user_id IS NULL)
                        AND status IN ('active', 'draft')
                        ORDER BY title ASC
                    """)
                    
                    result = db.session.execute(wizards_query, {'user_id': current_user_id})
                    
                    wizards = []
                    for row in result:
                        wizards.append({
                            "id": row.id,
                            "title": row.title,
                            "description": row.description or f"Wizard form: {row.title}",
                            "status": row.status,
                            "created_date": row.created_date
                        })
                    
                    return wizards if wizards else self._get_sample_wizards()
                    
                except Exception as e:
                    logger.warning(f"Database query for available wizards failed: {e}")
                    
        except Exception as e:
            logger.error(f"Error getting available wizards: {e}")
        
        # Fallback to sample data
        return self._get_sample_wizards()
    
    def _get_sample_wizards(self) -> List[Dict[str, Any]]:
        """Get sample wizard data as fallback"""
        return [
            {"id": "sample_wizard1", "title": "Customer Registration", "description": "Customer signup form"},
            {"id": "sample_wizard2", "title": "Product Survey", "description": "Product feedback survey"},
            {"id": "sample_wizard3", "title": "Order Processing", "description": "Multi-step order form"}
        ]


class WizardImportView(MethodView):
    """Handle wizard import operations"""
    
    def __init__(self):
        self.migration_manager = wizard_migration_manager
        self.allowed_extensions = {'.json', '.zip'}
        self.max_file_size = 50 * 1024 * 1024  # 50MB
    
    def get(self):
        """Display import form"""
        try:
            return render_template(
                'migration/import.html',
                allowed_extensions=list(self.allowed_extensions),
                max_file_size_mb=self.max_file_size // (1024 * 1024),
                page_title="Import Wizards"
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Error loading import form: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_migration.index'))
    
    def post(self):
        """Execute wizard import"""
        try:
            # Check if file was uploaded
            if 'import_file' not in request.files:
                flash("No file selected for import", 'warning')
                return redirect(url_for('wizard_import.index'))
            
            file = request.files['import_file']
            if file.filename == '':
                flash("No file selected for import", 'warning')
                return redirect(url_for('wizard_import.index'))
            
            # Validate file
            validation_error = self._validate_upload_file(file)
            if validation_error:
                flash(validation_error, 'error')
                return redirect(url_for('wizard_import.index'))
            
            # Get import options
            overwrite_existing = request.form.get('overwrite_existing') == 'on'
            validate_import = request.form.get('validate_import') == 'on'
            specific_wizards = request.form.get('specific_wizards', '').strip()
            
            wizard_ids = None
            if specific_wizards:
                wizard_ids = [id.strip() for id in specific_wizards.split(',') if id.strip()]
            
            # Save uploaded file temporarily
            filename = secure_filename(file.filename)
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as temp_file:
                file.save(temp_file.name)
                
                try:
                    # Validate file first if requested
                    if validate_import:
                        validation = self.migration_manager.validator.validate_export_package(temp_file.name)
                        if not validation['valid']:
                            flash(f"Import validation failed: {'; '.join(validation['errors'])}", 'error')
                            return redirect(url_for('wizard_import.index'))
                    
                    # Import wizards
                    import_result = self.migration_manager.importer.import_from_file(
                        file_path=temp_file.name,
                        wizard_ids=wizard_ids,
                        validate=validate_import,
                        overwrite=overwrite_existing
                    )
                    
                    # Report results
                    imported_count = import_result['imported_count']
                    failed_count = import_result['failed_count']
                    
                    if imported_count > 0:
                        flash(f"Successfully imported {imported_count} wizard(s)", 'success')
                    
                    if failed_count > 0:
                        flash(f"Failed to import {failed_count} wizard(s)", 'warning')
                        # Show detailed errors
                        for result in import_result['results']:
                            if result['status'] == 'error':
                                flash(f"Wizard {result['wizard_id']}: {result['error']}", 'error')
                    
                    return render_template(
                        'migration/import_results.html',
                        import_result=import_result,
                        page_title="Import Results"
                    )
                    
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_file.name)
                    except OSError:
                        pass
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Import failed: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_import.index'))
    
    def _validate_upload_file(self, file) -> Optional[str]:
        """Validate uploaded file"""
        
        # Check file extension
        filename = secure_filename(file.filename)
        file_ext = Path(filename).suffix.lower()
        
        if file_ext not in self.allowed_extensions:
            return f"File type {file_ext} not allowed. Allowed types: {', '.join(self.allowed_extensions)}"
        
        # Check file size (approximate)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size > self.max_file_size:
            return f"File too large. Maximum size: {self.max_file_size // (1024*1024)}MB"
        
        if file_size == 0:
            return "File is empty"
        
        return None


class WizardBackupView(MethodView):
    """Handle wizard backup operations"""
    
    def __init__(self):
        self.migration_manager = wizard_migration_manager
    
    def get(self):
        """Display backup form"""
        try:
            available_wizards = self._get_available_wizards()
            return render_template(
                'migration/backup.html',
                wizards=available_wizards,
                page_title="Backup Wizards"
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Error loading backup form: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_migration.index'))
    
    def post(self):
        """Create wizard backup"""
        try:
            # Get form data
            wizard_ids = request.form.getlist('wizard_ids')
            include_all_data = request.form.get('include_all_data') == 'on'
            backup_name = request.form.get('backup_name', '').strip()
            
            if not wizard_ids:
                flash("Please select at least one wizard to backup", 'warning')
                return redirect(url_for('wizard_backup.index'))
            
            # Generate backup filename
            if not backup_name:
                backup_name = f"wizard_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create temporary backup file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                backup_file = self.migration_manager.create_backup(
                    wizard_ids=wizard_ids,
                    backup_path=temp_file.name,
                    include_all_data=include_all_data
                )
            
            # Return backup file for download
            return send_file(
                backup_file,
                as_attachment=True,
                download_name=f"{backup_name}.zip",
                mimetype='application/zip'
            )
            
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.HIGH
            )
            flash(f"Backup failed: {error.user_friendly_message}", 'error')
            return redirect(url_for('wizard_backup.index'))
    
    def _get_available_wizards(self) -> List[Dict[str, Any]]:
        """Get list of available wizards"""
        # Query database for available wizards
        try:
            from flask import current_app
            from flask_login import current_user
            
            # Check if SQLAlchemy is available
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                from flask_sqlalchemy import SQLAlchemy
                from sqlalchemy import text
                
                db = current_app.extensions['sqlalchemy'].db
                
                try:
                    current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                    
                    # Query available wizards
                    wizards_query = text("""
                        SELECT id, title, description, status, created_date
                        FROM wizard_forms 
                        WHERE (is_public = true OR user_id = :user_id OR user_id IS NULL)
                        AND status IN ('active', 'draft')
                        ORDER BY title ASC
                    """)
                    
                    result = db.session.execute(wizards_query, {'user_id': current_user_id})
                    
                    wizards = []
                    for row in result:
                        wizards.append({
                            "id": row.id,
                            "title": row.title,
                            "description": row.description or f"Wizard form: {row.title}",
                            "status": row.status,
                            "created_date": row.created_date
                        })
                    
                    return wizards if wizards else self._get_sample_wizards()
                    
                except Exception as e:
                    logger.warning(f"Database query for available wizards failed: {e}")
                    
        except Exception as e:
            logger.error(f"Error getting available wizards: {e}")
        
        # Fallback to sample data
        return self._get_sample_wizards()
    
    def _get_sample_wizards(self) -> List[Dict[str, Any]]:
        """Get sample wizard data as fallback"""
        return [
            {"id": "sample_wizard1", "title": "Customer Registration", "description": "Customer signup form"},
            {"id": "sample_wizard2", "title": "Product Survey", "description": "Product feedback survey"},
            {"id": "sample_wizard3", "title": "Order Processing", "description": "Multi-step order form"}
        ]


class WizardMigrationAPIView(MethodView):
    """API endpoints for wizard migration"""
    
    def __init__(self):
        self.migration_manager = wizard_migration_manager
    
    def get(self, action=None, wizard_id=None):
        """Handle GET API requests"""
        try:
            if action == 'status':
                return jsonify(self.migration_manager.get_migration_status())
            
            elif action == 'validate':
                file_path = request.args.get('file_path')
                if not file_path:
                    return jsonify({'error': 'file_path required'}), 400
                
                validation = self.migration_manager.validator.validate_export_package(file_path)
                return jsonify(validation)
            
            elif action == 'wizards':
                # Return list of available wizards
                wizards = self._get_available_wizards()
                return jsonify({'wizards': wizards})
            
            else:
                return jsonify({'error': 'Invalid action'}), 400
                
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.MEDIUM
            )
            return jsonify({'error': error.user_friendly_message}), 500
    
    def post(self, action=None):
        """Handle POST API requests"""
        try:
            if action == 'export':
                data = request.get_json()
                wizard_ids = data.get('wizard_ids', [])
                options = data.get('options', {})
                
                if not wizard_ids:
                    return jsonify({'error': 'wizard_ids required'}), 400
                
                # Export to temporary file
                with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                    export_file = self.migration_manager.exporter.export_to_file(
                        wizard_ids=wizard_ids,
                        file_path=temp_file.name,
                        **options
                    )
                
                return jsonify({
                    'success': True,
                    'export_file': export_file,
                    'wizard_count': len(wizard_ids)
                })
            
            elif action == 'import':
                data = request.get_json()
                file_path = data.get('file_path')
                options = data.get('options', {})
                
                if not file_path:
                    return jsonify({'error': 'file_path required'}), 400
                
                import_result = self.migration_manager.importer.import_from_file(
                    file_path=file_path,
                    **options
                )
                
                return jsonify(import_result)
            
            else:
                return jsonify({'error': 'Invalid action'}), 400
                
        except Exception as e:
            error = wizard_error_handler.handle_error(
                e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.MEDIUM
            )
            return jsonify({'error': error.user_friendly_message}), 500
    
    def _get_available_wizards(self) -> List[Dict[str, Any]]:
        """Get list of available wizards"""
        # Query database for available wizards
        try:
            from flask import current_app
            from flask_login import current_user
            
            # Check if SQLAlchemy is available
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                from flask_sqlalchemy import SQLAlchemy
                from sqlalchemy import text
                
                db = current_app.extensions['sqlalchemy'].db
                
                try:
                    current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                    
                    # Query available wizards
                    wizards_query = text("""
                        SELECT id, title, description, status, created_date
                        FROM wizard_forms 
                        WHERE (is_public = true OR user_id = :user_id OR user_id IS NULL)
                        AND status IN ('active', 'draft')
                        ORDER BY title ASC
                    """)
                    
                    result = db.session.execute(wizards_query, {'user_id': current_user_id})
                    
                    wizards = []
                    for row in result:
                        wizards.append({
                            "id": row.id,
                            "title": row.title,
                            "description": row.description or f"Wizard form: {row.title}",
                            "status": row.status,
                            "created_date": row.created_date
                        })
                    
                    return wizards if wizards else self._get_sample_wizards()
                    
                except Exception as e:
                    logger.warning(f"Database query for available wizards failed: {e}")
                    
        except Exception as e:
            logger.error(f"Error getting available wizards: {e}")
        
        # Fallback to sample data
        return self._get_sample_wizards()
    
    def _get_sample_wizards(self) -> List[Dict[str, Any]]:
        """Get sample wizard data as fallback"""
        return [
            {"id": "sample_wizard1", "title": "Customer Registration", "description": "Customer signup form"},
            {"id": "sample_wizard2", "title": "Product Survey", "description": "Product feedback survey"},
            {"id": "sample_wizard3", "title": "Order Processing", "description": "Multi-step order form"}
        ]


def _get_available_wizards() -> List[Dict[str, Any]]:
    """Get list of available wizards (shared utility)"""
    try:
        from flask import current_app
        from flask_login import current_user
        
        # Check if SQLAlchemy is available
        if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
            from flask_sqlalchemy import SQLAlchemy
            from sqlalchemy import text
            
            db = current_app.extensions['sqlalchemy'].db
            
            try:
                current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                
                # Query available wizards
                wizards_query = text("""
                    SELECT id, title, description, status, created_date
                    FROM wizard_forms 
                    WHERE (is_public = true OR user_id = :user_id OR user_id IS NULL)
                    AND status IN ('active', 'draft')
                    ORDER BY title ASC
                """)
                
                result = db.session.execute(wizards_query, {'user_id': current_user_id})
                
                wizards = []
                for row in result:
                    wizards.append({
                        "id": row.id,
                        "title": row.title,
                        "description": row.description or f"Wizard form: {row.title}",
                        "status": row.status,
                        "created_date": row.created_date
                    })
                
                return wizards if wizards else _get_sample_available_wizards()
                
            except Exception as e:
                logger.warning(f"Database query for available wizards failed: {e}")
                
    except Exception as e:
        logger.error(f"Error getting available wizards: {e}")
    
    # Fallback to sample data
    return _get_sample_available_wizards()

def _get_sample_available_wizards() -> List[Dict[str, Any]]:
    """Get sample wizard data as fallback"""
    return [
        {"id": "wizard1", "title": "Customer Registration", "description": "Customer signup form"},
        {"id": "wizard2", "title": "Product Survey", "description": "Product feedback survey"},
        {"id": "wizard3", "title": "Order Processing", "description": "Multi-step order form"}
    ]


def _get_recent_migrations() -> List[Dict[str, Any]]:
    """Get recent migration activities"""
    return [
        {
            "id": "migration1",
            "type": "export",
            "wizard_count": 2,
            "status": "completed",
            "created_at": "2024-01-15T10:30:00Z",
            "created_by": "admin"
        },
        {
            "id": "migration2", 
            "type": "import",
            "wizard_count": 1,
            "status": "completed",
            "created_at": "2024-01-14T15:45:00Z",
            "created_by": "user1"
        }
    ]