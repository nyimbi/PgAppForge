"""
Field Exclusion Demonstration View

This view demonstrates the smart field exclusion system and provides
administrative tools for managing field exclusions.
"""

import logging
from typing import Any, Dict, List
from flask import render_template, jsonify, request
from pgappforge.models.sqla import Model
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose
from flask_babel import lazy_gettext, gettext
from .smart_exclusion_mixin import SmartExclusionMixin
from ..models.field_analyzer import (
    analyze_model_fields, FieldSupportLevel, UnsupportedReason
)

log = logging.getLogger(__name__)


class FieldExclusionDemoView(BaseView):
    """
    Administrative view for demonstrating and managing the field exclusion system.
    
    This view provides:
    - Demonstration of smart field exclusion
    - Field analysis reports
    - Exclusion configuration tools
    - Testing interface for different field types
    """
    
    route_base = "/admin/field-exclusion"
    default_view = "demo"
    
    @expose("/")
    @expose("/demo")
    @has_access
    def demo(self):
        """Main demonstration page showing field exclusion in action."""
        demo_data = {
            'title': gettext('Smart Field Exclusion Demo'),
            'description': gettext(
                'This page demonstrates the automatic exclusion of unsupported '
                'field types from search and filter operations.'
            ),
            'supported_operations': {
                'search': gettext('Full-text search operations'),
                'filter': gettext('Filter/query operations'),
                'display': gettext('List and detail view display')
            },
            'excluded_types': {
                'binary_data': {
                    'name': gettext('Binary Data'),
                    'types': ['BLOB', 'BYTEA', 'BINARY', 'VARBINARY'],
                    'reason': gettext('Binary data cannot be meaningfully searched or filtered')
                },
                'multimedia': {
                    'name': gettext('Multimedia Content'),
                    'types': ['ImageColumn', 'FileColumn', 'AudioColumn'],
                    'reason': gettext('Media files require specialized handling and viewers')
                },
                'complex_structure': {
                    'name': gettext('Complex Structures'),
                    'types': ['JSONB', 'JSON', 'ARRAY', 'HSTORE'],
                    'reason': gettext('Complex data structures need custom search/filter logic')
                },
                'spatial_data': {
                    'name': gettext('Spatial Data'),
                    'types': ['Geometry', 'Geography', 'PostGIS'],
                    'reason': gettext('Spatial data requires map-based interfaces and spatial queries')
                },
                'vector_embeddings': {
                    'name': gettext('Vector Embeddings'),
                    'types': ['Vector', 'pgvector'],
                    'reason': gettext('ML embeddings require similarity search, not text search')
                },
                'specialized': {
                    'name': gettext('Specialized Types'),
                    'types': ['TSVECTOR', 'INET', 'MACADDR', 'LTREE', 'UUID'],
                    'reason': gettext('Specialized types need custom handling and validation')
                }
            }
        }
        
        return self.render_template(
            'field_exclusion_demo/demo.html',
            **demo_data
        )
    
    @expose("/analyze/<model_name>")
    @has_access
    def analyze_model(self, model_name):
        """Analyze a specific model's field types and exclusions."""
        try:
            # Try to find the model class
            model_class = self._find_model_class(model_name)
            if not model_class:
                return jsonify({
                    'error': f'Model "{model_name}" not found'
                }), 404
            
            # Generate field analysis report
            report = analyze_model_fields(model_class, strict_mode=True)
            
            # Add model information
            report['model_info'] = {
                'name': model_name,
                'table_name': getattr(model_class.__table__, 'name', 'unknown'),
                'class_name': model_class.__name__
            }
            
            return jsonify(report)
            
        except Exception as e:
            log.exception(f"Error analyzing model {model_name}")
            return jsonify({
                'error': f'Error analyzing model: {str(e)}'
            }), 500
    
    @expose("/models")
    @has_access
    def list_models(self):
        """List all available models for analysis."""
        models = []
        
        try:
            # Get all registered models from the AppBuilder
            if hasattr(self.appbuilder, 'sm') and hasattr(self.appbuilder.sm, 'db'):
                from sqlalchemy import inspect
                
                # Get all tables from the database
                inspector = inspect(self.appbuilder.sm.db.engine)
                table_names = inspector.get_table_names()
                
                for table_name in table_names:
                    models.append({
                        'name': table_name,
                        'display_name': table_name.replace('_', ' ').title(),
                        'analyze_url': f'/admin/field-exclusion/analyze/{table_name}'
                    })
            
            # Sort by name
            models.sort(key=lambda x: x['name'])
            
        except Exception as e:
            log.exception("Error listing models")
            models = []
        
        return self.render_template(
            'field_exclusion_demo/models.html',
            models=models,
            title=gettext('Model Field Analysis')
        )
    
    @expose("/report")
    @has_access
    def exclusion_report(self):
        """Generate a comprehensive exclusion report for all models."""
        try:
            report_data = {
                'title': gettext('Field Exclusion Report'),
                'generated_at': self._get_current_timestamp(),
                'models': [],
                'summary': {
                    'total_models': 0,
                    'total_fields': 0,
                    'excluded_fields': 0,
                    'exclusion_reasons': {}
                }
            }
            
            # Analyze all models
            if hasattr(self.appbuilder, 'sm') and hasattr(self.appbuilder.sm, 'db'):
                from sqlalchemy import inspect
                
                inspector = inspect(self.appbuilder.sm.db.engine)
                table_names = inspector.get_table_names()
                
                for table_name in table_names[:10]:  # Limit to first 10 for demo
                    try:
                        model_class = self._find_model_class(table_name)
                        if model_class:
                            model_report = analyze_model_fields(model_class)
                            model_report['model_name'] = table_name
                            report_data['models'].append(model_report)
                            
                            # Update summary
                            report_data['summary']['total_models'] += 1
                            report_data['summary']['total_fields'] += model_report.get('total_columns', 0)
                            report_data['summary']['excluded_fields'] += len(model_report.get('unsupported', []))
                            
                            # Count exclusion reasons
                            for reason, fields in model_report.get('exclusion_summary', {}).items():
                                if reason not in report_data['summary']['exclusion_reasons']:
                                    report_data['summary']['exclusion_reasons'][reason] = 0
                                report_data['summary']['exclusion_reasons'][reason] += len(fields)
                                
                    except Exception as e:
                        log.warning(f"Error analyzing model {table_name}: {e}")
                        continue
            
            return self.render_template(
                'field_exclusion_demo/report.html',
                **report_data
            )
            
        except Exception as e:
            log.exception("Error generating exclusion report")
            return self.render_template(
                'field_exclusion_demo/error.html',
                error=str(e)
            )
    
    @expose("/test")
    @has_access
    def test_exclusion(self):
        """Interactive testing interface for field exclusion rules."""
        return self.render_template(
            'field_exclusion_demo/test.html',
            title=gettext('Test Field Exclusion'),
            description=gettext(
                'Use this interface to test how different field types '
                'are handled by the exclusion system.'
            )
        )
    
    @expose("/api/test-field-type", methods=['POST'])
    @has_access
    def api_test_field_type(self):
        """API endpoint for testing individual field types."""
        try:
            data = request.get_json()
            field_type_name = data.get('field_type')
            
            if not field_type_name:
                return jsonify({
                    'error': 'field_type parameter is required'
                }), 400
            
            # Try to import and test the field type
            result = self._test_field_type(field_type_name)
            return jsonify(result)
            
        except Exception as e:
            log.exception("Error testing field type")
            return jsonify({
                'error': f'Error testing field type: {str(e)}'
            }), 500
    
    def _find_model_class(self, model_name: str):
        """Try to find a model class by name."""
        try:
            # This is a simplified approach - in a real app you'd have
            # a proper model registry
            if hasattr(self.appbuilder, 'sm') and hasattr(self.appbuilder.sm, 'db'):
                from sqlalchemy import MetaData
                
                # Get metadata to find tables
                metadata = MetaData()
                metadata.reflect(bind=self.appbuilder.sm.db.engine)
                
                if model_name in metadata.tables:
                    # Create a dynamic model class for testing
                    table = metadata.tables[model_name]
                    
                    # Create a basic model class
                    class DynamicModel(Model):
                        __table__ = table
                        __tablename__ = model_name
                    
                    DynamicModel.__name__ = f"Dynamic{model_name.title().replace('_', '')}"
                    return DynamicModel
            
            return None
            
        except Exception as e:
            log.exception(f"Error finding model class for {model_name}")
            return None
    
    def _test_field_type(self, field_type_name: str) -> Dict[str, Any]:
        """Test a specific field type with the exclusion system."""
        try:
            from ..models.field_analyzer import DEFAULT_ANALYZER
            
            # Try to import the field type
            field_type_class = self._import_field_type(field_type_name)
            if not field_type_class:
                return {
                    'error': f'Could not import field type: {field_type_name}',
                    'field_type': field_type_name
                }
            
            # Create a dummy column for testing
            from sqlalchemy import Column
            dummy_column = Column('test_field', field_type_class())
            
            # Analyze the column
            support_level, reason, metadata = DEFAULT_ANALYZER.analyze_column(dummy_column)
            
            return {
                'field_type': field_type_name,
                'support_level': support_level.value,
                'unsupported_reason': reason.value if reason else None,
                'metadata': metadata,
                'can_search': support_level in {
                    FieldSupportLevel.FULLY_SUPPORTED,
                    FieldSupportLevel.SEARCHABLE_ONLY,
                    FieldSupportLevel.LIMITED_SUPPORT
                },
                'can_filter': support_level in {
                    FieldSupportLevel.FULLY_SUPPORTED,
                    FieldSupportLevel.FILTERABLE_ONLY,
                    FieldSupportLevel.LIMITED_SUPPORT
                }
            }
            
        except Exception as e:
            return {
                'error': f'Error testing field type: {str(e)}',
                'field_type': field_type_name
            }
    
    def _import_field_type(self, field_type_name: str):
        """Try to import a field type class by name."""
        try:
            # Try standard SQLAlchemy types first
            from sqlalchemy import (
                String, Integer, Boolean, DateTime, Date, Text, Float, 
                Numeric, JSON, BINARY, BLOB
            )
            
            standard_types = {
                'String': String,
                'Integer': Integer,
                'Boolean': Boolean,
                'DateTime': DateTime,
                'Date': Date,
                'Text': Text,
                'Float': Float,
                'Numeric': Numeric,
                'JSON': JSON,
                'BINARY': BINARY,
                'BLOB': BLOB,
            }
            
            if field_type_name in standard_types:
                return standard_types[field_type_name]
            
            # Try PostgreSQL types
            try:
                from sqlalchemy.dialects.postgresql import (
                    JSONB, ARRAY, UUID, INET, MACADDR, TSVECTOR, HSTORE
                )
                pg_types = {
                    'JSONB': JSONB,
                    'ARRAY': ARRAY,
                    'UUID': UUID,
                    'INET': INET,
                    'MACADDR': MACADDR,
                    'TSVECTOR': TSVECTOR,
                    'HSTORE': HSTORE,
                }
                if field_type_name in pg_types:
                    return pg_types[field_type_name]
            except ImportError:
                pass
            
            # Try PgAppForge types
            try:
                from pgappforge.fieldwidgets import ImageColumn, FileColumn
                from pgappforge.models.postgresql import Vector, Geometry, Geography
                
                fab_types = {
                    'ImageColumn': ImageColumn,
                    'FileColumn': FileColumn,
                    'Vector': Vector,
                    'Geometry': Geometry,
                    'Geography': Geography,
                }
                if field_type_name in fab_types:
                    return fab_types[field_type_name]
            except ImportError:
                pass
            
            return None
            
        except Exception as e:
            log.exception(f"Error importing field type {field_type_name}")
            return None
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp as formatted string."""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')