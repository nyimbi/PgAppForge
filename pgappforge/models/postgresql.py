"""
PostgreSQL-specific model fields and types for PgAppForge

This module provides SQLAlchemy field definitions and form fields for 
PostgreSQL-specific data types including JSONB, arrays, PostGIS, and pgvector.
"""
import json
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import (
    ARRAY, BIGINT, BIT, BOOLEAN, BYTEA, CHAR, DATE, DOUBLE_PRECISION,
    ENUM, FLOAT, INET, INTEGER, INTERVAL, JSON, JSONB, MACADDR, MACADDR8,
    MONEY, NUMERIC, OID, REAL, SMALLINT, TEXT, TIME, TIMESTAMP, TSVECTOR,
    UUID, VARCHAR, HSTORE
)
from sqlalchemy import DECIMAL
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.types import TypeDecorator, UserDefinedType
from wtforms import Field
from wtforms.widgets import TextArea

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets_postgresql.postgresql import (
    JSONBWidget, PostgreSQLArrayWidget, PostGISGeometryWidget, 
    PgVectorWidget, PostgreSQLIntervalWidget, PostgreSQLUUIDWidget,
    PostgreSQLBitStringWidget
)


# Custom SQLAlchemy types for advanced PostgreSQL features

class Vector(UserDefinedType):
    """
    SQLAlchemy type for pgvector extension supporting high-dimensional embeddings
    
    This type handles storage and retrieval of vector embeddings for similarity search
    and machine learning applications. Supports dimensions up to 16,000.
    
    Args:
        dim (int): The dimension of the vector (e.g., 768 for OpenAI embeddings)
    
    Examples:
        >>> # Define a model with vector embeddings
        >>> class Document(db.Model):
        ...     embedding = Column(Vector(768))  # OpenAI embedding size
        ...
        >>> # Query for similar vectors
        >>> similar = db.session.query(Document).order_by(
        ...     Document.embedding.cosine_distance('[0.1, 0.2, ...]')
        ... ).limit(10)
    """
    def __init__(self, dim):
        self.dim = dim

    def get_col_spec(self):
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                return '[' + ','.join(str(x) for x in value) + ']'
            return str(value)
        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                # Parse vector string format [1,2,3] or (1,2,3)
                value = value.strip('()[]')
                return [float(x.strip()) for x in value.split(',') if x.strip()]
            return value
        return process


class Geometry(UserDefinedType):
    """
    SQLAlchemy type for PostGIS geometry data with spatial indexing support
    
    Handles 2D/3D spatial data including points, lines, polygons, and complex geometries.
    Supports spatial relationships, distance calculations, and geographic projections.
    
    Args:
        geometry_type (str): Type of geometry ('POINT', 'LINESTRING', 'POLYGON', etc.)
        srid (int): Spatial Reference System Identifier (default: 4326 for WGS84)
    
    Examples:
        >>> # Define location fields
        >>> class Store(db.Model):
        ...     location = Column(Geometry('POINT', 4326))
        ...     delivery_area = Column(Geometry('POLYGON', 4326))
        ...
        >>> # Find stores within 1000 meters
        >>> nearby = db.session.query(Store).filter(
        ...     func.ST_DWithin(Store.location, 'POINT(-74.006 40.7128)', 1000)
        ... )
    """
    def __init__(self, geometry_type='GEOMETRY', srid=4326):
        self.geometry_type = geometry_type.upper()
        self.srid = srid

    def get_col_spec(self):
        return f"GEOMETRY({self.geometry_type}, {self.srid})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            # Convert WKT to PostGIS format
            return f"ST_GeomFromText('{value}', {self.srid})"
        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            # This would typically return WKT format
            return value
        return process


class Geography(UserDefinedType):
    """
    SQLAlchemy type for PostGIS geography data optimized for Earth calculations
    
    Unlike geometry, geography calculations are performed on the curved surface
    of the Earth, providing more accurate distance and area calculations for
    global applications.
    
    Args:
        geography_type (str): Type of geography ('POINT', 'LINESTRING', 'POLYGON', etc.)
        srid (int): Spatial Reference System Identifier (default: 4326 for WGS84)
    
    Examples:
        >>> # Global location tracking
        >>> class User(db.Model):
        ...     global_location = Column(Geography('POINT', 4326))
        ...
        >>> # Calculate great circle distances
        >>> distance = func.ST_Distance(user1.global_location, user2.global_location)
    """
    def __init__(self, geography_type='GEOGRAPHY', srid=4326):
        self.geography_type = geography_type.upper()
        self.srid = srid

    def get_col_spec(self):
        return f"GEOGRAPHY({self.geography_type}, {self.srid})"


class LTREE(UserDefinedType):
    """
    SQLAlchemy type for PostgreSQL ltree extension supporting hierarchical data
    
    LTREE provides efficient storage and querying of tree-like data structures
    such as organizational charts, category hierarchies, and taxonomies.
    
    The path format uses dots to separate labels: 'root.branch.leaf'
    Labels can contain letters, digits, and underscores.
    
    Examples:
        >>> # Organizational hierarchy
        >>> class Employee(db.Model):
        ...     org_path = Column(LTREE)
        ...
        >>> # Find all employees under 'engineering.backend'
        >>> engineers = db.session.query(Employee).filter(
        ...     Employee.org_path.op('<@')('engineering.backend')
        ... )
    """
    def get_col_spec(self):
        return "LTREE"


class HSTORE(UserDefinedType):
    """
    SQLAlchemy type for PostgreSQL hstore extension for key-value storage
    
    HSTORE provides efficient storage of key-value pairs within a single column,
    with support for indexing and querying individual keys. Useful for storing
    dynamic attributes, configuration settings, or flexible metadata.
    
    Keys and values must be text strings. For complex data structures, consider JSONB.
    
    Examples:
        >>> # User preferences
        >>> class User(db.Model):
        ...     preferences = Column(HSTORE)
        ...
        >>> # Query users with specific preference
        >>> theme_users = db.session.query(User).filter(
        ...     User.preferences['theme'].astext == 'dark'
        ... )
    """
    def get_col_spec(self):
        return "HSTORE"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, dict):
                return value
            return value
        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            return dict(value) if hasattr(value, 'items') else value
        return process


# WTForms field classes for PostgreSQL types

class JSONBField(Field):
    """
    Form field for JSONB data with validation and formatting
    """
    widget = JSONBWidget()

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = json.loads(valuelist[0]) if valuelist[0] else None
            except json.JSONDecodeError:
                self.data = valuelist[0]  # Keep as string for error display
                raise ValueError('Invalid JSON format')
        else:
            self.data = None

    def _value(self):
        if self.data:
            if isinstance(self.data, (dict, list)):
                return json.dumps(self.data, indent=2, ensure_ascii=False)
            return str(self.data)
        return ''


class PostgreSQLArrayField(Field):
    """
    Form field for PostgreSQL array types
    """
    def __init__(self, array_type='text', separator=',', **kwargs):
        self.array_type = array_type
        self.separator = separator
        self.widget = PostgreSQLArrayWidget(array_type=array_type, separator=separator)
        super().__init__(**kwargs)

    def process_formdata(self, valuelist):
        if valuelist and valuelist[0]:
            # Handle PostgreSQL array format {item1,item2,item3}
            array_str = valuelist[0].strip()
            if array_str.startswith('{') and array_str.endswith('}'):
                items = array_str[1:-1].split(',')
                self.data = [item.strip().strip('"\'') for item in items if item.strip()]
            else:
                self.data = [item.strip() for item in array_str.split(self.separator) if item.strip()]
        else:
            self.data = []

    def _value(self):
        if self.data:
            return '{' + ','.join(f'"{item}"' for item in self.data) + '}'
        return '{}'


class PostGISGeometryField(Field):
    """
    Form field for PostGIS geometry types
    """
    def __init__(self, geometry_type='POINT', srid=4326, **kwargs):
        self.geometry_type = geometry_type
        self.srid = srid
        self.widget = PostGISGeometryWidget(geometry_type=geometry_type, srid=srid)
        super().__init__(**kwargs)

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = valuelist[0] if valuelist[0] else None
        else:
            self.data = None

    def _value(self):
        return self.data or ''


class PgVectorField(Field):
    """
    Form field for pgvector embeddings
    """
    def __init__(self, dimension=768, **kwargs):
        self.dimension = dimension
        self.widget = PgVectorWidget(dimension=dimension)
        super().__init__(**kwargs)

    def process_formdata(self, valuelist):
        if valuelist and valuelist[0]:
            try:
                # Try to parse as JSON array
                if valuelist[0].strip().startswith('['):
                    self.data = json.loads(valuelist[0])
                else:
                    # Try comma-separated values
                    self.data = [float(x.strip()) for x in valuelist[0].split(',') if x.strip()]
                
                # Validate dimension
                if len(self.data) != self.dimension:
                    raise ValueError(f'Vector dimension mismatch: got {len(self.data)}, expected {self.dimension}')
                    
            except (json.JSONDecodeError, ValueError) as e:
                self.data = valuelist[0]  # Keep original for error display
                raise ValueError(f'Invalid vector format: {e}')
        else:
            self.data = None

    def _value(self):
        if self.data:
            if isinstance(self.data, list):
                return '[' + ', '.join(str(x) for x in self.data) + ']'
            return str(self.data)
        return ''


class PostgreSQLIntervalField(Field):
    """
    Form field for PostgreSQL interval type
    """
    widget = PostgreSQLIntervalWidget()

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = valuelist[0] if valuelist[0] else None
        else:
            self.data = None

    def _value(self):
        return self.data or ''


class PostgreSQLUUIDField(Field):
    """
    Form field for PostgreSQL UUID type
    """
    widget = PostgreSQLUUIDWidget()

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = valuelist[0] if valuelist[0] else None
        else:
            self.data = None

    def _value(self):
        return self.data or ''


class PostgreSQLBitStringField(Field):
    """
    Form field for PostgreSQL bit and bit varying types
    """
    def __init__(self, length=None, **kwargs):
        self.length = length
        self.widget = PostgreSQLBitStringWidget(length=length)
        super().__init__(**kwargs)

    def process_formdata(self, valuelist):
        if valuelist:
            value = valuelist[0] if valuelist[0] else None
            if value and not all(c in '01' for c in value):
                raise ValueError('Bit string must contain only 0s and 1s')
            if self.length and value and len(value) != self.length:
                raise ValueError(f'Bit string length must be {self.length}')
            self.data = value
        else:
            self.data = None

    def _value(self):
        return self.data or ''
    
    def to_hex(self) -> str:
        """Convert bit string to hexadecimal representation"""
        if not self.data:
            return '0x0'
        
        # Pad to multiple of 4 bits for clean hex conversion
        padded = self.data.ljust((len(self.data) + 3) // 4 * 4, '0')
        hex_value = hex(int(padded, 2))[2:].upper()
        return f'0x{hex_value}'
    
    def to_int(self) -> int:
        """Convert bit string to integer value"""
        if not self.data:
            return 0
        return int(self.data, 2)


class PostgreSQLTreeField(Field):
    """
    WTForms field for hierarchical tree data with comprehensive tree management
    
    Supports both LTREE paths and parent_id/foreign key relationships for
    building and managing hierarchical data structures with rich UI interactions.
    
    Features:
        - LTREE path support for PostgreSQL ltree extension
        - Parent-child relationship support for standard tables
        - Interactive visual tree with drag-and-drop
        - Import/export in multiple formats (JSON, CSV, SQL)
        - Real-time validation and orphan detection
        - Search and filter capabilities
        - Batch operations and tree repair tools
    
    Args:
        mode (str): 'ltree' for LTREE paths or 'parent_id' for foreign key relationships
        id_field (str): Name of the ID field (for parent_id mode)
        parent_id_field (str): Name of the parent ID field (for parent_id mode)
        label_field (str): Name of the display label field
        max_depth (int): Maximum tree depth allowed
        allow_reorder (bool): Whether to allow node reordering
        allow_drag_drop (bool): Whether to enable drag-and-drop
        validation_rules (dict): Custom validation rules
    
    Examples:
        >>> # LTREE mode for organizational hierarchy
        >>> class DepartmentForm(FlaskForm):
        ...     org_structure = PostgreSQLTreeField(
        ...         'Organization', 
        ...         mode='ltree',
        ...         max_depth=5
        ...     )
        
        >>> # Parent-ID mode for category tree
        >>> class CategoryForm(FlaskForm):
        ...     category_tree = PostgreSQLTreeField(
        ...         'Categories',
        ...         mode='parent_id',
        ...         id_field='category_id',
        ...         parent_id_field='parent_category_id',
        ...         label_field='category_name'
        ...     )
    """
    
    def __init__(self, 
                 mode='ltree',
                 id_field='id',
                 parent_id_field='parent_id',
                 label_field='name',
                 max_depth=10,
                 allow_reorder=True,
                 allow_drag_drop=True,
                 path_separator='.',
                 validation_rules=None,
                 **kwargs):
        self.mode = mode
        self.id_field = id_field
        self.parent_id_field = parent_id_field
        self.label_field = label_field
        self.max_depth = max_depth
        self.allow_reorder = allow_reorder
        self.allow_drag_drop = allow_drag_drop
        self.path_separator = path_separator
        self.validation_rules = validation_rules or {}
        
        self.widget = PostgreSQLTreeWidget(
            mode=mode,
            id_field=id_field,
            parent_id_field=parent_id_field,
            label_field=label_field,
            max_depth=max_depth,
            allow_reorder=allow_reorder,
            allow_drag_drop=allow_drag_drop,
            path_separator=path_separator,
            validation_rules=validation_rules
        )
        
        super().__init__(**kwargs)
    
    def process_formdata(self, valuelist):
        """Process tree data from form input with comprehensive validation"""
        if valuelist and valuelist[0]:
            tree_data_str = valuelist[0].strip()
            
            try:
                if self.mode == 'ltree':
                    # Process LTREE data
                    self.data = self._process_ltree_data(tree_data_str)
                else:
                    # Process parent-child relationship data
                    self.data = self._process_parent_id_data(tree_data_str)
                
                # Validate the processed tree data
                self._validate_tree_structure()
                
            except (json.JSONDecodeError, ValueError) as e:
                self.data = tree_data_str  # Keep original for error display
                raise ValueError(f'Invalid tree data format: {e}')
        else:
            self.data = None
    
    def _process_ltree_data(self, data_str: str) -> dict:
        """Process LTREE format data"""
        try:
            # Try JSON format first
            if data_str.strip().startswith(('{', '[')):
                return json.loads(data_str)
            else:
                # Parse LTREE paths
                return self._parse_ltree_paths(data_str)
        except json.JSONDecodeError:
            return self._parse_ltree_paths(data_str)
    
    def _parse_ltree_paths(self, paths_str: str) -> dict:
        """Parse LTREE paths into hierarchical structure"""
        paths = [p.strip() for p in paths_str.split('\n') if p.strip()]
        tree = {}
        
        for path in paths:
            parts = path.split(self.path_separator)
            current = tree
            
            for i, part in enumerate(parts):
                if part not in current:
                    current[part] = {
                        'label': part,
                        'path': self.path_separator.join(parts[:i+1]),
                        'children': {}
                    }
                current = current[part]['children']
        
        return tree
    
    def _process_parent_id_data(self, data_str: str) -> list:
        """Process parent-child relationship data"""
        try:
            # Try JSON format
            data = json.loads(data_str)
            
            if isinstance(data, list):
                # List of objects with parent-child relationships
                return self._validate_parent_child_data(data)
            else:
                # Hierarchical JSON - convert to flat structure
                return self._convert_hierarchical_to_flat(data)
                
        except json.JSONDecodeError:
            # Try CSV format
            return self._parse_csv_data(data_str)
    
    def _validate_parent_child_data(self, data: list) -> list:
        """Validate parent-child relationship data structure"""
        required_fields = {self.id_field, self.label_field}
        
        for item in data:
            if not isinstance(item, dict):
                raise ValueError('Each item must be a dictionary')
            
            missing_fields = required_fields - set(item.keys())
            if missing_fields:
                raise ValueError(f'Missing required fields: {", ".join(missing_fields)}')
        
        return data
    
    def _convert_hierarchical_to_flat(self, tree_data: dict) -> list:
        """Convert hierarchical JSON to flat parent-child structure"""
        flat_data = []
        id_counter = 1
        
        def traverse(node_dict, parent_id=None):
            nonlocal id_counter
            
            for key, node in node_dict.items():
                current_id = id_counter
                id_counter += 1
                
                flat_item = {
                    self.id_field: current_id,
                    self.label_field: node.get('label', key),
                    self.parent_id_field: parent_id
                }
                
                flat_data.append(flat_item)
                
                # Process children
                if 'children' in node and node['children']:
                    traverse(node['children'], current_id)
        
        traverse(tree_data)
        return flat_data
    
    def _parse_csv_data(self, csv_str: str) -> list:
        """Parse CSV data into parent-child structure"""
        lines = [line.strip() for line in csv_str.split('\n') if line.strip()]
        
        if not lines:
            return []
        
        # Assume first line is header
        headers = [h.strip().strip('"') for h in lines[0].split(',')]
        
        # Validate required columns
        required_cols = {self.id_field, self.label_field}
        if not required_cols.issubset(set(headers)):
            missing = required_cols - set(headers)
            raise ValueError(f'CSV missing required columns: {", ".join(missing)}')
        
        data = []
        for line in lines[1:]:
            values = [v.strip().strip('"') for v in line.split(',')]
            if len(values) != len(headers):
                continue
            
            row = dict(zip(headers, values))
            
            # Convert data types
            try:
                if self.id_field in row and row[self.id_field]:
                    row[self.id_field] = int(row[self.id_field])
                if (self.parent_id_field in row and 
                    row[self.parent_id_field] and 
                    row[self.parent_id_field].lower() not in ('null', 'none', '')):
                    row[self.parent_id_field] = int(row[self.parent_id_field])
                else:
                    row[self.parent_id_field] = None
            except ValueError:
                continue
            
            data.append(row)
        
        return data
    
    def _validate_tree_structure(self):
        """Validate the tree structure according to rules"""
        if not self.data:
            return
        
        if self.mode == 'ltree':
            self._validate_ltree_structure()
        else:
            self._validate_parent_child_structure()
    
    def _validate_ltree_structure(self):
        """Validate LTREE structure"""
        def validate_node(node_dict, depth=0):
            if depth > self.max_depth:
                raise ValueError(f'Tree depth exceeds maximum of {self.max_depth}')
            
            for key, node in node_dict.items():
                # Validate path format
                if 'path' in node:
                    path_parts = node['path'].split(self.path_separator)
                    if len(path_parts) != depth + 1:
                        raise ValueError(f'Invalid path depth for node "{key}"')
                
                # Validate children
                if 'children' in node and node['children']:
                    validate_node(node['children'], depth + 1)
        
        validate_node(self.data)
    
    def _validate_parent_child_structure(self):
        """Validate parent-child relationship structure"""
        if not isinstance(self.data, list):
            raise ValueError('Parent-child data must be a list of objects')
        
        ids = set()
        parent_ids = set()
        
        # Check for duplicate IDs and collect parent references
        for item in self.data:
            item_id = item[self.id_field]
            if item_id in ids:
                raise ValueError(f'Duplicate ID found: {item_id}')
            ids.add(item_id)
            
            parent_id = item.get(self.parent_id_field)
            if parent_id is not None:
                parent_ids.add(parent_id)
        
        # Check for orphaned references
        orphaned = parent_ids - ids
        if orphaned:
            raise ValueError(f'Orphaned parent references: {", ".join(map(str, orphaned))}')
    
    def _value(self):
        """Format tree data for display"""
        if not self.data:
            return ''
        
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, indent=2, ensure_ascii=False)
        else:
            return str(self.data)


# Mixin classes for enhanced PostgreSQL profile support

class PostgreSQLProfileMixin:
    """
    Enhanced profile mixin with PostgreSQL-specific field types
    """
    
    # JSONB fields for flexible data storage
    preferences_jsonb = Column(JSONB, default=dict)
    metadata_jsonb = Column(JSONB, default=dict)
    
    # Array fields for multi-value attributes
    skills_array = Column(ARRAY(TEXT), default=list)
    languages_array = Column(ARRAY(VARCHAR(10)), default=list)
    tags_array = Column(ARRAY(VARCHAR(50)), default=list)
    
    # UUID fields for external system integration
    external_id = Column(UUID)
    sync_id = Column(UUID)
    
    # Network address fields
    last_login_ip = Column(INET)
    registration_ip = Column(INET)
    
    # Full-text search support
    profile_search_vector = Column(TSVECTOR)
    
    # Interval fields for time-based data
    session_timeout = Column(INTERVAL, default='1 hour')
    password_age = Column(INTERVAL)
    
    # Bit string for feature flags
    feature_flags = Column(BIT(32), default='00000000000000000000000000000000')
    
    def get_jsonb_field(self, field_name: str, key: str, default: Any = None) -> Any:
        """Get a value from a JSONB field"""
        field_value = getattr(self, field_name, {})
        return field_value.get(key, default) if field_value else default
    
    def set_jsonb_field(self, field_name: str, key: str, value: Any) -> None:
        """Set a value in a JSONB field"""
        field_value = getattr(self, field_name) or {}
        field_value[key] = value
        setattr(self, field_name, field_value)
    
    def add_to_array(self, field_name: str, value: Any) -> None:
        """Add a value to an array field"""
        current_array = getattr(self, field_name) or []
        if value not in current_array:
            current_array.append(value)
            setattr(self, field_name, current_array)
    
    def remove_from_array(self, field_name: str, value: Any) -> None:
        """Remove a value from an array field"""
        current_array = getattr(self, field_name) or []
        if value in current_array:
            current_array.remove(value)
            setattr(self, field_name, current_array)


class PostGISProfileMixin:
    """
    Profile mixin with PostGIS spatial capabilities
    """
    
    # Location as point geometry
    location = Column(Geometry('POINT', 4326))
    
    # Home and work locations
    home_location = Column(Geometry('POINT', 4326))
    work_location = Column(Geometry('POINT', 4326))
    
    # Service area or territory (polygon)
    service_area = Column(Geometry('POLYGON', 4326))
    
    # Travel route or path
    travel_route = Column(Geometry('LINESTRING', 4326))
    
    # Geography fields for global calculations
    global_location = Column(Geography('POINT', 4326))
    
    def calculate_distance_to(self, other_location: str) -> Optional[float]:
        """Calculate distance to another location using PostGIS
        
        Args:
            other_location: WKT representation of the other location
            
        Returns:
            Distance in meters, or None if calculation fails
        """
        if not self.location or not other_location:
            return None
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            result = db.session.execute(
                text("SELECT ST_Distance(ST_GeomFromText(:loc1, 4326)::geography, ST_GeomFromText(:loc2, 4326)::geography)"),
                {"loc1": str(self.location), "loc2": other_location}
            ).scalar()
            
            return float(result) if result is not None else None
        except Exception:
            # Fallback to approximate calculation using haversine formula
            return self._calculate_haversine_distance(other_location)
    
    def _calculate_haversine_distance(self, other_location: str) -> Optional[float]:
        """Fallback distance calculation using haversine formula"""
        import re
        import math
        
        try:
            # Parse POINT(lng lat) format
            point_match = re.match(r'POINT\(([\d\.-]+)\s+([\d\.-]+)\)', other_location)
            if not point_match:
                return None
                
            other_lng, other_lat = float(point_match.group(1)), float(point_match.group(2))
            
            # Parse self location (assuming it's stored as WKT)
            self_match = re.match(r'POINT\(([\d\.-]+)\s+([\d\.-]+)\)', str(self.location))
            if not self_match:
                return None
                
            self_lng, self_lat = float(self_match.group(1)), float(self_match.group(2))
            
            # Haversine formula
            R = 6371000  # Earth's radius in meters
            lat1, lat2 = math.radians(self_lat), math.radians(other_lat)
            dlat = math.radians(other_lat - self_lat)
            dlng = math.radians(other_lng - self_lng)
            
            a = (math.sin(dlat/2) * math.sin(dlat/2) +
                 math.cos(lat1) * math.cos(lat2) *
                 math.sin(dlng/2) * math.sin(dlng/2))
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            
            return R * c
        except Exception:
            return None
    
    def find_nearby_profiles(self, radius_meters: float = 1000) -> List:
        """Find profiles within a given radius using PostGIS spatial queries
        
        Args:
            radius_meters: Search radius in meters (default: 1000)
            
        Returns:
            List of nearby profile objects within the specified radius
        """
        if not self.location:
            return []
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            # Use PostGIS ST_DWithin for efficient spatial query
            query = text("""
                SELECT * FROM {table_name} 
                WHERE ST_DWithin(
                    location::geography, 
                    ST_GeomFromText(:location, 4326)::geography, 
                    :radius
                ) AND id != :current_id
                ORDER BY ST_Distance(
                    location::geography, 
                    ST_GeomFromText(:location, 4326)::geography
                )
            """.format(table_name=self.__tablename__))
            
            result = db.session.execute(query, {
                "location": str(self.location),
                "radius": radius_meters,
                "current_id": getattr(self, 'id', None)
            })
            
            # Convert results back to model instances
            profiles = []
            for row in result:
                profile = self.__class__()
                for key, value in row._mapping.items():
                    setattr(profile, key, value)
                profiles.append(profile)
            
            return profiles
            
        except Exception:
            # Fallback to basic filtering (less efficient)
            return self._find_nearby_profiles_fallback(radius_meters)
    
    def _find_nearby_profiles_fallback(self, radius_meters: float) -> List:
        """Fallback method for finding nearby profiles without PostGIS"""
        try:
            from pgappforge import db
            
            # Get all profiles with locations
            all_profiles = db.session.query(self.__class__).filter(
                self.__class__.location.isnot(None)
            ).all()
            
            nearby = []
            for profile in all_profiles:
                if profile.id == getattr(self, 'id', None):
                    continue
                    
                distance = self.calculate_distance_to(str(profile.location))
                if distance is not None and distance <= radius_meters:
                    nearby.append(profile)
            
            # Sort by distance
            nearby.sort(key=lambda p: self.calculate_distance_to(str(p.location)) or float('inf'))
            return nearby
            
        except Exception:
            return []


class PgVectorProfileMixin:
    """
    Profile mixin with pgvector embedding capabilities for AI/ML features
    """
    
    # Profile embedding vector for similarity search
    profile_embedding = Column(Vector(768))  # OpenAI embedding dimension
    
    # Skill embeddings for matching
    skills_embedding = Column(Vector(384))   # Smaller dimension for skills
    
    # Interest embeddings
    interests_embedding = Column(Vector(256))
    
    # Text content embeddings
    bio_embedding = Column(Vector(768))
    
    def calculate_profile_similarity(self, other_profile) -> Optional[float]:
        """Calculate cosine similarity between profile embeddings using pgvector
        
        Args:
            other_profile: Another profile object with embedding vector
            
        Returns:
            Cosine similarity score between 0 and 1, or None if calculation fails
        """
        if not self.profile_embedding or not other_profile.profile_embedding:
            return None
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            # Use pgvector cosine distance operator (<=>)
            result = db.session.execute(
                text("SELECT 1 - (:embedding1 <=> :embedding2) as similarity"),
                {
                    "embedding1": str(self.profile_embedding),
                    "embedding2": str(other_profile.profile_embedding)
                }
            ).scalar()
            
            return float(result) if result is not None else None
            
        except Exception:
            # Fallback to manual cosine similarity calculation
            return self._calculate_cosine_similarity(
                self.profile_embedding, 
                other_profile.profile_embedding
            )
    
    def _calculate_cosine_similarity(self, vec1, vec2) -> Optional[float]:
        """Manual cosine similarity calculation as fallback"""
        import math
        
        try:
            # Convert vectors to lists if they're strings
            if isinstance(vec1, str):
                vec1 = [float(x) for x in vec1.strip('[]').split(',')]
            if isinstance(vec2, str):
                vec2 = [float(x) for x in vec2.strip('[]').split(',')]
            
            if len(vec1) != len(vec2):
                return None
            
            # Calculate dot product and magnitudes
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            magnitude1 = math.sqrt(sum(x * x for x in vec1))
            magnitude2 = math.sqrt(sum(x * x for x in vec2))
            
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            return dot_product / (magnitude1 * magnitude2)
            
        except Exception:
            return None
    
    def find_similar_profiles(self, limit: int = 10, threshold: float = 0.7) -> List:
        """Find similar profiles using pgvector similarity search
        
        Args:
            limit: Maximum number of similar profiles to return
            threshold: Minimum similarity threshold (0.0 to 1.0)
            
        Returns:
            List of tuples (profile, similarity_score) ordered by similarity
        """
        if not self.profile_embedding:
            return []
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            # Use pgvector similarity search with distance operators
            query = text("""
                SELECT *, (1 - (profile_embedding <=> :embedding)) as similarity 
                FROM {table_name}
                WHERE profile_embedding IS NOT NULL 
                AND id != :current_id
                AND (1 - (profile_embedding <=> :embedding)) >= :threshold
                ORDER BY profile_embedding <=> :embedding
                LIMIT :limit
            """.format(table_name=self.__tablename__))
            
            result = db.session.execute(query, {
                "embedding": str(self.profile_embedding),
                "current_id": getattr(self, 'id', None),
                "threshold": threshold,
                "limit": limit
            })
            
            similar_profiles = []
            for row in result:
                profile = self.__class__()
                similarity_score = None
                
                for key, value in row._mapping.items():
                    if key == 'similarity':
                        similarity_score = float(value)
                    else:
                        setattr(profile, key, value)
                
                similar_profiles.append((profile, similarity_score))
            
            return similar_profiles
            
        except Exception:
            # Fallback to manual similarity calculation
            return self._find_similar_profiles_fallback(limit, threshold)
    
    def _find_similar_profiles_fallback(self, limit: int, threshold: float) -> List:
        """Fallback method for finding similar profiles without pgvector"""
        try:
            from pgappforge import db
            
            # Get all profiles with embeddings
            all_profiles = db.session.query(self.__class__).filter(
                self.__class__.profile_embedding.isnot(None)
            ).all()
            
            similar = []
            for profile in all_profiles:
                if profile.id == getattr(self, 'id', None):
                    continue
                    
                similarity = self.calculate_profile_similarity(profile)
                if similarity is not None and similarity >= threshold:
                    similar.append((profile, similarity))
            
            # Sort by similarity (descending) and limit
            similar.sort(key=lambda x: x[1], reverse=True)
            return similar[:limit]
            
        except Exception:
            return []


class AdvancedPostgreSQLProfileMixin(PostgreSQLProfileMixin, PostGISProfileMixin, PgVectorProfileMixin):
    """
    Complete PostgreSQL profile mixin with all advanced features
    """
    
    # Additional specialized fields
    organizational_tree = Column(LTREE)      # Hierarchical organization structure
    custom_attributes = Column(HSTORE)       # Key-value store for custom attributes
    
    # Time series data
    activity_timestamps = Column(ARRAY(TIMESTAMP))
    performance_metrics = Column(JSONB)
    
    # Advanced search (using text type since TSQUERY not available in all versions)
    content_search = Column(TEXT)
    
    def get_organizational_level(self) -> int:
        """Get the organizational level from LTREE path
        
        Returns:
            Depth level in the organizational hierarchy (0 for root)
        """
        if self.organizational_tree:
            path = str(self.organizational_tree).strip()
            if path:
                return len(path.split('.'))
        return 0
    
    def is_ancestor_of(self, other_profile) -> bool:
        """Check if this profile is an ancestor in the organizational tree
        
        Args:
            other_profile: Profile to check relationship with
            
        Returns:
            True if this profile is an ancestor of the other profile
        """
        if not self.organizational_tree or not other_profile.organizational_tree:
            return False
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            # Use LTREE ancestor operator (@>)
            result = db.session.execute(
                text("SELECT :ancestor @> :descendant"),
                {
                    "ancestor": str(self.organizational_tree),
                    "descendant": str(other_profile.organizational_tree)
                }
            ).scalar()
            
            return bool(result) if result is not None else False
            
        except Exception:
            # Fallback to string-based comparison
            self_path = str(self.organizational_tree)
            other_path = str(other_profile.organizational_tree)
            return (other_path.startswith(self_path + '.') or 
                    other_path == self_path)
    
    def get_descendants(self) -> List:
        """Get all descendant profiles in the organizational tree
        
        Returns:
            List of profiles that are descendants of this profile
        """
        if not self.organizational_tree:
            return []
            
        try:
            from sqlalchemy import text
            from pgappforge import db
            
            # Use LTREE descendant query
            query = text("""
                SELECT * FROM {table_name}
                WHERE organizational_tree <@ :ancestor
                AND id != :current_id
                ORDER BY organizational_tree
            """.format(table_name=self.__tablename__))
            
            result = db.session.execute(query, {
                "ancestor": str(self.organizational_tree),
                "current_id": getattr(self, 'id', None)
            })
            
            descendants = []
            for row in result:
                profile = self.__class__()
                for key, value in row._mapping.items():
                    setattr(profile, key, value)
                descendants.append(profile)
            
            return descendants
            
        except Exception:
            return []
    
    def get_ancestors(self) -> List:
        """Get all ancestor profiles in the organizational tree
        
        Returns:
            List of profiles that are ancestors of this profile
        """
        if not self.organizational_tree:
            return []
            
        ancestors = []
        path_parts = str(self.organizational_tree).split('.')
        
        try:
            from pgappforge import db
            
            # Build ancestor paths
            for i in range(1, len(path_parts)):
                ancestor_path = '.'.join(path_parts[:i])
                
                ancestor = db.session.query(self.__class__).filter(
                    self.__class__.organizational_tree == ancestor_path
                ).first()
                
                if ancestor:
                    ancestors.append(ancestor)
            
            return ancestors
            
        except Exception:
            return []


# Column type mappings for form field generation
POSTGRESQL_TYPE_FIELD_MAPPING = {
    # Standard PostgreSQL types
    INTEGER: 'IntegerField',
    BIGINT: 'IntegerField',
    SMALLINT: 'IntegerField',
    DECIMAL: 'DecimalField',
    NUMERIC: 'DecimalField',
    REAL: 'FloatField',
    DOUBLE_PRECISION: 'FloatField',
    MONEY: 'DecimalField',
    
    # Text types
    TEXT: 'TextAreaField',
    VARCHAR: 'StringField',
    CHAR: 'StringField',
    
    # Date/time types
    DATE: 'DateField',
    TIME: 'TimeField',
    TIMESTAMP: 'DateTimeField',
    INTERVAL: PostgreSQLIntervalField,
    
    # Boolean
    BOOLEAN: 'BooleanField',
    
    # Network types
    INET: 'StringField',
    MACADDR: 'StringField',
    MACADDR8: 'StringField',
    
    # UUID
    UUID: PostgreSQLUUIDField,
    
    # JSON types
    JSON: JSONBField,
    JSONB: JSONBField,
    
    # Array types
    ARRAY: PostgreSQLArrayField,
    
    # Binary
    BYTEA: 'StringField',
    BIT: PostgreSQLBitStringField,
    
    # Full-text search
    TSVECTOR: 'StringField',
    
    # Custom types
    Vector: PgVectorField,
    Geometry: PostGISGeometryField,
    Geography: PostGISGeometryField,
    LTREE: PostgreSQLTreeField,
    HSTORE: JSONBField,
}


def get_postgresql_field_for_column(column) -> str:
    """
    Get the appropriate form field class for a PostgreSQL column type
    """
    column_type = type(column.type)
    
    # Handle array types specially
    if isinstance(column.type, ARRAY):
        return PostgreSQLArrayField
    
    # Handle custom types
    for pg_type, field_class in POSTGRESQL_TYPE_FIELD_MAPPING.items():
        if isinstance(column.type, pg_type):
            return field_class
    
    # Default fallback
    return 'StringField'