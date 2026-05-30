# Process Engine API Reference

Complete API documentation for PgAppForge's Process Automation Engine.

## 📚 Module Overview

| Module | Description | Location |
|--------|-------------|----------|
| `process_engine` | Core process execution engine | `pgappforge.process.engine` |
| `workflow_builder` | Workflow definition and management | `pgappforge.process.workflow` |
| `approval_system` | Multi-level approval workflows | `pgappforge.process.approval` |
| `rule_engine` | Business rules and validation | `pgappforge.process.rules` |
| `notification_manager` | Process notifications | `pgappforge.process.notifications` |
| `process_views` | Web interface for process management | `pgappforge.process.views` |

## 🏗️ Core Classes

### ProcessEngine

Central orchestrator for all process operations.

```python
class ProcessEngine:
    def __init__(
        self,
        app: Optional[Flask] = None,
        db_session: Optional[Any] = None,
        notification_manager: Optional[NotificationManager] = None,
        rule_engine: Optional[RuleEngine] = None
    ):
```

**Methods:**

#### `start_process(definition_id: str, initiator_id: int, context: Dict[str, Any] = None) -> ProcessInstance`

Start a new process instance.

```python
engine = ProcessEngine(app=app, db_session=db.session)

instance = await engine.start_process(
    definition_id="employee_onboarding",
    initiator_id=123,
    context={
        "employee_name": "John Doe",
        "department": "Engineering",
        "start_date": "2024-01-15"
    }
)
```

**Parameters:**
- `definition_id` - Process definition identifier
- `initiator_id` - User who started the process
- `context` - Initial process variables

**Returns:** `ProcessInstance` object with execution details

#### `execute_step(instance_id: str, step_id: str, action: str, actor_id: int, data: Dict[str, Any] = None) -> StepResult`

Execute a process step.

```python
result = await engine.execute_step(
    instance_id=instance.id,
    step_id="manager_approval",
    action="approve",
    actor_id=456,
    data={"comments": "Approved with conditions"}
)
```

**Parameters:**
- `instance_id` - Process instance identifier
- `step_id` - Step identifier within the process
- `action` - Action to execute (approve, reject, complete, etc.)
- `actor_id` - User performing the action
- `data` - Additional step data

**Returns:** `StepResult` with execution outcome and next steps

#### `get_process_instance(instance_id: str) -> ProcessInstance`

Retrieve process instance details.

```python
instance = await engine.get_process_instance("proc_123")
print(f"Status: {instance.status}")
print(f"Current step: {instance.current_step}")
```

#### `get_user_tasks(user_id: int, status: str = 'pending') -> List[UserTask]`

Get tasks assigned to a user.

```python
tasks = await engine.get_user_tasks(
    user_id=123,
    status='pending'
)

for task in tasks:
    print(f"Task: {task.title} - Due: {task.due_date}")
```

#### `cancel_process(instance_id: str, reason: str, canceller_id: int) -> bool`

Cancel a running process.

```python
success = await engine.cancel_process(
    instance_id="proc_123",
    reason="No longer needed",
    canceller_id=456
)
```

### WorkflowBuilder

Define and manage workflow structures.

```python
class WorkflowBuilder:
    def __init__(self, engine: ProcessEngine):
        self.engine = engine
        self.steps = []
        self.transitions = []
```

**Methods:**

#### `create_definition(name: str, description: str, version: str = "1.0") -> WorkflowDefinition`

Create a new workflow definition.

```python
builder = WorkflowBuilder(engine)

definition = builder.create_definition(
    name="Purchase Request",
    description="Multi-level purchase approval workflow",
    version="2.1"
)
```

#### `add_step(step_id: str, step_type: StepType, config: Dict[str, Any]) -> WorkflowBuilder`

Add a step to the workflow.

```python
# Human task step
builder.add_step(
    step_id="manager_review",
    step_type=StepType.HUMAN_TASK,
    config={
        "title": "Manager Review",
        "description": "Review purchase request details",
        "assignee_rule": "user.department_manager",
        "due_days": 3,
        "form_schema": {
            "fields": [
                {"name": "decision", "type": "select", "options": ["approve", "reject"]},
                {"name": "comments", "type": "textarea", "required": False}
            ]
        }
    }
)

# Service task step
builder.add_step(
    step_id="send_notification",
    step_type=StepType.SERVICE_TASK,
    config={
        "service": "notification_service",
        "method": "send_email",
        "parameters": {
            "template": "purchase_approved",
            "recipient": "${initiator.email}"
        }
    }
)

# Decision gateway
builder.add_step(
    step_id="amount_check",
    step_type=StepType.EXCLUSIVE_GATEWAY,
    config={
        "conditions": [
            {"expression": "${amount >= 10000}", "target": "cfo_approval"},
            {"expression": "${amount < 10000}", "target": "auto_approve"}
        ]
    }
)
```

#### `add_transition(from_step: str, to_step: str, condition: str = None) -> WorkflowBuilder`

Define step transitions.

```python
builder.add_transition("start", "manager_review") \
       .add_transition("manager_review", "amount_check") \
       .add_transition("amount_check", "cfo_approval", "${amount >= 10000}") \
       .add_transition("amount_check", "auto_approve", "${amount < 10000}")
```

#### `set_start_step(step_id: str) -> WorkflowBuilder`

Define the starting step.

```python
builder.set_start_step("manager_review")
```

#### `build() -> WorkflowDefinition`

Build and validate the workflow definition.

```python
definition = builder.build()
await engine.deploy_definition(definition)
```

### ProcessInstance

Represents a running process instance.

```python
@dataclass
class ProcessInstance:
    id: str
    definition_id: str
    initiator_id: int
    status: ProcessStatus
    current_step: Optional[str]
    context: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    metadata: Optional[Dict[str, Any]] = None
```

**Status Values:**
- `RUNNING` - Process is active
- `COMPLETED` - Process finished successfully
- `CANCELLED` - Process was cancelled
- `FAILED` - Process failed with error
- `SUSPENDED` - Process is temporarily paused

### UserTask

Represents a task assigned to a user.

```python
@dataclass
class UserTask:
    id: str
    process_instance_id: str
    step_id: str
    title: str
    description: str
    assignee_id: int
    status: TaskStatus
    due_date: Optional[datetime]
    form_data: Optional[Dict[str, Any]]
    created_at: datetime
    claimed_at: Optional[datetime]
    completed_at: Optional[datetime]
```

**Task Status:**
- `CREATED` - Task created but not yet assigned
- `ASSIGNED` - Task assigned to user
- `CLAIMED` - User has claimed the task
- `COMPLETED` - Task completed
- `CANCELLED` - Task was cancelled

## 🔐 Approval System

Multi-level approval workflows with delegation support.

### ApprovalChain

Define approval hierarchies and rules.

```python
class ApprovalChain:
    def __init__(self, chain_id: str, name: str):
        self.chain_id = chain_id
        self.name = name
        self.levels = []
```

**Methods:**

#### `add_level(level_id: str, approver_rule: str, required: bool = True, parallel: bool = False) -> ApprovalChain`

Add approval level to the chain.

```python
chain = ApprovalChain("purchase_approval", "Purchase Approval Chain")

chain.add_level(
    level_id="manager",
    approver_rule="user.manager",
    required=True
).add_level(
    level_id="finance",
    approver_rule="role:finance_manager",
    required=True
).add_level(
    level_id="cfo",
    approver_rule="role:cfo",
    required=False  # Only for amounts > 50k
)
```

**Approver Rules:**
- `user.manager` - User's direct manager
- `role:role_name` - Users with specific role
- `department:dept_name` - Department heads
- `expression:${...}` - Custom expression

#### `set_escalation_rule(level_id: str, timeout_hours: int, escalate_to: str) -> ApprovalChain`

Define escalation rules for timeouts.

```python
chain.set_escalation_rule(
    level_id="manager",
    timeout_hours=72,
    escalate_to="user.manager.manager"  # Skip level manager
)
```

### ApprovalRequest

Represents an approval request.

```python
@dataclass
class ApprovalRequest:
    id: str
    process_instance_id: str
    chain_id: str
    current_level: int
    status: ApprovalStatus
    context: Dict[str, Any]
    created_at: datetime
    decisions: List[ApprovalDecision]
```

**Approval Status:**
- `PENDING` - Waiting for approval
- `APPROVED` - All required approvals received
- `REJECTED` - Request was rejected
- `ESCALATED` - Escalated due to timeout

### ApprovalDecision

Individual approval decision.

```python
@dataclass
class ApprovalDecision:
    level_id: str
    approver_id: int
    decision: Decision
    comments: Optional[str]
    decided_at: datetime
    delegated_from: Optional[int] = None
```

**Decision Types:**
- `APPROVE` - Approve the request
- `REJECT` - Reject the request
- `DELEGATE` - Delegate to another user
- `REQUEST_INFO` - Request additional information

## 🎯 Rule Engine

Business rules and validation system.

### RuleEngine

Execute business rules and validations.

```python
class RuleEngine:
    def __init__(self, rule_repository: RuleRepository):
        self.repository = rule_repository
        self.evaluator = RuleEvaluator()
```

**Methods:**

#### `evaluate_rule(rule_id: str, context: Dict[str, Any]) -> RuleResult`

Evaluate a business rule.

```python
rule_engine = RuleEngine(rule_repository)

result = rule_engine.evaluate_rule(
    rule_id="expense_approval_required",
    context={
        "amount": 5000,
        "category": "software",
        "requester": user_data
    }
)

if result.passed:
    print(f"Rule passed: {result.message}")
else:
    print(f"Rule failed: {result.errors}")
```

#### `validate_transition(from_step: str, to_step: str, context: Dict[str, Any]) -> ValidationResult`

Validate step transitions.

```python
validation = rule_engine.validate_transition(
    from_step="manager_approval",
    to_step="finance_approval",
    context=process_context
)
```

### Rule Definition

Define business rules declaratively.

```python
# JSON rule definition
{
    "rule_id": "expense_limit_check",
    "name": "Expense Limit Validation",
    "conditions": [
        {
            "field": "amount",
            "operator": "<=",
            "value": "${user.expense_limit}"
        },
        {
            "field": "category",
            "operator": "in",
            "value": ["office_supplies", "software", "travel"]
        }
    ],
    "actions": [
        {
            "type": "set_variable",
            "name": "auto_approve",
            "value": true
        }
    ]
}
```

**Operators:**
- `==`, `!=` - Equality
- `>`, `>=`, `<`, `<=` - Comparison
- `in`, `not_in` - List membership
- `contains`, `starts_with`, `ends_with` - String operations
- `matches` - Regex pattern

## 📢 Notification System

Process event notifications and alerts.

### NotificationManager

Manage process notifications across channels.

```python
class NotificationManager:
    def __init__(
        self,
        email_service: Optional[EmailService] = None,
        sms_service: Optional[SMSService] = None,
        slack_service: Optional[SlackService] = None
    ):
```

**Methods:**

#### `send_task_notification(task: UserTask, notification_type: NotificationType) -> bool`

Send task-related notifications.

```python
notification_manager = NotificationManager(
    email_service=email_service,
    slack_service=slack_service
)

# Task assignment notification
await notification_manager.send_task_notification(
    task=user_task,
    notification_type=NotificationType.TASK_ASSIGNED
)

# Task reminder notification
await notification_manager.send_task_notification(
    task=overdue_task,
    notification_type=NotificationType.TASK_REMINDER
)
```

#### `send_process_notification(instance: ProcessInstance, event: ProcessEvent) -> bool`

Send process event notifications.

```python
await notification_manager.send_process_notification(
    instance=process_instance,
    event=ProcessEvent.PROCESS_COMPLETED
)
```

**Notification Types:**
- `TASK_ASSIGNED` - New task assigned
- `TASK_REMINDER` - Task deadline reminder
- `TASK_ESCALATED` - Task escalated
- `PROCESS_STARTED` - Process instance started
- `PROCESS_COMPLETED` - Process completed
- `PROCESS_CANCELLED` - Process cancelled
- `APPROVAL_REQUIRED` - Approval needed

### NotificationTemplate

Define notification templates.

```python
@dataclass
class NotificationTemplate:
    template_id: str
    name: str
    channels: List[NotificationChannel]
    subject_template: str
    body_template: str
    variables: Dict[str, str]
```

**Example Template:**
```python
template = NotificationTemplate(
    template_id="task_assigned",
    name="Task Assignment Notification",
    channels=[NotificationChannel.EMAIL, NotificationChannel.SLACK],
    subject_template="New Task: ${task.title}",
    body_template="""
    Hello ${assignee.name},

    You have been assigned a new task: ${task.title}

    Description: ${task.description}
    Due Date: ${task.due_date}
    Process: ${instance.definition.name}

    Please complete this task by logging into the system.
    """,
    variables={
        "task": "UserTask object",
        "assignee": "User object",
        "instance": "ProcessInstance object"
    }
)
```

## 🌐 REST API

Complete REST API for external integrations.

### Process Management API

#### `POST /api/v1/processes`

Start a new process instance.

**Request:**
```json
{
  "definition_id": "employee_onboarding",
  "context": {
    "employee_name": "John Doe",
    "department": "Engineering",
    "start_date": "2024-01-15"
  }
}
```

**Response:**
```json
{
  "instance_id": "proc_12345",
  "status": "running",
  "current_step": "manager_review",
  "created_at": "2024-01-10T10:00:00Z"
}
```

#### `GET /api/v1/processes/{instance_id}`

Get process instance details.

**Response:**
```json
{
  "id": "proc_12345",
  "definition_id": "employee_onboarding",
  "status": "running",
  "current_step": "manager_review",
  "context": {
    "employee_name": "John Doe",
    "department": "Engineering"
  },
  "created_at": "2024-01-10T10:00:00Z",
  "updated_at": "2024-01-10T14:30:00Z"
}
```

#### `POST /api/v1/processes/{instance_id}/steps/{step_id}/execute`

Execute a process step.

**Request:**
```json
{
  "action": "approve",
  "data": {
    "comments": "Approved with standard conditions"
  }
}
```

**Response:**
```json
{
  "success": true,
  "next_step": "hr_review",
  "message": "Step completed successfully"
}
```

### Task Management API

#### `GET /api/v1/tasks`

Get user tasks.

**Parameters:**
- `status` - Filter by task status
- `process_definition` - Filter by process type
- `due_before` - Tasks due before date
- `assigned_to` - Filter by assignee

**Response:**
```json
{
  "tasks": [
    {
      "id": "task_123",
      "title": "Review Employee Application",
      "description": "Review and approve new employee",
      "status": "assigned",
      "due_date": "2024-01-15T17:00:00Z",
      "process_instance_id": "proc_12345",
      "step_id": "manager_review"
    }
  ],
  "total": 5,
  "page": 1,
  "per_page": 20
}
```

#### `POST /api/v1/tasks/{task_id}/claim`

Claim a task for execution.

**Response:**
```json
{
  "success": true,
  "claimed_at": "2024-01-10T15:00:00Z"
}
```

#### `POST /api/v1/tasks/{task_id}/complete`

Complete a task.

**Request:**
```json
{
  "form_data": {
    "decision": "approve",
    "comments": "All documentation is complete"
  }
}
```

### Workflow Definition API

#### `POST /api/v1/workflow-definitions`

Create workflow definition.

**Request:**
```json
{
  "name": "Expense Approval",
  "description": "Multi-level expense approval workflow",
  "version": "1.0",
  "steps": [
    {
      "step_id": "manager_review",
      "type": "human_task",
      "config": {
        "title": "Manager Review",
        "assignee_rule": "user.manager"
      }
    }
  ],
  "transitions": [
    {
      "from": "start",
      "to": "manager_review"
    }
  ]
}
```

#### `GET /api/v1/workflow-definitions`

List workflow definitions.

#### `PUT /api/v1/workflow-definitions/{definition_id}/deploy`

Deploy workflow definition.

## 🔧 Configuration

### Process Engine Configuration

```python
# config.py

# Process Engine settings
PROCESS_ENGINE_ENABLED = True
PROCESS_TASK_TIMEOUT = 86400  # 24 hours default
PROCESS_MAX_INSTANCES = 10000
PROCESS_CLEANUP_INTERVAL = 3600  # 1 hour

# Database settings
PROCESS_DATABASE_URI = os.environ.get('PROCESS_DB_URL') or SQLALCHEMY_DATABASE_URI
PROCESS_POOL_SIZE = 20
PROCESS_POOL_TIMEOUT = 30

# Notification settings
PROCESS_NOTIFICATIONS_ENABLED = True
PROCESS_EMAIL_TEMPLATES_DIR = 'templates/process/email'
PROCESS_SMS_PROVIDER = 'twilio'  # twilio, nexmo
PROCESS_SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Rule engine settings
PROCESS_RULES_ENGINE = 'jsonpath'  # jsonpath, jinja2
PROCESS_RULES_CACHE_TTL = 300  # 5 minutes

# Security settings
PROCESS_REQUIRE_AUTHENTICATION = True
PROCESS_AUDIT_ENABLED = True
PROCESS_ENCRYPT_SENSITIVE_DATA = True
```

### Workflow Definition Storage

```python
# File-based definitions
WORKFLOW_DEFINITIONS_DIR = 'workflows/'

# Database-based definitions
WORKFLOW_DEFINITIONS_TABLE = 'process_definitions'

# Version control integration
WORKFLOW_GIT_REPOSITORY = 'git@github.com:org/workflows.git'
WORKFLOW_AUTO_DEPLOY = True
```

## 🔍 Monitoring & Analytics

### Process Metrics

```python
# Get process performance metrics
metrics = await engine.get_metrics(
    timeframe='24h',
    definition_id='expense_approval'
)

print(f"Instances started: {metrics['instances_started']}")
print(f"Instances completed: {metrics['instances_completed']}")
print(f"Average completion time: {metrics['avg_completion_time']}")
print(f"Success rate: {metrics['success_rate']}%")
```

### Performance Monitoring

```python
# Monitor step performance
step_metrics = await engine.get_step_metrics(
    definition_id='purchase_request',
    step_id='manager_approval'
)

print(f"Average processing time: {step_metrics['avg_processing_time']}")
print(f"Escalation rate: {step_metrics['escalation_rate']}%")
```

### Audit Trail

```python
# Get process audit trail
audit_trail = await engine.get_audit_trail(
    instance_id='proc_12345'
)

for event in audit_trail:
    print(f"{event.timestamp}: {event.actor} - {event.action}")
```

## 🚨 Error Handling

### Custom Exceptions

```python
class ProcessEngineError(Exception):
    """Base exception for process engine."""

class ProcessNotFoundError(ProcessEngineError):
    """Process instance not found."""

class InvalidTransitionError(ProcessEngineError):
    """Invalid step transition."""

class RuleEvaluationError(ProcessEngineError):
    """Business rule evaluation failed."""

class ApprovalTimeoutError(ProcessEngineError):
    """Approval timeout exceeded."""
```

### Error Response Format

```json
{
  "error": {
    "type": "InvalidTransitionError",
    "message": "Cannot transition from 'approved' to 'pending'",
    "process_instance_id": "proc_12345",
    "step_id": "manager_review",
    "code": "invalid_transition"
  }
}
```

## 🔄 Integration Patterns

### Event-Driven Integration

```python
# Listen for process events
@process_engine.on('process_completed')
async def handle_process_completion(instance: ProcessInstance):
    if instance.definition_id == 'employee_onboarding':
        await hr_system.create_employee_record(instance.context)

@process_engine.on('task_overdue')
async def handle_task_overdue(task: UserTask):
    await notification_manager.send_escalation_notification(task)
```

### External System Integration

```python
# Custom service task
class ERPIntegrationService:
    async def create_purchase_order(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create purchase order in ERP system."""
        order_data = {
            'vendor_id': context['vendor_id'],
            'amount': context['amount'],
            'items': context['items']
        }

        response = await erp_client.create_order(order_data)
        return {'order_id': response['id'], 'status': 'created'}

# Register service
engine.register_service('erp_integration', ERPIntegrationService())
```

## 📝 Best Practices

### Workflow Design
1. **Keep steps atomic** - Each step should do one thing
2. **Use clear naming** - Step IDs and names should be descriptive
3. **Define error paths** - Handle failure scenarios explicitly
4. **Minimize data size** - Keep context lean, use references for large data
5. **Version workflows** - Use semantic versioning for workflow definitions

### Performance Optimization
1. **Index database fields** - Ensure process queries are efficient
2. **Batch operations** - Process multiple tasks together when possible
3. **Cache rules** - Cache business rule evaluations
4. **Monitor metrics** - Track performance and optimize bottlenecks
5. **Archive completed** - Move old instances to archive storage

### Security Considerations
1. **Validate inputs** - Sanitize all user inputs and context data
2. **Check permissions** - Verify user permissions for each action
3. **Encrypt sensitive data** - Protect sensitive context variables
4. **Audit everything** - Log all process actions for compliance
5. **Rate limiting** - Prevent abuse of process APIs

For more detailed examples and tutorials, see:
- [Workflow Design Guide](workflow_design.md)
- [Process Integration Tutorial](../tutorials/process_automation.md)
- [Approval System Setup](approval_configuration.md)