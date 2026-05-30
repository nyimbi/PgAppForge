"""
Advanced Field Type Analysis and Auto-Exclusion System for PgAppForge

This module provides comprehensive field type detection and automatic exclusion
of unsupported field types from search and filter operations.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union
from enum import Enum
import inspect

# SQLAlchemy imports
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Date, Float, Numeric
from sqlalchemy.sql.sqltypes import (
    ARRAY, BIGINT, BINARY, BIT, BLOB, BOOLEAN, CHAR, CLOB, DATE, DATETIME,
    DECIMAL, FLOAT, INTEGER, INTERVAL, LARGEBINARY, NCHAR, NUMERIC, NVARCHAR, 
    REAL, SMALLINT, TEXT, TIME, TIMESTAMP, VARBINARY, VARCHAR
)
from sqlalchemy.types import TypeEngine, UserDefinedType
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.ext.hybrid import hybrid_property

try:
    # PostgreSQL-specific types
    from sqlalchemy.dialects.postgresql import (
        ARRAY as PG_ARRAY, BIGINT as PG_BIGINT, BIT as PG_BIT, 
        BOOLEAN as PG_BOOLEAN, BYTEA, CHAR as PG_CHAR, DATE as PG_DATE, 
        DOUBLE_PRECISION, ENUM as PG_ENUM, FLOAT as PG_FLOAT, 
        INET, INTEGER as PG_INTEGER, INTERVAL as PG_INTERVAL, 
        JSON, JSONB, MACADDR, MACADDR8, MONEY, NUMERIC as PG_NUMERIC, 
        OID, REAL as PG_REAL, SMALLINT as PG_SMALLINT, 
        TEXT as PG_TEXT, TIME as PG_TIME, TIMESTAMP as PG_TIMESTAMP, 
        TSVECTOR, UUID as PG_UUID, VARCHAR as PG_VARCHAR, HSTORE
    )
    HAS_POSTGRESQL = True
except ImportError:
    HAS_POSTGRESQL = False

try:
    # MySQL-specific types
    from sqlalchemy.dialects.mysql import (
        BIGINT as MY_BIGINT, BINARY as MY_BINARY, BIT as MY_BIT,
        BLOB as MY_BLOB, BOOLEAN as MY_BOOLEAN, CHAR as MY_CHAR,
        DATE as MY_DATE, DATETIME as MY_DATETIME, DECIMAL as MY_DECIMAL,
        DOUBLE as MY_DOUBLE, ENUM as MY_ENUM, FLOAT as MY_FLOAT,
        INTEGER as MY_INTEGER, JSON as MY_JSON, LONGBLOB, LONGTEXT,
        MEDIUMBLOB, MEDIUMINT, MEDIUMTEXT, NUMERIC as MY_NUMERIC,
        REAL as MY_REAL, SET as MY_SET, SMALLINT as MY_SMALLINT,
        TEXT as MY_TEXT, TIME as MY_TIME, TIMESTAMP as MY_TIMESTAMP,
        TINYBLOB, TINYINT, TINYTEXT, VARBINARY as MY_VARBINARY,
        VARCHAR as MY_VARCHAR, YEAR
    )
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False

try:
    # SQLite-specific types (usually compatible with standard types)
    from sqlalchemy.dialects.sqlite import (
        DATE as SQLITE_DATE, DATETIME as SQLITE_DATETIME,
        JSON as SQLITE_JSON, NUMERIC as SQLITE_NUMERIC,
        TIME as SQLITE_TIME
    )
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False

try:
    # Custom PgAppForge types
    from pgappforge.fieldwidgets import ImageColumn, FileColumn
    HAS_FAB_WIDGETS = True
except ImportError:
    HAS_FAB_WIDGETS = False

try:
    # Custom PostgreSQL types (if available)
    from pgappforge.models.postgresql import (
        Vector, Geometry, Geography, LTREE, HSTORE as FAB_HSTORE
    )
    HAS_FAB_POSTGRESQL = True
except ImportError:
    HAS_FAB_POSTGRESQL = False


log = logging.getLogger(__name__)


class FieldSupportLevel(Enum):
    """
    Enumeration of field support levels for search and filtering operations.
    """
    FULLY_SUPPORTED = "fully_supported"      # Full search and filter support
    SEARCHABLE_ONLY = "searchable_only"      # Can be searched but not filtered
    FILTERABLE_ONLY = "filterable_only"      # Can be filtered but not searched
    LIMITED_SUPPORT = "limited_support"      # Basic support with limitations
    UNSUPPORTED = "unsupported"              # No search or filter support
    CUSTOM_HANDLER = "custom_handler"        # Requires custom handling


class UnsupportedReason(Enum):
    """
    Reasons why a field type might be unsupported for search/filter operations.
    """
    BINARY_DATA = "binary_data"                    # Binary/blob data
    MULTIMEDIA = "multimedia"                      # Images, audio, video
    COMPLEX_STRUCTURE = "complex_structure"        # JSON, arrays, nested objects
    SPATIAL_DATA = "spatial_data"                  # Geographic/geometric data
    LARGE_TEXT = "large_text"                     # Very large text fields
    VECTOR_EMBEDDINGS = "vector_embeddings"       # ML vector embeddings
    NETWORK_ADDRESSES = "network_addresses"       # IP addresses, MAC addresses
    SPECIALIZED_FORMAT = "specialized_format"     # UUID, bit strings, intervals
    FULL_TEXT_SEARCH = "full_text_search"        # Full-text search vectors
    PERFORMANCE_CONCERN = "performance_concern"   # Types that cause performance issues
    UI_LIMITATION = "ui_limitation"               # Types without proper UI widgets


class FieldTypeAnalyzer:
    """
    Comprehensive field type analyzer for automatic exclusion of unsupported types.
    
    This class analyzes SQLAlchemy column types and determines their suitability
    for search and filter operations, automatically excluding unsupported types
    while providing detailed reasoning and alternative handling suggestions.
    """
    
    # Core supported types that work well with search and filtering
    FULLY_SUPPORTED_TYPES = {
        # Standard string types
        String, VARCHAR, CHAR, TEXT,
        
        # Numeric types
        Integer, BIGINT, SMALLINT, Float, REAL, Numeric, DECIMAL,
        
        # Date/time types
        DateTime, Date, TIMESTAMP, TIME,
        
        # Boolean type
        Boolean, BOOLEAN,
        
        # Enum types work well for filtering
    }
    
    # Types that can be searched but filtering is problematic
    SEARCHABLE_ONLY_TYPES = {
        # Large text fields can be searched but filtering is expensive
        CLOB, LONGTEXT if HAS_MYSQL else None,
        MEDIUMTEXT if HAS_MYSQL else None,
    }
    
    # Types that can be filtered but searching doesn't make sense
    FILTERABLE_ONLY_TYPES = {
        # These can have equality filters but text search doesn't apply
    }
    
    # Types with limited support (basic operations only)
    LIMITED_SUPPORT_TYPES = {
        # UUIDs can be filtered by exact match but not partial search
        PG_UUID if HAS_POSTGRESQL else None,
        
        # JSON can be filtered by keys but searching content is complex
        JSON, JSONB if HAS_POSTGRESQL else None,
        MY_JSON if HAS_MYSQL else None,
        SQLITE_JSON if HAS_SQLITE else None,
        
        # Arrays can be filtered for containment but not text-searched
        ARRAY, PG_ARRAY if HAS_POSTGRESQL else None,
        
        # Enums can be filtered but searching is limited
        PG_ENUM if HAS_POSTGRESQL else None,
        MY_ENUM if HAS_MYSQL else None,
        MY_SET if HAS_MYSQL else None,
    }
    
    # Completely unsupported types
    UNSUPPORTED_TYPES = {
        # Binary data
        BINARY, VARBINARY, LARGEBINARY, BYTEA if HAS_POSTGRESQL else None,
        MY_BINARY if HAS_MYSQL else None, MY_VARBINARY if HAS_MYSQL else None,
        
        # BLOB types
        BLOB, MY_BLOB if HAS_MYSQL else None, LONGBLOB if HAS_MYSQL else None,
        MEDIUMBLOB if HAS_MYSQL else None, TINYBLOB if HAS_MYSQL else None,
        
        # Bit strings
        BIT, PG_BIT if HAS_POSTGRESQL else None, MY_BIT if HAS_MYSQL else None,
        
        # Network addresses
        INET if HAS_POSTGRESQL else None,
        MACADDR if HAS_POSTGRESQL else None,
        MACADDR8 if HAS_POSTGRESQL else None,
        
        # Spatial data
        Geometry if HAS_FAB_POSTGRESQL else None,
        Geography if HAS_FAB_POSTGRESQL else None,
        
        # Vector embeddings
        Vector if HAS_FAB_POSTGRESQL else None,
        
        # Full-text search vectors
        TSVECTOR if HAS_POSTGRESQL else None,
        
        # Specialized types
        INTERVAL, PG_INTERVAL if HAS_POSTGRESQL else None,
        MONEY if HAS_POSTGRESQL else None,
        OID if HAS_POSTGRESQL else None,
        YEAR if HAS_MYSQL else None,
        
        # Tree/hierarchical data
        LTREE if HAS_FAB_POSTGRESQL else None,
        
        # Key-value stores
        HSTORE if HAS_POSTGRESQL else None,
        FAB_HSTORE if HAS_FAB_POSTGRESQL else None,
    }
    
    # PgAppForge specific unsupported types
    FAB_UNSUPPORTED_TYPES = {
        ImageColumn if HAS_FAB_WIDGETS else None,
        FileColumn if HAS_FAB_WIDGETS else None,
    }
    
    def __init__(self, strict_mode: bool = True, custom_rules: Optional[Dict] = None):
        """
        Initialize the field type analyzer.
        
        Args:
            strict_mode: If True, err on the side of exclusion for ambiguous types
            custom_rules: Additional custom type classification rules
        """
        self.strict_mode = strict_mode
        self.custom_rules = custom_rules or {}
        
        # Build consolidated type mappings (remove None values)
        self.fully_supported = {t for t in self.FULLY_SUPPORTED_TYPES if t is not None}
        self.searchable_only = {t for t in self.SEARCHABLE_ONLY_TYPES if t is not None}
        self.filterable_only = {t for t in self.FILTERABLE_ONLY_TYPES if t is not None}
        self.limited_support = {t for t in self.LIMITED_SUPPORT_TYPES if t is not None}
        self.unsupported = {t for t in self.UNSUPPORTED_TYPES if t is not None}
        self.fab_unsupported = {t for t in self.FAB_UNSUPPORTED_TYPES if t is not None}
        
        # Add database-specific type mappings
        self._add_database_specific_mappings()
        
        # Apply custom rules
        self._apply_custom_rules()
        
    def _add_database_specific_mappings(self):
        """Add database-specific type classifications."""
        # PostgreSQL specific
        if HAS_POSTGRESQL:
            # PostgreSQL text types are well-supported
            self.fully_supported.update({PG_TEXT, PG_VARCHAR, PG_CHAR})
            
            # PostgreSQL numeric types
            self.fully_supported.update({
                PG_INTEGER, PG_BIGINT, PG_SMALLINT, PG_NUMERIC, 
                PG_REAL, PG_FLOAT, DOUBLE_PRECISION
            })
            
            # PostgreSQL date/time types
            self.fully_supported.update({PG_DATE, PG_TIME, PG_TIMESTAMP})
            
            # PostgreSQL boolean
            self.fully_supported.add(PG_BOOLEAN)
        
        # MySQL specific
        if HAS_MYSQL:
            # MySQL text types
            self.fully_supported.update({MY_TEXT, MY_VARCHAR, MY_CHAR})
            
            # MySQL numeric types  
            self.fully_supported.update({
                MY_INTEGER, MY_BIGINT, MY_SMALLINT, MEDIUMINT, TINYINT,
                MY_NUMERIC, MY_DECIMAL, MY_REAL, MY_FLOAT, MY_DOUBLE
            })
            
            # MySQL date/time types
            self.fully_supported.update({MY_DATE, MY_TIME, MY_TIMESTAMP, MY_DATETIME})
            
            # MySQL boolean
            self.fully_supported.add(MY_BOOLEAN)
            
            # MySQL text variants (searchable but potentially slow for filtering)
            self.searchable_only.update({LONGTEXT, MEDIUMTEXT, TINYTEXT})
        
        # SQLite specific
        if HAS_SQLITE:
            self.fully_supported.update({
                SQLITE_DATE, SQLITE_DATETIME, SQLITE_TIME, SQLITE_NUMERIC
            })
            self.limited_support.add(SQLITE_JSON)
    
    def _apply_custom_rules(self):
        """Apply custom user-defined type classification rules."""
        for type_class, support_level in self.custom_rules.items():
            # Remove from all existing categories
            self._remove_type_from_all_categories(type_class)
            
            # Add to appropriate category
            if support_level == FieldSupportLevel.FULLY_SUPPORTED:
                self.fully_supported.add(type_class)
            elif support_level == FieldSupportLevel.SEARCHABLE_ONLY:
                self.searchable_only.add(type_class)
            elif support_level == FieldSupportLevel.FILTERABLE_ONLY:
                self.filterable_only.add(type_class)
            elif support_level == FieldSupportLevel.LIMITED_SUPPORT:
                self.limited_support.add(type_class)
            elif support_level == FieldSupportLevel.UNSUPPORTED:
                self.unsupported.add(type_class)
    
    def _remove_type_from_all_categories(self, type_class: Type):
        """Remove a type from all classification categories."""
        for category in [self.fully_supported, self.searchable_only, 
                        self.filterable_only, self.limited_support, 
                        self.unsupported, self.fab_unsupported]:
            category.discard(type_class)
    
    def analyze_column(self, column: Column) -> Tuple[FieldSupportLevel, Optional[UnsupportedReason], Dict[str, Any]]:
        """
        Analyze a SQLAlchemy column and determine its search/filter support level.
        
        Args:
            column: SQLAlchemy Column object to analyze
            
        Returns:
            Tuple of (support_level, unsupported_reason, metadata)
        """
        metadata = {
            'column_name': column.name if hasattr(column, 'name') else 'unknown',
            'python_type': str(type(column.type)),
            'sqlalchemy_type': column.type.__class__.__name__,
            'nullable': getattr(column, 'nullable', True),
            'primary_key': getattr(column, 'primary_key', False),
            'foreign_key': bool(getattr(column, 'foreign_keys', [])),
            'unique': getattr(column, 'unique', False),
            'indexed': getattr(column, 'index', False),
        }
        
        # Check for PgAppForge specific unsupported types first
        if self._is_fab_unsupported_type(column.type):
            reason = self._get_fab_unsupported_reason(column.type)
            metadata['details'] = f"PgAppForge specific unsupported type: {reason}"
            return FieldSupportLevel.UNSUPPORTED, reason, metadata
        
        # Check type hierarchy for classification
        column_type_class = type(column.type)
        
        # Check fully supported types
        if self._type_matches_any(column_type_class, self.fully_supported):
            metadata['details'] = "Fully supported for both search and filtering"
            return FieldSupportLevel.FULLY_SUPPORTED, None, metadata
        
        # Check searchable only types
        if self._type_matches_any(column_type_class, self.searchable_only):
            metadata['details'] = "Supports search operations but filtering may be inefficient"
            return FieldSupportLevel.SEARCHABLE_ONLY, UnsupportedReason.PERFORMANCE_CONCERN, metadata
        
        # Check filterable only types
        if self._type_matches_any(column_type_class, self.filterable_only):
            metadata['details'] = "Supports filtering but text search is not applicable"
            return FieldSupportLevel.FILTERABLE_ONLY, UnsupportedReason.UI_LIMITATION, metadata
        
        # Check limited support types
        if self._type_matches_any(column_type_class, self.limited_support):
            reason = self._get_limited_support_reason(column.type)
            metadata['details'] = f"Limited support: {reason}"
            return FieldSupportLevel.LIMITED_SUPPORT, reason, metadata
        
        # Check explicitly unsupported types
        if self._type_matches_any(column_type_class, self.unsupported):
            reason = self._get_unsupported_reason(column.type)
            metadata['details'] = f"Unsupported type: {reason}"
            return FieldSupportLevel.UNSUPPORTED, reason, metadata
        
        # Handle unknown types based on strict mode
        if self.strict_mode:
            # In strict mode, unknown types are unsupported by default
            metadata['details'] = "Unknown type treated as unsupported in strict mode"
            return FieldSupportLevel.UNSUPPORTED, UnsupportedReason.SPECIALIZED_FORMAT, metadata
        else:
            # In permissive mode, assume basic support
            metadata['details'] = "Unknown type with basic support in permissive mode"
            return FieldSupportLevel.LIMITED_SUPPORT, UnsupportedReason.UI_LIMITATION, metadata
    
    def _is_fab_unsupported_type(self, column_type: TypeEngine) -> bool:
        """Check if the column type is a PgAppForge specific unsupported type."""
        return self._type_matches_any(type(column_type), self.fab_unsupported)
    
    def _get_fab_unsupported_reason(self, column_type: TypeEngine) -> UnsupportedReason:
        """Get the reason why a PgAppForge type is unsupported."""
        if HAS_FAB_WIDGETS:
            if isinstance(column_type, ImageColumn):
                return UnsupportedReason.MULTIMEDIA
            elif isinstance(column_type, FileColumn):
                return UnsupportedReason.BINARY_DATA
        return UnsupportedReason.SPECIALIZED_FORMAT
    
    def _get_limited_support_reason(self, column_type: TypeEngine) -> UnsupportedReason:
        """Get the reason why a type has limited support."""
        type_class = type(column_type)
        
        # JSON types
        if type_class in {JSON, JSONB} or (HAS_MYSQL and type_class == MY_JSON):
            return UnsupportedReason.COMPLEX_STRUCTURE
        
        # Array types
        if type_class in {ARRAY} or (HAS_POSTGRESQL and type_class == PG_ARRAY):
            return UnsupportedReason.COMPLEX_STRUCTURE
        
        # UUID types
        if HAS_POSTGRESQL and type_class == PG_UUID:
            return UnsupportedReason.SPECIALIZED_FORMAT
        
        # Enum types
        if (HAS_POSTGRESQL and type_class == PG_ENUM) or \
           (HAS_MYSQL and type_class in {MY_ENUM, MY_SET}):
            return UnsupportedReason.UI_LIMITATION
        
        return UnsupportedReason.UI_LIMITATION
    
    def _get_unsupported_reason(self, column_type: TypeEngine) -> UnsupportedReason:
        """Get the reason why a type is unsupported."""
        type_class = type(column_type)
        
        # Binary data types
        binary_types = {BINARY, VARBINARY, LARGEBINARY, BLOB}
        if HAS_POSTGRESQL:
            binary_types.add(BYTEA)
        if HAS_MYSQL:
            binary_types.update({MY_BINARY, MY_VARBINARY, MY_BLOB, LONGBLOB, MEDIUMBLOB, TINYBLOB})
        
        if type_class in binary_types:
            return UnsupportedReason.BINARY_DATA
        
        # Spatial data types
        if HAS_FAB_POSTGRESQL and type_class in {Geometry, Geography}:
            return UnsupportedReason.SPATIAL_DATA
        
        # Vector embedding types
        if HAS_FAB_POSTGRESQL and type_class == Vector:
            return UnsupportedReason.VECTOR_EMBEDDINGS
        
        # Network address types
        if HAS_POSTGRESQL and type_class in {INET, MACADDR, MACADDR8}:
            return UnsupportedReason.NETWORK_ADDRESSES
        
        # Full-text search types
        if HAS_POSTGRESQL and type_class == TSVECTOR:
            return UnsupportedReason.FULL_TEXT_SEARCH
        
        # Bit string types
        bit_types = {BIT}
        if HAS_POSTGRESQL:
            bit_types.add(PG_BIT)
        if HAS_MYSQL:
            bit_types.add(MY_BIT)
        if type_class in bit_types:
            return UnsupportedReason.SPECIALIZED_FORMAT
        
        # Specialized PostgreSQL types
        if HAS_POSTGRESQL and type_class in {MONEY, OID, INTERVAL, PG_INTERVAL}:
            return UnsupportedReason.SPECIALIZED_FORMAT
        
        # Tree/hierarchical types
        if HAS_FAB_POSTGRESQL and type_class == LTREE:
            return UnsupportedReason.COMPLEX_STRUCTURE
        
        # Key-value store types
        if (HAS_POSTGRESQL and type_class == HSTORE) or \
           (HAS_FAB_POSTGRESQL and type_class == FAB_HSTORE):
            return UnsupportedReason.COMPLEX_STRUCTURE
        
        # MySQL specific types
        if HAS_MYSQL and type_class == YEAR:
            return UnsupportedReason.SPECIALIZED_FORMAT
        
        return UnsupportedReason.SPECIALIZED_FORMAT
    
    def _type_matches_any(self, type_class: Type, type_set: Set[Type]) -> bool:
        """
        Check if a type class matches any type in the given set,
        including inheritance relationships.
        """
        # Direct match
        if type_class in type_set:
            return True
        
        # Check inheritance
        for supported_type in type_set:
            if supported_type and issubclass(type_class, supported_type):
                return True
        
        return False
    
    def get_searchable_columns(self, columns: List[Column]) -> List[str]:
        """
        Get a list of column names that support search operations.
        
        Args:
            columns: List of SQLAlchemy Column objects
            
        Returns:
            List of column names suitable for search operations
        """
        searchable_columns = []
        
        for column in columns:
            support_level, reason, metadata = self.analyze_column(column)
            
            if support_level in {FieldSupportLevel.FULLY_SUPPORTED, FieldSupportLevel.SEARCHABLE_ONLY}:
                searchable_columns.append(column.name)
            elif support_level == FieldSupportLevel.LIMITED_SUPPORT and not self.strict_mode:
                # In permissive mode, include limited support columns for search
                searchable_columns.append(column.name)
        
        return searchable_columns
    
    def get_filterable_columns(self, columns: List[Column]) -> List[str]:
        """
        Get a list of column names that support filter operations.
        
        Args:
            columns: List of SQLAlchemy Column objects
            
        Returns:
            List of column names suitable for filter operations
        """
        filterable_columns = []
        
        for column in columns:
            support_level, reason, metadata = self.analyze_column(column)
            
            if support_level in {FieldSupportLevel.FULLY_SUPPORTED, FieldSupportLevel.FILTERABLE_ONLY}:
                filterable_columns.append(column.name)
            elif support_level == FieldSupportLevel.LIMITED_SUPPORT:
                # Limited support types often support basic filtering
                filterable_columns.append(column.name)
        
        return filterable_columns
    
    def generate_exclusion_report(self, columns: List[Column]) -> Dict[str, Any]:
        """
        Generate a comprehensive report of column exclusions and reasons.
        
        Args:
            columns: List of SQLAlchemy Column objects to analyze
            
        Returns:
            Detailed report dictionary with exclusion analysis
        """
        report = {
            'total_columns': len(columns),
            'fully_supported': [],
            'searchable_only': [],
            'filterable_only': [],
            'limited_support': [],
            'unsupported': [],
            'exclusion_summary': {},
            'recommendations': []
        }
        
        exclusion_reasons = {}
        
        for column in columns:
            support_level, reason, metadata = self.analyze_column(column)
            
            column_info = {
                'name': column.name,
                'type': metadata['sqlalchemy_type'],
                'reason': reason.value if reason else None,
                'details': metadata.get('details', ''),
                'metadata': metadata
            }
            
            if support_level == FieldSupportLevel.FULLY_SUPPORTED:
                report['fully_supported'].append(column_info)
            elif support_level == FieldSupportLevel.SEARCHABLE_ONLY:
                report['searchable_only'].append(column_info)
            elif support_level == FieldSupportLevel.FILTERABLE_ONLY:
                report['filterable_only'].append(column_info)
            elif support_level == FieldSupportLevel.LIMITED_SUPPORT:
                report['limited_support'].append(column_info)
            elif support_level == FieldSupportLevel.UNSUPPORTED:
                report['unsupported'].append(column_info)
                
                # Track exclusion reasons
                if reason:
                    if reason.value not in exclusion_reasons:
                        exclusion_reasons[reason.value] = []
                    exclusion_reasons[reason.value].append(column.name)
        
        report['exclusion_summary'] = exclusion_reasons
        
        # Generate recommendations
        report['recommendations'] = self._generate_recommendations(report)
        
        return report
    
    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on the exclusion analysis."""
        recommendations = []
        
        # Check for binary data exclusions
        if 'binary_data' in report['exclusion_summary']:
            recommendations.append(
                "Consider using separate file storage for binary data columns and "
                "storing file paths/URLs instead of binary data directly in the database."
            )
        
        # Check for multimedia exclusions
        if 'multimedia' in report['exclusion_summary']:
            recommendations.append(
                "For multimedia columns, implement custom upload/display widgets and "
                "use metadata fields (filename, size, type) for searching and filtering."
            )
        
        # Check for JSON/complex structure exclusions
        if 'complex_structure' in report['exclusion_summary']:
            recommendations.append(
                "For JSON/array columns, consider extracting commonly-searched keys "
                "into separate indexed columns or implement custom filter widgets."
            )
        
        # Check for spatial data
        if 'spatial_data' in report['exclusion_summary']:
            recommendations.append(
                "For spatial data columns, implement custom map-based filtering widgets "
                "and consider adding derived location text fields for text-based search."
            )
        
        # Check for performance concerns
        if 'performance_concern' in report['exclusion_summary']:
            recommendations.append(
                "For large text fields, consider implementing full-text search indexes "
                "or separate search-optimized fields with truncated content."
            )
        
        # Check for UI limitations
        if 'ui_limitation' in report['exclusion_summary']:
            recommendations.append(
                "For specialized field types, consider implementing custom form widgets "
                "or converting values to user-friendly formats for display."
            )
        
        return recommendations


def analyze_model_fields(model_class: Type, strict_mode: bool = True) -> Dict[str, Any]:
    """
    Convenience function to analyze all fields in a SQLAlchemy model class.
    
    Args:
        model_class: SQLAlchemy model class to analyze
        strict_mode: Whether to use strict mode for unknown types
        
    Returns:
        Complete analysis report for the model's fields
    """
    analyzer = FieldTypeAnalyzer(strict_mode=strict_mode)
    
    # Get all columns from the model
    columns = []
    if hasattr(model_class, '__table__'):
        columns = list(model_class.__table__.columns)
    
    return analyzer.generate_exclusion_report(columns)


# Pre-configured analyzer instances
DEFAULT_ANALYZER = FieldTypeAnalyzer(strict_mode=True)
PERMISSIVE_ANALYZER = FieldTypeAnalyzer(strict_mode=False)