# Models and Database API Reference

Complete API reference for PgAppForge's model interfaces, database integration, and ORM functionality.

## 📚 Module Overview

| Module | Description | Primary Classes |
|--------|-------------|----------------|
| `pgappforge.models.sqla` | SQLAlchemy integration | `Model`, `SQLA` |
| `pgappforge.models.sqla.interface` | SQLAlchemy interface | `SQLAInterface` |
| `pgappforge.models.mixins` | Model mixins and utilities | `AuditMixin`, `FileColumn`, `ImageColumn` |
| `pgappforge.models.filters` | Database filters | `FilterEqual`, `FilterNotEqual`, `FilterLike` |
| `pgappforge.models.datamodel` | Data model abstraction | `SQLAModel` |

## 🗄️ Database Integration

### SQLA

Main SQLAlchemy integration class.

```python
from pgappforge.models.sqla import SQLA

class SQLA:
    def __init__(self, app: Flask = None):
        self.db = None
        if app:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Initialize with Flask app."""
        pass

    @property
    def session(self) -> Session:
        """Get current database session."""
        return self.db.session

    @property
    def engine(self) -> Engine:
        """Get database engine."""
        return self.db.engine

    def create_all(self) -> None:
        """Create all database tables."""
        self.db.create_all()

    def drop_all(self) -> None:
        """Drop all database tables."""
        self.db.drop_all()
```

#### Usage Example

```python
from flask import Flask
from pgappforge import AppBuilder
from pgappforge.models.sqla import SQLA

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Create tables
db.create_all()
```

### Model Base Class

Enhanced SQLAlchemy declarative base with PgAppForge features.

```python
from pgappforge.models.sqla import Model
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship

class Model(DeclarativeBase):
    """Enhanced SQLAlchemy Model base class."""
    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        """Generate table name from class name."""
        return cls.__name__.lower()

    def __repr__(self):
        """String representation of model."""
        return f'<{self.__class__.__name__} {self.id}>'
```

#### Basic Model Example

```python
class Employee(Model):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hire_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

    # Computed property
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    # Class method
    @classmethod
    def get_active_employees(cls):
        return cls.query.filter_by(is_active=True).all()

    # Instance method
    def deactivate(self):
        self.is_active = False
        db.session.commit()
```

## 🔍 Model Interfaces

### SQLAInterface

Interface class that connects models to views.

```python
from pgappforge.models.sqla.interface import SQLAInterface

class SQLAInterface:
    def __init__(self, obj: Model, session: Session = None):
        """
        Initialize interface for a model.

        Args:
            obj: SQLAlchemy model class
            session: Database session (optional)
        """
        self.obj = obj
        self.session = session or db.session
```

#### Methods

##### `get_columns_list() -> List[str]`

Get list of all model columns.

```python
interface = SQLAInterface(Employee)
columns = interface.get_columns_list()
# Returns: ['id', 'first_name', 'last_name', 'email', 'hire_date', 'is_active']
```

##### `get_user_columns_list() -> List[str]`

Get list of user-visible columns (excludes system columns).

```python
user_columns = interface.get_user_columns_list()
```

##### `get_search_columns_list() -> List[str]`

Get list of searchable columns.

```python
search_columns = interface.get_search_columns_list()
```

##### `get_order_columns_list() -> List[str]`

Get list of sortable columns.

```python
order_columns = interface.get_order_columns_list()
```

##### `get_filters() -> Dict[str, List[Filter]]`

Get available filters for the model.

```python
filters = interface.get_filters()
# Returns dict of column_name -> [available_filters]
```

##### `query(filters: FilterSet = None, order_column: str = '', order_direction: str = '', page: int = None, page_size: int = None) -> Query`

Build filtered and paginated query.

```python
# Basic query
query = interface.query()

# Filtered query
from pgappforge.models.sqla.filters import FilterEqual
filters = FilterSet([FilterEqual('is_active', True)])
query = interface.query(filters=filters)

# Paginated query
query = interface.query(page=1, page_size=20)

# Ordered query
query = interface.query(
    order_column='last_name',
    order_direction='asc'
)
```

##### `get(id: Any) -> Model`

Get model instance by ID.

```python
employee = interface.get(123)
```

##### `get_pk_value(item: Model) -> Any`

Get primary key value from model instance.

```python
pk = interface.get_pk_value(employee)
```

##### `add(item: Model) -> Model`

Add new model instance.

```python
employee = Employee(
    first_name='John',
    last_name='Doe',
    email='john.doe@company.com'
)
saved_employee = interface.add(employee)
```

##### `edit(item: Model) -> Model`

Update existing model instance.

```python
employee.first_name = 'Jonathan'
updated_employee = interface.edit(employee)
```

##### `delete(item: Model) -> bool`

Delete model instance.

```python
success = interface.delete(employee)
```

### Advanced Querying

#### Custom Queries

```python
class EmployeeInterface(SQLAInterface):
    def __init__(self, obj, session=None):
        super().__init__(obj, session)

    def get_active_employees(self):
        """Get only active employees."""
        return self.session.query(self.obj).filter_by(is_active=True)

    def get_employees_by_department(self, department_id):
        """Get employees in specific department."""
        return self.session.query(self.obj).filter_by(
            department_id=department_id,
            is_active=True
        )

    def get_recent_hires(self, days=30):
        """Get employees hired in last N days."""
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        return self.session.query(self.obj).filter(
            self.obj.hire_date >= cutoff_date
        )
```

#### Query Optimization

```python
from sqlalchemy.orm import joinedload, selectinload

class OptimizedEmployeeInterface(SQLAInterface):
    def get_employees_with_department(self):
        """Get employees with department data (avoid N+1 queries)."""
        return self.session.query(self.obj).options(
            joinedload(Employee.department)
        ).all()

    def get_employees_with_projects(self):
        """Get employees with their projects."""
        return self.session.query(self.obj).options(
            selectinload(Employee.projects)
        ).all()
```

## 🔧 Model Mixins

### AuditMixin

Adds audit trail functionality to models.

```python
from pgappforge.models.mixins import AuditMixin
from datetime import datetime

class AuditMixin:
    """Mixin to add audit fields to models."""

    created_on = Column(DateTime, default=datetime.now, nullable=False)
    changed_on = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    @declared_attr
    def created_by_fk(cls):
        return Column(Integer, ForeignKey('ab_user.id'), default=cls.get_user_id, nullable=False)

    @declared_attr
    def created_by(cls):
        return relationship("User", primaryjoin=f'{cls.__name__}.created_by_fk == User.id')

    @declared_attr
    def changed_by_fk(cls):
        return Column(Integer, ForeignKey('ab_user.id'), default=cls.get_user_id, onupdate=cls.get_user_id, nullable=False)

    @declared_attr
    def changed_by(cls):
        return relationship("User", primaryjoin=f'{cls.__name__}.changed_by_fk == User.id')

    @classmethod
    def get_user_id(cls):
        """Get current user ID for audit fields."""
        try:
            from flask import g
            return g.user.id if hasattr(g, 'user') and g.user else None
        except:
            return None
```

#### Usage Example

```python
class Employee(Model, AuditMixin):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    # Audit fields automatically added:
    # created_on, changed_on, created_by_fk, changed_by_fk
    # created_by, changed_by relationships
```

### FileColumn

Handle file uploads and storage.

```python
from pgappforge.models.mixins import FileColumn

class FileColumn(TypeDecorator):
    """Column type for file uploads."""
    impl = String

    def __init__(self, **kwargs):
        """
        Initialize FileColumn.

        Args:
            **kwargs: Additional arguments
        """
        super().__init__(length=255, **kwargs)
```

#### Usage Example

```python
class Document(Model):
    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    file = Column(FileColumn)  # Handles file upload/storage
    description = Column(Text)

    @property
    def file_url(self):
        """Get URL for the uploaded file."""
        if self.file:
            return f'/uploads/{self.file}'
        return None

    @property
    def file_size(self):
        """Get file size in bytes."""
        if self.file:
            import os
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], self.file)
            if os.path.exists(file_path):
                return os.path.getsize(file_path)
        return 0
```

### ImageColumn

Handle image uploads with resizing and thumbnails.

```python
from pgappforge.models.mixins import ImageColumn

class ImageColumn(FileColumn):
    """Column type for image uploads with resizing."""

    def __init__(self, size=(300, 300, True), thumbnail_size=(150, 150, True), **kwargs):
        """
        Initialize ImageColumn.

        Args:
            size: Tuple of (width, height, crop) for main image
            thumbnail_size: Tuple of (width, height, crop) for thumbnail
            **kwargs: Additional arguments
        """
        self.size = size
        self.thumbnail_size = thumbnail_size
        super().__init__(**kwargs)
```

#### Usage Example

```python
class Profile(Model):
    __tablename__ = 'profiles'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    avatar = Column(ImageColumn(
        size=(400, 400, True),           # Main image: 400x400, cropped
        thumbnail_size=(100, 100, True)  # Thumbnail: 100x100, cropped
    ))
    cover_photo = Column(ImageColumn(
        size=(1200, 300, True),          # Wide banner format
        thumbnail_size=(300, 75, True)
    ))

    @property
    def avatar_url(self):
        """Get URL for avatar image."""
        if self.avatar:
            return f'/uploads/images/{self.avatar}'
        return '/static/img/default-avatar.png'

    @property
    def avatar_thumbnail_url(self):
        """Get URL for avatar thumbnail."""
        if self.avatar:
            return f'/uploads/thumbnails/{self.avatar}'
        return '/static/img/default-avatar-thumb.png'
```

## 🔍 Filters and Search

### Base Filters

Foundation classes for database filtering.

```python
from pgappforge.models.filters import BaseFilter

class BaseFilter:
    """Base class for all filters."""
    name = 'Base Filter'
    arg_name = 'bf'

    def __init__(self, column_name, datamodel, is_related_view=False):
        self.column_name = column_name
        self.datamodel = datamodel
        self.is_related_view = is_related_view

    def apply(self, query, value):
        """Apply filter to query."""
        raise NotImplementedError
```

### Standard Filters

#### FilterEqual

Exact match filter.

```python
from pgappforge.models.filters import FilterEqual

class FilterEqual(BaseFilter):
    name = 'Equal to'
    arg_name = 'eql'

    def apply(self, query, value):
        return query.filter(getattr(self.datamodel.obj, self.column_name) == value)
```

#### FilterNotEqual

Not equal filter.

```python
from pgappforge.models.filters import FilterNotEqual

class FilterNotEqual(BaseFilter):
    name = 'Not Equal to'
    arg_name = 'neq'

    def apply(self, query, value):
        return query.filter(getattr(self.datamodel.obj, self.column_name) != value)
```

#### FilterLike

Text search filter.

```python
from pgappforge.models.filters import FilterLike

class FilterLike(BaseFilter):
    name = 'Contains'
    arg_name = 'like'

    def apply(self, query, value):
        return query.filter(
            getattr(self.datamodel.obj, self.column_name).contains(value)
        )
```

#### FilterStartsWith

Starts with text filter.

```python
from pgappforge.models.filters import FilterStartsWith

class FilterStartsWith(BaseFilter):
    name = 'Starts with'
    arg_name = 'sw'

    def apply(self, query, value):
        return query.filter(
            getattr(self.datamodel.obj, self.column_name).startswith(value)
        )
```

#### FilterEndsWith

Ends with text filter.

```python
from pgappforge.models.filters import FilterEndsWith

class FilterEndsWith(BaseFilter):
    name = 'Ends with'
    arg_name = 'ew'

    def apply(self, query, value):
        return query.filter(
            getattr(self.datamodel.obj, self.column_name).endswith(value)
        )
```

#### FilterGreater

Greater than filter.

```python
from pgappforge.models.filters import FilterGreater

class FilterGreater(BaseFilter):
    name = 'Greater than'
    arg_name = 'gt'

    def apply(self, query, value):
        return query.filter(getattr(self.datamodel.obj, self.column_name) > value)
```

#### FilterSmaller

Less than filter.

```python
from pgappforge.models.filters import FilterSmaller

class FilterSmaller(BaseFilter):
    name = 'Smaller than'
    arg_name = 'lt'

    def apply(self, query, value):
        return query.filter(getattr(self.datamodel.obj, self.column_name) < value)
```

### Date and Time Filters

#### FilterDateTimeRange

Date/time range filter.

```python
from pgappforge.models.filters import FilterDateTimeRange

class FilterDateTimeRange(BaseFilter):
    name = 'Date/Time Range'
    arg_name = 'dtr'

    def apply(self, query, value):
        start_date, end_date = value
        column = getattr(self.datamodel.obj, self.column_name)
        return query.filter(column.between(start_date, end_date))
```

#### FilterYear

Filter by year.

```python
from pgappforge.models.filters import FilterYear
from sqlalchemy import extract

class FilterYear(BaseFilter):
    name = 'Year'
    arg_name = 'year'

    def apply(self, query, value):
        column = getattr(self.datamodel.obj, self.column_name)
        return query.filter(extract('year', column) == value)
```

### Custom Filters

#### Creating Custom Filters

```python
from pgappforge.models.filters import BaseFilter
from sqlalchemy import func

class FilterFullTextSearch(BaseFilter):
    """Full-text search filter for PostgreSQL."""
    name = 'Full Text Search'
    arg_name = 'fts'

    def apply(self, query, value):
        # PostgreSQL full-text search
        column = getattr(self.datamodel.obj, self.column_name)
        return query.filter(
            func.to_tsvector('english', column).match(value)
        )

class FilterDistanceFromLocation(BaseFilter):
    """Geographic distance filter."""
    name = 'Distance from Location'
    arg_name = 'dist'

    def apply(self, query, value):
        # value should be (latitude, longitude, distance_km)
        lat, lng, distance = value

        # Using PostGIS extension
        location_column = getattr(self.datamodel.obj, self.column_name)
        point = func.ST_Point(lng, lat)
        return query.filter(
            func.ST_DWithin(
                func.ST_Transform(location_column, 3857),
                func.ST_Transform(point, 3857),
                distance * 1000  # Convert km to meters
            )
        )

class FilterArrayContains(BaseFilter):
    """Filter for PostgreSQL array columns."""
    name = 'Array Contains'
    arg_name = 'arr_contains'

    def apply(self, query, value):
        column = getattr(self.datamodel.obj, self.column_name)
        return query.filter(column.contains([value]))

class FilterJSONPath(BaseFilter):
    """Filter for JSON column paths."""
    name = 'JSON Path'
    arg_name = 'json_path'

    def apply(self, query, value):
        # value should be (json_path, expected_value)
        json_path, expected_value = value
        column = getattr(self.datamodel.obj, self.column_name)
        return query.filter(
            column[json_path].astext == str(expected_value)
        )
```

### Filter Usage in Views

```python
class EmployeeModelView(ModelView):
    datamodel = SQLAInterface(Employee)

    # Apply default filters
    base_filters = [
        FilterEqual('is_active', True),  # Show only active employees
        FilterGreater('hire_date', date(2020, 1, 1))  # Hired after 2020
    ]

    # Available search filters
    search_filters = [
        FilterLike,
        FilterEqual,
        FilterNotEqual,
        FilterStartsWith,
        FilterEndsWith
    ]

    # Custom filter methods
    def get_user_filter(self):
        """Apply user-specific filters."""
        if g.user.has_role('Manager'):
            # Managers see all employees in their department
            return FilterEqual('department_id', g.user.department_id)
        elif g.user.has_role('Employee'):
            # Employees see only themselves
            return FilterEqual('id', g.user.employee_id)
        return None

    def get_query(self):
        """Override to apply dynamic filters."""
        query = super().get_query()

        # Apply user-specific filter
        user_filter = self.get_user_filter()
        if user_filter:
            query = user_filter.apply(query, None)

        return query
```

## 📊 Advanced Features

### Model Validation

#### Field Validation

```python
from sqlalchemy.orm import validates
from sqlalchemy.exc import ValidationError

class Employee(Model):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    email = Column(String(100), nullable=False)
    salary = Column(Float)
    age = Column(Integer)

    @validates('email')
    def validate_email(self, key, address):
        """Validate email format."""
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', address):
            raise ValueError('Invalid email format')
        return address

    @validates('salary')
    def validate_salary(self, key, salary):
        """Validate salary range."""
        if salary is not None and (salary < 0 or salary > 1000000):
            raise ValueError('Salary must be between 0 and 1,000,000')
        return salary

    @validates('age')
    def validate_age(self, key, age):
        """Validate age range."""
        if age is not None and (age < 16 or age > 100):
            raise ValueError('Age must be between 16 and 100')
        return age
```

#### Model-Level Validation

```python
from sqlalchemy.orm import Session
from sqlalchemy import event

class Employee(Model):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    employee_id = Column(String(20), unique=True)
    email = Column(String(100), unique=True)
    manager_id = Column(Integer, ForeignKey('employees.id'))

    def validate_model(self):
        """Validate entire model."""
        errors = []

        # Business rule: Employee cannot be their own manager
        if self.manager_id == self.id:
            errors.append('Employee cannot be their own manager')

        # Business rule: Check email domain
        if self.email and not self.email.endswith('@company.com'):
            errors.append('Email must be from company domain')

        if errors:
            raise ValidationError('; '.join(errors))

@event.listens_for(Employee, 'before_insert')
@event.listens_for(Employee, 'before_update')
def validate_employee(mapper, connection, target):
    """Validate employee before saving."""
    target.validate_model()
```

### Soft Delete

```python
from sqlalchemy import Boolean, DateTime
from datetime import datetime

class SoftDeleteMixin:
    """Mixin for soft delete functionality."""
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime)
    deleted_by_fk = Column(Integer, ForeignKey('ab_user.id'))

    @declared_attr
    def deleted_by(cls):
        return relationship("User", foreign_keys=[cls.deleted_by_fk])

    def delete(self):
        """Soft delete the record."""
        self.is_deleted = True
        self.deleted_at = datetime.now()
        if hasattr(g, 'user') and g.user:
            self.deleted_by_fk = g.user.id

    def restore(self):
        """Restore soft deleted record."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by_fk = None

    @classmethod
    def active_only(cls):
        """Query filter for non-deleted records."""
        return cls.query.filter(cls.is_deleted == False)

    @classmethod
    def deleted_only(cls):
        """Query filter for deleted records."""
        return cls.query.filter(cls.is_deleted == True)

class Employee(Model, AuditMixin, SoftDeleteMixin):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)

# Usage
# Get active employees only
active_employees = Employee.active_only().all()

# Soft delete an employee
employee = Employee.query.get(1)
employee.delete()
db.session.commit()

# Restore deleted employee
employee.restore()
db.session.commit()
```

### Versioning

```python
class VersionedMixin:
    """Mixin for record versioning."""
    version = Column(Integer, default=1, nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.version = 1

    def increment_version(self):
        """Increment version number."""
        self.version += 1

@event.listens_for(Session, 'before_flush')
def increment_version_on_update(session, flush_context, instances):
    """Auto-increment version on update."""
    for instance in session.dirty:
        if isinstance(instance, VersionedMixin):
            instance.increment_version()

class Document(Model, VersionedMixin):
    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True)
    title = Column(String(200))
    content = Column(Text)

# Usage
doc = Document(title="My Document", content="Initial content")
db.session.add(doc)
db.session.commit()
print(doc.version)  # 1

doc.content = "Updated content"
db.session.commit()
print(doc.version)  # 2
```

For more information, see:
- [Core API Reference](core_api_reference.md)
- [Developer Getting Started Guide](../developer/getting_started.md)
- [Security API Reference](../security/security_api_reference.md)