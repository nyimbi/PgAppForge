"""
Enhanced ModelView Integration with Field Type Analysis

This module provides enhanced ModelView classes that automatically integrate
with the Field Type Analysis system to provide intelligent field handling,
automatic exclusions, and improved user experience for Flask-AppBuilder applications.

Classes:
    EnhancedModelView: ModelView with intelligent field analysis
    SmartExclusionMixin: Mixin for automatic field exclusion
    FieldAnalysisManager: Centralized field analysis management
    ModelInspector: Deep model introspection utilities

Features:
    - Automatic field type detection and exclusion
    - Smart search and filter column selection
    - Performance-optimized field analysis with caching
    - User-friendly warnings for excluded fields
    - Configurable analysis rules and overrides
    - Integration with existing Flask-AppBuilder patterns
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, Callable
from functools import lru_cache, wraps
from datetime import datetime, timedelta, timezone

from flask import flash, request, current_app
from flask_babel import lazy_gettext as _
from sqlalchemy import Column, inspect
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.ext.hybrid import hybrid_property

from .field_analyzer import (
    FieldTypeAnalyzer, FieldSupportLevel, UnsupportedReason,
    analyze_model_fields, DEFAULT_ANALYZER
)

try:
    from flask_appbuilder.models.sqla import Model
    from flask_appbuilder.models.sqla.interface import SQLAInterface
    from flask_appbuilder.views import ModelView as BaseModelView
    HAS_FAB_MODELS = True
except ImportError:
    # Fallback for testing or when Flask-AppBuilder is not available
    HAS_FAB_MODELS = False
    Model = object
    SQLAInterface = object
    BaseModelView = object

log = logging.getLogger(__name__)


class FieldAnalysisCache:
    """
    Intelligent caching system for field analysis results.
    
    Provides efficient caching of field analysis results with automatic
    invalidation and memory management to ensure optimal performance
    even with large numbers of models and fields.
    """
    
    def __init__(self, max_cache_size: int = 1000, cache_ttl_seconds: int = 3600):
        """
        Initialize the field analysis cache.
        
        Args:
            max_cache_size: Maximum number of cached analysis results
            cache_ttl_seconds: Time-to-live for cached results in seconds
        """
        self.max_cache_size = max_cache_size
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        
    def get_cache_key(self, model_class: Type, analyzer_config: Dict[str, Any]) -> str:
        """
        Generate a cache key for a model and analyzer configuration.
        
        Args:
            model_class: SQLAlchemy model class
            analyzer_config: Analyzer configuration dictionary
            
        Returns:
            Unique cache key string
        """
        model_name = f"{model_class.__module__}.{model_class.__name__}"
        config_hash = hash(frozenset(analyzer_config.items()))
        return f"{model_name}:{config_hash}"
    
    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached analysis result if valid.
        
        Args:
            cache_key: Cache key to lookup
            
        Returns:
            Cached analysis result or None if not found/expired
        """
        if cache_key not in self._cache:
            return None
        
        # Check if cache entry has expired
        timestamp = self._cache_timestamps.get(cache_key)
        if timestamp and datetime.now(tz=timezone.utc) - timestamp > self.cache_ttl:
            self._invalidate_entry(cache_key)
            return None
        
        return self._cache[cache_key]
    
    def set(self, cache_key: str, analysis_result: Dict[str, Any]) -> None:
        """
        Store analysis result in cache.
        
        Args:
            cache_key: Cache key for storage
            analysis_result: Analysis result to cache
        """
        # Enforce cache size limit
        if len(self._cache) >= self.max_cache_size:
            self._evict_oldest_entries()
        
        self._cache[cache_key] = analysis_result.copy()
        self._cache_timestamps[cache_key] = datetime.now(tz=timezone.utc)
        
        log.debug(f"Cached field analysis for {cache_key}")
    
    def invalidate(self, model_class: Type) -> None:
        """
        Invalidate all cache entries for a specific model.
        
        Args:
            model_class: Model class to invalidate
        """
        model_name = f"{model_class.__module__}.{model_class.__name__}"
        keys_to_remove = [key for key in self._cache.keys() if key.startswith(model_name)]
        
        for key in keys_to_remove:
            self._invalidate_entry(key)
        
        log.debug(f"Invalidated cache for model {model_name}")
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._cache_timestamps.clear()
        log.debug("Cleared all field analysis cache")
    
    def _invalidate_entry(self, cache_key: str) -> None:
        """Remove a specific cache entry."""
        self._cache.pop(cache_key, None)
        self._cache_timestamps.pop(cache_key, None)
    
    def _evict_oldest_entries(self, num_to_evict: int = None) -> None:
        """Evict oldest cache entries to make room."""
        if num_to_evict is None:
            num_to_evict = max(1, len(self._cache) // 10)  # Evict 10% of entries
        
        # Sort by timestamp and remove oldest
        sorted_entries = sorted(
            self._cache_timestamps.items(),
            key=lambda x: x[1]
        )
        
        for cache_key, _ in sorted_entries[:num_to_evict]:
            self._invalidate_entry(cache_key)


class ModelInspector:
    """
    Deep model introspection utilities for enhanced field analysis.
    
    Provides comprehensive model introspection capabilities including
    relationship analysis, hybrid property detection, and advanced
    field metadata extraction.
    """
    
    @staticmethod
    def get_model_columns(model_class: Type) -> List[Column]:
        """
        Get all columns from a SQLAlchemy model.
        
        Args:
            model_class: SQLAlchemy model class
            
        Returns:
            List of Column objects
        """
        if not hasattr(model_class, '__table__'):
            return []
        
        return list(model_class.__table__.columns)
    
    @staticmethod
    def get_model_relationships(model_class: Type) -> Dict[str, RelationshipProperty]:
        """
        Get all relationships from a SQLAlchemy model.
        
        Args:
            model_class: SQLAlchemy model class
            
        Returns:
            Dictionary mapping relationship names to RelationshipProperty objects
        """
        relationships = {}
        
        if hasattr(model_class, '__mapper__'):
            for attr_name, attr in model_class.__mapper__.all_orm_descriptors.items():
                if isinstance(attr, RelationshipProperty):
                    relationships[attr_name] = attr
        
        return relationships
    
    @staticmethod
    def get_hybrid_properties(model_class: Type) -> Dict[str, hybrid_property]:
        """
        Get all hybrid properties from a SQLAlchemy model.
        
        Args:
            model_class: SQLAlchemy model class
            
        Returns:
            Dictionary mapping property names to hybrid_property objects
        """
        hybrid_props = {}
        
        if hasattr(model_class, '__mapper__'):
            for attr_name, attr in model_class.__mapper__.all_orm_descriptors.items():
                if isinstance(attr, hybrid_property):
                    hybrid_props[attr_name] = attr
        
        return hybrid_props
    
    @staticmethod
    def get_searchable_relationships(model_class: Type, max_depth: int = 2) -> Dict[str, Dict[str, Any]]:
        """
        Get relationships that can be used for searching.
        
        Args:
            model_class: SQLAlchemy model class
            max_depth: Maximum relationship depth to analyze
            
        Returns:
            Dictionary with searchable relationship information
        """
        searchable_rels = {}
        relationships = ModelInspector.get_model_relationships(model_class)
        
        for rel_name, rel_prop in relationships.items():
            try:
                related_model = rel_prop.mapper.class_
                related_columns = ModelInspector.get_model_columns(related_model)
                
                # Analyze related model's searchable fields
                analyzer = DEFAULT_ANALYZER
                searchable_fields = analyzer.get_searchable_columns(related_columns)
                
                if searchable_fields:
                    searchable_rels[rel_name] = {
                        'model': related_model,
                        'searchable_fields': searchable_fields,
                        'relationship_type': str(rel_prop.direction),
                        'foreign_keys': [str(fk) for fk in rel_prop.local_columns]
                    }
                    
            except Exception as e:
                log.warning(f"Error analyzing relationship {rel_name}: {str(e)}")
                continue
        
        return searchable_rels
    
    @staticmethod
    def extract_field_metadata(column: Column) -> Dict[str, Any]:
        """
        Extract comprehensive metadata from a database column.
        
        Args:
            column: SQLAlchemy Column object
            
        Returns:
            Dictionary with detailed field metadata
        """
        metadata = {
            'name': column.name,
            'type_name': column.type.__class__.__name__,
            'python_type': str(type(column.type)),
            'nullable': getattr(column, 'nullable', True),
            'primary_key': getattr(column, 'primary_key', False),
            'unique': getattr(column, 'unique', False),
            'indexed': getattr(column, 'index', False),
            'autoincrement': getattr(column, 'autoincrement', False),
            'foreign_keys': [str(fk) for fk in getattr(column, 'foreign_keys', [])],
            'default': str(column.default) if column.default else None,
            'server_default': str(column.server_default) if column.server_default else None,
        }
        
        # Add type-specific metadata
        if hasattr(column.type, 'length'):
            metadata['max_length'] = column.type.length
        
        if hasattr(column.type, 'precision'):
            metadata['precision'] = column.type.precision
            
        if hasattr(column.type, 'scale'):
            metadata['scale'] = column.type.scale
        
        if hasattr(column.type, 'enums') and column.type.enums:
            metadata['enum_values'] = list(column.type.enums)
        
        return metadata


class SmartExclusionMixin:
    """
    Mixin for automatic intelligent field exclusion in ModelViews.
    
    Provides automatic field exclusion capabilities with user-friendly
    warnings, performance optimization, and configurable behavior.
    """
    
    # Class-level cache instance (shared across all instances)
    _field_analysis_cache = FieldAnalysisCache()
    
    # Configuration options
    field_analysis_enabled = True
    field_analysis_strict_mode = True
    field_analysis_cache_enabled = True
    field_analysis_show_warnings = True
    field_analysis_custom_rules = None
    
    def __init__(self, *args, **kwargs):
        """Initialize the smart exclusion mixin."""
        super().__init__(*args, **kwargs)
        
        # Initialize analyzer with custom configuration
        self._field_analyzer = None
        self._analysis_cache_key = None
        self._last_analysis_result = None
        
    @property
    def field_analyzer(self) -> FieldTypeAnalyzer:
        """Get or create the field analyzer instance."""
        if self._field_analyzer is None:
            custom_rules = getattr(self, 'field_analysis_custom_rules', None) or {}
            strict_mode = getattr(self, 'field_analysis_strict_mode', True)
            
            self._field_analyzer = FieldTypeAnalyzer(
                strict_mode=strict_mode,
                custom_rules=custom_rules
            )
        
        return self._field_analyzer
    
    def get_enhanced_search_columns(self) -> List[str]:
        """
        Get intelligently filtered search columns.
        
        Returns:
            List of column names suitable for search operations
        """
        if not getattr(self, 'field_analysis_enabled', True):
            # Fall back to default behavior if analysis is disabled
            return getattr(self, 'search_columns', []) or self._get_default_search_columns()
        
        # Get analysis results (cached if possible)
        analysis_result = self._get_field_analysis()
        
        # Extract searchable columns
        searchable_columns = []
        
        # Add fully supported columns
        for col_info in analysis_result.get('fully_supported', []):
            searchable_columns.append(col_info['name'])
        
        # Add searchable-only columns
        for col_info in analysis_result.get('searchable_only', []):
            searchable_columns.append(col_info['name'])
        
        # In permissive mode, add limited support columns
        if not getattr(self, 'field_analysis_strict_mode', True):
            for col_info in analysis_result.get('limited_support', []):
                searchable_columns.append(col_info['name'])
        
        # Show user warnings about excluded fields
        if getattr(self, 'field_analysis_show_warnings', True):
            self._show_exclusion_warnings(analysis_result)
        
        return searchable_columns
    
    def get_enhanced_list_columns(self) -> List[str]:
        """
        Get intelligently filtered list/display columns.
        
        Returns:
            List of column names suitable for list display
        """
        if not getattr(self, 'field_analysis_enabled', True):
            return getattr(self, 'list_columns', []) or self._get_default_list_columns()
        
        analysis_result = self._get_field_analysis()
        
        # For list display, be more permissive but exclude clearly problematic types
        display_columns = []
        
        # Include all supported types
        for support_level in ['fully_supported', 'searchable_only', 'filterable_only', 'limited_support']:
            for col_info in analysis_result.get(support_level, []):
                display_columns.append(col_info['name'])
        
        # Exclude only clearly non-displayable types
        excluded_reasons = {
            UnsupportedReason.BINARY_DATA,
            UnsupportedReason.MULTIMEDIA,
            UnsupportedReason.VECTOR_EMBEDDINGS
        }
        
        for col_info in analysis_result.get('unsupported', []):
            if col_info.get('reason') not in [r.value for r in excluded_reasons]:
                # Include unsupported types that can still be displayed
                display_columns.append(col_info['name'])
        
        return display_columns
    
    def get_enhanced_edit_columns(self) -> List[str]:
        """
        Get intelligently filtered edit/form columns.
        
        Returns:
            List of column names suitable for edit forms
        """
        if not getattr(self, 'field_analysis_enabled', True):
            return getattr(self, 'edit_columns', []) or self._get_default_edit_columns()
        
        analysis_result = self._get_field_analysis()
        
        # For edit forms, exclude primary keys and non-editable types
        editable_columns = []
        
        for support_level in ['fully_supported', 'searchable_only', 'filterable_only', 'limited_support']:
            for col_info in analysis_result.get(support_level, []):
                # Skip primary keys and auto-increment fields
                metadata = col_info.get('metadata', {})
                if metadata.get('primary_key') or metadata.get('autoincrement'):
                    continue
                
                editable_columns.append(col_info['name'])
        
        # Include some unsupported types that might still be editable
        editable_unsupported = {
            UnsupportedReason.SPECIALIZED_FORMAT,
            UnsupportedReason.UI_LIMITATION
        }
        
        for col_info in analysis_result.get('unsupported', []):
            if col_info.get('reason') in [r.value for r in editable_unsupported]:
                metadata = col_info.get('metadata', {})
                if not (metadata.get('primary_key') or metadata.get('autoincrement')):
                    editable_columns.append(col_info['name'])
        
        return editable_columns
    
    def _get_field_analysis(self) -> Dict[str, Any]:
        """
        Get field analysis results with caching.
        
        Returns:
            Field analysis results dictionary
        """
        if not hasattr(self, 'datamodel') or not self.datamodel:
            return {'total_columns': 0, 'fully_supported': [], 'unsupported': []}
        
        model_class = self.datamodel.obj
        
        # Generate cache key
        config = {
            'strict_mode': getattr(self, 'field_analysis_strict_mode', True),
            'custom_rules': str(getattr(self, 'field_analysis_custom_rules', {}))
        }
        cache_key = self._field_analysis_cache.get_cache_key(model_class, config)
        
        # Try to get from cache
        if getattr(self, 'field_analysis_cache_enabled', True):
            cached_result = self._field_analysis_cache.get(cache_key)
            if cached_result:
                return cached_result
        
        # Perform analysis
        analysis_result = analyze_model_fields(model_class, getattr(self, 'field_analysis_strict_mode', True))
        
        # Cache the result
        if getattr(self, 'field_analysis_cache_enabled', True):
            self._field_analysis_cache.set(cache_key, analysis_result)
        
        return analysis_result
    
    def _show_exclusion_warnings(self, analysis_result: Dict[str, Any]) -> None:
        """
        Show user-friendly warnings about excluded fields.
        
        Args:
            analysis_result: Field analysis results
        """
        unsupported_fields = analysis_result.get('unsupported', [])
        limited_fields = analysis_result.get('limited_support', [])
        
        if not (unsupported_fields or limited_fields):
            return
        
        # Group exclusions by reason for cleaner messaging
        exclusion_summary = analysis_result.get('exclusion_summary', {})
        
        warning_messages = []
        
        if 'binary_data' in exclusion_summary:
            fields = ', '.join(exclusion_summary['binary_data'])
            warning_messages.append(f"Binary data fields excluded from search: {fields}")
        
        if 'multimedia' in exclusion_summary:
            fields = ', '.join(exclusion_summary['multimedia'])
            warning_messages.append(f"Multimedia fields excluded from search: {fields}")
        
        if 'complex_structure' in exclusion_summary:
            fields = ', '.join(exclusion_summary['complex_structure'])
            warning_messages.append(f"Complex data fields have limited search support: {fields}")
        
        # Show warnings (only in debug mode or for admins)
        if current_app.debug or (hasattr(current_app, 'user') and getattr(current_app.user, 'is_admin', False)):
            for message in warning_messages:
                flash(_(f"Field Analysis: {message}"), 'info')
    
    def _get_default_search_columns(self) -> List[str]:
        """Get default search columns if no analysis is available."""
        if hasattr(self, 'datamodel') and self.datamodel:
            columns = ModelInspector.get_model_columns(self.datamodel.obj)
            return [col.name for col in columns if not col.primary_key][:5]  # Limit to first 5
        return []
    
    def _get_default_list_columns(self) -> List[str]:
        """Get default list columns if no analysis is available."""
        if hasattr(self, 'datamodel') and self.datamodel:
            columns = ModelInspector.get_model_columns(self.datamodel.obj)
            return [col.name for col in columns][:10]  # Limit to first 10
        return []
    
    def _get_default_edit_columns(self) -> List[str]:
        """Get default edit columns if no analysis is available."""
        if hasattr(self, 'datamodel') and self.datamodel:
            columns = ModelInspector.get_model_columns(self.datamodel.obj)
            # Exclude primary keys and auto-increment fields
            return [col.name for col in columns 
                   if not (col.primary_key or getattr(col, 'autoincrement', False))]
        return []


@lru_cache(maxsize=128)
def get_model_analysis_report(model_class: Type, strict_mode: bool = True) -> Dict[str, Any]:
    """
    Cached function to get comprehensive model analysis report.
    
    Args:
        model_class: SQLAlchemy model class
        strict_mode: Whether to use strict mode analysis
        
    Returns:
        Comprehensive model analysis report
    """
    return analyze_model_fields(model_class, strict_mode)


class EnhancedModelView(SmartExclusionMixin, BaseModelView if HAS_FAB_MODELS else object):
    """
    Enhanced ModelView with intelligent field type analysis and automatic exclusions.
    
    This class extends the standard Flask-AppBuilder ModelView with intelligent
    field analysis capabilities, providing automatic field exclusions, enhanced
    search functionality, and improved user experience.
    
    Features:
        - Automatic field type detection and exclusion
        - Smart search and filter column selection
        - Performance-optimized field analysis with caching
        - User-friendly warnings for excluded fields
        - Configurable analysis rules and overrides
        - Integration with existing Flask-AppBuilder patterns
    
    Usage:
        class MyModelView(EnhancedModelView):
            datamodel = SQLAInterface(MyModel)
            
            # Optional: Configure field analysis
            field_analysis_strict_mode = False
            field_analysis_show_warnings = True
            field_analysis_custom_rules = {
                MyModel.special_field: FieldSupportLevel.FULLY_SUPPORTED
            }
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the enhanced model view."""
        super().__init__(*args, **kwargs)
        
        # Apply intelligent defaults if columns not explicitly set
        if not hasattr(self, 'search_columns') or not self.search_columns:
            self.search_columns = self.get_enhanced_search_columns()
        
        if not hasattr(self, 'list_columns') or not self.list_columns:
            self.list_columns = self.get_enhanced_list_columns()
        
        if not hasattr(self, 'edit_columns') or not self.edit_columns:
            self.edit_columns = self.get_enhanced_edit_columns()
    
    @property
    def model_analysis_report(self) -> Dict[str, Any]:
        """
        Get comprehensive analysis report for the current model.
        
        Returns:
            Detailed field analysis report
        """
        if hasattr(self, 'datamodel') and self.datamodel:
            return get_model_analysis_report(
                self.datamodel.obj,
                getattr(self, 'field_analysis_strict_mode', True)
            )
        return {}
    
    def get_field_recommendations(self) -> List[str]:
        """
        Get recommendations for improving field handling.
        
        Returns:
            List of recommendation strings
        """
        analysis_result = self._get_field_analysis()
        return analysis_result.get('recommendations', [])
    
    def refresh_field_analysis(self) -> None:
        """
        Refresh field analysis cache for this model.
        
        Call this method if the model structure has changed
        and you need to update the field analysis.
        """
        if hasattr(self, 'datamodel') and self.datamodel:
            self._field_analysis_cache.invalidate(self.datamodel.obj)
            
            # Regenerate columns
            self.search_columns = self.get_enhanced_search_columns()
            self.list_columns = self.get_enhanced_list_columns()
            self.edit_columns = self.get_enhanced_edit_columns()
            
            log.info(f"Refreshed field analysis for {self.datamodel.obj.__name__}")


class FieldAnalysisManager:
    """
    Centralized manager for field analysis across the application.
    
    Provides global configuration, cache management, and utilities
    for field analysis across multiple models and views.
    """
    
    def __init__(self):
        """Initialize the field analysis manager."""
        self._global_cache = FieldAnalysisCache()
        self._global_config = {
            'strict_mode': True,
            'cache_enabled': True,
            'show_warnings': True,
            'custom_rules': {}
        }
    
    def configure(self, **config) -> None:
        """
        Configure global field analysis settings.
        
        Args:
            **config: Configuration options
        """
        self._global_config.update(config)
        log.info(f"Updated global field analysis configuration: {config}")
    
    def analyze_all_models(self, models: List[Type]) -> Dict[str, Dict[str, Any]]:
        """
        Analyze multiple models and return comprehensive report.
        
        Args:
            models: List of SQLAlchemy model classes
            
        Returns:
            Dictionary mapping model names to analysis reports
        """
        results = {}
        
        for model in models:
            try:
                model_name = f"{model.__module__}.{model.__name__}"
                results[model_name] = analyze_model_fields(
                    model,
                    self._global_config.get('strict_mode', True)
                )
            except Exception as e:
                log.error(f"Error analyzing model {model}: {str(e)}")
                results[model_name] = {'error': str(e)}
        
        return results
    
    def get_application_summary(self, models: List[Type]) -> Dict[str, Any]:
        """
        Get application-wide field analysis summary.
        
        Args:
            models: List of all application models
            
        Returns:
            Application-wide analysis summary
        """
        all_results = self.analyze_all_models(models)
        
        summary = {
            'total_models': len(models),
            'total_columns': 0,
            'fully_supported_columns': 0,
            'limited_support_columns': 0,
            'unsupported_columns': 0,
            'common_exclusion_reasons': {},
            'recommendations': set()
        }
        
        for model_name, result in all_results.items():
            if 'error' in result:
                continue
                
            summary['total_columns'] += result.get('total_columns', 0)
            summary['fully_supported_columns'] += len(result.get('fully_supported', []))
            summary['limited_support_columns'] += len(result.get('limited_support', []))
            summary['unsupported_columns'] += len(result.get('unsupported', []))
            
            # Aggregate exclusion reasons
            for reason, fields in result.get('exclusion_summary', {}).items():
                if reason not in summary['common_exclusion_reasons']:
                    summary['common_exclusion_reasons'][reason] = 0
                summary['common_exclusion_reasons'][reason] += len(fields)
            
            # Collect recommendations
            summary['recommendations'].update(result.get('recommendations', []))
        
        summary['recommendations'] = list(summary['recommendations'])
        
        return summary
    
    def clear_cache(self) -> None:
        """Clear all cached field analysis results."""
        self._global_cache.clear()
        SmartExclusionMixin._field_analysis_cache.clear()
        
        # Clear function cache
        get_model_analysis_report.cache_clear()
        
        log.info("Cleared all field analysis caches")


# Global manager instance
field_analysis_manager = FieldAnalysisManager()


def smart_exclusion_decorator(view_class: Type[BaseModelView]) -> Type[BaseModelView]:
    """
    Decorator to add smart exclusion capabilities to existing ModelView classes.
    
    Args:
        view_class: ModelView class to enhance
        
    Returns:
        Enhanced ModelView class with smart exclusion
        
    Usage:
        @smart_exclusion_decorator
        class MyModelView(ModelView):
            datamodel = SQLAInterface(MyModel)
    """
    if not issubclass(view_class, BaseModelView):
        raise ValueError("Decorator can only be applied to ModelView subclasses")
    
    # Create a new class that includes SmartExclusionMixin
    class EnhancedView(SmartExclusionMixin, view_class):
        pass
    
    # Copy metadata from original class
    EnhancedView.__name__ = view_class.__name__
    EnhancedView.__module__ = view_class.__module__
    EnhancedView.__qualname__ = view_class.__qualname__
    
    return EnhancedView


def analyze_view_performance(view_instance: BaseModelView) -> Dict[str, Any]:
    """
    Analyze the performance impact of field analysis on a ModelView.
    
    Args:
        view_instance: ModelView instance to analyze
        
    Returns:
        Performance analysis report
    """
    import time
    
    performance_report = {
        'model_name': str(view_instance.datamodel.obj if hasattr(view_instance, 'datamodel') else 'Unknown'),
        'analysis_enabled': getattr(view_instance, 'field_analysis_enabled', False),
        'cache_enabled': getattr(view_instance, 'field_analysis_cache_enabled', False),
        'timing': {}
    }
    
    if hasattr(view_instance, 'get_enhanced_search_columns'):
        # Time search column analysis
        start_time = time.time()
        search_columns = view_instance.get_enhanced_search_columns()
        end_time = time.time()
        
        performance_report['timing']['search_columns'] = {
            'duration_ms': (end_time - start_time) * 1000,
            'column_count': len(search_columns)
        }
        
        # Time list column analysis
        start_time = time.time()
        list_columns = view_instance.get_enhanced_list_columns()
        end_time = time.time()
        
        performance_report['timing']['list_columns'] = {
            'duration_ms': (end_time - start_time) * 1000,
            'column_count': len(list_columns)
        }
    
    return performance_report


__all__ = [
    'EnhancedModelView',
    'SmartExclusionMixin',
    'FieldAnalysisManager',
    'ModelInspector',
    'FieldAnalysisCache',
    'field_analysis_manager',
    'smart_exclusion_decorator',
    'analyze_view_performance',
    'get_model_analysis_report'
]