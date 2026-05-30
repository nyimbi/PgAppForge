"""
Test suite for PostgreSQL-specific types and widgets

Tests cover JSONB, PostGIS, pgvector, arrays, and other PostgreSQL types
with their corresponding widgets and form fields.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from flask import Flask
from pgappforge import AppBuilder, SQLA
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, INET, BIT
from wtforms import Form

from pgappforge.models.postgresql import (
    JSONBField, PostgreSQLArrayField, PostGISGeometryField, PgVectorField,
    PostgreSQLUUIDField, PostgreSQLBitStringField, PostgreSQLTreeField,
    Vector, Geometry, LTREE, HSTORE,
    PostgreSQLProfileMixin, PostGISProfileMixin, PgVectorProfileMixin
)
from pgappforge.widgets_postgresql.postgresql import (
    JSONBWidget, PostgreSQLArrayWidget, PostGISGeometryWidget,
    PgVectorWidget, PostgreSQLUUIDWidget, PostgreSQLBitStringWidget
)
from pgappforge.widgets_postgresql.tree_widget import (
    PostgreSQLTreeWidget
)


class TestJSONBField:
    """Test JSONB field and widget functionality"""
    
    def test_jsonb_field_valid_json(self):
        """Test JSONB field with valid JSON data"""
        field = JSONBField()
        
        # Test with dictionary
        field.process_formdata(['{"key": "value", "number": 42}'])
        assert field.data == {"key": "value", "number": 42}
        
        # Test with array
        field.process_formdata(['[1, 2, 3, "test"]'])
        assert field.data == [1, 2, 3, "test"]
        
        # Test with null/empty
        field.process_formdata([''])
        assert field.data is None
        
        field.process_formdata([])
        assert field.data is None
    
    def test_jsonb_field_invalid_json(self):
        """Test JSONB field with invalid JSON"""
        field = JSONBField()
        
        with pytest.raises(ValueError, match="Invalid JSON format"):
            field.process_formdata(['{invalid json'])
    
    def test_jsonb_field_value_display(self):
        """Test JSONB field value formatting for display"""
        field = JSONBField()
        
        # Test dict formatting
        field.data = {"name": "test", "count": 5}
        formatted = field._value()
        assert '"name": "test"' in formatted
        assert '"count": 5' in formatted
        
        # Test list formatting
        field.data = [1, 2, 3]
        formatted = field._value()
        assert formatted == '[\n  1,\n  2,\n  3\n]'
        
        # Test empty data
        field.data = None
        assert field._value() == ''


class TestPostgreSQLArrayField:
    """Test PostgreSQL array field functionality"""
    
    def test_array_field_processing(self):
        """Test array field data processing"""
        field = PostgreSQLArrayField(array_type='text')
        
        # Test PostgreSQL array format
        field.process_formdata(['{item1,item2,item3}'])
        assert field.data == ['item1', 'item2', 'item3']
        
        # Test comma-separated format
        field.process_formdata(['item1,item2,item3'])
        assert field.data == ['item1', 'item2', 'item3']
        
        # Test empty array
        field.process_formdata(['{}'])
        assert field.data == []
        
        field.process_formdata([''])
        assert field.data == []
    
    def test_array_field_value_display(self):
        """Test array field value formatting"""
        field = PostgreSQLArrayField()
        
        field.data = ['item1', 'item2', 'item3']
        assert field._value() == '{"item1","item2","item3"}'
        
        field.data = []
        assert field._value() == '{}'
        
        field.data = None
        assert field._value() == '{}'


class TestPostGISGeometryField:
    """Test PostGIS geometry field functionality"""
    
    def test_geometry_field_processing(self):
        """Test geometry field data processing"""
        field = PostGISGeometryField(geometry_type='POINT')
        
        # Test WKT point
        field.process_formdata(['POINT(-74.0060 40.7128)'])
        assert field.data == 'POINT(-74.0060 40.7128)'
        
        # Test empty data
        field.process_formdata([''])
        assert field.data is None
        
        field.process_formdata([])
        assert field.data is None
    
    def test_geometry_field_types(self):
        """Test different geometry types"""
        # Point field
        point_field = PostGISGeometryField(geometry_type='POINT', srid=4326)
        assert point_field.geometry_type == 'POINT'
        assert point_field.srid == 4326
        
        # Polygon field
        polygon_field = PostGISGeometryField(geometry_type='POLYGON', srid=3857)
        assert polygon_field.geometry_type == 'POLYGON'
        assert polygon_field.srid == 3857


class TestPgVectorField:
    """Test pgvector field functionality"""
    
    def test_vector_field_json_format(self):
        """Test vector field with JSON array format"""
        field = PgVectorField(dimension=3)
        
        field.process_formdata(['[1.0, 2.0, 3.0]'])
        assert field.data == [1.0, 2.0, 3.0]
    
    def test_vector_field_csv_format(self):
        """Test vector field with comma-separated format"""
        field = PgVectorField(dimension=4)
        
        field.process_formdata(['0.1, 0.2, 0.3, 0.4'])
        assert field.data == [0.1, 0.2, 0.3, 0.4]
    
    def test_vector_field_dimension_validation(self):
        """Test vector field dimension validation"""
        field = PgVectorField(dimension=3)
        
        with pytest.raises(ValueError, match="Vector dimension mismatch"):
            field.process_formdata(['[1.0, 2.0]'])  # Only 2 dimensions, expected 3
    
    def test_vector_field_invalid_format(self):
        """Test vector field with invalid format"""
        field = PgVectorField(dimension=2)
        
        with pytest.raises(ValueError, match="Invalid vector format"):
            field.process_formdata(['not a vector'])
    
    def test_vector_field_value_display(self):
        """Test vector field value formatting"""
        field = PgVectorField(dimension=3)
        
        field.data = [1.5, 2.5, 3.5]
        assert field._value() == '[1.5, 2.5, 3.5]'
        
        field.data = None
        assert field._value() == ''


class TestPostgreSQLUUIDField:
    """Test PostgreSQL UUID field"""
    
    def test_uuid_field_processing(self):
        """Test UUID field data processing"""
        field = PostgreSQLUUIDField()
        
        valid_uuid = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
        field.process_formdata([valid_uuid])
        assert field.data == valid_uuid
        
        field.process_formdata([''])
        assert field.data is None


class TestPostgreSQLBitStringField:
    """Test PostgreSQL bit string field"""
    
    def test_bit_string_field_valid(self):
        """Test bit string field with valid data"""
        field = PostgreSQLBitStringField(length=8)
        
        field.process_formdata(['10110101'])
        assert field.data == '10110101'
    
    def test_bit_string_field_invalid_chars(self):
        """Test bit string field with invalid characters"""
        field = PostgreSQLBitStringField(length=4)
        
        with pytest.raises(ValueError, match="only 0s and 1s"):
            field.process_formdata(['102a'])
    
    def test_bit_string_field_length_validation(self):
        """Test bit string field length validation"""
        field = PostgreSQLBitStringField(length=4)
        
        with pytest.raises(ValueError, match="length must be 4"):
            field.process_formdata(['101101'])  # 6 chars, expected 4


class TestPostgreSQLWidgets:
    """Test PostgreSQL widget HTML generation"""
    
    def test_jsonb_widget_render(self):
        """Test JSONB widget HTML rendering"""
        widget = JSONBWidget()
        field = MagicMock()
        field.name = 'test_field'
        field.id = 'test_field_id'
        field.data = {'key': 'value'}
        
        html = widget(field)
        
        assert 'jsonb-widget-container' in str(html)
        assert 'textarea' in str(html)
        assert 'jsonb-format' in str(html)
        assert 'jsonb-validate' in str(html)
    
    def test_array_widget_render(self):
        """Test PostgreSQL array widget rendering"""
        widget = PostgreSQLArrayWidget(array_type='text')
        field = MagicMock()
        field.name = 'test_array'
        field.id = 'test_array_id'
        field.data = ['item1', 'item2']
        
        html = widget(field)
        
        assert 'postgresql-array-widget' in str(html)
        assert 'array-add' in str(html)
        assert 'array-remove' in str(html)
        assert 'item1' in str(html)
        assert 'item2' in str(html)
    
    def test_postgis_widget_render(self):
        """Test PostGIS geometry widget rendering"""
        widget = PostGISGeometryWidget(geometry_type='POINT', srid=4326)
        field = MagicMock()
        field.name = 'location'
        field.id = 'location_id'
        field.data = 'POINT(-74 40.7)'
        
        html = widget(field)
        
        assert 'postgis-geometry-widget' in str(html)
        assert 'geometry-map' in str(html)
        assert 'leaflet' in str(html).lower()
        assert 'data-geometry-type="POINT"' in str(html)
        assert 'data-srid="4326"' in str(html)
    
    def test_pgvector_widget_render(self):
        """Test pgvector widget rendering"""
        widget = PgVectorWidget(dimension=768)
        field = MagicMock()
        field.name = 'embedding'
        field.id = 'embedding_id'
        field.data = [0.1, 0.2, 0.3]
        
        html = widget(field)
        
        assert 'pgvector-widget' in str(html)
        assert 'vector-visualization' in str(html)
        assert 'data-dimension="768"' in str(html)
        assert 'vector-normalize' in str(html)


class TestPostgreSQLTypes:
    """Test custom SQLAlchemy PostgreSQL types"""
    
    def test_vector_type(self):
        """Test Vector SQLAlchemy type"""
        vector_type = Vector(768)
        
        assert vector_type.get_col_spec() == "VECTOR(768)"
        assert vector_type.dim == 768
    
    def test_geometry_type(self):
        """Test Geometry SQLAlchemy type"""
        geom_type = Geometry('POINT', 4326)
        
        assert geom_type.get_col_spec() == "GEOMETRY(POINT, 4326)"
        assert geom_type.geometry_type == 'POINT'
        assert geom_type.srid == 4326
    
    def test_ltree_type(self):
        """Test LTREE type"""
        ltree_type = LTREE()
        assert ltree_type.get_col_spec() == "LTREE"
    
    def test_hstore_type(self):
        """Test HSTORE type"""
        hstore_type = HSTORE()
        assert hstore_type.get_col_spec() == "HSTORE"


class TestPostgreSQLProfileMixins:
    """Test PostgreSQL profile mixin functionality"""
    
    def test_postgresql_profile_mixin_methods(self):
        """Test PostgreSQL profile mixin helper methods"""
        
        class TestProfile(PostgreSQLProfileMixin):
            def __init__(self):
                self.preferences_jsonb = {}
                self.skills_array = []
        
        profile = TestProfile()
        
        # Test JSONB methods
        profile.set_jsonb_field('preferences_jsonb', 'theme', 'dark')
        assert profile.get_jsonb_field('preferences_jsonb', 'theme') == 'dark'
        assert profile.get_jsonb_field('preferences_jsonb', 'nonexistent', 'default') == 'default'
        
        # Test array methods
        profile.add_to_array('skills_array', 'Python')
        profile.add_to_array('skills_array', 'PostgreSQL')
        profile.add_to_array('skills_array', 'Python')  # Duplicate should not be added
        
        assert profile.skills_array == ['Python', 'PostgreSQL']
        
        profile.remove_from_array('skills_array', 'Python')
        assert profile.skills_array == ['PostgreSQL']
    
    def test_postgis_profile_mixin_methods(self):
        """Test PostGIS profile mixin methods"""
        
        class TestProfile(PostGISProfileMixin):
            def __init__(self):
                self.location = None
        
        profile = TestProfile()
        
        # Test geometry methods (would require actual PostGIS in production)
        distance = profile.calculate_distance_to('POINT(-74 40.7)')
        assert distance is None  # Expected in test environment
        
        nearby = profile.find_nearby_profiles(1000)
        assert nearby == []  # Expected in test environment
    
    def test_pgvector_profile_mixin_methods(self):
        """Test pgvector profile mixin methods"""
        
        class TestProfile(PgVectorProfileMixin):
            def __init__(self):
                self.profile_embedding = None
        
        profile = TestProfile()
        
        # Test vector methods (would require actual pgvector in production)
        similarity = profile.calculate_profile_similarity(profile)
        assert similarity is None  # Expected in test environment
        
        similar = profile.find_similar_profiles()
        assert similar == []  # Expected in test environment


class TestFormIntegration:
    """Test PostgreSQL fields in WTForms"""
    
    def test_create_form_with_postgresql_fields(self):
        """Test creating a form with PostgreSQL fields"""
        
        class PostgreSQLTestForm(Form):
            settings = JSONBField(label='Settings')
            skills = PostgreSQLArrayField(array_type='text', label='Skills')
            location = PostGISGeometryField(geometry_type='POINT', label='Location')
            embedding = PgVectorField(dimension=3, label='Embedding')
            user_id = PostgreSQLUUIDField(label='User ID')
            features = PostgreSQLBitStringField(length=8, label='Features')
        
        form = PostgreSQLTestForm()
        
        # Verify fields are created correctly
        assert isinstance(form.settings, JSONBField)
        assert isinstance(form.skills, PostgreSQLArrayField)
        assert isinstance(form.location, PostGISGeometryField)
        assert isinstance(form.embedding, PgVectorField)
        assert isinstance(form.user_id, PostgreSQLUUIDField)
        assert isinstance(form.features, PostgreSQLBitStringField)
        
        # Test field properties
        assert form.skills.array_type == 'text'
        assert form.location.geometry_type == 'POINT'
        assert form.embedding.dimension == 3
        assert form.features.length == 8


class TestPostgreSQLIntegration:
    """Test integration with actual PostgreSQL database"""
    
    @pytest.mark.skipif(True, reason="Requires PostgreSQL database with extensions")
    def test_database_integration(self):
        """Test with actual PostgreSQL database (skipped by default)"""
        
        # This test would require a real PostgreSQL database with extensions
        engine = create_engine('postgresql://test:test@localhost/test_db')
        
        # Would test actual database operations here
        pass


@pytest.fixture
def mock_field():
    """Create a mock form field for testing"""
    field = MagicMock()
    field.name = 'test_field'
    field.id = 'test_field_id'
    field.data = None
    return field


class TestWidgetJavaScript:
    """Test widget JavaScript functionality"""
    
    def test_jsonb_widget_javascript_functions(self):
        """Test JSONB widget includes necessary JavaScript"""
        widget = JSONBWidget()
        field = MagicMock()
        field.name = 'test'
        field.id = 'test_id'
        field.data = {}
        
        html = str(widget(field))
        
        # Check for JavaScript functionality
        assert 'jsonb-format' in html
        assert 'jsonb-minify' in html
        assert 'jsonb-validate' in html
        assert 'JSON.parse' in html
        assert 'JSON.stringify' in html
    
    def test_array_widget_javascript_functions(self):
        """Test array widget JavaScript functionality"""
        widget = PostgreSQLArrayWidget(array_type='text')
        field = MagicMock()
        field.name = 'test'
        field.id = 'test_id'
        field.data = []
        
        html = str(widget(field))
        
        # Check for JavaScript functionality
        assert 'array-add' in html
        assert 'array-remove' in html
        assert 'updateArrayValue' in html
    
    def test_postgis_widget_includes_leaflet(self):
        """Test PostGIS widget includes Leaflet dependencies"""
        widget = PostGISGeometryWidget()
        field = MagicMock()
        field.name = 'location'
        field.id = 'location_id'
        field.data = None
        
        html = str(widget(field))
        
        # Check for Leaflet includes
        assert 'leaflet' in html.lower()
        assert 'openstreetmap' in html.lower()
        assert 'L.map' in html
    
    def test_pgvector_widget_visualization(self):
        """Test pgvector widget includes visualization"""
        widget = PgVectorWidget(dimension=5)
        field = MagicMock()
        field.name = 'vector'
        field.id = 'vector_id'
        field.data = None
        
        html = str(widget(field))
        
        # Check for visualization elements
        assert 'vector-canvas' in html
        assert 'vector-normalize' in html
        assert 'updateVisualization' in html


class TestPostgreSQLTreeField:
    """Test PostgreSQL tree field functionality"""
    
    def test_tree_field_ltree_mode(self):
        """Test tree field with LTREE mode"""
        field = PostgreSQLTreeField(
            mode='ltree',
            max_depth=5,
            path_separator='.'
        )
        
        # Test LTREE path processing
        ltree_paths = "company.engineering.database\ncompany.marketing.content"
        field.process_formdata([ltree_paths])
        
        assert isinstance(field.data, dict)
        assert 'company' in field.data
        assert 'engineering' in field.data['company']['children']
        assert 'marketing' in field.data['company']['children']
    
    def test_tree_field_parent_id_mode(self):
        """Test tree field with parent-child relationships"""
        field = PostgreSQLTreeField(
            mode='parent_id',
            id_field='id',
            parent_id_field='parent_id',
            label_field='name'
        )
        
        # Test parent-child JSON data
        parent_child_data = json.dumps([
            {'id': 1, 'name': 'Root', 'parent_id': None},
            {'id': 2, 'name': 'Child1', 'parent_id': 1},
            {'id': 3, 'name': 'Child2', 'parent_id': 1},
            {'id': 4, 'name': 'Grandchild', 'parent_id': 2}
        ])
        
        field.process_formdata([parent_child_data])
        
        assert isinstance(field.data, list)
        assert len(field.data) == 4
        
        # Verify structure
        ids = [item['id'] for item in field.data]
        assert set(ids) == {1, 2, 3, 4}
    
    def test_tree_field_csv_parsing(self):
        """Test tree field CSV parsing"""
        field = PostgreSQLTreeField(
            mode='parent_id',
            id_field='id',
            parent_id_field='parent_id',
            label_field='name'
        )
        
        csv_data = '''id,name,parent_id
1,"Root",
2,"Child1",1
3,"Child2",1'''
        
        field.process_formdata([csv_data])
        
        assert isinstance(field.data, list)
        assert len(field.data) == 3
        
        root = next(item for item in field.data if item['id'] == 1)
        assert root['name'] == 'Root'
        assert root['parent_id'] is None
    
    def test_tree_field_validation_max_depth(self):
        """Test tree field depth validation"""
        field = PostgreSQLTreeField(
            mode='ltree',
            max_depth=2,
            path_separator='.'
        )
        
        # This should exceed max depth
        deep_paths = "a.b.c.d"
        
        with pytest.raises(ValueError, match="Tree depth exceeds maximum"):
            field.process_formdata([deep_paths])
    
    def test_tree_field_validation_orphans(self):
        """Test tree field orphan validation"""
        field = PostgreSQLTreeField(
            mode='parent_id',
            id_field='id',
            parent_id_field='parent_id',
            label_field='name'
        )
        
        # Create data with orphaned reference
        orphaned_data = json.dumps([
            {'id': 1, 'name': 'Root', 'parent_id': None},
            {'id': 2, 'name': 'Child', 'parent_id': 999}  # 999 doesn't exist
        ])
        
        with pytest.raises(ValueError, match="Orphaned parent references"):
            field.process_formdata([orphaned_data])
    
    def test_tree_field_validation_duplicates(self):
        """Test tree field duplicate ID validation"""
        field = PostgreSQLTreeField(
            mode='parent_id',
            id_field='id',
            parent_id_field='parent_id',
            label_field='name'
        )
        
        # Create data with duplicate IDs
        duplicate_data = json.dumps([
            {'id': 1, 'name': 'Root1', 'parent_id': None},
            {'id': 1, 'name': 'Root2', 'parent_id': None}  # Duplicate ID
        ])
        
        with pytest.raises(ValueError, match="Duplicate ID found"):
            field.process_formdata([duplicate_data])
    
    def test_tree_field_value_display(self):
        """Test tree field value formatting for display"""
        field = PostgreSQLTreeField(mode='ltree')
        
        # Test with hierarchical data
        field.data = {
            'root': {
                'label': 'root',
                'path': 'root',
                'children': {
                    'child': {
                        'label': 'child',
                        'path': 'root.child',
                        'children': {}
                    }
                }
            }
        }
        
        value = field._value()
        assert 'root' in value
        assert 'child' in value
        assert 'children' in value
    
    def test_tree_field_helpers(self):
        """Test tree field helper methods"""
        field = PostgreSQLTreeField(mode='ltree')
        
        # Set up test data
        field.data = {
            'company': {
                'label': 'company',
                'path': 'company',
                'children': {
                    'dept': {
                        'label': 'dept',
                        'path': 'company.dept',
                        'children': {}
                    }
                }
            }
        }
        
        # Test get_tree_paths method
        paths = field.get_tree_paths()
        assert 'company' in paths
        assert 'company.dept' in paths
        assert len(paths) == 2


class TestPostgreSQLTreeWidget:
    """Test PostgreSQL tree widget functionality"""
    
    def test_tree_widget_ltree_mode(self):
        """Test tree widget in LTREE mode"""
        widget = PostgreSQLTreeWidget(
            mode='ltree',
            max_depth=5,
            path_separator='.'
        )
        
        field = MagicMock()
        field.id = 'test_tree'
        field.name = 'tree_field'
        field.data = ''
        
        html = widget(field)
        
        assert 'postgresql-tree-widget' in str(html)
        assert 'data-mode="ltree"' in str(html)
        assert 'data-max-depth="5"' in str(html)
        assert 'data-path-separator="."' in str(html)
    
    def test_tree_widget_parent_id_mode(self):
        """Test tree widget in parent-ID mode"""
        widget = PostgreSQLTreeWidget(
            mode='parent_id',
            id_field='category_id',
            parent_id_field='parent_category_id',
            label_field='category_name'
        )
        
        field = MagicMock()
        field.id = 'category_tree'
        field.name = 'categories'
        field.data = ''
        
        html = widget(field)
        
        assert 'postgresql-tree-widget' in str(html)
        assert 'data-mode="parent_id"' in str(html)
        assert 'data-id-field="category_id"' in str(html)
        assert 'data-parent-id-field="parent_category_id"' in str(html)
        assert 'data-label-field="category_name"' in str(html)
    
    def test_tree_widget_controls(self):
        """Test tree widget control elements"""
        widget = PostgreSQLTreeWidget()
        field = MagicMock()
        field.id = 'test_tree'
        field.name = 'tree'
        field.data = ''
        
        html = str(widget(field))
        
        # Check for control buttons
        assert 'tree-add-root' in html
        assert 'tree-expand-all' in html
        assert 'tree-collapse-all' in html
        assert 'tree-refresh' in html
        assert 'tree-export' in html
        assert 'tree-import' in html
        assert 'tree-validate' in html
        assert 'tree-repair' in html
    
    def test_tree_widget_drag_drop_config(self):
        """Test tree widget drag-and-drop configuration"""
        widget_enabled = PostgreSQLTreeWidget(allow_drag_drop=True)
        widget_disabled = PostgreSQLTreeWidget(allow_drag_drop=False)
        
        field = MagicMock()
        field.id = 'test_tree'
        field.name = 'tree'
        field.data = ''
        
        html_enabled = str(widget_enabled(field))
        html_disabled = str(widget_disabled(field))
        
        assert 'data-allow-drag-drop="true"' in html_enabled
        assert 'data-allow-drag-drop="false"' in html_disabled
    
    def test_tree_widget_import_export_modal(self):
        """Test tree widget import/export modal"""
        widget = PostgreSQLTreeWidget(mode='parent_id')
        field = MagicMock()
        field.id = 'test_tree'
        field.name = 'tree'
        field.data = ''
        
        html = str(widget(field))
        
        # Check for modal elements
        assert 'tree-import-export-modal' in html
        assert 'export-format' in html
        assert 'import-format' in html
        assert 'export-data' in html
        assert 'import-data' in html
        
        # Check for parent_id specific options
        assert 'Parent-ID Table' in html
    
    def test_tree_widget_javascript_initialization(self):
        """Test tree widget JavaScript initialization"""
        widget = PostgreSQLTreeWidget(
            mode='ltree',
            max_depth=8,
            path_separator='/'
        )
        
        field = MagicMock()
        field.id = 'my_tree_field'
        field.name = 'tree'
        field.data = ''
        
        html = str(widget(field))
        
        # Check JavaScript initialization
        assert 'window.treeWidget_my_tree_field' in html
        assert 'mode: \'ltree\'' in html
        assert 'maxDepth: 8' in html
        assert 'pathSeparator: \'/\'' in html
        assert 'PostgreSQL Tree Widget loaded' in html
    
    def test_tree_widget_styling(self):
        """Test tree widget CSS styling"""
        widget = PostgreSQLTreeWidget()
        field = MagicMock()
        field.id = 'test_tree'
        field.name = 'tree'
        field.data = ''
        
        html = str(widget(field))
        
        # Check for key CSS classes
        assert 'tree-container' in html
        assert 'tree-root' in html
        assert 'tree-controls' in html
        assert 'tree-info' in html
        assert 'tree-stats' in html
        assert 'node-content' in html
        assert 'node-children' in html
        
        # Check for responsive design elements
        assert '@media (max-width: 768px)' in html
        assert '@media print' in html


class TestTreeWidgetIntegration:
    """Test tree widget integration scenarios"""
    
    def test_ltree_to_parent_child_conversion(self):
        """Test conversion between LTREE and parent-child formats"""
        # Create LTREE field
        ltree_field = PostgreSQLTreeField(mode='ltree')
        
        # Process LTREE paths
        paths = "company.engineering.database\ncompany.engineering.frontend\ncompany.marketing"
        ltree_field.process_formdata([paths])
        
        # Verify hierarchical structure
        assert 'company' in ltree_field.data
        assert 'engineering' in ltree_field.data['company']['children']
        assert 'marketing' in ltree_field.data['company']['children']
    
    def test_parent_child_validation_workflow(self):
        """Test complete parent-child validation workflow"""
        field = PostgreSQLTreeField(
            mode='parent_id',
            id_field='id',
            parent_id_field='parent_id',
            label_field='name',
            max_depth=3
        )
        
        # Valid hierarchical data
        valid_data = json.dumps([
            {'id': 1, 'name': 'Root', 'parent_id': None},
            {'id': 2, 'name': 'Level1', 'parent_id': 1},
            {'id': 3, 'name': 'Level2', 'parent_id': 2}
        ])
        
        # Should not raise any errors
        field.process_formdata([valid_data])
        assert len(field.data) == 3
        
        # Invalid data - exceeds depth
        deep_data = json.dumps([
            {'id': 1, 'name': 'Root', 'parent_id': None},
            {'id': 2, 'name': 'L1', 'parent_id': 1},
            {'id': 3, 'name': 'L2', 'parent_id': 2},
            {'id': 4, 'name': 'L3', 'parent_id': 3},
            {'id': 5, 'name': 'L4', 'parent_id': 4}  # Exceeds max_depth=3
        ])
        
        with pytest.raises(ValueError):
            field.process_formdata([deep_data])
    
    def test_form_integration(self):
        """Test tree field integration with WTForms"""
        class TreeTestForm(Form):
            org_hierarchy = PostgreSQLTreeField(
                'Organization',
                mode='ltree',
                max_depth=4
            )
            categories = PostgreSQLTreeField(
                'Categories',
                mode='parent_id',
                id_field='cat_id',
                parent_id_field='parent_cat_id',
                label_field='cat_name'
            )
        
        form = TreeTestForm()
        
        # Verify fields are created correctly
        assert isinstance(form.org_hierarchy, PostgreSQLTreeField)
        assert isinstance(form.categories, PostgreSQLTreeField)
        
        # Verify field configuration
        assert form.org_hierarchy.mode == 'ltree'
        assert form.org_hierarchy.max_depth == 4
        assert form.categories.mode == 'parent_id'
        assert form.categories.id_field == 'cat_id'
        assert form.categories.parent_id_field == 'parent_cat_id'
        assert form.categories.label_field == 'cat_name'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])