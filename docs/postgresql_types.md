# PostgreSQL Types Support in PgAppForge

PgAppForge now includes comprehensive support for PostgreSQL-specific data types with rich widgets and form fields. This includes JSONB, PostGIS geometry types, pgvector embeddings, arrays, and many other PostgreSQL features.

## Overview

The PostgreSQL types support provides:

- **JSONB Support**: Rich JSON editing with syntax highlighting and validation
- **PostGIS Integration**: Interactive map widgets for geometry/geography types
- **pgvector Support**: Vector embeddings with similarity search capabilities  
- **Array Types**: Dynamic array editing with add/remove functionality
- **Network Types**: IP address and MAC address validation
- **UUID Generation**: UUID fields with automatic generation
- **Interval Types**: Time interval input with presets
- **Bit Strings**: Binary string editing with bit manipulation tools
- **Full-text Search**: TSVECTOR and TSQUERY support
- **LTREE**: Hierarchical data structures with interactive tree widget
- **Tree Widget**: Comprehensive hierarchical data management for both LTREE and parent-child relationships
- **HSTORE**: Key-value pair storage

## Installation Requirements

```bash
# PostgreSQL with extensions
sudo apt-get install postgresql-14 postgresql-14-postgis-3
pip install psycopg2-binary

# For pgvector support
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# Create extensions in your database
psql -d your_database -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -d your_database -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d your_database -c "CREATE EXTENSION IF NOT EXISTS ltree;"
psql -d your_database -c "CREATE EXTENSION IF NOT EXISTS hstore;"
```

## JSONB Support

### Model Definition

```python
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.postgresql import PostgreSQLProfileMixin

class UserProfile(Model, PostgreSQLProfileMixin):
    settings = Column(JSONB, default=dict)
    metadata = Column(JSONB, default=dict)
    preferences = Column(JSONB, default=dict)
```

### Form Field Usage

```python
from pgappforge.models.postgresql import JSONBField

class ProfileForm(DynamicForm):
    settings = JSONBField(label='User Settings')
    metadata = JSONBField(label='Profile Metadata')
```

### Widget Features

- **Syntax Highlighting**: JSON syntax highlighting in textarea
- **Validation**: Real-time JSON validation with error messages
- **Formatting**: Format/minify JSON with toolbar buttons
- **Auto-completion**: Smart JSON editing assistance

### Usage Example

```python
# Set JSONB data
profile.settings = {
    "theme": "dark",
    "notifications": {
        "email": True,
        "push": False,
        "frequency": "daily"
    },
    "dashboard": {
        "layout": "grid",
        "widgets": ["stats", "charts", "activity"]
    }
}

# Query JSONB data
users_with_dark_theme = session.query(UserProfile).filter(
    UserProfile.settings['theme'].astext == 'dark'
).all()

# Update nested JSONB
session.query(UserProfile).filter(
    UserProfile.id == user_id
).update({
    UserProfile.settings: UserProfile.settings.op('||')(
        {"notifications": {"sms": True}}
    )
})
```

## PostgreSQL Arrays

### Model Definition

```python
from sqlalchemy.dialects.postgresql import ARRAY, TEXT, INTEGER

class UserProfile(Model):
    skills = Column(ARRAY(TEXT), default=list)
    scores = Column(ARRAY(INTEGER), default=list)
    tags = Column(ARRAY(VARCHAR(50)), default=list)
```

### Form Field Usage

```python
from pgappforge.models.postgresql import PostgreSQLArrayField

class ProfileForm(DynamicForm):
    skills = PostgreSQLArrayField(array_type='text', label='Skills')
    scores = PostgreSQLArrayField(array_type='integer', label='Scores')
```

### Widget Features

- **Dynamic Add/Remove**: Add and remove array items dynamically
- **Type Validation**: Validate array item types
- **Drag & Drop**: Reorder array items
- **Bulk Import**: Import arrays from CSV or JSON

### Usage Example

```python
# Add items to arrays
profile.skills.append('Python')
profile.skills.extend(['JavaScript', 'PostgreSQL'])

# Query arrays
python_developers = session.query(UserProfile).filter(
    UserProfile.skills.any('Python')
).all()

# Array overlap queries
web_developers = session.query(UserProfile).filter(
    UserProfile.skills.overlap(['JavaScript', 'HTML', 'CSS'])
).all()
```

## PostGIS Geometry Support

### Model Definition

```python
from pgappforge.models.postgresql import Geometry, Geography

class UserProfile(Model):
    location = Column(Geometry('POINT', 4326))
    service_area = Column(Geometry('POLYGON', 4326))
    travel_route = Column(Geometry('LINESTRING', 4326))
    global_location = Column(Geography('POINT', 4326))
```

### Form Field Usage

```python
from pgappforge.models.postgresql import PostGISGeometryField

class ProfileForm(DynamicForm):
    location = PostGISGeometryField(
        geometry_type='POINT', 
        srid=4326,
        label='Location'
    )
    service_area = PostGISGeometryField(
        geometry_type='POLYGON',
        srid=4326,
        label='Service Area'
    )
```

### Widget Features

- **Interactive Maps**: Leaflet-based map interface
- **Drawing Tools**: Draw points, lines, and polygons
- **Current Location**: Get user's GPS location
- **WKT Display**: View Well-Known Text representation
- **Coordinate Display**: Show lat/lng coordinates
- **Multiple Formats**: Support for WKT, GeoJSON, and more

### Usage Example

```python
# Set location
profile.location = 'POINT(-74.0060 40.7128)'  # NYC

# Distance queries
nearby_users = session.query(UserProfile).filter(
    func.ST_DWithin(
        UserProfile.location,
        func.ST_GeomFromText('POINT(-74.0060 40.7128)', 4326),
        1000  # 1000 meters
    )
).all()

# Area queries
users_in_manhattan = session.query(UserProfile).filter(
    func.ST_Within(
        UserProfile.location,
        func.ST_GeomFromText(manhattan_polygon_wkt, 4326)
    )
).all()
```

## pgvector Embeddings

### Model Definition

```python
from pgappforge.models.postgresql import Vector

class UserProfile(Model):
    profile_embedding = Column(Vector(768))  # OpenAI embeddings
    skills_embedding = Column(Vector(384))   # Sentence transformers
    content_embedding = Column(Vector(512))  # Custom embeddings
```

### Form Field Usage

```python
from pgappforge.models.postgresql import PgVectorField

class ProfileForm(DynamicForm):
    profile_embedding = PgVectorField(
        dimension=768,
        label='Profile Embedding'
    )
```

### Widget Features

- **Vector Visualization**: Bar chart of vector components
- **Normalization**: L2 normalize vectors
- **Random Generation**: Generate random test vectors
- **Dimension Validation**: Ensure correct vector dimensions
- **Statistics Display**: Show magnitude, mean, min/max values

### Usage Example

```python
# Set embeddings
profile.profile_embedding = generate_profile_embedding(profile.bio)

# Similarity search
similar_profiles = session.query(UserProfile).order_by(
    UserProfile.profile_embedding.cosine_distance(query_embedding)
).limit(10).all()

# Vector operations
session.query(UserProfile).filter(
    UserProfile.profile_embedding.cosine_distance(query_embedding) < 0.5
).all()
```

## Other PostgreSQL Types

### UUID Fields

```python
from pgappforge.models.postgresql import PostgreSQLUUIDField
from sqlalchemy.dialects.postgresql import UUID

class UserProfile(Model):
    external_id = Column(UUID)
    sync_id = Column(UUID)

# Form usage
class ProfileForm(DynamicForm):
    external_id = PostgreSQLUUIDField(label='External ID')
```

### Interval Fields

```python
from sqlalchemy.dialects.postgresql import INTERVAL
from pgappforge.models.postgresql import PostgreSQLIntervalField

class UserProfile(Model):
    session_timeout = Column(INTERVAL, default='1 hour')
    password_age = Column(INTERVAL)

# Form usage
class ProfileForm(DynamicForm):
    session_timeout = PostgreSQLIntervalField(label='Session Timeout')
```

### Bit String Fields

```python
from sqlalchemy.dialects.postgresql import BIT
from pgappforge.models.postgresql import PostgreSQLBitStringField

class UserProfile(Model):
    feature_flags = Column(BIT(32))
    permissions = Column(BIT(64))

# Form usage  
class ProfileForm(DynamicForm):
    feature_flags = PostgreSQLBitStringField(length=32, label='Features')
```

### Network Address Fields

```python
from sqlalchemy.dialects.postgresql import INET, MACADDR

class UserProfile(Model):
    last_ip = Column(INET)
    device_mac = Column(MACADDR)
    allowed_networks = Column(ARRAY(INET))
```

## Advanced PostgreSQL Features

### Full-Text Search

```python
from sqlalchemy.dialects.postgresql import TSVECTOR, TSQUERY

class UserProfile(Model):
    search_vector = Column(TSVECTOR)
    
    def update_search_vector(self):
        self.search_vector = func.to_tsvector('english', 
            f"{self.name} {self.bio} {' '.join(self.skills)}")

# Search queries
search_results = session.query(UserProfile).filter(
    UserProfile.search_vector.match('python & developer')
).all()
```

### LTREE Hierarchical Data

```python
from pgappforge.models.postgresql import LTREE

class UserProfile(Model):
    org_path = Column(LTREE)  # e.g., 'engineering.backend.senior'
    
# Hierarchical queries
engineering_team = session.query(UserProfile).filter(
    UserProfile.org_path.op('<@')('engineering')
).all()
```

### HSTORE Key-Value Storage

```python
from pgappforge.models.postgresql import HSTORE

class UserProfile(Model):
    attributes = Column(HSTORE)

# Set attributes
profile.attributes = {
    'badge_color': 'blue',
    'parking_spot': 'A15',
    'access_level': '3'
}

# Query attributes
vip_users = session.query(UserProfile).filter(
    UserProfile.attributes['access_level'] == '5'
).all()
```

## Profile Mixins

Use pre-built mixins for common PostgreSQL functionality:

### PostgreSQLProfileMixin

```python
from pgappforge.models.postgresql import PostgreSQLProfileMixin

class UserProfile(Model, PostgreSQLProfileMixin):
    # Includes: JSONB preferences, array skills, UUID fields, etc.
    pass

# Helper methods available
profile.set_jsonb_field('preferences', 'theme', 'dark')
profile.add_to_array('skills_array', 'Python')
```

### PostGISProfileMixin

```python
from pgappforge.models.postgresql import PostGISProfileMixin

class UserProfile(Model, PostGISProfileMixin):
    # Includes: location, service_area, travel_route, etc.
    pass

# Spatial methods available  
distance = profile.calculate_distance_to(other_location)
nearby = profile.find_nearby_profiles(radius_meters=1000)
```

### PgVectorProfileMixin

```python
from pgappforge.models.postgresql import PgVectorProfileMixin

class UserProfile(Model, PgVectorProfileMixin):
    # Includes: profile_embedding, skills_embedding, etc.
    pass

# Vector methods available
similarity = profile.calculate_profile_similarity(other_profile)
similar_profiles = profile.find_similar_profiles(limit=10)
```

### Combined Advanced Mixin

```python
from pgappforge.models.postgresql import AdvancedPostgreSQLProfileMixin

class UserProfile(Model, AdvancedPostgreSQLProfileMixin):
    # Includes all PostgreSQL features
    pass
```

## Performance Considerations

### Indexing

```sql
-- JSONB indexes
CREATE INDEX CONCURRENTLY idx_profile_settings_theme 
ON user_profile USING GIN ((settings->>'theme'));

-- Array indexes  
CREATE INDEX CONCURRENTLY idx_profile_skills_gin
ON user_profile USING GIN (skills);

-- PostGIS spatial indexes
CREATE INDEX CONCURRENTLY idx_profile_location_gist
ON user_profile USING GIST (location);

-- pgvector indexes
CREATE INDEX CONCURRENTLY idx_profile_embedding_cosine
ON user_profile USING ivfflat (profile_embedding vector_cosine_ops)
WITH (lists = 100);

-- Full-text search indexes
CREATE INDEX CONCURRENTLY idx_profile_search_gin
ON user_profile USING GIN (search_vector);
```

### Query Optimization

```python
# JSONB query optimization
query = session.query(UserProfile).filter(
    UserProfile.settings['notifications']['email'].astext == 'true'
)

# Array query optimization  
query = session.query(UserProfile).filter(
    UserProfile.skills.contains(['Python'])
)

# Spatial query optimization
query = session.query(UserProfile).filter(
    func.ST_DWithin(
        UserProfile.location,
        func.ST_Point(-74, 40.7),
        1000
    )
)

# Vector similarity optimization
query = session.query(UserProfile).order_by(
    UserProfile.profile_embedding.cosine_distance(embedding)
).limit(20)
```

## Migration Examples

### Adding PostgreSQL Columns

```python
"""Add PostgreSQL specific columns

Revision ID: postgresql_001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID

def upgrade():
    # Add JSONB column
    op.add_column('user_profile', 
        sa.Column('preferences', JSONB, server_default='{}'))
    
    # Add array column
    op.add_column('user_profile',
        sa.Column('skills', ARRAY(sa.TEXT), server_default='{}'))
    
    # Add UUID column
    op.add_column('user_profile',
        sa.Column('external_id', UUID))
    
    # Add PostGIS column (requires PostGIS extension)
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    op.execute('''
        ALTER TABLE user_profile 
        ADD COLUMN location GEOMETRY(POINT, 4326)
    ''')
    
    # Add pgvector column (requires pgvector extension)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('''
        ALTER TABLE user_profile 
        ADD COLUMN embedding VECTOR(768)
    ''')

def downgrade():
    op.drop_column('user_profile', 'embedding')
    op.drop_column('user_profile', 'location')
    op.drop_column('user_profile', 'external_id')
    op.drop_column('user_profile', 'skills')
    op.drop_column('user_profile', 'preferences')
```

## Testing

Run the PostgreSQL-specific tests:

```bash
# Run all PostgreSQL tests
pytest tests/test_postgresql_types.py -v

# Run specific test categories
pytest tests/test_postgresql_types.py::TestJSONBField -v
pytest tests/test_postgresql_types.py::TestPostgreSQLArrayField -v
pytest tests/test_postgresql_types.py::TestPgVectorField -v

# Run with PostgreSQL database (requires setup)
POSTGRESQL_TEST_DB=postgresql://test:test@localhost/test_fab \
    pytest tests/test_postgresql_types.py -v -k "not skip"
```

## Example Application

See the complete example in `examples/postgresql_profile_example.py`:

```bash
cd examples
python postgresql_profile_example.py
```

This demonstrates all PostgreSQL features including:
- JSONB settings and preferences
- Array fields for skills and tags  
- PostGIS location tracking
- pgvector profile embeddings
- UUID external system integration
- Hierarchical tree structures (LTREE and parent-child)
- Interactive tree widget with drag-and-drop
- Advanced querying and indexing

## Configuration

Configure PostgreSQL-specific settings:

```python
# app.config
SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/dbname'

# Enable PostgreSQL extensions
FAB_ENABLE_POSTGRESQL_EXTENSIONS = True

# pgvector configuration
PGVECTOR_DEFAULT_DIMENSION = 768
PGVECTOR_INDEX_LISTS = 100

# PostGIS configuration  
POSTGIS_DEFAULT_SRID = 4326
POSTGIS_ENABLE_3D = False

# JSONB configuration
JSONB_ENABLE_SYNTAX_HIGHLIGHTING = True
JSONB_PRETTY_PRINT = True
```

## Troubleshooting

### Common Issues

**Extension not found**
```bash
# Install required extensions
sudo apt-get install postgresql-14-contrib
sudo apt-get install postgresql-14-postgis-3

# Enable in database
psql -d mydb -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

**pgvector installation**
```bash
# Compile from source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

**Permission errors**
```sql
-- Grant permissions
GRANT USAGE ON SCHEMA public TO myuser;
GRANT CREATE ON SCHEMA public TO myuser;
```

### Performance Issues

**Slow JSONB queries**
- Add GIN indexes on frequently queried JSONB paths
- Use `@>` operator for containment queries
- Consider extracting frequently queried fields

**Slow vector similarity**
- Create appropriate ivfflat indexes
- Tune the lists parameter based on data size
- Use approximate search for large datasets

**Slow spatial queries**  
- Ensure GIST indexes on geometry columns
- Use appropriate SRID for your use case
- Consider using geography type for global data

# PostgreSQL Tree Widget: Complete Documentation

The PostgreSQL Tree Widget is a comprehensive hierarchical data management component that provides rich interactive functionality for both LTREE path-based and traditional parent-child relationship tree structures.

## Table of Contents

1. [Overview](#overview)
2. [Installation & Setup](#installation--setup) 
3. [Parent-Child Mode](#parent-child-mode)
4. [LTREE Mode](#ltree-mode)
5. [Widget Configuration](#widget-configuration)
6. [Interactive Features](#interactive-features)
7. [Import/Export Functionality](#importexport-functionality)
8. [Validation & Tree Repair](#validation--tree-repair)
9. [JavaScript API](#javascript-api)
10. [Styling & Customization](#styling--customization)
11. [Performance Considerations](#performance-considerations)
12. [Complete Examples](#complete-examples)

## Overview

### Core Features

✅ **Dual Mode Support**: LTREE paths or parent_id/foreign key relationships  
✅ **Visual Tree Interface**: Interactive expand/collapse with drag-and-drop  
✅ **CRUD Operations**: Add, edit, delete nodes with confirmation dialogs  
✅ **Real-time Search**: Search with highlighting and automatic parent expansion  
✅ **Import/Export**: JSON, CSV, SQL, and LTREE format support  
✅ **Tree Validation**: Orphan detection, circular reference prevention  
✅ **Tree Repair**: Automatic structure repair and consistency maintenance  
✅ **Responsive Design**: Mobile-friendly with touch support  
✅ **Accessibility**: Keyboard navigation and screen reader support  

### Browser Requirements

- Modern browsers with ES6 support
- jQuery 3.0+
- Bootstrap 3.x/4.x CSS framework
- Font Awesome icons

## Installation & Setup

### Database Prerequisites

```sql
-- For LTREE mode (optional)
CREATE EXTENSION IF NOT EXISTS ltree;

-- For enhanced full-text search (optional)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Python Dependencies

```python
# Already included with flask-appbuilder
from pgappforge.widgets_postgresql.tree_widget import PostgreSQLTreeWidget
from pgappforge.models.postgresql import PostgreSQLTreeField
```

## Parent-Child Mode

The most common and straightforward mode for hierarchical data using traditional foreign key relationships.

### Basic Table Structure

```sql
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES categories(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sort_order INTEGER DEFAULT 0
);

-- Indexes for performance
CREATE INDEX idx_categories_parent_id ON categories(parent_id);
CREATE INDEX idx_categories_name ON categories(name);
```

### Model Definition

```python
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from pgappforge import Model

class Category(Model):
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    parent_id = Column(Integer, ForeignKey('categories.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    sort_order = Column(Integer, default=0)
    
    def __repr__(self):
        return f'<Category {self.name}>'
```

### Form Integration

```python
from flask_wtf import FlaskForm
from pgappforge.models.postgresql import PostgreSQLTreeField

class CategoryManagementForm(FlaskForm):
    """Complete category hierarchy management form"""
    
    category_tree = PostgreSQLTreeField(
        'Product Categories',
        mode='parent_id',
        id_field='id',
        parent_id_field='parent_id', 
        label_field='name',
        max_depth=6,
        allow_drag_drop=True,
        allow_reorder=True,
        validation_rules={
            'min_nodes': 1,
            'max_nodes': 1000,
            'required_root': True
        }
    )
```

### View Implementation

```python
from flask import render_template, request, jsonify
from pgappforge import BaseView, expose

class CategoryManagerView(BaseView):
    route_base = '/categories'
    
    @expose('/')
    def list(self):
        """Main category management interface"""
        form = CategoryManagementForm()
        
        if request.method == 'POST' and form.validate():
            # Process tree data
            tree_data = form.category_tree.data
            self.update_category_hierarchy(tree_data)
            
        # Load existing data
        categories = self.get_category_hierarchy()
        form.category_tree.data = categories
        
        return render_template('categories/manage.html', form=form)
    
    def get_category_hierarchy(self):
        """Retrieve categories in parent-child format"""
        categories = db.session.query(Category).all()
        return [{
            'id': cat.id,
            'name': cat.name,
            'parent_id': cat.parent_id
        } for cat in categories]
    
    def update_category_hierarchy(self, tree_data):
        """Update category hierarchy from tree widget data"""
        if not isinstance(tree_data, list):
            return
        
        for item in tree_data:
            category = Category.query.get(item.get('id'))
            if category:
                category.name = item.get('name', category.name)
                category.parent_id = item.get('parent_id')
            else:
                # Create new category
                category = Category(
                    name=item.get('name', 'New Category'),
                    parent_id=item.get('parent_id')
                )
                db.session.add(category)
        
        db.session.commit()
```

### Sample Data Structure

```python
# Input data format expected by the widget
sample_categories = [
    {"id": 1, "name": "Electronics", "parent_id": None},
    {"id": 2, "name": "Computers", "parent_id": 1},
    {"id": 3, "name": "Laptops", "parent_id": 2},
    {"id": 4, "name": "Gaming Laptops", "parent_id": 3},
    {"id": 5, "name": "Business Laptops", "parent_id": 3},
    {"id": 6, "name": "Tablets", "parent_id": 2},
    {"id": 7, "name": "Smartphones", "parent_id": 1},
    {"id": 8, "name": "Android Phones", "parent_id": 7},
    {"id": 9, "name": "iPhones", "parent_id": 7}
]
```

### Advanced Querying

```sql
-- Find all descendants of a category
WITH RECURSIVE category_tree AS (
    -- Root categories or specific parent
    SELECT id, name, parent_id, 1 as level, name::text as path
    FROM categories 
    WHERE parent_id IS NULL  -- or parent_id = :specific_id
    
    UNION ALL
    
    -- Recursive part
    SELECT c.id, c.name, c.parent_id, ct.level + 1, 
           (ct.path || ' > ' || c.name)::text as path
    FROM categories c
    JOIN category_tree ct ON c.parent_id = ct.id
    WHERE ct.level < 10  -- Prevent infinite recursion
)
SELECT * FROM category_tree ORDER BY level, path;

-- Find all ancestors of a specific category
WITH RECURSIVE ancestors AS (
    SELECT id, name, parent_id, 0 as level
    FROM categories
    WHERE id = :category_id
    
    UNION ALL
    
    SELECT c.id, c.name, c.parent_id, a.level + 1
    FROM categories c
    JOIN ancestors a ON c.id = a.parent_id
)
SELECT * FROM ancestors WHERE id != :category_id ORDER BY level DESC;

-- Get tree statistics
SELECT 
    COUNT(*) as total_categories,
    COUNT(*) FILTER (WHERE parent_id IS NULL) as root_categories,
    MAX(level) as max_depth
FROM (
    WITH RECURSIVE depth_calc AS (
        SELECT id, parent_id, 1 as level FROM categories WHERE parent_id IS NULL
        UNION ALL
        SELECT c.id, c.parent_id, d.level + 1 
        FROM categories c JOIN depth_calc d ON c.parent_id = d.id
    )
    SELECT * FROM depth_calc
) t;
```

## LTREE Mode

For PostgreSQL LTREE extension providing materialized path hierarchy with advanced querying capabilities.

### Table Structure

```sql
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    org_path LTREE NOT NULL,
    manager_id INTEGER,
    budget DECIMAL(12,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Essential LTREE indexes
CREATE INDEX idx_departments_path_gist ON departments USING GIST (org_path);
CREATE INDEX idx_departments_path_btree ON departments USING BTREE (org_path);

-- For pattern matching queries
CREATE INDEX idx_departments_path_pattern ON departments USING BTREE (org_path text_pattern_ops);
```

### Model Definition

```python
from pgappforge.models.postgresql import LTREE

class Department(Model):
    __tablename__ = 'departments'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    org_path = Column(LTREE, nullable=False)
    manager_id = Column(Integer)
    budget = Column(Numeric(12, 2))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Department {self.name} ({self.org_path})>'
    
    @property
    def level(self):
        """Calculate organizational level"""
        return len(str(self.org_path).split('.'))
    
    @property
    def parent_path(self):
        """Get parent path"""
        parts = str(self.org_path).split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None
    
    def get_children(self):
        """Get direct children"""
        pattern = f"{self.org_path}.*{{1}}"
        return Department.query.filter(Department.org_path.op('~')(pattern)).all()
    
    def get_descendants(self):
        """Get all descendants"""
        return Department.query.filter(Department.org_path.op('<@')(self.org_path)).all()
    
    def get_ancestors(self):
        """Get all ancestors"""
        return Department.query.filter(self.org_path.op('~')(Department.org_path)).all()
```

### LTREE Form Configuration

```python
class OrganizationForm(FlaskForm):
    org_structure = PostgreSQLTreeField(
        'Organization Structure',
        mode='ltree',
        max_depth=8,
        path_separator='.',
        validation_rules={
            'min_nodes': 1,
            'max_nodes': 500,
            'required_root': True
        }
    )
```

### LTREE Path Examples

```
# Organizational hierarchy
company
company.engineering  
company.engineering.backend
company.engineering.backend.database
company.engineering.backend.api
company.engineering.frontend
company.engineering.frontend.react
company.engineering.frontend.vue
company.marketing
company.marketing.digital
company.marketing.content
company.sales
company.sales.enterprise
company.sales.smb

# Geographic hierarchy  
world
world.americas
world.americas.north
world.americas.north.usa
world.americas.north.usa.california
world.americas.north.usa.texas
world.americas.south
world.americas.south.brazil
world.europe
world.europe.western
world.europe.western.germany
world.europe.western.france
world.asia
world.asia.east
world.asia.east.china
world.asia.east.japan
```

### LTREE Advanced Queries

```sql
-- Find all engineering departments
SELECT * FROM departments WHERE org_path ~ '*.engineering.*';

-- Find direct children of engineering
SELECT * FROM departments WHERE org_path ~ 'company.engineering.*{1}';

-- Find all departments under engineering (descendants)
SELECT * FROM departments WHERE org_path <@ 'company.engineering';

-- Find all ancestors of a specific department
SELECT * FROM departments WHERE 'company.engineering.backend.database' ~ org_path;

-- Calculate depth of each department
SELECT name, org_path, nlevel(org_path) as depth FROM departments;

-- Find departments at specific depth level
SELECT * FROM departments WHERE nlevel(org_path) = 3;

-- Find sibling departments
SELECT * FROM departments 
WHERE org_path ~ (
    SELECT subpath(org_path, 0, nlevel(org_path)-1) || '.*{1}'::lquery
    FROM departments WHERE id = :dept_id
) AND id != :dept_id;

-- Get department hierarchy with levels
SELECT 
    name,
    org_path,
    nlevel(org_path) as level,
    subpath(org_path, 0, 1)::text as division,
    subpath(org_path, -1, 1)::text as department
FROM departments 
ORDER BY org_path;

-- Text search with hierarchy context
SELECT 
    name, 
    org_path,
    ts_rank_cd(to_tsvector('english', name), plainto_tsquery('database')) as rank
FROM departments 
WHERE to_tsvector('english', name) @@ plainto_tsquery('database')
    AND org_path <@ 'company.engineering'
ORDER BY rank DESC;
```

## Widget Configuration

### Complete Configuration Options

```python
tree_widget = PostgreSQLTreeWidget(
    # Mode selection
    mode='parent_id',                    # 'parent_id' or 'ltree'
    
    # Field mappings (for parent_id mode)
    id_field='id',                       # Primary key field name
    parent_id_field='parent_id',         # Parent reference field  
    label_field='name',                  # Display field name
    
    # LTREE specific
    path_separator='.',                  # Path separator for LTREE mode
    
    # Tree constraints
    max_depth=10,                        # Maximum tree depth
    
    # Interactive features
    allow_reorder=True,                  # Enable node reordering
    allow_drag_drop=True,                # Enable drag-and-drop
    
    # Custom templates
    node_template='''
        <div class="custom-node">
            <span class="node-icon {{icon_class}}"></span>
            <span class="node-label">{{label}}</span>
            <span class="node-actions">{{actions}}</span>
        </div>
    ''',
    
    # Validation rules
    validation_rules={
        'min_nodes': 1,                  # Minimum nodes required
        'max_nodes': 1000,               # Maximum nodes allowed
        'required_root': True,           # Require at least one root
        'max_children_per_node': 50,     # Max children per node
        'allowed_characters': r'^[a-zA-Z0-9\s\-_]+$',  # Label validation regex
        'reserved_names': ['root', 'admin', 'system']   # Forbidden names
    }
)
```

### Field Integration Patterns

```python
# Simple integration
class MyForm(FlaskForm):
    tree_data = PostgreSQLTreeField('Hierarchy')

# Advanced integration with custom validation
class AdvancedForm(FlaskForm):
    tree_data = PostgreSQLTreeField(
        'Complex Hierarchy',
        mode='parent_id',
        validators=[
            DataRequired(),
            Length(min=1, message="At least one node required"),
            custom_tree_validator
        ]
    )
    
    def validate_tree_data(self, field):
        """Custom validation example"""
        if not field.data:
            raise ValidationError("Tree cannot be empty")
        
        # Check for business logic constraints
        node_count = len(field.data) if isinstance(field.data, list) else 0
        if node_count > 100:
            raise ValidationError("Tree cannot exceed 100 nodes")
        
        # Validate specific business rules
        root_nodes = [n for n in field.data if not n.get('parent_id')]
        if len(root_nodes) != 1:
            raise ValidationError("Tree must have exactly one root node")

def custom_tree_validator(form, field):
    """Reusable custom validator"""
    # Implement your specific validation logic
    pass
```

## Interactive Features

### Node Operations

#### Add Node
- **Trigger**: Click "Add Child" button on any node
- **Behavior**: Prompts for node name, validates against rules
- **Constraints**: Respects max_depth settings
- **Animation**: Smooth slide-in animation for new nodes

#### Edit Node  
- **Trigger**: Click edit button or double-click node label
- **Behavior**: In-place text editing with validation
- **Auto-save**: Saves on blur or Enter key
- **Rollback**: Reverts on Escape or invalid input

#### Delete Node
- **Trigger**: Click delete button  
- **Confirmation**: Shows confirmation dialog
- **Cascade**: Optionally deletes all child nodes
- **Animation**: Fade-out animation before removal

#### Drag & Drop
- **Visual Feedback**: Shows drop zones and drag indicators
- **Validation**: Prevents circular references and depth violations
- **Ghost Image**: Shows dragged node preview
- **Constraints**: Respects parent-child relationships

### Search & Filter

```javascript
// Search functionality 
const widget = window.treeWidget_myfield;

// Simple text search
widget.searchNodes('engineering');

// Advanced search options
widget.searchNodes('backend', {
    caseSensitive: false,
    searchFields: ['name', 'description'],
    expandMatches: true,
    highlightMatches: true
});

// Clear search
widget.clearSearch();

// Custom search filters
widget.addSearchFilter('department', function(node, searchTerm) {
    return node.path && node.path.includes(searchTerm);
});
```

### Keyboard Navigation

```
Tab/Shift+Tab    - Navigate between nodes
Enter            - Edit selected node  
Space            - Toggle node expansion
Delete           - Delete selected node (with confirmation)
Escape           - Cancel current operation
Arrow Keys       - Navigate tree structure
Ctrl+A           - Select all nodes
Ctrl+C           - Copy selected nodes
Ctrl+V           - Paste nodes
F2               - Rename selected node
```

## Import/Export Functionality

### Supported Formats

#### JSON Hierarchical
```json
{
  "electronics": {
    "label": "Electronics", 
    "children": {
      "computers": {
        "label": "Computers",
        "children": {
          "laptops": {
            "label": "Laptops",
            "children": {}
          }
        }
      }
    }
  }
}
```

#### JSON Parent-Child Array
```json
[
  {"id": 1, "name": "Electronics", "parent_id": null},
  {"id": 2, "name": "Computers", "parent_id": 1},
  {"id": 3, "name": "Laptops", "parent_id": 2}
]
```

#### CSV Format
```csv
id,name,parent_id,description
1,"Electronics",,""
2,"Computers",1,"Computer equipment"
3,"Laptops",2,"Portable computers"
4,"Gaming Laptops",3,"High-performance gaming"
```

#### LTREE Paths
```
electronics
electronics.computers
electronics.computers.laptops
electronics.computers.laptops.gaming
electronics.computers.tablets
electronics.smartphones
```

#### SQL INSERT Statements
```sql
-- Generated INSERT statements
INSERT INTO categories (id, name, parent_id) VALUES
(1, 'Electronics', NULL),
(2, 'Computers', 1),
(3, 'Laptops', 2),
(4, 'Gaming Laptops', 3);
```

### Import/Export JavaScript API

```javascript
const treeWidget = window.treeWidget_myfield;

// Export operations
const jsonData = treeWidget.exportToFormat('json');
const csvData = treeWidget.exportToFormat('csv');
const sqlData = treeWidget.exportToFormat('sql_insert');

// Import operations  
treeWidget.importFromData(jsonData, 'json', {
    merge: false,           // Replace existing data
    validate: true,         // Validate before import
    repair: true,          // Auto-repair issues
    preserveIds: false     // Generate new IDs
});

// Bulk operations
treeWidget.exportToFile('categories.json', 'json');
treeWidget.importFromFile(fileInput.files[0], {
    format: 'auto',        // Auto-detect format
    preview: true          // Show preview before import
});

// Custom format handlers
treeWidget.addExportHandler('xml', function(treeData) {
    // Convert treeData to XML format
    return xmlString;
});

treeWidget.addImportHandler('yaml', function(yamlData) {
    // Parse YAML and return tree structure
    return parsedData;
});
```

## Validation & Tree Repair

### Built-in Validation

#### Structure Validation
- **Depth Limits**: Enforces maximum tree depth
- **Node Limits**: Validates min/max node counts
- **Required Roots**: Ensures root node presence
- **Circular References**: Prevents nodes from being ancestors of themselves

#### Data Validation  
- **Duplicate IDs**: Detects duplicate identifiers in parent-child mode
- **Orphaned Nodes**: Identifies nodes with invalid parent references
- **Path Format**: Validates LTREE path syntax
- **Field Requirements**: Ensures required fields are present

#### Real-time Validation
```javascript
// Validation triggers
- On node creation/modification
- During drag-and-drop operations  
- Before save operations
- On import/export

// Validation feedback
- Visual indicators (red borders, warning icons)
- Tooltip error messages
- Validation summary panel
- Console logging for debugging
```

### Tree Repair Functionality

```javascript
const treeWidget = window.treeWidget_myfield;

// Manual repair trigger
treeWidget.repairTree();

// Auto-repair options
treeWidget.configure({
    autoRepair: {
        enabled: true,
        onImport: true,          // Repair during imports
        onValidation: false,     // Repair during validation
        orphanStrategy: 'move_to_root',  // 'move_to_root', 'delete', 'ignore'
        depthStrategy: 'truncate',       // 'truncate', 'flatten', 'ignore'
        duplicateStrategy: 'rename'      // 'rename', 'merge', 'delete'
    }
});

// Repair strategies
const repairStrategies = {
    orphans: {
        'move_to_root': 'Move orphaned nodes to root level',
        'delete': 'Delete orphaned nodes',
        'assign_parent': 'Assign to nearest valid parent',
        'ignore': 'Leave as-is with warning'
    },
    
    depth_violations: {
        'truncate': 'Move deep nodes to max allowed level', 
        'flatten': 'Flatten deep branches',
        'split': 'Split into multiple trees'
    },
    
    duplicates: {
        'rename': 'Append suffix to duplicate names',
        'merge': 'Merge duplicate nodes',
        'delete': 'Delete duplicate entries'
    }
};

// Custom repair handlers
treeWidget.addRepairHandler('custom_rule', function(treeData, issues) {
    // Implement custom repair logic
    return repairedTreeData;
});
```

### Validation Rules Configuration

```python
validation_rules = {
    # Structure constraints
    'min_nodes': 1,
    'max_nodes': 1000,  
    'max_depth': 8,
    'max_children_per_node': 25,
    'required_root': True,
    'allow_multiple_roots': False,
    
    # Data constraints
    'min_label_length': 1,
    'max_label_length': 100,
    'allowed_characters': r'^[a-zA-Z0-9\s\-_\.]+$',
    'reserved_names': ['root', 'admin', 'system', 'null'],
    'case_sensitive': False,
    'unique_labels': False,
    'unique_paths': True,
    
    # Business rules
    'require_description': False,
    'max_name_words': 10,
    'forbidden_patterns': [r'test.*', r'.*temp.*'],
    
    # Custom validation function
    'custom_validator': lambda node: validate_business_logic(node)
}
```

## JavaScript API

### Core Widget API

```javascript
// Widget initialization
const treeWidget = window.treeWidget_myfield;

// Tree manipulation
treeWidget.addRootNode('New Root');
treeWidget.addChildNode(parentId, 'Child Name');
treeWidget.deleteNode(nodeId);
treeWidget.moveNode(nodeId, newParentId);
treeWidget.renameNode(nodeId, 'New Name');

// Tree navigation  
treeWidget.expandAll();
treeWidget.collapseAll();
treeWidget.expandNode(nodeId);
treeWidget.collapseNode(nodeId);
treeWidget.selectNode(nodeId);
treeWidget.scrollToNode(nodeId);

// Data operations
const treeData = treeWidget.getTreeData();
treeWidget.setTreeData(newData);
treeWidget.clearTree();
treeWidget.refresh();

// Validation and repair
const isValid = treeWidget.validateTree();
const issues = treeWidget.getValidationIssues();
treeWidget.repairTree();

// Event handling
treeWidget.on('nodeAdded', function(node) {
    console.log('Node added:', node);
});

treeWidget.on('nodeDeleted', function(nodeId) {
    console.log('Node deleted:', nodeId);
});

treeWidget.on('treeMoved', function(nodeId, oldParentId, newParentId) {
    console.log('Node moved:', nodeId);
});

treeWidget.on('treeChanged', function(changeType, data) {
    console.log('Tree changed:', changeType, data);
});

// Configuration
treeWidget.configure({
    maxDepth: 10,
    allowDragDrop: true,
    autoSave: true,
    animations: true
});

// Statistics
const stats = treeWidget.getStatistics();
console.log('Total nodes:', stats.nodeCount);
console.log('Max depth:', stats.maxDepth);
console.log('Root nodes:', stats.rootCount);
```

### Event System

```javascript
// Available events
const events = [
    'nodeAdded',           // New node created
    'nodeDeleted',         // Node removed  
    'nodeRenamed',         // Node label changed
    'nodeMoved',           // Node parent changed
    'nodeSelected',        // Node selection changed
    'nodeExpanded',        // Node expanded
    'nodeCollapsed',       // Node collapsed
    'treeLoaded',          // Tree data loaded
    'treeChanged',         // Any tree modification
    'validationFailed',    // Validation errors
    'repairCompleted',     // Tree repair finished
    'importStarted',       // Import operation started
    'importCompleted',     // Import operation finished
    'exportStarted',       // Export operation started  
    'exportCompleted'      // Export operation finished
];

// Event registration
treeWidget.on('nodeAdded', function(event) {
    console.log('Added node:', event.node);
    console.log('Parent:', event.parentId);
    console.log('Position:', event.position);
});

// Multiple event handlers
treeWidget.on(['nodeAdded', 'nodeDeleted'], function(event) {
    updateTreeStatistics();
});

// One-time event handlers  
treeWidget.once('treeLoaded', function(event) {
    console.log('Tree loaded for first time');
});

// Event removal
treeWidget.off('nodeAdded', handlerFunction);
treeWidget.off('nodeAdded');  // Remove all handlers
```

### Advanced API Usage

```javascript
// Batch operations
treeWidget.startBatch();  // Suspend events/updates
treeWidget.addNode(parentId, 'Node 1');
treeWidget.addNode(parentId, 'Node 2'); 
treeWidget.addNode(parentId, 'Node 3');
treeWidget.endBatch();    // Commit changes, fire events

// Transaction support
treeWidget.transaction(function() {
    // All operations are atomic
    treeWidget.moveNode(1, 5);
    treeWidget.renameNode(2, 'Updated');
    // If any operation fails, all are rolled back
});

// Async operations
async function loadTreeData() {
    const data = await fetch('/api/tree-data').then(r => r.json());
    treeWidget.setTreeData(data);
}

// Custom node rendering
treeWidget.setNodeRenderer(function(node, element) {
    element.addClass('custom-node');
    element.find('.node-label').append(`<span class="node-id">#${node.id}</span>`);
    
    // Add custom actions
    const actions = element.find('.node-actions');
    actions.append('<button class="btn-custom">Custom Action</button>');
});

// Plugin system
treeWidget.use({
    name: 'customPlugin',
    init: function(widget) {
        widget.customMethod = function() {
            console.log('Custom functionality');
        };
    }
});
```

## Styling & Customization

### CSS Classes Reference

```css
/* Container classes */
.postgresql-tree-widget          /* Main widget container */
.tree-container                  /* Tree display area */
.tree-root                      /* Root tree element */
.tree-empty                     /* Empty state display */
.tree-controls                  /* Control button area */
.tree-info                      /* Status/info area */

/* Node classes */  
.tree-node                      /* Individual tree node */
.tree-node.selected            /* Selected node state */
.tree-node.dragging            /* Node being dragged */
.tree-node.drag-over           /* Drop target highlight */
.tree-node.invalid             /* Validation error state */
.tree-node.orphaned            /* Orphaned node state */
.tree-node.newly-added         /* Animation class for new nodes */
.tree-node.being-deleted       /* Animation class for deletion */

/* Node content */
.node-content                   /* Node content wrapper */  
.node-content.root              /* Root node styling */
.node-toggle                    /* Expand/collapse button */
.node-icon                      /* Node icon */
.node-label                     /* Node text label */
.node-actions                   /* Action buttons container */
.node-children                  /* Children container */

/* States */
.node-toggle.expanded           /* Expanded state */
.node-toggle.no-children        /* Leaf node state */
.node-children.collapsed        /* Collapsed children */

/* Search */
.tree-search                    /* Search input area */
.tree-node.search-highlight     /* Search result highlight */
.tree-node.search-hidden        /* Filtered out nodes */

/* Modal */
.tree-import-export-modal       /* Import/export modal */
.import-preview-area            /* Import preview section */
```

### Custom Styling Examples

```css
/* Custom color scheme */
.postgresql-tree-widget {
    --tree-primary: #2563eb;
    --tree-secondary: #64748b;  
    --tree-success: #059669;
    --tree-warning: #d97706;
    --tree-danger: #dc2626;
    --tree-background: #f8fafc;
    --tree-border: #e2e8f0;
}

/* Modern flat design */
.postgresql-tree-widget .node-content {
    background: linear-gradient(145deg, #ffffff, #f1f5f9);
    border: 1px solid var(--tree-border);
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    transition: all 0.2s ease;
}

.postgresql-tree-widget .node-content:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    border-color: var(--tree-primary);
}

/* Dark theme */
.postgresql-tree-widget.dark-theme {
    background: #1a202c;
    color: #e2e8f0;
}

.dark-theme .node-content {
    background: #2d3748;
    border-color: #4a5568;
    color: #e2e8f0;
}

.dark-theme .node-content:hover {
    background: #4a5568;
    border-color: #63b3ed;
}

/* Custom icons */
.node-icon.department { color: #3b82f6; }
.node-icon.team { color: #10b981; }
.node-icon.person { color: #f59e0b; }

/* Compact layout */
.postgresql-tree-widget.compact .node-content {
    padding: 4px 8px;
    font-size: 13px;
}

.postgresql-tree-widget.compact .node-children {
    margin-left: 20px;
    padding-left: 12px;
}

/* Custom animations */
@keyframes nodeSlideIn {
    from {
        opacity: 0;
        transform: translateX(-20px) scale(0.95);
    }
    to {
        opacity: 1;
        transform: translateX(0) scale(1);
    }
}

.tree-node.newly-added {
    animation: nodeSlideIn 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Template Customization

```python
# Custom node template
custom_template = '''
<div class="custom-tree-node" data-id="{{id}}" data-level="{{level}}">
    <div class="node-header">
        <span class="node-toggle {{toggle_class}}">
            <i class="fas {{toggle_icon}}"></i>
        </span>
        
        <div class="node-info">
            <span class="node-icon {{node_type}}">
                <i class="fas {{type_icon}}"></i>
            </span>
            <span class="node-title" contenteditable="true">{{label}}</span>
            <span class="node-meta">{{description}}</span>
        </div>
        
        <div class="node-actions">
            <div class="btn-group btn-group-xs">
                <button class="btn btn-default node-add" title="Add Child">
                    <i class="fas fa-plus"></i>
                </button>
                <button class="btn btn-info node-edit" title="Edit">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn btn-warning node-move" title="Move">
                    <i class="fas fa-arrows-alt"></i>
                </button>
                <button class="btn btn-danger node-delete" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    </div>
    
    <div class="node-children {{children_class}}"></div>
</div>
'''

# Apply custom template
widget = PostgreSQLTreeWidget(
    node_template=custom_template,
    template_context={
        'toggle_class': 'fa-chevron-right',
        'toggle_icon': 'fa-chevron-right',
        'node_type': 'department',
        'type_icon': 'fa-building'
    }
)
```

## Performance Considerations

### Database Optimization

```sql
-- Parent-child table indexes
CREATE INDEX CONCURRENTLY idx_categories_parent_id ON categories(parent_id);
CREATE INDEX CONCURRENTLY idx_categories_name ON categories(name);
CREATE INDEX CONCURRENTLY idx_categories_path ON categories USING GIN(to_tsvector('english', name));

-- LTREE indexes
CREATE INDEX CONCURRENTLY idx_departments_path_gist ON departments USING GIST(org_path);
CREATE INDEX CONCURRENTLY idx_departments_path_btree ON departments(org_path);

-- Partial indexes for active records
CREATE INDEX CONCURRENTLY idx_categories_active_tree 
    ON categories(parent_id, name) WHERE active = true;

-- Composite indexes for common queries  
CREATE INDEX CONCURRENTLY idx_categories_parent_sort 
    ON categories(parent_id, sort_order, name);
```

### JavaScript Performance

```javascript
// Virtualization for large trees
treeWidget.configure({
    virtualization: {
        enabled: true,
        itemHeight: 32,           // Fixed height per node
        windowSize: 50,           // Visible items
        bufferSize: 10,           // Off-screen buffer
        threshold: 1000           // Enable when > 1000 nodes
    },
    
    // Lazy loading
    lazyLoading: {
        enabled: true,
        chunkSize: 100,           // Load 100 nodes at a time
        trigger: 'scroll',        // 'scroll' or 'expand'
        preloadDepth: 2           // Preload 2 levels deep
    },
    
    // Performance optimizations
    debounceSearch: 300,          // Debounce search input
    batchUpdates: true,           // Batch DOM updates
    cacheRendering: true,         // Cache rendered nodes
    minimizeReflows: true         // Optimize DOM operations
});

// Memory management
treeWidget.dispose();  // Clean up event listeners and DOM
```

### Large Dataset Strategies

```python
# Pagination approach
class TreeDataView(BaseView):
    def get_tree_data(self, parent_id=None, limit=100):
        """Load tree data in chunks"""
        query = Category.query
        
        if parent_id:
            query = query.filter(Category.parent_id == parent_id)
        else:
            query = query.filter(Category.parent_id.is_(None))
        
        return query.limit(limit).all()
    
    @expose('/tree-data/<int:parent_id>')
    def tree_data(self, parent_id=None):
        """AJAX endpoint for tree data"""
        nodes = self.get_tree_data(parent_id)
        return jsonify([{
            'id': node.id,
            'name': node.name,
            'parent_id': node.parent_id,
            'has_children': self.has_children(node.id)
        } for node in nodes])
    
    def has_children(self, node_id):
        """Check if node has children without loading them"""
        return db.session.query(
            Category.query.filter(Category.parent_id == node_id).exists()
        ).scalar()

# Caching strategy
from flask_caching import Cache

cache = Cache(config={'CACHE_TYPE': 'redis'})

@cache.memoize(timeout=300)  # Cache for 5 minutes
def get_cached_tree_data():
    """Cache entire tree structure"""
    return build_tree_structure()

# Background processing
from celery import Celery

@celery.task
def rebuild_tree_cache():
    """Background task to rebuild tree cache"""
    tree_data = build_tree_structure()
    cache.set('tree_data', tree_data, timeout=3600)
    return True
```

## Complete Examples

### Example 1: E-commerce Category Management

```python
# models.py
from pgappforge import Model
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, DateTime, Numeric
from datetime import datetime

class ProductCategory(Model):
    """E-commerce product categories with hierarchical structure"""
    __tablename__ = 'product_categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    parent_id = Column(Integer, ForeignKey('product_categories.id'))
    slug = Column(String(100), unique=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # SEO fields
    meta_title = Column(String(200))
    meta_description = Column(Text)
    
    def __repr__(self):
        return f'<ProductCategory {self.name}>'
    
    @property
    def full_path(self):
        """Get full category path for breadcrumbs"""
        path = [self.name]
        current = self
        while current.parent_id:
            parent = ProductCategory.query.get(current.parent_id)
            if parent:
                path.insert(0, parent.name)
                current = parent
            else:
                break
        return ' > '.join(path)

# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Length
from pgappforge.models.postgresql import PostgreSQLTreeField

class CategoryManagementForm(FlaskForm):
    """Complete e-commerce category management"""
    
    category_tree = PostgreSQLTreeField(
        'Product Categories',
        mode='parent_id',
        id_field='id',
        parent_id_field='parent_id',
        label_field='name',
        max_depth=6,
        allow_drag_drop=True,
        validation_rules={
            'min_nodes': 1,
            'max_nodes': 500,
            'required_root': True,
            'max_label_length': 100,
            'reserved_names': ['root', 'admin', 'system']
        }
    )

# views.py
from flask import render_template, request, jsonify, flash
from pgappforge import BaseView, expose, has_access
from .models import ProductCategory
from .forms import CategoryManagementForm

class CategoryManagerView(BaseView):
    route_base = '/categories'
    default_view = 'list'
    
    @expose('/')
    @has_access
    def list(self):
        """Main category management interface"""
        form = CategoryManagementForm()
        
        if request.method == 'POST' and form.validate():
            try:
                self.update_category_hierarchy(form.category_tree.data)
                flash('Categories updated successfully!', 'success')
            except Exception as e:
                flash(f'Error updating categories: {str(e)}', 'error')
                
        # Load current categories
        categories = self.get_category_hierarchy()
        form.category_tree.data = categories
        
        return render_template(
            'categories/manage.html', 
            form=form,
            stats=self.get_category_stats()
        )
    
    @expose('/api/categories')
    def api_categories(self):
        """JSON API for category data"""
        categories = self.get_category_hierarchy()
        return jsonify({
            'data': categories,
            'count': len(categories)
        })
    
    def get_category_hierarchy(self):
        """Retrieve categories in parent-child format"""
        categories = db.session.query(ProductCategory).filter(
            ProductCategory.is_active == True
        ).order_by(ProductCategory.sort_order, ProductCategory.name).all()
        
        return [{
            'id': cat.id,
            'name': cat.name,
            'parent_id': cat.parent_id,
            'description': cat.description,
            'slug': cat.slug,
            'sort_order': cat.sort_order
        } for cat in categories]
    
    def update_category_hierarchy(self, tree_data):
        """Update category hierarchy from tree widget"""
        if not isinstance(tree_data, list):
            return
            
        # Start transaction
        try:
            for item in tree_data:
                category_id = item.get('id')
                
                if category_id:
                    # Update existing category
                    category = ProductCategory.query.get(category_id)
                    if category:
                        category.name = item.get('name', category.name)
                        category.parent_id = item.get('parent_id')
                        category.updated_at = datetime.utcnow()
                else:
                    # Create new category
                    category = ProductCategory(
                        name=item.get('name', 'New Category'),
                        parent_id=item.get('parent_id'),
                        slug=self.generate_slug(item.get('name', 'new-category'))
                    )
                    db.session.add(category)
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            raise e
    
    def generate_slug(self, name):
        """Generate URL-friendly slug from name"""
        import re
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')
    
    def get_category_stats(self):
        """Get category statistics"""
        total = ProductCategory.query.count()
        active = ProductCategory.query.filter(ProductCategory.is_active == True).count()
        roots = ProductCategory.query.filter(ProductCategory.parent_id.is_(None)).count()
        
        return {
            'total': total,
            'active': active,
            'inactive': total - active,
            'roots': roots
        }
```

### Example 2: Organizational Chart (LTREE)

```python
# models.py
from pgappforge.models.postgresql import LTREE
from sqlalchemy import Column, Integer, String, Numeric, Boolean

class Department(Model):
    """Organizational departments using LTREE"""
    __tablename__ = 'departments'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    org_path = Column(LTREE, nullable=False, unique=True)
    department_code = Column(String(20), unique=True)
    manager_id = Column(Integer)
    budget = Column(Numeric(12, 2))
    employee_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    
    def __repr__(self):
        return f'<Department {self.name} ({self.org_path})>'
    
    @property
    def level(self):
        """Get organizational level"""
        return len(str(self.org_path).split('.'))
    
    @property
    def parent_path(self):
        """Get parent department path"""
        parts = str(self.org_path).split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None
    
    def get_children(self):
        """Get direct child departments"""
        pattern = f"{self.org_path}.*{{1}}"
        return Department.query.filter(
            Department.org_path.op('~')(pattern),
            Department.is_active == True
        ).order_by(Department.name).all()
    
    def get_all_descendants(self):
        """Get all descendant departments"""
        return Department.query.filter(
            Department.org_path.op('<@')(self.org_path),
            Department.id != self.id
        ).all()
    
    def calculate_total_budget(self):
        """Calculate total budget including all descendants"""
        descendants = self.get_all_descendants()
        total = self.budget or 0
        for dept in descendants:
            total += dept.budget or 0
        return total

# forms.py
class OrganizationChartForm(FlaskForm):
    """Organizational structure management"""
    
    org_structure = PostgreSQLTreeField(
        'Organization Structure',
        mode='ltree',
        max_depth=8,
        path_separator='.',
        allow_drag_drop=True,
        validation_rules={
            'min_nodes': 1,
            'max_nodes': 200,
            'required_root': True,
            'max_label_length': 50
        }
    )

# views.py
class OrganizationView(BaseView):
    route_base = '/organization'
    
    @expose('/')
    def chart(self):
        """Display organization chart"""
        form = OrganizationChartForm()
        
        if request.method == 'POST' and form.validate():
            self.update_organization(form.org_structure.data)
            
        # Load organization data as LTREE paths
        departments = self.get_organization_paths()
        form.org_structure.data = departments
        
        return render_template('organization/chart.html', form=form)
    
    def get_organization_paths(self):
        """Convert departments to LTREE path format"""
        departments = Department.query.filter(
            Department.is_active == True
        ).order_by(Department.org_path).all()
        
        paths = []
        for dept in departments:
            paths.append(str(dept.org_path))
        
        return '\\n'.join(paths)
    
    def update_organization(self, ltree_data):
        """Update organization from LTREE paths"""
        if not ltree_data:
            return
            
        paths = [p.strip() for p in ltree_data.split('\\n') if p.strip()]
        
        try:
            # Clear existing inactive departments
            Department.query.update({Department.is_active: False})
            
            for path in paths:
                department = Department.query.filter(
                    Department.org_path == path
                ).first()
                
                if not department:
                    # Create new department
                    name = path.split('.')[-1].replace('_', ' ').title()
                    department = Department(
                        name=name,
                        org_path=path,
                        department_code=self.generate_dept_code(path)
                    )
                    db.session.add(department)
                
                department.is_active = True
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            raise e
    
    def generate_dept_code(self, path):
        """Generate department code from path"""
        parts = path.split('.')
        code = ''.join([p[:2].upper() for p in parts])
        return code[:20]  # Limit to 20 characters
```

### Example 3: File/Folder Structure Manager

```python
# models.py
class FileSystemNode(Model):
    """File system tree structure"""
    __tablename__ = 'filesystem_nodes'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey('filesystem_nodes.id'))
    node_type = Column(String(20), default='folder')  # 'file' or 'folder'
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100))
    file_path = Column(String(500))
    is_hidden = Column(Boolean, default=False)
    permissions = Column(String(10), default='755')
    created_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<FileSystemNode {self.name} ({self.node_type})>'
    
    @property
    def full_path(self):
        """Get full file path"""
        path_parts = []
        current = self
        
        while current:
            path_parts.insert(0, current.name)
            current = FileSystemNode.query.get(current.parent_id) if current.parent_id else None
        
        return '/'.join(path_parts)
    
    def get_size_display(self):
        """Human readable file size"""
        if self.file_size == 0:
            return '0 B'
        
        size_names = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        size = float(self.file_size)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"

# forms.py  
class FileManagerForm(FlaskForm):
    """File system management form"""
    
    file_tree = PostgreSQLTreeField(
        'File System',
        mode='parent_id',
        id_field='id', 
        parent_id_field='parent_id',
        label_field='name',
        max_depth=10,
        allow_drag_drop=True,
        node_template='''
            <div class="file-node {{node_type}}" data-id="{{id}}" data-type="{{node_type}}">
                <div class="node-content">
                    <span class="node-toggle"><i class="fa fa-chevron-right"></i></span>
                    <span class="file-icon">
                        <i class="fa {{icon_class}}"></i>
                    </span>
                    <span class="file-name" contenteditable="true">{{label}}</span>
                    <span class="file-size">{{size}}</span>
                    <div class="file-actions">
                        <button class="btn btn-xs btn-default" data-action="rename">
                            <i class="fa fa-edit"></i>
                        </button>
                        <button class="btn btn-xs btn-info" data-action="move">
                            <i class="fa fa-arrows"></i>
                        </button>
                        <button class="btn btn-xs btn-danger" data-action="delete">
                            <i class="fa fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="node-children"></div>
            </div>
        ''',
        validation_rules={
            'max_nodes': 5000,
            'max_label_length': 255,
            'forbidden_patterns': [r'[<>:"/\\|?*]']  # Invalid filename chars
        }
    )

# views.py
class FileManagerView(BaseView):
    route_base = '/files'
    
    @expose('/')
    def manager(self):
        """File manager interface"""
        form = FileManagerForm()
        
        if request.method == 'POST':
            if form.validate():
                self.update_file_structure(form.file_tree.data)
            
        # Load file system data
        files = self.get_file_tree_data()
        form.file_tree.data = files
        
        return render_template('files/manager.html', form=form)
    
    @expose('/upload', methods=['POST'])
    def upload_file(self):
        """Handle file uploads"""
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        parent_id = request.form.get('parent_id')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        try:
            # Save file and create database record
            file_node = FileSystemNode(
                name=file.filename,
                parent_id=parent_id,
                node_type='file',
                file_size=len(file.read()),
                mime_type=file.content_type or 'application/octet-stream'
            )
            
            # Save file to storage
            file_path = self.save_uploaded_file(file, file_node)
            file_node.file_path = file_path
            
            db.session.add(file_node)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'file_id': file_node.id,
                'name': file_node.name
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    def get_file_tree_data(self):
        """Get file system data for tree widget"""
        nodes = FileSystemNode.query.order_by(
            FileSystemNode.node_type.desc(),  # Folders first
            FileSystemNode.name
        ).all()
        
        return [{
            'id': node.id,
            'name': node.name,
            'parent_id': node.parent_id,
            'node_type': node.node_type,
            'size': node.get_size_display(),
            'icon_class': self.get_file_icon(node)
        } for node in nodes]
    
    def get_file_icon(self, node):
        """Get appropriate icon for file/folder"""
        if node.node_type == 'folder':
            return 'fa-folder'
        
        # File type icons based on extension
        ext = node.name.split('.')[-1].lower() if '.' in node.name else ''
        
        icon_map = {
            'pdf': 'fa-file-pdf-o',
            'doc': 'fa-file-word-o', 'docx': 'fa-file-word-o',
            'xls': 'fa-file-excel-o', 'xlsx': 'fa-file-excel-o', 
            'ppt': 'fa-file-powerpoint-o', 'pptx': 'fa-file-powerpoint-o',
            'jpg': 'fa-file-image-o', 'png': 'fa-file-image-o', 'gif': 'fa-file-image-o',
            'mp4': 'fa-file-video-o', 'avi': 'fa-file-video-o',
            'mp3': 'fa-file-audio-o', 'wav': 'fa-file-audio-o',
            'zip': 'fa-file-archive-o', 'rar': 'fa-file-archive-o',
            'txt': 'fa-file-text-o', 'md': 'fa-file-text-o',
            'py': 'fa-file-code-o', 'js': 'fa-file-code-o', 'html': 'fa-file-code-o'
        }
        
        return icon_map.get(ext, 'fa-file-o')
    
    def save_uploaded_file(self, file, file_node):
        """Save uploaded file to storage"""
        import os
        from werkzeug.utils import secure_filename
        
        filename = secure_filename(file.filename)
        upload_dir = os.path.join(current_app.root_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, f"{file_node.id}_{filename}")
        file.save(file_path)
        
        return file_path
```

### Example 4: Menu/Navigation Builder

```python
# models.py
class MenuItem(Model):
    """Website menu items with hierarchy"""
    __tablename__ = 'menu_items'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey('menu_items.id'))
    url = Column(String(500))
    icon_class = Column(String(50))
    css_class = Column(String(100))
    target = Column(String(20), default='_self')  # _self, _blank, etc.
    sort_order = Column(Integer, default=0)
    is_published = Column(Boolean, default=True)
    requires_auth = Column(Boolean, default=False)
    required_role = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<MenuItem {self.title}>'
    
    def to_dict(self, include_children=False):
        """Convert to dictionary for JSON serialization"""
        data = {
            'id': self.id,
            'title': self.title,
            'parent_id': self.parent_id,
            'url': self.url,
            'icon_class': self.icon_class,
            'target': self.target,
            'sort_order': self.sort_order
        }
        
        if include_children:
            data['children'] = [
                child.to_dict(include_children=True) 
                for child in self.get_children()
            ]
        
        return data
    
    def get_children(self):
        """Get direct children ordered by sort_order"""
        return MenuItem.query.filter(
            MenuItem.parent_id == self.id,
            MenuItem.is_published == True
        ).order_by(MenuItem.sort_order, MenuItem.title).all()

# forms.py
class MenuBuilderForm(FlaskForm):
    """Navigation menu builder"""
    
    menu_structure = PostgreSQLTreeField(
        'Navigation Menu',
        mode='parent_id',
        id_field='id',
        parent_id_field='parent_id', 
        label_field='title',
        max_depth=5,
        allow_drag_drop=True,
        node_template='''
            <div class="menu-node" data-id="{{id}}" data-url="{{url}}">
                <div class="node-content">
                    <span class="node-toggle"><i class="fa fa-chevron-right"></i></span>
                    <span class="menu-icon">
                        <i class="{{icon_class}} fa-fw"></i>
                    </span>
                    <div class="menu-details">
                        <div class="menu-title" contenteditable="true">{{title}}</div>
                        <div class="menu-url">{{url}}</div>
                    </div>
                    <div class="menu-actions">
                        <button class="btn btn-xs btn-info" data-action="edit">
                            <i class="fa fa-edit"></i>
                        </button>
                        <button class="btn btn-xs btn-success" data-action="add-child">
                            <i class="fa fa-plus"></i>
                        </button>
                        <button class="btn btn-xs btn-danger" data-action="delete">
                            <i class="fa fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="node-children"></div>
            </div>
        ''',
        validation_rules={
            'max_nodes': 100,
            'max_depth': 5,
            'required_root': False
        }
    )
    
    # Additional menu item fields
    title = StringField('Title', validators=[DataRequired(), Length(max=100)])
    url = StringField('URL', validators=[Length(max=500)])  
    icon_class = StringField('Icon Class')
    target = SelectField('Target', choices=[
        ('_self', 'Same Window'),
        ('_blank', 'New Window'),
        ('_parent', 'Parent Frame'),
        ('_top', 'Top Frame')
    ], default='_self')
    requires_auth = BooleanField('Requires Authentication')
    required_role = StringField('Required Role')

# views.py
class MenuBuilderView(BaseView):
    route_base = '/menu-builder'
    
    @expose('/')
    def builder(self):
        """Menu builder interface"""  
        form = MenuBuilderForm()
        
        if request.method == 'POST' and form.validate():
            self.update_menu_structure(form.menu_structure.data)
            flash('Menu updated successfully!', 'success')
            
        # Load current menu
        menu_items = self.get_menu_tree_data()
        form.menu_structure.data = menu_items
        
        return render_template('menu/builder.html', form=form)
    
    @expose('/preview')
    def preview(self):
        """Preview generated menu"""
        menu_html = self.generate_menu_html()
        return render_template('menu/preview.html', menu_html=menu_html)
    
    def get_menu_tree_data(self):
        """Get menu items for tree widget"""
        items = MenuItem.query.filter(
            MenuItem.is_published == True
        ).order_by(MenuItem.sort_order, MenuItem.title).all()
        
        return [{
            'id': item.id,
            'title': item.title,
            'parent_id': item.parent_id,
            'url': item.url or '#',
            'icon_class': item.icon_class or 'fa-link'
        } for item in items]
    
    def update_menu_structure(self, tree_data):
        """Update menu from tree widget data"""
        if not isinstance(tree_data, list):
            return
            
        try:
            for item_data in tree_data:
                item_id = item_data.get('id')
                
                if item_id:
                    # Update existing item
                    menu_item = MenuItem.query.get(item_id)
                    if menu_item:
                        menu_item.title = item_data.get('title', menu_item.title)
                        menu_item.parent_id = item_data.get('parent_id')
                else:
                    # Create new item
                    menu_item = MenuItem(
                        title=item_data.get('title', 'New Menu Item'),
                        parent_id=item_data.get('parent_id'),
                        url='#'
                    )
                    db.session.add(menu_item)
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            raise e
    
    def generate_menu_html(self):
        """Generate HTML for menu preview"""
        root_items = MenuItem.query.filter(
            MenuItem.parent_id.is_(None),
            MenuItem.is_published == True
        ).order_by(MenuItem.sort_order, MenuItem.title).all()
        
        return self._render_menu_items(root_items)
    
    def _render_menu_items(self, items, level=0):
        """Recursively render menu items as HTML"""
        if not items:
            return ''
        
        html = '<ul class="nav navbar-nav">' if level == 0 else '<ul class="dropdown-menu">'
        
        for item in items:
            children = item.get_children()
            has_children = len(children) > 0
            
            css_classes = ['nav-item']
            if has_children:
                css_classes.append('dropdown')
            if item.css_class:
                css_classes.append(item.css_class)
            
            html += f'<li class="{" ".join(css_classes)}">'
            
            if has_children:
                html += f'''
                    <a href="{item.url or '#'}" class="nav-link dropdown-toggle" 
                       data-toggle="dropdown" target="{item.target}">
                '''
            else:
                html += f'<a href="{item.url or '#'}" class="nav-link" target="{item.target}">'
            
            if item.icon_class:
                html += f'<i class="{item.icon_class} fa-fw"></i> '
            
            html += f'{item.title}</a>'
            
            if has_children:
                html += self._render_menu_items(children, level + 1)
            
            html += '</li>'
        
        html += '</ul>'
        return html

# Usage in templates/menu/builder.html
```html
<!DOCTYPE html>
<html>
<head>
    <title>Menu Builder</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/font-awesome/4.7.0/css/font-awesome.min.css">
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-8">
                <h2>Menu Builder</h2>
                <form method="POST">
                    {{ form.csrf_token }}
                    {{ form.menu_structure() }}
                    <button type="submit" class="btn btn-primary">Save Menu</button>
                    <a href="{{ url_for('MenuBuilderView.preview') }}" class="btn btn-info" target="_blank">Preview</a>
                </form>
            </div>
            <div class="col-md-4">
                <h3>Menu Item Properties</h3>
                <div id="item-properties" style="display: none;">
                    <div class="form-group">
                        {{ form.title.label(class="control-label") }}
                        {{ form.title(class="form-control") }}
                    </div>
                    <div class="form-group">  
                        {{ form.url.label(class="control-label") }}
                        {{ form.url(class="form-control") }}
                    </div>
                    <div class="form-group">
                        {{ form.icon_class.label(class="control-label") }}
                        {{ form.icon_class(class="form-control", placeholder="fa-home") }}
                    </div>
                    <div class="form-group">
                        {{ form.target.label(class="control-label") }}
                        {{ form.target(class="form-control") }}
                    </div>
                    <div class="checkbox">
                        {{ form.requires_auth() }}
                        {{ form.requires_auth.label() }}
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js"></script>
    <script>
        // Handle menu item selection for editing
        $(document).on('click', '.menu-node .node-content', function(e) {
            e.stopPropagation();
            
            // Show properties panel
            $('#item-properties').show();
            
            // Populate form fields
            const $node = $(this).closest('.menu-node');
            const title = $node.find('.menu-title').text();
            const url = $node.data('url');
            
            $('#title').val(title);
            $('#url').val(url);
        });
    </script>
</body>
</html>
```

These complete examples demonstrate:

1. **E-commerce Categories**: Full CRUD with validation, SEO fields, and hierarchy management
2. **Organizational Chart**: LTREE-based department structure with budget calculations  
3. **File Manager**: File system interface with upload, icons, and file operations
4. **Menu Builder**: Navigation menu creation with HTML generation and preview

Each example includes models, forms, views, and templates showing real-world usage patterns for the PostgreSQL Tree Widget in different domains.
        'Category Hierarchy',
        mode='parent_id',
        id_field='category_id',
        parent_id_field='parent_category_id',
        label_field='category_name',
        max_depth=6
    )

# Model definition
class Category(Model):
    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(100))
    parent_category_id = Column(Integer, ForeignKey('category.category_id'))
```

**Parent-Child Data Structure:**
```json
[
    {"id": 1, "name": "Electronics", "parent_id": null},
    {"id": 2, "name": "Computers", "parent_id": 1},
    {"id": 3, "name": "Laptops", "parent_id": 2},
    {"id": 4, "name": "Gaming Laptops", "parent_id": 3}
]
```

### Widget Configuration

```python
# Advanced tree widget configuration
tree_field = PostgreSQLTreeField(
    'Hierarchical Data',
    mode='parent_id',                    # or 'ltree'
    id_field='id',                       # Primary key field name
    parent_id_field='parent_id',         # Parent reference field name
    label_field='name',                  # Display label field name
    max_depth=10,                        # Maximum tree depth
    allow_reorder=True,                  # Enable drag-and-drop reordering
    allow_drag_drop=True,                # Enable drag-and-drop functionality
    path_separator='.',                  # Path separator for LTREE mode
    validation_rules={                   # Custom validation rules
        'min_nodes': 1,
        'max_nodes': 1000,
        'required_root': True
    }
)
```

### Import/Export Formats

The tree widget supports multiple data formats:

**JSON Hierarchical:**
```json
{
    "company": {
        "label": "Company",
        "children": {
            "engineering": {
                "label": "Engineering",
                "children": {
                    "database": {
                        "label": "Database Team",
                        "children": {}
                    }
                }
            }
        }
    }
}
```

**CSV Parent-Child:**
```csv
id,name,parent_id
1,"Company",
2,"Engineering",1
3,"Database Team",2
4,"PostgreSQL Team",3
```

**LTREE Paths:**
```
company
company.engineering
company.engineering.database
company.engineering.database.postgresql
```

**SQL INSERT Statements:**
```sql
INSERT INTO categories (id, name, parent_id) VALUES
(1, 'Company', NULL),
(2, 'Engineering', 1),
(3, 'Database Team', 2),
(4, 'PostgreSQL Team', 3);
```

### Tree Validation

The widget performs comprehensive validation:

- **Depth Limits**: Enforces maximum tree depth
- **Orphan Detection**: Identifies nodes with invalid parent references
- **Circular References**: Prevents nodes from being their own ancestors
- **Duplicate IDs**: Ensures unique identifiers in parent-child mode
- **Path Format**: Validates LTREE path syntax and structure

### Database Queries

**LTREE Queries:**
```sql
-- Find all descendants of 'engineering'
SELECT * FROM departments WHERE org_path <@ 'company.engineering';

-- Find all ancestors of a specific node
SELECT * FROM departments WHERE 'company.engineering.database' ~ org_path;

-- Get immediate children
SELECT * FROM departments WHERE org_path ~ 'company.engineering.*{1}';

-- Calculate depth
SELECT org_path, nlevel(org_path) as depth FROM departments;
```

**Parent-Child Recursive Queries:**
```sql
-- Recursive CTE to get full hierarchy
WITH RECURSIVE hierarchy AS (
    SELECT id, name, parent_id, 1 as level, name::text as path
    FROM categories 
    WHERE parent_id IS NULL
    
    UNION ALL
    
    SELECT c.id, c.name, c.parent_id, h.level + 1, 
           (h.path || ' > ' || c.name)::text as path
    FROM categories c
    JOIN hierarchy h ON c.parent_id = h.id
)
SELECT * FROM hierarchy ORDER BY level, path;

-- Find all descendants of a node
WITH RECURSIVE descendants AS (
    SELECT id, name, parent_id FROM categories WHERE id = :node_id
    UNION ALL
    SELECT c.id, c.name, c.parent_id 
    FROM categories c
    JOIN descendants d ON c.parent_id = d.id
)
SELECT * FROM descendants WHERE id != :node_id;
```

### JavaScript API

The tree widget exposes a JavaScript API for custom interactions:

```javascript
// Access tree widget instance
var treeWidget = window.treeWidget_my_field_id;

// Programmatic operations
treeWidget.addRootNode('New Root');
treeWidget.expandAll();
treeWidget.collapseAll();
treeWidget.validateTree();
treeWidget.exportToFormat('json');

// Event handling
treeWidget.on('nodeAdded', function(node) {
    console.log('Node added:', node);
});

treeWidget.on('nodeDeleted', function(nodeId) {
    console.log('Node deleted:', nodeId);
});
```

### Styling Customization

```css
/* Customize tree appearance */
.postgresql-tree-widget .node-content {
    background: linear-gradient(135deg, #f5f7fa, #c3cfe2);
    border-radius: 8px;
}

.postgresql-tree-widget .node-content.selected {
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
}

/* Custom node icons */
.postgresql-tree-widget .node-icon.custom {
    color: #e74c3c;
    font-size: 18px;
}

/* Responsive adjustments */
@media (max-width: 768px) {
    .postgresql-tree-widget .node-children {
        margin-left: 15px;
        padding-left: 10px;
    }
}
```

## Best Practices

1. **Index Strategy**: Create indexes for all frequently queried paths and operations
2. **Data Validation**: Use form field validation before database constraints
3. **Widget Customization**: Customize widgets for specific use cases
4. **Migration Planning**: Plan schema changes carefully with PostgreSQL types
5. **Performance Monitoring**: Monitor query performance with PostgreSQL tools
6. **Extension Management**: Keep PostgreSQL extensions updated
7. **Backup Considerations**: Ensure backup tools support all PostgreSQL types

## Conclusion

PgAppForge's PostgreSQL support provides comprehensive coverage of advanced PostgreSQL features with rich user interfaces. This enables building sophisticated applications that leverage PostgreSQL's full capabilities while maintaining ease of use and development productivity.