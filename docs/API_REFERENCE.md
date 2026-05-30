# Workflow Generation API Reference

This document provides detailed API reference for the PgAppForge Workflow Generation system.

## 🏗️ Core Components

### WDLGenerator Class

The main class responsible for workflow-to-code generation.

```python
from pgappforge.workflow.generators.wdl_generator import WDLGenerator

generator = WDLGenerator(app_name="my_app")
```

#### Constructor

```python
WDLGenerator(app_name: str, output_dir: Optional[Path] = None)
```

**Parameters:**
- `app_name` (str): Name of the PgAppForge application
- `output_dir` (Optional[Path]): Output directory for generated files (default: current directory)

#### Methods

##### `generate_from_file(workflow_file: str) -> List[str]`

Generate PgAppForge code from a workflow definition file.

**Parameters:**
- `workflow_file` (str): Path to the workflow definition file (.yaml, .yml, or .wdl)

**Returns:**
- `List[str]`: List of generated file paths

**Example:**
```python
generator = WDLGenerator("hr_system")
files = generator.generate_from_file("employee_onboarding.yaml")
print(f"Generated {len(files)} files")
```

##### `generate_from_yaml_data(workflow_data: Dict[str, Any]) -> List[str]`

Generate PgAppForge code from parsed workflow data.

**Parameters:**
- `workflow_data` (Dict[str, Any]): Parsed workflow definition dictionary

**Returns:**
- `List[str]`: List of generated file paths

**Example:**
```python
import yaml

with open("workflow.yaml") as f:
    data = yaml.safe_load(f)

generator = WDLGenerator("my_app")
files = generator.generate_from_yaml_data(data)
```

##### `validate_workflow_definition(workflow_data: Dict[str, Any]) -> Tuple[bool, List[str]]`

Validate a workflow definition.

**Parameters:**
- `workflow_data` (Dict[str, Any]): Workflow definition to validate

**Returns:**
- `Tuple[bool, List[str]]`: (is_valid, list_of_errors)

**Example:**
```python
is_valid, errors = generator.validate_workflow_definition(workflow_data)
if not is_valid:
    for error in errors:
        print(f"Validation error: {error}")
```

### Template System

The template system generates code using Jinja2 templates.

#### Template Context Variables

When rendering templates, the following variables are available:

```python
{
    'app_name': str,                    # Application name
    'workflow_name': str,               # Workflow name (e.g., "EmployeeOnboarding")
    'workflow_data': Dict[str, Any],    # Complete workflow definition
    'step_name': str,                   # Current step name (when applicable)
    'step_data': Dict[str, Any],        # Current step data (when applicable)
    'entity_name': str,                 # Current entity name (when applicable)
    'entity_data': Dict[str, Any],      # Current entity data (when applicable)
    'timestamp': datetime,              # Generation timestamp
    'version': str,                     # Workflow version
    'description': str,                 # Workflow description
}
```

#### Available Templates

| Template | Purpose | Output |
|----------|---------|--------|
| `models/model.py.j2` | SQLAlchemy models | `models/{entity}_model.py` |
| `views/view.py.j2` | PgAppForge views | `views/{step}_view.py` |
| `forms/form.py.j2` | WTForms | `forms/{step}_form.py` |
| `templates/template.html.j2` | Bootstrap templates | `templates/{step}.html` |
| `api/api.py.j2` | RESTful APIs | `api/workflow_api.py` |
| `tests/test.py.j2` | Test suites | `tests/test_{workflow}.py` |
| `migrations/migration.py.j2` | Database migrations | `migrations/001_{workflow}.py` |

## 📊 Workflow Definition Schema

### Root Schema

```yaml
WorkflowName:
  version: string                    # Semantic version (required)
  description: string               # Workflow description (optional)
  entities: EntityDefinitions       # Entity definitions (optional)
  steps: StepDefinitions           # Step definitions (required)
  permissions: PermissionMap       # Permission mappings (optional)
  notifications: NotificationConfig # Notification settings (optional)
  features: FeatureConfig          # Feature toggles (optional)
  ui: UIConfig                     # UI customization (optional)
  security: SecurityConfig         # Security settings (optional)
  metadata: MetadataInfo           # Additional metadata (optional)
```

### Entity Definition Schema

```yaml
entities:
  EntityName: "existing"             # Reference to existing model
  EntityName:                        # New entity definition
    fields:                          # Field definitions (required)
      - fieldName:                   # Field configuration
          type: string               # Field type (required)
          required: boolean          # Whether field is required (default: false)
          unique: boolean            # Whether field must be unique (default: false)
          nullable: boolean          # Whether field can be null (default: true)
          default: any               # Default value (optional)
          validation: ValidationRules # Validation configuration (optional)
          description: string        # Field description (optional)
```

### Step Definition Schema

```yaml
steps:
  StepName:
    title: string                    # Human-readable title (required)
    description: string              # Step description (optional)
    icon: string                     # Icon name (optional)
    estimatedTime: string            # Estimated completion time (optional)
    permissions: StepPermissions     # Step-specific permissions (optional)
    fields: FieldDefinitions         # Form fields for this step (required)
    validation: ValidationRules      # Step-level validation (optional)
    conditions: ConditionalLogic     # Conditional display logic (optional)
```

### Field Type Reference

#### String Fields

```yaml
fieldName:
  type: string
  required: true
  validation:
    minLength: 2
    maxLength: 100
    pattern: "^[A-Za-z ]+$"
  placeholder: "Enter your name"
```

#### Email Fields

```yaml
fieldName:
  type: email
  required: true
  unique: true
  validation:
    pattern: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"
  placeholder: "user@example.com"
```

#### Select Fields

```yaml
fieldName:
  type: select
  required: true
  choices:
    - ["value1", "Display Label 1"]
    - ["value2", "Display Label 2"]
  default: "value1"
```

#### File Upload Fields

```yaml
fieldName:
  type: file
  required: true
  accept: [".pdf", ".jpg", ".png"]
  description: "Upload identification document"
  validation:
    maxSize: 16777216  # 16MB in bytes
```

#### Date Fields

```yaml
fieldName:
  type: date
  required: true
  validation:
    min: "today"
    max: "2030-12-31"
  default: "today"
```

#### Numeric Fields

```yaml
fieldName:
  type: float  # or integer
  required: true
  validation:
    min: 0
    max: 999999.99
  placeholder: "0.00"
```

### Validation Rules

```yaml
validation:
  required: boolean                  # Field is required
  minLength: integer                # Minimum string length
  maxLength: integer                # Maximum string length
  min: number                       # Minimum numeric value
  max: number                       # Maximum numeric value
  pattern: string                   # Regular expression pattern
  unique: boolean                   # Value must be unique
  custom: string                    # Custom validation function name
```

### Permission Configuration

```yaml
permissions:
  StepName:
    view: ["role1", "role2"]         # Roles that can view this step
    edit: ["role1"]                  # Roles that can edit this step
    delete: ["admin"]                # Roles that can delete records
    
# Global permissions
permissions:
  default_view: ["public"]
  default_edit: ["authenticated"]
  admin_roles: ["admin", "super_admin"]
```

### Feature Configuration

```yaml
features:
  auto_save: boolean                 # Enable auto-save (default: false)
  auto_save_interval: integer        # Auto-save interval in seconds (default: 30)
  collaboration: boolean             # Enable real-time collaboration (default: false)
  real_time: boolean                 # Enable real-time updates (default: false)
  comments: boolean                  # Enable commenting system (default: false)
  file_upload: boolean               # Enable file uploads (default: false)
  max_file_size: integer             # Maximum file size in bytes (default: 10MB)
  allowed_extensions: [string]       # Allowed file extensions
  versioning: boolean                # Enable record versioning (default: false)
  audit_trail: boolean               # Enable audit trail (default: true)
```

### Notification Configuration

```yaml
notifications:
  email:
    enabled: boolean                 # Enable email notifications (default: false)
    templates:
      step_completed: string         # Template for step completion
      approval_needed: string        # Template for approval requests
      workflow_completed: string     # Template for workflow completion
      error_occurred: string         # Template for error notifications
  sms:
    enabled: boolean                 # Enable SMS notifications (default: false)
    provider: string                 # SMS provider (twilio, etc.)
  slack:
    enabled: boolean                 # Enable Slack notifications (default: false)
    webhook_url: string              # Slack webhook URL
```

### Security Configuration

```yaml
security:
  auth_type: string                  # Authentication type (AUTH_DB, AUTH_OAUTH, etc.)
  admin_role: string                 # Admin role name (default: "Admin")
  public_role: string                # Public role name (default: "Public")
  allow_registration: boolean        # Allow user registration (default: false)
  registration_role: string          # Default role for new users
  audit: boolean                     # Enable audit logging (default: true)
  encryption: [string]               # Fields to encrypt
  session_timeout: integer           # Session timeout in minutes
  password_policy:
    min_length: integer              # Minimum password length
    require_uppercase: boolean       # Require uppercase letters
    require_lowercase: boolean       # Require lowercase letters
    require_numbers: boolean         # Require numbers
    require_special: boolean         # Require special characters
```

## 🔧 Advanced Usage

### Custom Templates

You can override default templates by placing custom templates in the appropriate directory:

```python
generator = WDLGenerator("my_app")
generator.template_dirs = [
    "/path/to/custom/templates",
    "/path/to/default/templates"
]
```

### Custom Field Types

Define custom field types by extending the field type mapping:

```python
from pgappforge.workflow.generators.wdl_generator import WDLGenerator

class CustomWDLGenerator(WDLGenerator):
    def __init__(self, app_name: str):
        super().__init__(app_name)
        self.field_type_mapping.update({
            'custom_field': self._generate_custom_field
        })
    
    def _generate_custom_field(self, field_name: str, field_config: Dict[str, Any]) -> str:
        # Custom field generation logic
        return f"CustomField('{field_name}', **{field_config})"
```

### Custom Validators

Add custom validation functions:

```python
def custom_validator(value, field_config):
    """Custom validation function."""
    min_val = field_config.get('validation', {}).get('min', 0)
    if value < min_val:
        raise ValidationError(f"Value must be at least {min_val}")
    return value

# Register custom validator
generator.custom_validators['custom_min'] = custom_validator
```

### Conditional Field Logic

Implement conditional field display:

```yaml
fields:
  - employment_type:
      type: select
      choices: [["full_time", "Full Time"], ["contract", "Contract"]]
  
  - contract_duration:
      type: integer
      conditions:
        type: field_value
        field: employment_type
        value: contract
      validation:
        min: 1
        max: 24
```

### Workflow State Management

The generated code includes workflow state management:

```python
from pgappforge.workflow.core import WorkflowState

# Create workflow instance
workflow_state = WorkflowState(
    workflow_name="EmployeeOnboarding",
    current_step="PersonalInfo",
    data={"firstName": "John", "lastName": "Doe"}
)

# Progress to next step
workflow_state.complete_step("PersonalInfo")
workflow_state.start_step("DocumentUpload")

# Check permissions
if workflow_state.can_user_access_step(current_user, "ManagerApproval"):
    # User can access this step
    pass
```

## 🧪 Testing Generated Code

### Model Testing

```python
import pytest
from your_app.models.document_model import Document

class TestDocumentModel:
    def test_document_creation(self, db_session):
        document = Document(
            document_type="passport",
            file_name="passport.pdf",
            file_path="/uploads/passport.pdf"
        )
        db_session.add(document)
        db_session.commit()
        
        assert document.id is not None
        assert document.uploaded_at is not None
        assert document.document_type == "passport"
    
    def test_document_validation(self):
        # Test validation rules
        with pytest.raises(ValidationError):
            Document(document_type="")  # Empty type should fail
```

### View Testing

```python
import pytest
from flask import url_for

class TestPersonalInfoView:
    def test_get_personal_info_form(self, client, authenticated_user):
        response = client.get(url_for('PersonalInfoView.add'))
        assert response.status_code == 200
        assert b'Personal Information' in response.data
    
    def test_post_personal_info_valid_data(self, client, authenticated_user):
        data = {
            'firstName': 'John',
            'lastName': 'Doe',
            'email': 'john.doe@example.com',
            'phoneNumber': '+1234567890',
            'dateOfBirth': '1990-01-01',
            'address': '123 Main St, City, State'
        }
        response = client.post(url_for('PersonalInfoView.add'), data=data)
        assert response.status_code == 302  # Redirect after successful submission
    
    def test_post_personal_info_invalid_data(self, client, authenticated_user):
        data = {
            'firstName': 'J',  # Too short
            'email': 'invalid-email'
        }
        response = client.post(url_for('PersonalInfoView.add'), data=data)
        assert response.status_code == 200  # Returns form with errors
        assert b'Field must be at least 2 characters' in response.data
```

### API Testing

```python
import pytest
import json

class TestWorkflowAPI:
    def test_create_personal_info(self, client, auth_headers):
        data = {
            'firstName': 'John',
            'lastName': 'Doe',
            'email': 'john.doe@example.com'
        }
        response = client.post(
            '/api/v1/personalinfo/',
            data=json.dumps(data),
            headers={**auth_headers, 'Content-Type': 'application/json'}
        )
        assert response.status_code == 201
        
        response_data = json.loads(response.data)
        assert response_data['firstName'] == 'John'
        assert response_data['id'] is not None
    
    def test_get_personal_info_list(self, client, auth_headers):
        response = client.get('/api/v1/personalinfo/', headers=auth_headers)
        assert response.status_code == 200
        
        response_data = json.loads(response.data)
        assert 'result' in response_data
        assert isinstance(response_data['result'], list)
```

## 🔌 Extension Points

### Custom View Mixins

Extend generated views with custom functionality:

```python
from pgappforge.workflow.views import WorkflowModelView

class AuditMixin:
    def pre_add(self, item):
        item.created_by = g.user.username
        item.created_at = datetime.utcnow()
        return super().pre_add(item)
    
    def pre_update(self, item):
        item.modified_by = g.user.username
        item.modified_at = datetime.utcnow()
        return super().pre_update(item)

# Use in custom template
class CustomPersonalInfoView(AuditMixin, PersonalInfoView):
    pass
```

### Custom Form Widgets

Create custom form widgets:

```python
from pgappforge.workflow.widgets import WorkflowFormWidget

class SignaturePadWidget(WorkflowFormWidget):
    template = 'widgets/signature_pad.html'
    
    def __call__(self, field, **kwargs):
        kwargs['data-signature'] = 'true'
        return super().__call__(field, **kwargs)
```

### Custom Validators

Implement custom field validators:

```python
from wtforms.validators import ValidationError

def validate_employee_id(form, field):
    if not re.match(r'^EMP\d{4}$', field.data):
        raise ValidationError('Employee ID must be in format EMP####')

# Use in form definition
class CustomHRProcessingForm(HRProcessingForm):
    employee_id = StringField('Employee ID', validators=[
        DataRequired(),
        validate_employee_id
    ])
```

## 📈 Performance Optimization

### Database Optimization

Generated models include performance optimizations:

```python
# Automatic index generation
class Document(Model):
    __table_args__ = (
        Index('idx_document_type_date', 'document_type', 'uploaded_at'),
        Index('idx_document_status', 'verification_status'),
    )
```

### Caching

Enable caching for improved performance:

```python
from flask_caching import Cache

# In your configuration
CACHE_TYPE = 'redis'
CACHE_REDIS_URL = 'redis://localhost:6379/0'

# Generated views include caching
@cache.memoize(timeout=300)
def get_workflow_statistics():
    return db.session.query(WorkflowState).filter(
        WorkflowState.status == 'completed'
    ).count()
```

### Query Optimization

Generated code includes optimized queries:

```python
# Eager loading relationships
def get_workflow_with_steps(workflow_id):
    return db.session.query(WorkflowState).options(
        joinedload(WorkflowState.steps),
        joinedload(WorkflowState.current_step_data)
    ).filter(WorkflowState.id == workflow_id).first()
```

## 🔒 Security Considerations

### Input Validation

All generated forms include comprehensive validation:

```python
# Automatic CSRF protection
class PersonalInfoForm(FlaskForm):
    class Meta:
        csrf = True
        csrf_time_limit = 3600  # 1 hour

# SQL injection prevention through ORM
def get_user_by_email(email):
    return User.query.filter(User.email == email).first()  # Safe
```

### Access Control

Generated views implement proper access control:

```python
class ManagerApprovalView(ModelView):
    # Role-based access control
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit']
    
    # Method-level security
    @has_access
    def add(self):
        # Only users with proper role can access
        return super().add()
```

### Data Encryption

Sensitive fields are automatically encrypted:

```python
from pgappforge.workflow.security import encrypt_field, decrypt_field

# Automatic encryption for marked fields
class Employee(Model):
    salary = Column(Text)  # Encrypted field
    
    def set_salary(self, value):
        self.salary = encrypt_field(str(value))
    
    def get_salary(self):
        return float(decrypt_field(self.salary))
```

---

This API reference provides comprehensive documentation for developers working with the PgAppForge Workflow Generation system. For additional examples and advanced usage patterns, see the main documentation and example workflows.