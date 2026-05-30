"""
Test suite for PostgreSQL, PostGIS, and pgVector data type support
in the Enhanced Database Inspector.
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, MagicMock

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, Column, Integer, String, Text, types
from sqlalchemy.engine import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import TypeDecorator

from pgappforge.cli.generators.database_inspector import (
    EnhancedDatabaseInspector,
    ColumnType
)


class MockPostgreSQLColumn:
    """Mock PostgreSQL column for testing type categorization."""
    
    def __init__(self, name, type_string, nullable=True, primary_key=False, foreign_keys=None):
        self.name = name
        
        # Create proper SQLAlchemy type mock with isinstance() compatibility
        self.type = Mock()
        self.type.__str__ = lambda: type_string
        
        # Fix: Add proper type checking for isinstance() calls
        if 'ARRAY' in type_string.upper() or '[]' in type_string:
            # Mock ARRAY type for isinstance checks
            self.type.__class__ = sa.types.ARRAY
        elif 'JSON' in type_string.upper():
            self.type.__class__ = sa.types.JSON
        elif 'TEXT' in type_string.upper():
            self.type.__class__ = sa.types.Text
        elif 'INTEGER' in type_string.upper() or 'INT' in type_string.upper():
            self.type.__class__ = sa.types.Integer
        elif 'BOOLEAN' in type_string.upper():
            self.type.__class__ = sa.types.Boolean
        else:
            self.type.__class__ = sa.types.String
            
        self.nullable = nullable
        self.primary_key = primary_key
        self.foreign_keys = foreign_keys or []


class TestPostgreSQLAdvancedTypes(unittest.TestCase):
    """Test PostgreSQL, PostGIS, and pgVector data type support."""

    def setUp(self):
        """Set up test environment."""
        self.test_db_uri = "sqlite:///:memory:"  # Using SQLite for basic testing
        self.inspector = EnhancedDatabaseInspector(self.test_db_uri)

    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self.inspector, 'engine'):
            self.inspector.engine.dispose()

    def test_postgresql_uuid_type_categorization(self):
        """Test PostgreSQL UUID type categorization."""
        column = MockPostgreSQLColumn('user_id', 'UUID')
        category = self.inspector._categorize_column(column, 'users')
        self.assertEqual(category, ColumnType.UUID)

    def test_postgresql_jsonb_type_categorization(self):
        """Test PostgreSQL JSONB type categorization."""
        column = MockPostgreSQLColumn('metadata', 'JSONB')
        category = self.inspector._categorize_column(column, 'documents')
        self.assertEqual(category, ColumnType.JSONB)

    def test_postgresql_hstore_type_categorization(self):
        """Test PostgreSQL HSTORE type categorization."""
        column = MockPostgreSQLColumn('attributes', 'HSTORE')
        category = self.inspector._categorize_column(column, 'products')
        self.assertEqual(category, ColumnType.HSTORE)

    def test_postgresql_ltree_type_categorization(self):
        """Test PostgreSQL LTREE type categorization."""
        column = MockPostgreSQLColumn('path', 'LTREE')
        category = self.inspector._categorize_column(column, 'categories')
        self.assertEqual(category, ColumnType.LTREE)

    def test_postgresql_inet_type_categorization(self):
        """Test PostgreSQL INET type categorization."""
        column = MockPostgreSQLColumn('ip_address', 'INET')
        category = self.inspector._categorize_column(column, 'connections')
        self.assertEqual(category, ColumnType.INET)

    def test_postgresql_cidr_type_categorization(self):
        """Test PostgreSQL CIDR type categorization."""
        column = MockPostgreSQLColumn('network', 'CIDR')
        category = self.inspector._categorize_column(column, 'networks')
        self.assertEqual(category, ColumnType.CIDR)

    def test_postgresql_macaddr_type_categorization(self):
        """Test PostgreSQL MACADDR type categorization."""
        column = MockPostgreSQLColumn('mac_address', 'MACADDR')
        category = self.inspector._categorize_column(column, 'devices')
        self.assertEqual(category, ColumnType.MACADDR)

    def test_postgresql_tsvector_type_categorization(self):
        """Test PostgreSQL TSVECTOR type categorization."""
        column = MockPostgreSQLColumn('search_vector', 'TSVECTOR')
        category = self.inspector._categorize_column(column, 'articles')
        self.assertEqual(category, ColumnType.TSVECTOR)

    def test_postgresql_tsquery_type_categorization(self):
        """Test PostgreSQL TSQUERY type categorization."""
        column = MockPostgreSQLColumn('search_query', 'TSQUERY')
        category = self.inspector._categorize_column(column, 'searches')
        self.assertEqual(category, ColumnType.TSQUERY)

    def test_postgis_geometry_type_categorization(self):
        """Test PostGIS GEOMETRY type categorization."""
        column = MockPostgreSQLColumn('location', 'GEOMETRY')
        category = self.inspector._categorize_column(column, 'places')
        self.assertEqual(category, ColumnType.GEOMETRY)

    def test_postgis_geography_type_categorization(self):
        """Test PostGIS GEOGRAPHY type categorization."""
        column = MockPostgreSQLColumn('coordinates', 'GEOGRAPHY')
        category = self.inspector._categorize_column(column, 'locations')
        self.assertEqual(category, ColumnType.GEOGRAPHY)

    def test_postgis_raster_type_categorization(self):
        """Test PostGIS RASTER type categorization."""
        column = MockPostgreSQLColumn('satellite_image', 'RASTER')
        category = self.inspector._categorize_column(column, 'imagery')
        self.assertEqual(category, ColumnType.RASTER)

    def test_pgvector_vector_type_categorization(self):
        """Test pgVector VECTOR type categorization."""
        column = MockPostgreSQLColumn('embedding', 'VECTOR')
        category = self.inspector._categorize_column(column, 'documents')
        self.assertEqual(category, ColumnType.VECTOR)

    def test_postgresql_range_types_categorization(self):
        """Test PostgreSQL range types categorization."""
        # Integer ranges
        column = MockPostgreSQLColumn('age_range', 'INT4RANGE')
        category = self.inspector._categorize_column(column, 'demographics')
        self.assertEqual(category, ColumnType.INT4RANGE)

        column = MockPostgreSQLColumn('big_range', 'INT8RANGE')
        category = self.inspector._categorize_column(column, 'measurements')
        self.assertEqual(category, ColumnType.INT8RANGE)

        # Numeric range
        column = MockPostgreSQLColumn('price_range', 'NUMRANGE')
        category = self.inspector._categorize_column(column, 'products')
        self.assertEqual(category, ColumnType.NUMRANGE)

        # Timestamp ranges
        column = MockPostgreSQLColumn('active_period', 'TSRANGE')
        category = self.inspector._categorize_column(column, 'events')
        self.assertEqual(category, ColumnType.TSRANGE)

        column = MockPostgreSQLColumn('scheduled_time', 'TSTZRANGE')
        category = self.inspector._categorize_column(column, 'appointments')
        self.assertEqual(category, ColumnType.TSTZRANGE)

        # Date range
        column = MockPostgreSQLColumn('vacation_period', 'DATERANGE')
        category = self.inspector._categorize_column(column, 'bookings')
        self.assertEqual(category, ColumnType.DATERANGE)

    def test_widget_suggestions_for_postgresql_types(self):
        """Test widget suggestions for PostgreSQL advanced types."""
        # UUID
        column = MockPostgreSQLColumn('id', 'UUID')
        widget = self.inspector._suggest_widget_type(column, ColumnType.UUID)
        self.assertEqual(widget, 'UUIDFieldWidget')

        # JSONB
        column = MockPostgreSQLColumn('data', 'JSONB')
        widget = self.inspector._suggest_widget_type(column, ColumnType.JSONB)
        self.assertEqual(widget, 'JSONEditorWidget')

        # HSTORE
        column = MockPostgreSQLColumn('properties', 'HSTORE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.HSTORE)
        self.assertEqual(widget, 'HStoreEditorWidget')

        # LTREE
        column = MockPostgreSQLColumn('path', 'LTREE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.LTREE)
        self.assertEqual(widget, 'TreeHierarchyWidget')

        # Network types
        column = MockPostgreSQLColumn('ip', 'INET')
        widget = self.inspector._suggest_widget_type(column, ColumnType.INET)
        self.assertEqual(widget, 'NetworkAddressWidget')

        column = MockPostgreSQLColumn('network', 'CIDR')
        widget = self.inspector._suggest_widget_type(column, ColumnType.CIDR)
        self.assertEqual(widget, 'NetworkAddressWidget')

        column = MockPostgreSQLColumn('mac', 'MACADDR')
        widget = self.inspector._suggest_widget_type(column, ColumnType.MACADDR)
        self.assertEqual(widget, 'MACAddressWidget')

        # Full-text search
        column = MockPostgreSQLColumn('search_vector', 'TSVECTOR')
        widget = self.inspector._suggest_widget_type(column, ColumnType.TSVECTOR)
        self.assertEqual(widget, 'FullTextSearchWidget')

    def test_widget_suggestions_for_postgis_types(self):
        """Test widget suggestions for PostGIS spatial types."""
        # Geometry
        column = MockPostgreSQLColumn('location', 'GEOMETRY')
        widget = self.inspector._suggest_widget_type(column, ColumnType.GEOMETRY)
        self.assertEqual(widget, 'PostGISMapWidget')

        # Geography
        column = MockPostgreSQLColumn('coordinates', 'GEOGRAPHY')
        widget = self.inspector._suggest_widget_type(column, ColumnType.GEOGRAPHY)
        self.assertEqual(widget, 'PostGISMapWidget')

        # Raster
        column = MockPostgreSQLColumn('image', 'RASTER')
        widget = self.inspector._suggest_widget_type(column, ColumnType.RASTER)
        self.assertEqual(widget, 'RasterImageWidget')

    def test_widget_suggestions_for_pgvector_types(self):
        """Test widget suggestions for pgVector types."""
        column = MockPostgreSQLColumn('embedding', 'VECTOR')
        widget = self.inspector._suggest_widget_type(column, ColumnType.VECTOR)
        self.assertEqual(widget, 'VectorSimilarityWidget')

    def test_widget_suggestions_for_range_types(self):
        """Test widget suggestions for PostgreSQL range types."""
        # Numeric ranges
        column = MockPostgreSQLColumn('age_range', 'INT4RANGE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.INT4RANGE)
        self.assertEqual(widget, 'NumericRangeWidget')

        column = MockPostgreSQLColumn('price_range', 'NUMRANGE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.NUMRANGE)
        self.assertEqual(widget, 'NumericRangeWidget')

        # Timestamp ranges
        column = MockPostgreSQLColumn('period', 'TSRANGE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.TSRANGE)
        self.assertEqual(widget, 'TimestampRangeWidget')

        # Date ranges
        column = MockPostgreSQLColumn('vacation', 'DATERANGE')
        widget = self.inspector._suggest_widget_type(column, ColumnType.DATERANGE)
        self.assertEqual(widget, 'DateRangeWidget')

    def test_validation_rules_for_postgresql_types(self):
        """Test validation rule generation for PostgreSQL advanced types."""
        # UUID validation
        column = MockPostgreSQLColumn('id', 'UUID', nullable=False)
        rules = self.inspector._generate_validation_rules(column, ColumnType.UUID)
        self.assertIn('DataRequired()', rules)
        self.assertIn('UUIDValidator()', rules)

        # Network address validation
        column = MockPostgreSQLColumn('ip', 'INET', nullable=False)
        rules = self.inspector._generate_validation_rules(column, ColumnType.INET)
        self.assertIn('DataRequired()', rules)
        self.assertIn('IPAddressValidator()', rules)

        # CIDR validation
        column = MockPostgreSQLColumn('network', 'CIDR')
        rules = self.inspector._generate_validation_rules(column, ColumnType.CIDR)
        self.assertIn('CIDRValidator()', rules)

        # MAC address validation
        column = MockPostgreSQLColumn('mac', 'MACADDR')
        rules = self.inspector._generate_validation_rules(column, ColumnType.MACADDR)
        self.assertIn('MACAddressValidator()', rules)

        # JSON validation
        column = MockPostgreSQLColumn('data', 'JSONB')
        rules = self.inspector._generate_validation_rules(column, ColumnType.JSONB)
        self.assertIn('JSONValidator()', rules)

    def test_validation_rules_for_spatial_types(self):
        """Test validation rule generation for PostGIS spatial types."""
        column = MockPostgreSQLColumn('location', 'GEOMETRY', nullable=False)
        rules = self.inspector._generate_validation_rules(column, ColumnType.GEOMETRY)
        self.assertIn('DataRequired()', rules)
        self.assertIn('PostGISGeometryValidator()', rules)

        column = MockPostgreSQLColumn('coordinates', 'GEOGRAPHY')
        rules = self.inspector._generate_validation_rules(column, ColumnType.GEOGRAPHY)
        self.assertIn('PostGISGeometryValidator()', rules)

    def test_validation_rules_for_vector_types(self):
        """Test validation rule generation for pgVector types."""
        column = MockPostgreSQLColumn('embedding', 'VECTOR', nullable=False)
        rules = self.inspector._generate_validation_rules(column, ColumnType.VECTOR)
        self.assertIn('DataRequired()', rules)
        self.assertIn('VectorDimensionValidator()', rules)

    def test_validation_rules_for_range_types(self):
        """Test validation rule generation for PostgreSQL range types."""
        # Numeric range
        column = MockPostgreSQLColumn('price_range', 'NUMRANGE')
        rules = self.inspector._generate_validation_rules(column, ColumnType.NUMRANGE)
        self.assertIn('NumericRangeValidator()', rules)

        # Timestamp range
        column = MockPostgreSQLColumn('period', 'TSRANGE')
        rules = self.inspector._generate_validation_rules(column, ColumnType.TSRANGE)
        self.assertIn('TimestampRangeValidator()', rules)

        # Date range
        column = MockPostgreSQLColumn('vacation', 'DATERANGE')
        rules = self.inspector._generate_validation_rules(column, ColumnType.DATERANGE)
        self.assertIn('DateRangeValidator()', rules)

    def test_case_insensitive_type_detection(self):
        """Test that type detection is case-insensitive."""
        # Test various case combinations
        test_cases = [
            ('uuid', ColumnType.UUID),
            ('UUID', ColumnType.UUID),
            ('Uuid', ColumnType.UUID),
            ('geometry', ColumnType.GEOMETRY),
            ('GEOMETRY', ColumnType.GEOMETRY),
            ('Geometry', ColumnType.GEOMETRY),
            ('vector', ColumnType.VECTOR),
            ('VECTOR', ColumnType.VECTOR),
            ('Vector', ColumnType.VECTOR),
        ]

        for type_str, expected_category in test_cases:
            column = MockPostgreSQLColumn('test_col', type_str)
            category = self.inspector._categorize_column(column, 'test_table')
            self.assertEqual(
                category, 
                expected_category,
                f"Failed for type string: {type_str}"
            )

    def test_complex_type_names(self):
        """Test detection of complex PostgreSQL type names."""
        # Test types with parameters
        column = MockPostgreSQLColumn('location', 'GEOMETRY(POINT,4326)')
        category = self.inspector._categorize_column(column, 'places')
        self.assertEqual(category, ColumnType.GEOMETRY)

        column = MockPostgreSQLColumn('embedding', 'VECTOR(768)')
        category = self.inspector._categorize_column(column, 'documents')
        self.assertEqual(category, ColumnType.VECTOR)

    def test_array_type_detection(self):
        """Test correct detection of PostgreSQL array types."""
        # Test that array types are detected as ARRAY, not the base type
        test_cases = [
            ('INET[]', ColumnType.ARRAY),
            ('TEXT[]', ColumnType.ARRAY),
            ('INTEGER[]', ColumnType.ARRAY),
            ('UUID[]', ColumnType.ARRAY),
            ('JSONB[]', ColumnType.ARRAY),
            ('GEOMETRY[]', ColumnType.ARRAY),
            ('VECTOR[]', ColumnType.ARRAY),
            # Mixed case
            ('inet[]', ColumnType.ARRAY),
            ('text[]', ColumnType.ARRAY),
            # Multi-dimensional arrays
            ('INTEGER[][]', ColumnType.ARRAY),
            ('TEXT[][][]', ColumnType.ARRAY),
        ]

        for type_str, expected_category in test_cases:
            column = MockPostgreSQLColumn('test_array', type_str)
            category = self.inspector._categorize_column(column, 'test_table')
            self.assertEqual(
                category,
                expected_category,
                f"Failed for array type: {type_str}, expected {expected_category}, got {category}"
            )

    def test_non_array_types_still_detected(self):
        """Test that non-array types are still detected correctly after array fix."""
        # Test that base types without [] are still detected as their specific types
        test_cases = [
            ('INET', ColumnType.INET),
            ('TEXT', ColumnType.TEXT),
            ('UUID', ColumnType.UUID),
            ('JSONB', ColumnType.JSONB),
            ('GEOMETRY', ColumnType.GEOMETRY),
            ('VECTOR', ColumnType.VECTOR),
        ]

        for type_str, expected_category in test_cases:
            column = MockPostgreSQLColumn('test_col', type_str)
            category = self.inspector._categorize_column(column, 'test_table')
            self.assertEqual(
                category,
                expected_category,
                f"Failed for base type: {type_str}, expected {expected_category}, got {category}"
            )


if __name__ == '__main__':
    unittest.main()