# PgAppForge Workflow System

A comprehensive workflow management system that extends PgAppForge with powerful form sequencing, AI optimization, real-time collaboration, and intelligent automation capabilities.

## 🌟 Features

### Core Workflow Capabilities
- **Multi-step Form Sequencing**: Create ordered workflows with conditional routing
- **State Management**: Persistent workflow state across sessions
- **Dynamic Security**: Workflow-aware permissions and role-based access
- **Real-time Collaboration**: Live multi-user editing with conflict resolution
- **AI-Powered Optimization**: Ollama-based workflow insights and suggestions
- **Automatic Generation**: AI-driven workflow creation from models and templates
- **Performance Optimization**: Redis caching, query optimization, and batch processing
- **State Persistence**: Robust backup, recovery, and disaster management

### Integration with PgAppForge
- **WorkflowMixin**: Makes any model workflow-aware
- **WorkflowModelView**: Enhanced CRUD operations with workflow support
- **Workflow-aware Widgets**: Smart UI components that adapt to workflow state
- **Security Integration**: Dynamic permissions based on workflow progression
- **Template System**: Pre-built workflow templates for common use cases

## 🚀 Quick Start

### 1. Enable Workflow for a Model

```python
from pgappforge.workflow.mixins import WorkflowMixin
from pgappforge import Model

class Employee(WorkflowMixin, Model):
    __tablename__ = 'employee'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False)
    position = Column(String(100))
    department = Column(String(100))
    
    # Enable workflow
    workflow_enabled = True
    workflow_name = 'employee_onboarding'
```

### 2. Create Workflow-Enabled View

```python
from pgappforge.workflow.views import WorkflowModelView
from pgappforge.models.sqla.interface import SQLAInterface

class EmployeeView(WorkflowModelView):
    datamodel = SQLAInterface(Employee)
    
    # Define workflow steps and form ordering
    workflow_definition = {
        'name': 'employee_onboarding',
        'description': 'Employee onboarding workflow',
        'steps': [
            {
                'id': 'personal_info',
                'name': 'Personal Information',
                'fields': ['name', 'email'],
                'required_role': 'HR'
            },
            {
                'id': 'employment_details',
                'name': 'Employment Details',
                'fields': ['position', 'department'],
                'required_role': 'Manager'
            },
            {
                'id': 'review_approval',
                'name': 'Review and Approval',
                'fields': ['approval_comments'],
                'required_role': 'Director'
            }
        ]
    }

# Register with AppBuilder
appbuilder.add_view(
    EmployeeView,
    "Employees",
    icon="fa-users",
    category="HR"
)
```

### 3. Access Workflow URLs

The workflow system automatically creates these endpoints:

- `/employeeview/add/personal_info` - Start workflow at specific step
- `/employeeview/edit/1/employment_details` - Edit specific workflow step
- `/employeeview/workflow_progress/1` - View workflow progress

## 📋 Form Sequencing

### Basic Configuration

```python
workflow_definition = {
    'name': 'document_approval',
    'steps': [
        {
            'id': 'draft',
            'name': 'Create Draft',
            'fields': ['title', 'content', 'category']
        },
        {
            'id': 'review',
            'name': 'Review',
            'fields': ['review_notes', 'approved']
        },
        {
            'id': 'publish',
            'name': 'Publish',
            'fields': ['publish_date', 'featured']
        }
    ]
}
```

### Conditional Routing

```python
{
    'id': 'approval_check',
    'name': 'Approval Check',
    'fields': ['approved'],
    'conditional_logic': {
        'type': 'simple',
        'conditions': [
            {
                'field': 'approved',
                'operator': 'equals',
                'value': True,
                'next_step': 'publish'
            },
            {
                'field': 'approved',
                'operator': 'equals',
                'value': False,
                'next_step': 'revision'
            }
        ]
    }
}
```

### Advanced Validation

```python
{
    'id': 'quality_check',
    'name': 'Quality Check',
    'fields': ['content', 'images'],
    'validation_rules': {
        'conditional_required': {
            'condition_field': 'content_type',
            'condition_value': 'article',
            'required_fields': ['images'],
            'message': 'Articles must include images'
        },
        'unique_combination': {
            'fields': ['title', 'category'],
            'message': 'Title must be unique within category'
        }
    }
}
```

## 🤖 AI-Powered Optimization

### Ollama Integration

Configure Ollama for AI-powered workflow optimization:

```python
# app.config
OLLAMA_HOST = 'http://localhost:11434'
OLLAMA_MODEL = 'gpt-oss'
ENABLE_EXTERNAL_AI_PROVIDERS = False  # Use Ollama only
```

### Automatic Insights

```python
from pgappforge.workflow.ai_optimization import get_workflow_insights

# Get AI-generated optimization suggestions
insights = await get_workflow_insights('employee_onboarding')

for insight in insights:
    print(f"Confidence: {insight.confidence:.2f}")
    print(f"Description: {insight.description}")
    print("Recommendations:")
    for rec in insight.recommendations:
        print(f"  - {rec}")
```

### Performance Analytics

```python
from pgappforge.workflow.ai_optimization import analyze_workflow

# Analyze workflow performance
metrics = await analyze_workflow('employee_onboarding')

print(f"Average completion time: {metrics.avg_completion_time:.1f} seconds")
print(f"Success rate: {metrics.success_rate:.1%}")
print(f"Bottleneck steps: {metrics.bottleneck_steps}")
```

## 🔄 Real-time Collaboration

### Enable WebSocket Support

```python
from flask_socketio import SocketIO
from pgappforge.workflow.collaboration import setup_socketio_handlers

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Setup workflow collaboration handlers
setup_socketio_handlers(socketio)
```

### Frontend Integration

```javascript
// Connect to workflow collaboration
const socket = io('/collaboration');

// Join workflow session
socket.emit('join_workflow', {
    workflow_id: 'workflow_state_123',
    step_id: 'personal_info'
});

// Listen for real-time updates
socket.on('collaboration_event', (event) => {
    if (event.event_type === 'form_updated') {
        updateFormField(event.data.field_name, event.data.field_value);
    }
});

// Send form updates
socket.emit('form_field_update', {
    workflow_id: 'workflow_state_123',
    step_id: 'personal_info',
    field_name: 'email',
    field_value: 'user@example.com'
});
```

### Conflict Resolution

```python
from pgappforge.workflow.collaboration import get_collaboration_manager

manager = get_collaboration_manager()

# Resolve conflicts manually
success = manager.resolve_conflict(
    conflict_id='conflict_123',
    resolution_strategy='manual',
    resolved_value='final_value',
    resolver_user_id=current_user.id
)
```

## 🏗️ Automatic Workflow Generation

### From Model Schema

```python
from pgappforge.workflow.auto_generation import generate_workflow_for_model

# Generate workflow automatically from model
workflow_def = generate_workflow_for_model(
    Employee,
    generation_type=GenerationType.AI_SUGGESTED,
    template_name='employee_onboarding'
)

# Register with engine
engine = get_workflow_engine()
engine.register_workflow(workflow_def)
```

### Custom Templates

```python
from pgappforge.workflow.auto_generation import WorkflowTemplate

# Create custom template
template = WorkflowTemplate(
    name='product_launch',
    description='Product launch workflow template',
    steps=[
        {
            'name': 'Product Concept',
            'fields': ['name', 'description', 'target_market'],
            'grouping': 'concept'
        },
        {
            'name': 'Development Planning',
            'fields': ['features', 'timeline', 'resources'],
            'grouping': 'planning'
        }
    ],
    applicable_models=['Product', 'Project'],
    business_domain='Product Management',
    complexity_level='medium'
)

# Register template
from pgappforge.workflow.auto_generation import register_workflow_template
register_workflow_template(template)
```

### CLI Generation

```bash
# Generate workflow from command line
flask generate-workflow Employee --template employee_onboarding --type ai_suggested
```

## 💾 State Persistence & Recovery

### Automatic Snapshots

```python
from pgappforge.workflow.persistence import auto_snapshot

@auto_snapshot('checkpoint')
def update_workflow_step(workflow_state, form_data):
    workflow_state.set_form_data_for_step('current_step', form_data)
    return workflow_state
```

### Manual Backup & Recovery

```python
from pgappforge.workflow.persistence import (
    create_workflow_snapshot, recover_workflow
)

# Create snapshot
snapshot_id = create_workflow_snapshot(workflow_state, 'manual_backup')

# Recover from snapshot
success = recover_workflow(workflow_state.id, snapshot_id)
```

### Transaction Safety

```python
from pgappforge.workflow.persistence import safe_workflow_operation

# Safe operations with automatic rollback
with safe_workflow_operation(workflow_state.id) as state:
    state.current_step = 'next_step'
    state.set_form_data_for_step('next_step', form_data)
    # Automatically rolls back on exception
```

## ⚡ Performance Optimization

### Caching Configuration

```python
# app.config
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'db': 1,
    'password': None
}

WORKFLOW_PERSISTENCE_STRATEGY = 'hybrid'
WORKFLOW_BATCH_SIZE = 100
```

### Optimized Queries

```python
from pgappforge.workflow.performance import get_query_optimizer

# Apply database optimizations
optimizer = get_query_optimizer()
optimizer.optimize_workflow_queries()
```

### Batch Processing

```python
from pgappforge.workflow.performance import batched

@batched('analytics_insert')
def record_workflow_event(event_data):
    # Events are automatically batched for performance
    pass
```

### Async Processing

```python
from pgappforge.workflow.performance import async_task

@async_task('ai_analysis')
def generate_insights(workflow_name):
    # Processed asynchronously without blocking
    pass
```

## 🔒 Security Integration

### Dynamic Permissions

```python
from pgappforge.workflow.security import workflow_permission_required

@workflow_permission_required('can_edit_step', 'employee_onboarding')
def edit_employment_details():
    # Only accessible if user can edit this workflow step
    pass
```

### Role-based Workflow Access

```python
from pgappforge.workflow.security import DynamicRoleManager

# Automatic role assignment based on workflow progression
manager = DynamicRoleManager()
manager.assign_workflow_role(
    user_id=user.id,
    workflow_name='employee_onboarding',
    role_name='HR_Reviewer'
)
```

### Step-level Security

```python
{
    'id': 'salary_negotiation',
    'name': 'Salary Negotiation',
    'fields': ['salary_range', 'benefits'],
    'required_role': 'Finance_Manager',
    'additional_permissions': ['can_view_salary_data']
}
```

## 🎨 Widget System

### Smart Widgets

```python
from pgappforge.workflow.widgets import get_workflow_widget

# Progress widget
progress_widget = get_workflow_widget(
    'workflow_progress',
    workflow_state=state,
    workflow_definition=definition,
    show_navigation=True
)

# Conditional field widget
conditional_widget = get_workflow_widget(
    'conditional',
    conditions={
        'type': 'workflow_step',
        'steps': ['employment_details']
    }
)
```

### Custom Widget Creation

```python
from pgappforge.workflow.widgets import workflow_aware

@workflow_aware
class CustomWidget(BaseWidget):
    def __call__(self, field, **kwargs):
        # Widget automatically gets workflow context
        workflow_data = kwargs.get('data-workflow-conditions', {})
        return super().__call__(field, **kwargs)
```

## 📊 Monitoring & Analytics

### Built-in Analytics

```python
from pgappforge.workflow.ai_optimization import get_ai_optimizer

optimizer = get_ai_optimizer()

# Record custom events
optimizer.record_workflow_event(
    workflow_name='employee_onboarding',
    event_type='custom_validation',
    step_id='personal_info',
    success=True,
    event_data={'validation_time': 2.3}
)
```

### Performance Metrics

```python
from pgappforge.workflow.performance import get_workflow_cache

cache = get_workflow_cache()
stats = cache.get_stats()

print(f"Cache hit ratio: {stats['cache_hit_ratio']:.2%}")
print(f"Average query time: {stats['avg_query_time']:.3f}s")
```

## 🧪 Testing

### Unit Tests

```python
from pgappforge.workflow.core import WorkflowEngine, WorkflowDefinition

def test_workflow_creation():
    engine = WorkflowEngine()
    
    workflow = WorkflowDefinition(
        name='test_workflow',
        steps=[step1, step2]
    )
    
    engine.register_workflow(workflow)
    assert 'test_workflow' in engine.workflow_definitions
```

### Integration Tests

```python
def test_complete_workflow_lifecycle():
    # Create workflow
    state = engine.create_workflow_state('test_workflow', 'Entity', 1)
    
    # Advance through steps
    success = engine.advance_workflow(state, 'step_2', form_data)
    assert success
    assert state.current_step == 'step_2'
```

## 🔧 Configuration

### Required Settings

```python
# Minimum required configuration
SECRET_KEY = 'your-secret-key'
SQLALCHEMY_DATABASE_URI = 'sqlite:///workflow.db'

# Workflow-specific settings
WORKFLOW_PERSISTENCE_STRATEGY = 'hybrid'
OLLAMA_HOST = 'http://localhost:11434'
OLLAMA_MODEL = 'gpt-oss'
```

### Optional Settings

```python
# Redis configuration
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'db': 1
}

# Performance settings
WORKFLOW_BATCH_SIZE = 100
WORKFLOW_CACHE_TTL = 1800

# AI settings
ENABLE_EXTERNAL_AI_PROVIDERS = False
OPENAI_API_KEY = 'your-openai-key'  # If external providers enabled
```

## 🚀 Advanced Usage

### Custom Workflow Engine

```python
from pgappforge.workflow.core import WorkflowEngine

class CustomWorkflowEngine(WorkflowEngine):
    def _validate_step_transition(self, workflow_state, from_step, to_step, form_data=None):
        # Custom validation logic
        return super()._validate_step_transition(workflow_state, from_step, to_step, form_data)

# Use custom engine
from pgappforge.workflow import core
core._workflow_engine = CustomWorkflowEngine()
```

### Workflow Events

```python
from pgappforge.workflow.core import WorkflowEngine

engine = get_workflow_engine()

@engine.on_workflow_event('step_completed')
def handle_step_completion(workflow_state, step_id, form_data):
    # Custom logic when step is completed
    send_notification(workflow_state.entity_id, f"Step {step_id} completed")

@engine.on_workflow_event('workflow_completed')
def handle_workflow_completion(workflow_state):
    # Custom logic when workflow is completed
    generate_completion_report(workflow_state)
```

## 📚 API Reference

### Core Classes

- `WorkflowEngine`: Main workflow orchestration engine
- `WorkflowDefinition`: Workflow structure and step definitions
- `WorkflowState`: Persistent workflow state management
- `WorkflowModelView`: Enhanced ModelView with workflow support
- `WorkflowMixin`: Model mixin for workflow capabilities

### AI & Optimization

- `AIWorkflowOptimizer`: AI-powered workflow analysis and optimization
- `WorkflowInsight`: AI-generated insights and recommendations
- `PerformanceMetrics`: Workflow performance tracking

### Collaboration

- `WorkflowCollaborationManager`: Real-time collaboration management
- `CollaborationMixin`: View mixin for collaboration features

### Persistence

- `WorkflowStatePersistence`: State backup and recovery
- `WorkflowCache`: High-performance caching system

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

This workflow system is part of PgAppForge and follows the same BSD license.

## 🆘 Support

- Documentation: [PgAppForge Docs](https://flask-appbuilder.readthedocs.io/)
- Issues: [GitHub Issues](https://github.com/dpgaspar/PgAppForge/issues)
- Discussions: [GitHub Discussions](https://github.com/dpgaspar/PgAppForge/discussions)