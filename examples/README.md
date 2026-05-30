# 📚 Workflow Examples

This directory contains comprehensive examples of workflow definitions for different use cases. Each example demonstrates specific patterns and features of the JHipster-inspired Flask-AppBuilder Workflow System.

## 🎯 Available Examples

### 1. **Employee Onboarding** (`employee_onboarding.yaml`)
**Complete enterprise HR workflow with approval chains**

- ✅ Multi-step forms with validation
- ✅ Role-based permissions (Employee → Manager → HR)
- ✅ File upload requirements
- ✅ Complex field validation
- ✅ Email notifications
- ✅ Audit trails

**Use Cases**: HR departments, employee lifecycle management

### 2. **Product Review** (`product_review.yaml`) 
**Customer review and moderation workflow**

- ✅ Public submission forms
- ✅ Content moderation
- ✅ Rating systems
- ✅ Image uploads
- ✅ Simple approval process

**Use Cases**: E-commerce platforms, review systems

### 3. **Purchase Approval** (`purchase_approval.yaml`)
**Enterprise procurement with multi-level approvals**

- ✅ Budget-based approval routing
- ✅ Conditional logic
- ✅ Multiple approval levels
- ✅ Vendor management
- ✅ Purchase order generation

**Use Cases**: Corporate procurement, expense management

### 4. **Customer Support** (`customer_support.yaml`)
**Ticket management and escalation workflow**

- ✅ Ticket classification
- ✅ SLA management
- ✅ Escalation rules
- ✅ Knowledge base integration
- ✅ Customer communication

**Use Cases**: Help desk systems, customer service

### 5. **Project Proposal** (`project_proposal.yaml`)
**Research and development proposal approval**

- ✅ Collaborative editing
- ✅ Peer review process
- ✅ Budget approval
- ✅ Resource allocation
- ✅ Timeline management

**Use Cases**: R&D departments, grant applications

### 6. **Invoice Processing** (`invoice_processing.yaml`)
**Accounts payable automation workflow**

- ✅ OCR data extraction
- ✅ Three-way matching
- ✅ Approval hierarchies
- ✅ Payment processing
- ✅ Exception handling

**Use Cases**: Finance departments, AP automation

### 7. **Content Publishing** (`content_publishing.yaml`)
**Editorial workflow for content management**

- ✅ Draft creation
- ✅ Editorial review
- ✅ SEO optimization
- ✅ Publishing schedule
- ✅ Content versioning

**Use Cases**: Publishing platforms, content management

### 8. **Equipment Request** (`equipment_request.yaml`)
**IT asset management and provisioning**

- ✅ Asset catalog integration
- ✅ Manager approval
- ✅ IT provisioning
- ✅ Asset tracking
- ✅ Return processing

**Use Cases**: IT departments, asset management

## 🚀 Quick Start with Examples

### Run Any Example

```bash
# 1. Choose an example
cd examples

# 2. Validate the workflow
flask fab workflow validate employee_onboarding.yaml

# 3. Generate application code
flask fab workflow generate employee_onboarding.yaml --app-name hr_system

# 4. See what would be generated (dry run)
flask fab workflow generate customer_support.yaml --app-name support_app --dry-run
```

### Initialize from Template

```bash
# Create a new workflow based on example patterns
flask fab workflow init my_workflow --template approval
flask fab workflow init my_workflow --template crud  
flask fab workflow init my_workflow --template basic
```

## 📊 Example Patterns

### Basic CRUD Pattern
```yaml
WorkflowName:
  steps:
    Create: {title: "Create Record", icon: "plus"}
    Edit: {title: "Edit Record", icon: "edit"}
    Delete: {title: "Delete Record", icon: "trash"}
```

### Approval Chain Pattern
```yaml
WorkflowName:
  steps:
    Submit: {permissions: {edit: ["user"]}}
    Review: {permissions: {edit: ["manager"]}}
    Approve: {permissions: {edit: ["admin"]}}
```

### Conditional Routing Pattern
```yaml
WorkflowName:
  steps:
    Assessment:
      fields:
        - amount: {type: float}
    ManagerApproval:
      conditions:
        - field: amount
          operator: greater_than
          value: 1000
    AutoApprove:
      conditions:
        - field: amount
          operator: less_than_or_equal
          value: 1000
```

### File Processing Pattern
```yaml
WorkflowName:
  features:
    file_upload: true
    max_file_size: 10485760  # 10MB
  steps:
    Upload:
      fields:
        - document: {type: file, accept: [".pdf", ".doc"]}
    Process:
      description: "Automated document processing"
    Review:
      fields:
        - extracted_data: {type: textarea, readonly: true}
```

## 🎨 Customization Examples

### Custom Field Validation
```yaml
fields:
  - employee_id:
      type: string
      validation:
        pattern: "^EMP[0-9]{4}$"
        custom: validate_unique_employee_id
  - salary:
      type: float
      validation:
        min: 30000
        max: 500000
        custom: validate_salary_range
```

### Dynamic Permissions
```yaml
permissions:
  RequestForm:
    view: ["public"]
    edit: ["user"]
  ManagerReview:
    view: ["manager", "admin"]
    edit: 
      - role: "manager"
        condition: "amount < 10000"
      - role: "admin"
```

### Notification Templates
```yaml
notifications:
  email:
    templates:
      step_completed: |
        Hi {user.first_name},
        
        The step "{step.title}" has been completed for {workflow.title}.
        
        Next steps: {next_steps}
        
        Best regards,
        The Workflow System
      
  slack:
    enabled: true
    templates:
      approval_needed: |
        🔔 Approval Needed
        
        *{workflow.title}*
        Submitted by: {user.name}
        Amount: ${amount:,.2f}
        
        [Review Now]({approval_url})
```

### Advanced UI Configuration
```yaml
ui:
  theme: "custom-theme.css"
  logo: "/static/img/company-logo.png"
  colors:
    primary: "#007bff"
    success: "#28a745"
    warning: "#ffc107"
    danger: "#dc3545"
  layout:
    sidebar: true
    breadcrumbs: true
    progress_bar: true
  components:
    step_navigation: true
    auto_save_indicator: true
    field_hints: true
```

## 🧪 Testing Examples

Each example includes comprehensive tests. Run them to understand the testing patterns:

```bash
# Generate test suite for an example
flask fab workflow generate employee_onboarding.yaml --app-name test_app

# Run generated tests
cd test_app
python -m pytest tests/test_employee_onboarding.py -v

# Run specific test types
python -m pytest tests/test_employee_onboarding.py::TestModels -v
python -m pytest tests/test_employee_onboarding.py::TestViews -v
python -m pytest tests/test_employee_onboarding.py::TestAPI -v
```

## 🔧 Integration Examples

### Flask-AppBuilder Integration
```python
# app/__init__.py
from flask_appbuilder import AppBuilder

# Import generated components
from .models.employee_model import Employee
from .views.onboarding_view import OnboardingView

# Register with AppBuilder
appbuilder.add_view(
    OnboardingView,
    "Employee Onboarding",
    icon="fa-user-plus",
    category="HR"
)
```

### API Integration
```python
# external_integration.py
import requests

# Use generated API
response = requests.post('http://localhost:8080/api/v1/employee_onboarding/', json={
    'firstName': 'John',
    'lastName': 'Doe',
    'email': 'john.doe@company.com'
})

if response.status_code == 201:
    employee_id = response.json()['id']
    print(f"Employee created with ID: {employee_id}")
```

### Database Integration
```python
# custom_queries.py
from sqlalchemy import func
from .models.employee_model import Employee

# Custom business logic using generated models
def get_onboarding_statistics():
    return {
        'total_employees': Employee.query.count(),
        'pending_onboarding': Employee.query.filter(
            Employee.onboarding_status == 'in_progress'
        ).count(),
        'completed_this_month': Employee.query.filter(
            func.date_trunc('month', Employee.onboarding_completed_at) == 
            func.date_trunc('month', func.now())
        ).count()
    }
```

## 📚 Learning Path

### Beginner
1. Start with `product_review.yaml` (simple workflow)
2. Try `equipment_request.yaml` (basic approval)
3. Generate and run these examples

### Intermediate  
1. Study `employee_onboarding.yaml` (complex forms)
2. Explore `purchase_approval.yaml` (conditional logic)
3. Customize generated code

### Advanced
1. Examine `invoice_processing.yaml` (complex integrations)
2. Study `content_publishing.yaml` (collaborative workflows)
3. Build custom templates and extensions

## 🎯 Best Practices from Examples

### Workflow Design
- **Keep steps focused**: Single responsibility per step
- **Use clear naming**: Descriptive step and field names
- **Plan permissions early**: Security-first approach
- **Consider user journey**: Logical flow and clear instructions

### Field Configuration
- **Use appropriate types**: Email for emails, date for dates
- **Add validation**: Prevent bad data early
- **Provide placeholders**: Guide user input
- **Set reasonable limits**: Balance usability with constraints

### Performance Optimization
- **Index frequently queried fields**: Speed up searches
- **Use lazy loading**: For large relationships
- **Cache expensive operations**: Reduce database load
- **Optimize file uploads**: Reasonable size limits

### Security Considerations
- **Apply least privilege**: Minimal necessary permissions
- **Validate all inputs**: Never trust user data
- **Encrypt sensitive data**: Use built-in encryption
- **Enable audit trails**: Track all changes

## 🆘 Common Issues and Solutions

### Issue: Generated code doesn't work
**Solution**: Check that all imports are correct and dependencies installed

### Issue: Permission errors
**Solution**: Ensure roles exist and are properly assigned to users

### Issue: File upload fails
**Solution**: Check file size limits and allowed extensions configuration

### Issue: Database migration errors
**Solution**: Ensure no conflicting migrations and database is accessible

### Issue: Templates not found
**Solution**: Verify template directories and Flask-AppBuilder configuration

## 🤝 Contributing Examples

Want to contribute a new example? Follow these guidelines:

1. **Create clear documentation**: Explain the use case and features
2. **Include comprehensive fields**: Demonstrate various field types
3. **Add proper validation**: Show validation patterns
4. **Configure permissions**: Demonstrate RBAC
5. **Test thoroughly**: Ensure example works end-to-end
6. **Follow naming conventions**: Consistent with existing examples

### Example Template
```yaml
YourWorkflowName:
  version: "1.0.0"
  description: "Clear description of what this workflow does"
  
  # Add helpful comments
  entities:
    # Define your data models
  
  steps:
    # Define workflow steps with clear names
  
  permissions:
    # Set appropriate permissions
  
  features:
    # Configure relevant features
```

---

**🎉 Explore these examples to master workflow development with Flask-AppBuilder!**

For more information, see the [main documentation](../docs/JHIPSTER_WORKFLOW_SYSTEM.md) and [API reference](../docs/API_REFERENCE.md).