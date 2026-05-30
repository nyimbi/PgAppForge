# Core API Reference

Complete API reference for PgAppForge's core modules and components.

## 📚 Module Overview

| Module | Description | Primary Classes |
|--------|-------------|----------------|
| `pgappforge.base` | Core AppBuilder class and application setup | `AppBuilder` |
| `pgappforge.views` | Base views and ModelView functionality | `ModelView`, `BaseView` |
| `pgappforge.baseviews` | Foundation view classes | `BaseView`, `BaseCRUDView` |
| `pgappforge.models.sqla` | SQLAlchemy model interfaces | `Model`, `SQLA` |
| `pgappforge.security` | Security and authentication system | `SecurityManager`, `BaseSecurityManager` |
| `pgappforge.forms` | Form handling and validation | `DynamicForm` |
| `pgappforge.widgets` | UI widgets and components | `ListWidget`, `ShowWidget`, `FormWidget` |
| `pgappforge.charts` | Chart and visualization views | `ChartView`, `GroupByChartView` |

## 🏗️ Core Classes

### AppBuilder

Central class that manages the entire PgAppForge application.

```python
class AppBuilder:
    def __init__(
        self,
        app: Optional[Flask] = None,
        session: Optional[Session] = None,
        menu: Optional[Menu] = None,
        indexview: Optional[BaseView] = None,
        static_folder: str = 'static/appbuilder',
        static_url_path: str = '/appbuilder',
        security_manager_class: Optional[BaseSecurityManager] = None,
        update_perms: bool = True
    ):
```

**Parameters:**
- `app` - Flask application instance
- `session` - Database session for SQLAlchemy
- `menu` - Custom menu instance
- `indexview` - Custom index view class
- `static_folder` - Static files directory
- `static_url_path` - URL path for static files
- `security_manager_class` - Custom security manager
- `update_perms` - Whether to auto-update permissions

#### Methods

##### `add_view(baseview: BaseView, name: str, href: str = '', icon: str = '', label: str = '', category: str = '', category_icon: str = '', category_label: str = '') -> None`

Register a view with the application.

```python
appbuilder.add_view(
    MyModelView,
    "My Models",
    href="/mymodels/",
    icon="fa-table",
    category="Data",
    category_icon="fa-database"
)
```

**Parameters:**
- `baseview` - View class to register
- `name` - Display name in menu
- `href` - URL path (auto-generated if not provided)
- `icon` - FontAwesome icon class
- `label` - Custom label (defaults to name)
- `category` - Menu category
- `category_icon` - Category icon
- `category_label` - Custom category label

##### `add_view_no_menu(baseview: BaseView, endpoint: str = None) -> None`

Register a view without adding it to the menu.

```python
appbuilder.add_view_no_menu(MyUtilityView)
```

##### `add_link(name: str, href: str, icon: str = '', label: str = '', category: str = '', category_icon: str = '') -> None`

Add a custom link to the menu.

```python
appbuilder.add_link(
    "External API",
    href="https://api.example.com",
    icon="fa-external-link",
    category="Tools"
)
```

##### `add_separator(category: str, category_icon: str = '', category_label: str = '') -> None`

Add a separator in the menu.

```python
appbuilder.add_separator("Reports")
```

##### `add_api(baseapi: BaseApi) -> None`

Register a REST API view.

```python
appbuilder.add_api(MyModelApi)
```

##### `security_cleanup() -> None`

Clean up permissions and roles (removes unused permissions).

```python
appbuilder.security_cleanup()
```

##### `get_url_for_login() -> str`

Get the login URL for the current security configuration.

```python
login_url = appbuilder.get_url_for_login()
```

##### `get_url_for_logout() -> str`

Get the logout URL.

```python
logout_url = appbuilder.get_url_for_logout()
```

### BaseView

Foundation class for all views in PgAppForge.

```python
class BaseView:
    route_base: str = None
    endpoint: str = None
    default_view: str = 'list'
    base_permissions: List[str] = ['can_list']
    class_permission_name: str = None
    method_permission_name: Dict[str, str] = {}
    base_filters: List = []
    search_filters: List = []
    extra_args: Dict = {}
```

**Class Attributes:**
- `route_base` - Base URL route for the view
- `endpoint` - Flask endpoint name
- `default_view` - Default method to call
- `base_permissions` - List of required permissions
- `class_permission_name` - Permission class name
- `method_permission_name` - Method-specific permission names
- `base_filters` - Default filters to apply
- `search_filters` - Available search filters
- `extra_args` - Extra arguments for templates

#### Decorators

##### `@expose(url: str, methods: List[str] = ['GET']) -> Callable`

Expose a method as a URL endpoint.

```python
class MyView(BaseView):
    @expose('/')
    def index(self):
        return self.render_template('my_template.html')

    @expose('/custom/<int:id>', methods=['GET', 'POST'])
    def custom_method(self, id):
        return f"ID: {id}"
```

##### `@has_access -> Callable`

Require authentication for the method.

```python
class MyView(BaseView):
    @expose('/protected')
    @has_access
    def protected_method(self):
        return "This requires login"
```

#### Methods

##### `render_template(template: str, **kwargs) -> str`

Render a Jinja2 template with PgAppForge context.

```python
def my_method(self):
    data = {'items': [1, 2, 3]}
    return self.render_template('my_template.html', data=data)
```

##### `update_redirect() -> str`

Get redirect URL after operations.

```python
redirect_url = self.update_redirect()
return redirect(redirect_url)
```

### ModelView

Advanced view for database model CRUD operations.

```python
class ModelView(BaseCRUDView):
    datamodel: Interface = None

    # List view configuration
    list_columns: List[str] = []
    list_title: str = ''
    list_template: str = 'appbuilder/general/model/list.html'

    # Search configuration
    search_columns: List[str] = []
    search_exclude_columns: List[str] = []
    search_form: Form = None

    # Form configuration
    add_columns: List[str] = []
    edit_columns: List[str] = []
    show_columns: List[str] = []

    # Ordering and pagination
    order_columns: List[str] = []
    base_order: Tuple[str, str] = ('id', 'asc')
    page_size: int = 20
    max_page_size: int = 100

    # Widgets
    list_widget: ListWidget = ListWidget
    show_widget: ShowWidget = ShowWidget
    add_widget: FormWidget = FormWidget
    edit_widget: FormWidget = FormWidget
    search_widget: SearchWidget = SearchWidget
```

#### Configuration Attributes

##### List View Configuration
- `list_columns` - Columns to display in list view
- `list_title` - Title for list page
- `list_template` - Custom list template
- `page_size` - Records per page
- `max_page_size` - Maximum allowed page size

##### Form Configuration
- `add_columns` - Columns in add form
- `edit_columns` - Columns in edit form
- `show_columns` - Columns in show view
- `add_form_extra_fields` - Additional form fields
- `edit_form_extra_fields` - Additional edit form fields

##### Search Configuration
- `search_columns` - Searchable columns
- `search_exclude_columns` - Columns to exclude from search
- `search_form` - Custom search form

#### Methods

##### `pre_add(item: Model) -> None`

Called before adding a new record.

```python
def pre_add(self, item):
    item.created_by = g.user
    item.status = 'active'
```

##### `post_add(item: Model) -> None`

Called after adding a new record.

```python
def post_add(self, item):
    flash(f'Successfully created {item.name}', 'success')
    self.send_notification(item)
```

##### `pre_update(item: Model) -> None`

Called before updating a record.

```python
def pre_update(self, item):
    item.modified_by = g.user
    item.modified_at = datetime.now()
```

##### `post_update(item: Model) -> None`

Called after updating a record.

```python
def post_update(self, item):
    self.log_change(item)
```

##### `pre_delete(item: Model) -> None`

Called before deleting a record.

```python
def pre_delete(self, item):
    if item.has_dependencies():
        raise Exception("Cannot delete: has dependencies")
```

##### `post_delete(item: Model) -> None`

Called after deleting a record.

```python
def post_delete(self, item):
    self.cleanup_related_data(item.id)
```

#### Form Customization

##### `add_form_extra_fields: Dict[str, Field]`

Add custom fields to the add form.

```python
from wtforms import StringField, SelectField

class MyModelView(ModelView):
    add_form_extra_fields = {
        'custom_field': StringField('Custom Field'),
        'priority': SelectField(
            'Priority',
            choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]
        )
    }
```

##### `edit_form_extra_fields: Dict[str, Field]`

Add custom fields to the edit form.

```python
class MyModelView(ModelView):
    edit_form_extra_fields = {
        'notes': TextAreaField('Internal Notes'),
        'last_reviewed': DateField('Last Reviewed')
    }
```

#### Formatters and Validators

##### `formatters_columns: Dict[str, Callable]`

Custom column formatters for display.

```python
class EmployeeView(ModelView):
    formatters_columns = {
        'salary': lambda x: f'${x:,.2f}' if x else '$0.00',
        'hire_date': lambda x: x.strftime('%Y-%m-%d') if x else '',
        'is_active': lambda x: '✓' if x else '✗'
    }
```

##### `validators_columns: Dict[str, List[Validator]]`

Custom field validators.

```python
from wtforms.validators import NumberRange, Email

class EmployeeView(ModelView):
    validators_columns = {
        'salary': [NumberRange(min=0, max=1000000)],
        'email': [Email()],
        'age': [NumberRange(min=18, max=100)]
    }
```

### Model (SQLAlchemy)

Base model class with PgAppForge enhancements.

```python
from pgappforge.models.mixins import AuditMixin, FileColumn, ImageColumn

class Model(DeclarativeBase):
    """Base model class."""
    pass

class MyModel(Model, AuditMixin):
    __tablename__ = 'my_table'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # File handling
    document = Column(FileColumn)
    photo = Column(ImageColumn(size=(300, 300, True)))
```

#### Mixins

##### `AuditMixin`

Adds audit trail fields to models.

```python
class MyModel(Model, AuditMixin):
    # Automatically adds:
    # created_on = Column(DateTime, default=datetime.now)
    # changed_on = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # created_by_fk = Column(Integer, ForeignKey('ab_user.id'))
    # changed_by_fk = Column(Integer, ForeignKey('ab_user.id'))
    pass
```

##### `FileColumn`

Handle file uploads.

```python
class Document(Model):
    title = Column(String(100))
    file = Column(FileColumn)  # Automatically handles file upload/storage
```

##### `ImageColumn`

Handle image uploads with resizing.

```python
class Profile(Model):
    name = Column(String(100))
    avatar = Column(ImageColumn(
        size=(200, 200, True),           # Resize to 200x200
        thumbnail_size=(50, 50, True)    # Create 50x50 thumbnail
    ))
```

### SecurityManager

Manages authentication, authorization, and user management.

```python
class SecurityManager(BaseSecurityManager):
    def __init__(self, appbuilder):
        super().__init__(appbuilder)
```

#### Authentication Methods

##### `auth_user_db(username: str, password: str) -> User`

Authenticate user against database.

```python
user = security_manager.auth_user_db('john_doe', 'password123')
if user:
    login_user(user)
```

##### `auth_user_ldap(username: str, password: str) -> User`

Authenticate user against LDAP.

```python
user = security_manager.auth_user_ldap('john_doe', 'password123')
```

##### `auth_user_oauth(userinfo: Dict) -> User`

Authenticate user via OAuth.

```python
user = security_manager.auth_user_oauth({
    'email': 'john@example.com',
    'name': 'John Doe'
})
```

#### User Management

##### `add_user(username: str, first_name: str, last_name: str, email: str, role: Role, password: str = '') -> User`

Add a new user.

```python
user = security_manager.add_user(
    username='jane_doe',
    first_name='Jane',
    last_name='Doe',
    email='jane@example.com',
    role=security_manager.find_role('User'),
    password='secure_password'
)
```

##### `find_user(username: str = None, email: str = None) -> User`

Find user by username or email.

```python
user = security_manager.find_user(username='john_doe')
user = security_manager.find_user(email='john@example.com')
```

##### `update_user(user: User) -> None`

Update user information.

```python
user.first_name = 'Jonathan'
security_manager.update_user(user)
```

##### `del_user(user: User) -> None`

Delete a user.

```python
security_manager.del_user(user)
```

#### Role Management

##### `add_role(name: str) -> Role`

Add a new role.

```python
role = security_manager.add_role('CustomRole')
```

##### `find_role(name: str) -> Role`

Find role by name.

```python
admin_role = security_manager.find_role('Admin')
```

##### `add_permission_role(role: Role, permission: Permission) -> None`

Add permission to role.

```python
permission = security_manager.find_permission('can_edit', 'MyModel')
security_manager.add_permission_role(admin_role, permission)
```

##### `del_permission_role(role: Role, permission: Permission) -> None`

Remove permission from role.

```python
security_manager.del_permission_role(role, permission)
```

#### Permission Management

##### `find_permission(name: str, view_menu: str) -> Permission`

Find permission by name and view.

```python
permission = security_manager.find_permission('can_list', 'EmployeeView')
```

##### `add_permission_view_menu(permission_name: str, view_menu_name: str) -> Permission`

Add permission for a view.

```python
permission = security_manager.add_permission_view_menu(
    'can_approve', 'ExpenseView'
)
```

##### `has_access(permission_name: str, view_name: str) -> bool`

Check if current user has access.

```python
if security_manager.has_access('can_edit', 'EmployeeView'):
    # User can edit employees
    pass
```

## 🎨 Widgets and UI Components

### ListWidget

Renders model list views.

```python
class CustomListWidget(ListWidget):
    template = 'my_custom_list.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.template = 'widgets/custom_list.html'
```

### ShowWidget

Renders model detail/show views.

```python
class CustomShowWidget(ShowWidget):
    template = 'widgets/custom_show.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
```

### FormWidget

Renders add/edit forms.

```python
class CustomFormWidget(FormWidget):
    template = 'widgets/custom_form.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
```

### SearchWidget

Renders search forms.

```python
class CustomSearchWidget(SearchWidget):
    template = 'widgets/custom_search.html'
```

## 📊 Charts and Visualizations

### ChartView

Base class for chart views.

```python
from pgappforge.charts.views import ChartView
from pgappforge.models.sqla.interface import SQLAInterface

class MyChartView(ChartView):
    datamodel = SQLAInterface(MyModel)
    chart_title = 'My Chart'
    label_columns = {'name': 'Name', 'value': 'Value'}

    def query_chart_data(self):
        # Return data for chart
        return [
            {'name': 'Category 1', 'value': 100},
            {'name': 'Category 2', 'value': 200}
        ]
```

### GroupByChartView

Chart view with grouping capabilities.

```python
class SalesGroupByChart(GroupByChartView):
    datamodel = SQLAInterface(Sale)
    chart_title = 'Sales by Region'

    # Group by column
    group_by_columns = ['region']

    # Chart configuration
    chart_type = 'ColumnChart'
    chart_3d = True
```

## 🔧 Forms and Validation

### DynamicForm

Dynamic form generation with validation.

```python
from pgappforge.forms import DynamicForm
from wtforms import StringField, IntegerField, validators

class CustomForm(DynamicForm):
    name = StringField('Name', [validators.Length(min=1, max=100)])
    age = IntegerField('Age', [validators.NumberRange(min=0, max=150)])
    email = StringField('Email', [validators.Email()])

    def validate_name(self, field):
        if field.data and field.data.lower() in ['admin', 'root']:
            raise ValidationError('Name not allowed')
```

### Field Types

#### Custom Field Implementations

```python
from wtforms import Field
from wtforms.widgets import TextInput

class ColorField(Field):
    """Custom color picker field."""
    widget = TextInput()

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = valuelist[0]

    def __call__(self, field, **kwargs):
        kwargs.setdefault('type', 'color')
        return super().__call__(field, **kwargs)

class TagField(Field):
    """Field for handling comma-separated tags."""
    widget = TextInput()

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = [tag.strip() for tag in valuelist[0].split(',')]

    def _value(self):
        if self.data:
            return ', '.join(self.data)
        return ''
```

## 🔌 Hooks and Events

### View Hooks

Override methods to customize behavior.

```python
class CustomModelView(ModelView):
    def pre_add(self, item):
        """Called before adding record."""
        item.created_by = g.user
        item.tenant_id = g.user.tenant_id

    def post_add(self, item):
        """Called after adding record."""
        self.send_notification('created', item)

    def pre_update(self, item):
        """Called before updating record."""
        item.modified_by = g.user
        item.version += 1

    def post_update(self, item):
        """Called after updating record."""
        self.log_change(item)

    def pre_delete(self, item):
        """Called before deleting record."""
        if not self.can_delete(item):
            raise Exception("Cannot delete this record")

    def post_delete(self, item):
        """Called after deleting record."""
        self.cleanup_references(item)
```

### Security Hooks

Customize security behavior.

```python
class CustomSecurityManager(SecurityManager):
    def pre_login(self, user):
        """Called before user login."""
        self.log_login_attempt(user)

    def post_login(self, user):
        """Called after successful login."""
        user.last_login = datetime.now()
        self.update_user(user)

    def pre_logout(self, user):
        """Called before user logout."""
        self.log_logout(user)
```

## 🛠️ Utilities and Helpers

### Decorators

```python
from pgappforge.security.decorators import has_access, protect

@has_access
def protected_view():
    """Requires authentication."""
    pass

@protect()
def api_endpoint():
    """API endpoint with permission check."""
    pass

@protect('can_custom_action')
def custom_action():
    """Custom permission check."""
    pass
```

### Context Processors

```python
@appbuilder.app.context_processor
def inject_vars():
    """Inject variables into all templates."""
    return {
        'app_version': '1.0.0',
        'current_user': g.user if hasattr(g, 'user') else None
    }
```

### Custom Filters

```python
from pgappforge.basefilters import BaseFilter

class CustomFilter(BaseFilter):
    name = 'Custom Filter'
    arg_name = 'cf'

    def apply(self, query, value):
        return query.filter(MyModel.custom_field == value)

# Use in ModelView
class MyModelView(ModelView):
    base_filters = [CustomFilter]
```

## 📝 Configuration Options

### Application Configuration

```python
# Core settings
APP_NAME = "My Application"
APP_THEME = ""  # Bootstrap theme
APP_ICON = "/static/img/logo.jpg"

# Security settings
AUTH_TYPE = AUTH_DB  # AUTH_LDAP, AUTH_OAUTH, etc.
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'
SECRET_KEY = 'your-secret-key'

# Database settings
SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Upload settings
UPLOAD_FOLDER = '/path/to/uploads'
IMG_UPLOAD_FOLDER = '/path/to/images'
IMG_UPLOAD_URL = '/uploads/images'
IMG_SIZE = (300, 200, True)

# UI settings
PGAF_PAGINATION_SIZE = 20
PGAF_THEME_SWITCHER = True
PGAF_ICON_SIZE = 16
```

### View Configuration

```python
class MyModelView(ModelView):
    # List configuration
    list_columns = ['name', 'created_on', 'is_active']
    list_title = 'My Records'

    # Form configuration
    add_columns = ['name', 'description', 'category']
    edit_columns = add_columns + ['is_active']

    # Search configuration
    search_columns = ['name', 'description']

    # Pagination
    page_size = 25
    max_page_size = 100

    # Ordering
    base_order = ('name', 'asc')
    order_columns = ['name', 'created_on']
```

For more detailed examples and advanced usage, see:
- [Developer Getting Started Guide](../developer/getting_started.md)
- [API Development Guide](../developer/api_development.md)
- [Security Architecture](../security/security_architecture.md)