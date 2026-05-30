"""
Enhanced View Mixins for PgAppForge

This module provides view mixins that automatically enhance CRUD operations
based on the mixins used in the underlying model, providing seamless
integration between model capabilities and view functionality.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Type
from datetime import datetime, timedelta
from flask import request, redirect, url_for, flash, jsonify, render_template, abort
from pgappforge import ModelView, BaseView, expose, has_access
from pgappforge.actions import action
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import protect
from wtforms import Form, StringField, TextAreaField, SelectField, BooleanField

log = logging.getLogger(__name__)


class EnhancedModelView(ModelView):
    """
    Enhanced ModelView that automatically adapts based on model mixins.
    
    This view detects mixins in the underlying model and automatically
    provides appropriate functionality and UI enhancements.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_mixin_enhancements()
    
    def _setup_mixin_enhancements(self):
        """Setup view enhancements based on model mixins."""
        if not self.datamodel or not hasattr(self.datamodel, 'obj'):
            return
        
        model_class = self.datamodel.obj
        
        # Detect and setup enhancements for each mixin
        self._setup_audit_enhancements(model_class)
        self._setup_soft_delete_enhancements(model_class)
        self._setup_versioning_enhancements(model_class)
        self._setup_search_enhancements(model_class)
        self._setup_workflow_enhancements(model_class)
        self._setup_approval_enhancements(model_class)
        self._setup_metadata_enhancements(model_class)
        self._setup_document_enhancements(model_class)
        self._setup_comment_enhancements(model_class)
        self._setup_translation_enhancements(model_class)
        self._setup_cache_enhancements(model_class)
        self._setup_project_enhancements(model_class)
    
    def _has_mixin(self, model_class, mixin_name: str) -> bool:
        """Check if model has a specific mixin."""
        return any(mixin_name in str(base) for base in model_class.__mro__)
    
    def _setup_audit_enhancements(self, model_class):
        """Setup audit trail enhancements."""
        if self._has_mixin(model_class, 'AuditLogMixin') or self._has_mixin(model_class, 'EnhancedAuditMixin'):
            # Add audit trail tab to show view
            if hasattr(self, 'show_template'):
                self.show_template = 'enhanced/show_with_audit.html'
            
            # Add audit trail columns to list view
            if hasattr(model_class, 'created_on'):
                self.list_columns = getattr(self, 'list_columns', []) + ['created_on', 'changed_on']
            
            # Add search on audit fields
            if hasattr(model_class, 'created_by'):
                self.search_columns = getattr(self, 'search_columns', []) + ['created_by', 'changed_by']
    
    def _setup_soft_delete_enhancements(self, model_class):
        """Setup soft delete enhancements."""
        if self._has_mixin(model_class, 'SoftDeleteMixin'):
            # Override delete to use soft delete
            self.can_delete = True
            
            # Add restore action
            @action("restore", "Restore", "Restore selected records", "fa-undo")
            def restore_records(self, items):
                count = 0
                for item in items:
                    if hasattr(item, 'restore'):
                        item.restore()
                        count += 1
                self.datamodel.session.commit()
                flash(f"Successfully restored {count} record(s)", "info")
                return redirect(self.get_redirect())
            
            # Add filter for deleted records
            self.base_filters = getattr(self, 'base_filters', []) + [
                ['is_deleted', lambda: False, 'eq']
            ]
            
            # Add show deleted toggle
            self.show_deleted_filter = True
    
    def _setup_versioning_enhancements(self, model_class):
        """Setup version control enhancements."""
        if self._has_mixin(model_class, 'VersioningMixin'):
            # Add version history action
            @action("version_history", "Version History", "View version history", "fa-history")
            def view_version_history(self, items):
                if len(items) != 1:
                    flash("Select exactly one record to view version history", "error")
                    return redirect(self.get_redirect())
                
                item = items[0]
                return redirect(url_for(f'{self.endpoint}.version_history', pk=item.id))
            
            # Add revert action
            @action("revert_version", "Revert Version", "Revert to previous version", "fa-undo")
            def revert_version(self, items):
                # Implementation would show version selection dialog
                flash("Version revert functionality", "info")
                return redirect(self.get_redirect())
    
    def _setup_search_enhancements(self, model_class):
        """Setup enhanced search capabilities."""
        if self._has_mixin(model_class, 'SearchableMixin') or self._has_mixin(model_class, 'FullTextSearchMixin'):
            # Add full-text search widget
            self.search_widget = 'enhanced_search.html'
            
            # Enable advanced search
            self.advanced_search = True
    
    def _setup_workflow_enhancements(self, model_class):
        """Setup workflow management enhancements."""
        if self._has_mixin(model_class, 'WorkflowMixin'):
            # Add state transition actions
            if hasattr(model_class, '__workflow_states__'):
                states = getattr(model_class, '__workflow_states__', {})
                
                for state, description in states.items():
                    @action(f"transition_to_{state}", f"Move to {description}", 
                           f"Transition selected records to {description}", "fa-arrow-right")
                    def transition_action(self, items, target_state=state):
                        count = 0
                        for item in items:
                            if hasattr(item, 'change_state') and item.can_transition_to(target_state):
                                item.change_state(target_state)
                                count += 1
                        self.datamodel.session.commit()
                        flash(f"Successfully transitioned {count} record(s) to {target_state}", "info")
                        return redirect(self.get_redirect())
            
            # Add workflow visualization
            self.workflow_enabled = True
    
    def _setup_approval_enhancements(self, model_class):
        """Setup approval workflow enhancements."""
        if self._has_mixin(model_class, 'ApprovalWorkflowMixin'):
            # Add approval actions
            @action("approve", "Approve", "Approve selected records", "fa-check")
            def approve_records(self, items):
                count = 0
                for item in items:
                    if hasattr(item, 'approve_step'):
                        try:
                            item.approve_step()
                            count += 1
                        except Exception as e:
                            flash(f"Failed to approve record {item.id}: {str(e)}", "error")
                
                if count > 0:
                    self.datamodel.session.commit()
                    flash(f"Successfully approved {count} record(s)", "success")
                
                return redirect(self.get_redirect())
            
            @action("reject", "Reject", "Reject selected records", "fa-times")
            def reject_records(self, items):
                count = 0
                for item in items:
                    if hasattr(item, 'reject_step'):
                        try:
                            item.reject_step()
                            count += 1
                        except Exception as e:
                            flash(f"Failed to reject record {item.id}: {str(e)}", "error")
                
                if count > 0:
                    self.datamodel.session.commit()
                    flash(f"Successfully rejected {count} record(s)", "warning")
                
                return redirect(self.get_redirect())
    
    def _setup_metadata_enhancements(self, model_class):
        """Setup metadata management enhancements."""
        if self._has_mixin(model_class, 'MetadataMixin'):
            # Add metadata editor
            self.metadata_enabled = True
            
            # Add metadata search capability
            @expose('/metadata_search/<int:pk>')
            def metadata_search(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                metadata = item.get_all_metadata() if hasattr(item, 'get_all_metadata') else {}
                return jsonify(metadata)
    
    def _setup_document_enhancements(self, model_class):
        """Setup document management enhancements."""
        if self._has_mixin(model_class, 'DocMixin'):
            # Add document preview
            @expose('/preview/<int:pk>')
            def preview_document(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                if not item.can_read():
                    abort(403)
                
                # Track document access
                if hasattr(item, 'track_document_access'):
                    item.track_document_access(action='preview')
                
                return render_template('enhanced/document_preview.html', item=item)
            
            # Add download action
            @expose('/download/<int:pk>')
            def download_document(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                if not item.can_download():
                    abort(403)
                
                # Track document access
                if hasattr(item, 'track_document_access'):
                    item.track_document_access(action='download')
                
                # Return file response
                # Implementation depends on document storage
                return redirect(item.get_download_url())
    
    def _setup_comment_enhancements(self, model_class):
        """Setup commenting system enhancements."""
        if self._has_mixin(model_class, 'CommentableMixin'):
            # Add comments tab to show view
            self.comments_enabled = True
            
            @expose('/comments/<int:pk>')
            def view_comments(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                comments = item.get_comments() if hasattr(item, 'get_comments') else []
                return render_template('enhanced/comments.html', item=item, comments=comments)
    
    def _setup_translation_enhancements(self, model_class):
        """Setup translation management enhancements."""
        if self._has_mixin(model_class, 'InternationalizationMixin'):
            # Add translation management
            @action("manage_translations", "Manage Translations", "Manage translations", "fa-language")
            def manage_translations(self, items):
                if len(items) != 1:
                    flash("Select exactly one record to manage translations", "error")
                    return redirect(self.get_redirect())
                
                item = items[0]
                return redirect(url_for(f'{self.endpoint}.translations', pk=item.id))
            
            @expose('/translations/<int:pk>')
            def translations(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                return render_template('enhanced/translations.html', item=item)
    
    def _setup_cache_enhancements(self, model_class):
        """Setup cache management enhancements."""
        if self._has_mixin(model_class, 'CacheMixin'):
            # Add cache management actions
            @action("refresh_cache", "Refresh Cache", "Refresh cached data", "fa-refresh")
            def refresh_cache(self, items):
                count = 0
                for item in items:
                    if hasattr(item, 'refresh_cache'):
                        item.refresh_cache()
                        count += 1
                
                flash(f"Successfully refreshed cache for {count} record(s)", "info")
                return redirect(self.get_redirect())
    
    def _setup_project_enhancements(self, model_class):
        """Setup project management enhancements."""
        if self._has_mixin(model_class, 'ProjectMixin'):
            # Add project management features
            @expose('/gantt/<int:pk>')
            def project_gantt(self, pk):
                item = self.datamodel.get(pk)
                if not item:
                    abort(404)
                
                gantt_data = item.render_mermaid(pk) if hasattr(item, 'render_mermaid') else ""
                return render_template('enhanced/project_gantt.html', item=item, gantt_data=gantt_data)


class AuditTrailView(BaseView):
    """Dedicated view for audit trail management."""
    
    route_base = '/admin/audit'
    default_view = 'list'
    
    @expose('/list/')
    @has_access
    def list(self):
        """Display audit trail list."""
        return render_template('enhanced/audit_trail.html')
    
    @expose('/details/<table_name>/<record_id>')
    @has_access
    def details(self, table_name, record_id):
        """Display detailed audit trail for a specific record."""
        from .fab_integration import AuditLogger
        
        audit_trail = AuditLogger.get_audit_trail(table_name, record_id)
        return render_template('enhanced/audit_details.html', 
                             table_name=table_name, 
                             record_id=record_id,
                             audit_trail=audit_trail)


class WorkflowVisualizationView(BaseView):
    """View for workflow visualization and management."""
    
    route_base = '/admin/workflow'
    default_view = 'dashboard'
    
    @expose('/dashboard/')
    @has_access  
    def dashboard(self):
        """Display workflow dashboard."""
        return render_template('enhanced/workflow_dashboard.html')
    
    @expose('/visualize/<model_name>')
    @has_access
    def visualize(self, model_name):
        """Visualize workflow for a specific model."""
        return render_template('enhanced/workflow_visualization.html', model_name=model_name)


class MetadataManagerView(BaseView):
    """View for metadata management across models."""
    
    route_base = '/admin/metadata'
    default_view = 'dashboard'
    
    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Display metadata management dashboard."""
        return render_template('enhanced/metadata_dashboard.html')
    
    @expose('/schema/<model_name>')
    @has_access
    def schema(self, model_name):
        """Manage metadata schema for a model."""
        return render_template('enhanced/metadata_schema.html', model_name=model_name)


class TranslationManagerView(BaseView):
    """View for translation management."""
    
    route_base = '/admin/translations'
    default_view = 'dashboard'
    
    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Display translation management dashboard."""
        return render_template('enhanced/translation_dashboard.html')
    
    @expose('/export/<model_name>')
    @has_access
    def export_translations(self, model_name):
        """Export translations for a model."""
        # Implementation for translation export
        return jsonify({'status': 'success'})
    
    @expose('/import/<model_name>', methods=['POST'])
    @has_access
    def import_translations(self, model_name):
        """Import translations for a model."""
        # Implementation for translation import
        return jsonify({'status': 'success'})


class DocumentManagerView(BaseView):
    """View for document management and processing."""
    
    route_base = '/admin/documents'
    default_view = 'dashboard'
    
    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Display document management dashboard."""
        return render_template('enhanced/document_dashboard.html')
    
    @expose('/process/<int:doc_id>')
    @has_access
    def process_document(self, doc_id):
        """Process document (OCR, metadata extraction, etc.)."""
        # Implementation for document processing
        return jsonify({'status': 'processing'})


class MixinConfigurationView(BaseView):
    """View for configuring mixin behavior."""
    
    route_base = '/admin/mixin-config'
    default_view = 'dashboard'
    
    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Display mixin configuration dashboard."""
        from .. import MIXIN_REGISTRY
        return render_template('enhanced/mixin_config.html', mixins=MIXIN_REGISTRY)
    
    @expose('/configure/<mixin_name>', methods=['GET', 'POST'])
    @has_access
    def configure(self, mixin_name):
        """Configure a specific mixin."""
        from .. import get_mixin_by_name
        
        mixin_class = get_mixin_by_name(mixin_name)
        if not mixin_class:
            abort(404)
        
        if request.method == 'POST':
            # Save configuration
            config = request.get_json()
            # Implementation for saving mixin configuration
            return jsonify({'status': 'saved'})
        
        return render_template('enhanced/mixin_configure.html', 
                             mixin_name=mixin_name, 
                             mixin_class=mixin_class)


def auto_detect_view_enhancements(model_class) -> List[str]:
    """
    Automatically detect what view enhancements should be applied
    based on the model's mixins.
    
    Args:
        model_class: The SQLAlchemy model class
        
    Returns:
        List of enhancement names that should be applied
    """
    enhancements = []
    
    # Map mixins to enhancements
    mixin_enhancement_map = {
        'AuditLogMixin': ['audit_trail', 'change_history'],
        'SoftDeleteMixin': ['soft_delete', 'restore_action'],
        'VersioningMixin': ['version_history', 'revert_capability'],
        'SearchableMixin': ['enhanced_search', 'full_text_search'],
        'WorkflowMixin': ['state_transitions', 'workflow_visualization'],
        'ApprovalWorkflowMixin': ['approval_actions', 'approval_dashboard'],
        'MetadataMixin': ['metadata_editor', 'dynamic_fields'],
        'DocMixin': ['document_preview', 'file_management'],
        'CommentableMixin': ['commenting_system', 'moderation'],
        'InternationalizationMixin': ['translation_management', 'locale_switching'],
        'CacheMixin': ['cache_management', 'performance_monitoring'],
        'ProjectMixin': ['gantt_charts', 'project_dashboard'],
        'MultiTenancyMixin': ['tenant_filtering', 'data_isolation'],
        'EncryptionMixin': ['secure_display', 'encryption_status']
    }
    
    # Check model's MRO for mixins
    for base in model_class.__mro__:
        base_name = base.__name__
        if base_name in mixin_enhancement_map:
            enhancements.extend(mixin_enhancement_map[base_name])
    
    return list(set(enhancements))  # Remove duplicates


__all__ = [
    'EnhancedModelView',
    'AuditTrailView',
    'WorkflowVisualizationView', 
    'MetadataManagerView',
    'TranslationManagerView',
    'DocumentManagerView',
    'MixinConfigurationView',
    'auto_detect_view_enhancements'
]