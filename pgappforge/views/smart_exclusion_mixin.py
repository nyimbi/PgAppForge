"""
Smart Field Exclusion Mixin for PgForge Views

This module provides view mixins that automatically exclude unsupported field types
from search and filter operations while providing detailed information about exclusions.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Union

from flask import flash, request
from flask_babel import lazy_gettext, gettext
from ..models.field_analyzer import (
    FieldTypeAnalyzer, FieldSupportLevel, UnsupportedReason,
    DEFAULT_ANALYZER, PERMISSIVE_ANALYZER, analyze_model_fields
)

log = logging.getLogger(__name__)


class SmartExclusionMixin:
    """
    Mixin for PgForge views that provides intelligent field exclusion
    for search and filter operations.
    
    This mixin automatically excludes unsupported field types including:
    - JSONB and complex JSON structures
    - Images, files, and multimedia content
    - Binary data (BLOB, BYTEA, etc.)
    - Vector embeddings (pgvector)
    - Spatial/geometric data (PostGIS)
    - Network addresses (INET, MACADDR)
    - Full-text search vectors (TSVECTOR)
    - Tree/hierarchical data (LTREE)
    - Other specialized types
    
    Features:
    - Automatic exclusion based on field type analysis
    - Detailed exclusion reporting and logging
    - Configurable strictness levels
    - User-friendly exclusion messages
    - Administrative exclusion reports
    - Custom exclusion rules support
    """
    
    # Configuration options
    field_analyzer_strict_mode = True
    """Whether to use strict mode for field analysis (excludes ambiguous types)"""
    
    show_exclusion_warnings = True
    """Whether to show warnings when fields are excluded from search/filter"""
    
    log_exclusion_details = True
    """Whether to log detailed information about excluded fields"""
    
    enable_exclusion_report = True
    """Whether to generate detailed exclusion reports for admins"""
    
    custom_exclusion_rules = None
    """Custom field type exclusion rules (dict mapping types to FieldSupportLevel)"""
    
    exclusion_message_template = lazy_gettext(
        "Some fields have been excluded from search/filtering due to their data type. "
        "Contact your administrator if you need access to specific fields."
    )
    """Template for user exclusion warnings"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._field_analyzer = None
        self._exclusion_cache = {}
        self._last_exclusion_report = None
        
    @property
    def field_analyzer(self) -> FieldTypeAnalyzer:
        """Get the field analyzer instance, creating it if necessary."""
        if self._field_analyzer is None:
            self._field_analyzer = FieldTypeAnalyzer(
                strict_mode=self.field_analyzer_strict_mode,
                custom_rules=self.custom_exclusion_rules or {}
            )
        return self._field_analyzer
    
    def get_smart_search_columns(self) -> List[str]:
        """
        Get search columns with intelligent exclusion of unsupported types.
        
        Returns:
            List of column names suitable for search operations
        """
        cache_key = 'search_columns'
        if cache_key not in self._exclusion_cache:
            try:
                # Get columns from the datamodel
                if hasattr(self.datamodel, 'obj') and hasattr(self.datamodel.obj, '__table__'):
                    columns = list(self.datamodel.obj.__table__.columns)
                    excluded_columns = []
                    searchable_columns = []
                    
                    for column in columns:
                        support_level, reason, metadata = self.field_analyzer.analyze_column(column)
                        
                        # Include columns that support search operations
                        if support_level in {
                            FieldSupportLevel.FULLY_SUPPORTED,
                            FieldSupportLevel.SEARCHABLE_ONLY,
                            FieldSupportLevel.LIMITED_SUPPORT
                        }:
                            searchable_columns.append(column.name)
                        else:
                            excluded_columns.append({
                                'name': column.name,
                                'type': metadata.get('sqlalchemy_type', 'unknown'),
                                'reason': reason.value if reason else 'unsupported',
                                'details': metadata.get('details', '')
                            })
                            
                            if self.log_exclusion_details:
                                log.info(f"Excluding column '{column.name}' from search: "
                                        f"{reason.value if reason else 'unsupported'}")
                    
                    # Cache the results
                    self._exclusion_cache[cache_key] = {
                        'searchable': searchable_columns,
                        'excluded': excluded_columns
                    }
                    
                    # Show exclusion warning to users if configured
                    if excluded_columns and self.show_exclusion_warnings:
                        self._show_exclusion_warning('search', len(excluded_columns))
                    
                else:
                    # Fallback to original search columns if model analysis fails
                    searchable_columns = getattr(self, 'search_columns', [])
                    self._exclusion_cache[cache_key] = {
                        'searchable': searchable_columns,
                        'excluded': []
                    }
                    
            except Exception as e:
                log.error(f"Error analyzing search columns: {e}")
                # Fallback to original search columns
                searchable_columns = getattr(self, 'search_columns', [])
                self._exclusion_cache[cache_key] = {
                    'searchable': searchable_columns,
                    'excluded': []
                }
        
        return self._exclusion_cache[cache_key]['searchable']
    
    def get_smart_filter_columns(self) -> List[str]:
        """
        Get filter columns with intelligent exclusion of unsupported types.
        
        Returns:
            List of column names suitable for filter operations
        """
        cache_key = 'filter_columns'
        if cache_key not in self._exclusion_cache:
            try:
                # Get columns from the datamodel
                if hasattr(self.datamodel, 'obj') and hasattr(self.datamodel.obj, '__table__'):
                    columns = list(self.datamodel.obj.__table__.columns)
                    excluded_columns = []
                    filterable_columns = []
                    
                    for column in columns:
                        support_level, reason, metadata = self.field_analyzer.analyze_column(column)
                        
                        # Include columns that support filter operations
                        if support_level in {
                            FieldSupportLevel.FULLY_SUPPORTED,
                            FieldSupportLevel.FILTERABLE_ONLY,
                            FieldSupportLevel.LIMITED_SUPPORT
                        }:
                            filterable_columns.append(column.name)
                        else:
                            excluded_columns.append({
                                'name': column.name,
                                'type': metadata.get('sqlalchemy_type', 'unknown'),
                                'reason': reason.value if reason else 'unsupported',
                                'details': metadata.get('details', '')
                            })
                            
                            if self.log_exclusion_details:
                                log.info(f"Excluding column '{column.name}' from filters: "
                                        f"{reason.value if reason else 'unsupported'}")
                    
                    # Cache the results
                    self._exclusion_cache[cache_key] = {
                        'filterable': filterable_columns,
                        'excluded': excluded_columns
                    }
                    
                    # Show exclusion warning to users if configured
                    if excluded_columns and self.show_exclusion_warnings:
                        self._show_exclusion_warning('filtering', len(excluded_columns))
                    
                else:
                    # Fallback to search columns if model analysis fails
                    filterable_columns = getattr(self, 'search_columns', [])
                    self._exclusion_cache[cache_key] = {
                        'filterable': filterable_columns,
                        'excluded': []
                    }
                    
            except Exception as e:
                log.error(f"Error analyzing filter columns: {e}")
                # Fallback to search columns
                filterable_columns = getattr(self, 'search_columns', [])
                self._exclusion_cache[cache_key] = {
                    'filterable': filterable_columns,
                    'excluded': []
                }
        
        return self._exclusion_cache[cache_key]['filterable']
    
    def _show_exclusion_warning(self, operation: str, excluded_count: int):
        """Show a user-friendly warning about excluded fields."""
        if excluded_count > 0:
            message = gettext(
                f"Note: {excluded_count} field(s) were automatically excluded from {operation} "
                f"due to their data type (e.g., images, binary data, complex structures)."
            )
            # Only show this as info, not warning, to avoid alarming users
            if hasattr(self, 'appbuilder') and hasattr(self.appbuilder.app, 'logger'):
                self.appbuilder.app.logger.info(f"Field exclusion notice: {message}")
    
    def get_exclusion_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive exclusion report for administrators.
        
        Returns:
            Dictionary containing detailed exclusion analysis
        """
        if not self.enable_exclusion_report:
            return {}
            
        if self._last_exclusion_report is None:
            try:
                if hasattr(self.datamodel, 'obj'):
                    self._last_exclusion_report = analyze_model_fields(
                        self.datamodel.obj,
                        strict_mode=self.field_analyzer_strict_mode
                    )
                else:
                    self._last_exclusion_report = {
                        'error': 'Unable to analyze model fields'
                    }
            except Exception as e:
                self._last_exclusion_report = {
                    'error': f'Error generating exclusion report: {str(e)}'
                }
        
        return self._last_exclusion_report
    
    def clear_exclusion_cache(self):
        """Clear the exclusion cache to force re-analysis."""
        self._exclusion_cache.clear()
        self._last_exclusion_report = None
    
    def get_excluded_fields_summary(self) -> Dict[str, List[str]]:
        """
        Get a summary of excluded fields by reason.
        
        Returns:
            Dictionary mapping exclusion reasons to lists of field names
        """
        summary = {}
        
        # Get exclusion data from cache
        search_data = self._exclusion_cache.get('search_columns', {})
        filter_data = self._exclusion_cache.get('filter_columns', {})
        
        all_excluded = []
        all_excluded.extend(search_data.get('excluded', []))
        all_excluded.extend(filter_data.get('excluded', []))
        
        # Group by reason
        for excluded_field in all_excluded:
            reason = excluded_field.get('reason', 'unknown')
            if reason not in summary:
                summary[reason] = []
            if excluded_field['name'] not in summary[reason]:
                summary[reason].append(excluded_field['name'])
        
        return summary


class AutoExclusionModelView:
    """
    Enhanced ModelView that automatically excludes unsupported field types
    from search and filter operations.
    
    This view automatically configures search_columns and other settings
    based on intelligent field type analysis.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Apply smart exclusion to search columns if not explicitly set
        if not hasattr(self, 'search_columns') or self.search_columns is None:
            if hasattr(self, 'get_smart_search_columns'):
                self.search_columns = self.get_smart_search_columns()
    
    def __call__(self, *args, **kwargs):
        """Override to ensure smart exclusion is applied before request processing."""
        # Refresh search columns with smart exclusion
        if hasattr(self, 'get_smart_search_columns'):
            smart_columns = self.get_smart_search_columns()
            if smart_columns != getattr(self, 'search_columns', []):
                self.search_columns = smart_columns
                
        return super().__call__(*args, **kwargs)


# Utility functions for easy integration

def apply_smart_exclusion(view_class, strict_mode: bool = True, 
                         show_warnings: bool = True) -> type:
    """
    Decorator/function to apply smart field exclusion to a view class.
    
    Args:
        view_class: The view class to enhance
        strict_mode: Whether to use strict mode for field analysis
        show_warnings: Whether to show exclusion warnings
        
    Returns:
        Enhanced view class with smart exclusion capabilities
    """
    class SmartExclusionView(SmartExclusionMixin, view_class):
        field_analyzer_strict_mode = strict_mode
        show_exclusion_warnings = show_warnings
        
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            
            # Apply smart exclusion to search columns
            if not hasattr(self, 'search_columns') or self.search_columns is None:
                self.search_columns = self.get_smart_search_columns()
    
    SmartExclusionView.__name__ = f"SmartExclusion{view_class.__name__}"
    SmartExclusionView.__qualname__ = f"SmartExclusion{view_class.__qualname__}"
    
    return SmartExclusionView


def get_exclusion_summary_for_model(model_class, strict_mode: bool = True) -> Dict[str, Any]:
    """
    Get a summary of field exclusions for a specific model class.
    
    Args:
        model_class: SQLAlchemy model class to analyze
        strict_mode: Whether to use strict mode for analysis
        
    Returns:
        Summary dictionary with exclusion information
    """
    return analyze_model_fields(model_class, strict_mode=strict_mode)