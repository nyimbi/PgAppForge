# Intelligent Business Process Engine

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Transform Flask-AppBuilder into a comprehensive business process automation platform by adding a visual workflow designer, ML-powered triggers, approval chains, and state machine management. This feature replaces complex business logic with intuitive visual workflows that non-technical users can create and manage.

## Background/Problem Statement
Modern web applications require increasingly complex business logic involving multi-step processes, approvals, notifications, and state transitions. Current Flask-AppBuilder applications handle this through:

- Hard-coded business logic scattered across views and models
- Manual approval processes requiring developer intervention  
- Limited workflow automation capabilities
- No visual representation of business processes
- Difficulty in modifying business rules without code changes

Organizations need the ability to:
- Define business processes visually without coding
- Automate approval workflows with escalation
- Track process execution and performance
- Integrate ML-powered decision making
- Allow business users to modify workflows independently

## Goals
- **Visual Process Designer**: Drag-and-drop workflow creation interface
- **Smart Automation**: ML-powered event detection and automated responses  
- **Approval Management**: Complex approval chains with escalation and delegation
- **State Machine Engine**: Robust state transition management for business objects
- **Process Analytics**: Real-time monitoring and performance metrics
- **Integration Ready**: Seamless integration with existing Flask-AppBuilder models and views
- **User Empowerment**: Enable business users to create and modify workflows

## Non-Goals
- Full-featured BPM suite (focus on Flask-AppBuilder integration)
- Replace existing Flask-AppBuilder security model
- Complex process mining or discovery features
- Advanced workflow simulation capabilities
- Integration with external BPM standards (BPMN, XPDL) in Phase 1

## Technical Dependencies

### External Libraries
- **NetworkX >= 3.0**: Process graph modeling and analysis
- **Celery >= 5.3.0**: Asynchronous task execution for process steps
- **Redis >= 4.0**: Process state caching and message queuing
- **SQLAlchemy-Utils >= 0.41.0**: Enhanced model utilities (already included)
- **Marshmallow >= 3.18.0**: Process definition serialization (already included)

### Internal Dependencies
- Flask-AppBuilder security system for access control
- Existing mixin architecture for audit trails
- Widget system for process designer UI components
- Real-time collaboration system for concurrent process editing

## Detailed Design

### Architecture Overview
```
┌─────────────────────────────────────────────────────────────────┐
│                    Business Process Engine                      │
├─────────────────────────────────────────────────────────────────┤
│  Process Designer UI  │  Process Runtime  │  Smart Triggers     │
│  ┌─────────────────┐  │  ┌─────────────┐  │  ┌─────────────────┐ │
│  │ Visual Designer │  │  │ State Engine│  │  │ ML Event Detect │ │
│  │ Node Library    │  │  │ Task Queue  │  │  │ Auto Responses  │ │
│  │ Canvas Manager  │  │  │ Executors   │  │  │ Condition Logic │ │
│  └─────────────────┘  │  └─────────────┘  │  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                       Core Data Models                         │
│  ProcessDefinition │ ProcessInstance │ ProcessStep │ ProcessLog │
├─────────────────────────────────────────────────────────────────┤
│                   Flask-AppBuilder Foundation                  │
│    Security │ Models │ Views │ Widgets │ Collaboration         │
└─────────────────────────────────────────────────────────────────┘
```

### Core Data Models

#### ProcessDefinition
```python
class ProcessDefinition(AuditMixin, Model):
    __tablename__ = 'ab_process_definitions'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default='draft')  # draft, active, deprecated
    
    # Process graph structure (JSON)
    process_graph = Column(JSONB, nullable=False)
    
    # Configuration
    settings = Column(JSONB, default=lambda: {})
    category = Column(String(50))
    tags = Column(JSONB, default=lambda: [])
    
    # Relationships
    instances = relationship("ProcessInstance", back_populates="definition")
    
    @hybrid_property
    def node_count(self):
        return len(self.process_graph.get('nodes', []))
```

#### ProcessInstance  
```python
class ProcessInstance(AuditMixin, Model):
    __tablename__ = 'ab_process_instances'
    
    id = Column(Integer, primary_key=True)
    process_definition_id = Column(Integer, ForeignKey('ab_process_definitions.id'))
    
    # Instance metadata
    name = Column(String(100))
    status = Column(String(20), default='running')  # running, completed, failed, suspended
    current_step = Column(String(100))
    
    # Context data
    context = Column(JSONB, default=lambda: {})
    input_data = Column(JSONB, default=lambda: {})
    output_data = Column(JSONB, default=lambda: {})
    
    # Timing
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    # Relationships
    definition = relationship("ProcessDefinition", back_populates="instances")
    steps = relationship("ProcessStep", back_populates="instance")
    logs = relationship("ProcessLog", back_populates="instance")
```

### Visual Process Designer

#### Frontend Components (JavaScript/React-style pseudocode)
```javascript
// Process Designer Canvas
class ProcessDesigner extends React.Component {
    constructor(props) {
        super(props);
        this.state = {
            nodes: [],
            edges: [],
            selectedNode: null,
            draggedNode: null
        };
    }
    
    // Node types available in palette
    nodeTypes = {
        'start': { icon: '▶️', name: 'Start Event' },
        'end': { icon: '⏹️', name: 'End Event' },
        'task': { icon: '📋', name: 'User Task' },
        'service': { icon: '⚙️', name: 'Service Task' },
        'gateway': { icon: '◆', name: 'Decision Gateway' },
        'approval': { icon: '✅', name: 'Approval Task' },
        'notification': { icon: '📧', name: 'Notification' }
    };
    
    render() {
        return (
            <div className="process-designer">
                <NodePalette nodeTypes={this.nodeTypes} />
                <ProcessCanvas 
                    nodes={this.state.nodes}
                    edges={this.state.edges}
                    onNodeAdd={this.addNode}
                    onNodeConnect={this.connectNodes}
                />
                <PropertyPanel node={this.state.selectedNode} />
            </div>
        );
    }
}
```

#### Process Runtime Engine

```python
class ProcessEngine:
    def __init__(self, redis_client, celery_app):
        self.redis = redis_client
        self.celery = celery_app
        self.state_machine = ProcessStateMachine()
    
    def start_process(self, definition_id: int, input_data: dict, 
                     initiated_by: int) -> ProcessInstance:
        """Start a new process instance"""
        definition = ProcessDefinition.query.get(definition_id)
        
        instance = ProcessInstance(
            process_definition_id=definition_id,
            input_data=input_data,
            context={'initiated_by': initiated_by},
            status='running'
        )
        db.session.add(instance)
        db.session.commit()
        
        # Execute first step
        self._execute_next_step(instance)
        
        return instance
    
    def _execute_next_step(self, instance: ProcessInstance):
        """Execute the next step in the process"""
        current_node = self._get_current_node(instance)
        
        if current_node['type'] == 'task':
            self._execute_user_task(instance, current_node)
        elif current_node['type'] == 'service':
            self._execute_service_task.delay(instance.id, current_node)
        elif current_node['type'] == 'gateway':
            self._evaluate_gateway(instance, current_node)
        elif current_node['type'] == 'approval':
            self._execute_approval_task(instance, current_node)
```

### Smart Triggers & ML Integration

```python
class SmartTriggerEngine:
    def __init__(self):
        self.ml_model = self._load_ml_model()
        self.trigger_rules = []
    
    def register_trigger(self, trigger_def: dict):
        """Register ML-powered trigger"""
        trigger = {
            'id': trigger_def['id'],
            'conditions': trigger_def['conditions'],
            'ml_features': trigger_def.get('ml_features', []),
            'action': trigger_def['action'],
            'confidence_threshold': trigger_def.get('threshold', 0.8)
        }
        self.trigger_rules.append(trigger)
    
    def evaluate_triggers(self, event_data: dict):
        """Evaluate if any triggers should fire"""
        for trigger in self.trigger_rules:
            if self._evaluate_conditions(trigger, event_data):
                confidence = self._ml_predict(trigger, event_data)
                
                if confidence >= trigger['confidence_threshold']:
                    self._execute_trigger_action(trigger, event_data, confidence)
    
    def _ml_predict(self, trigger: dict, event_data: dict) -> float:
        """Use ML model to predict if trigger should fire"""
        features = self._extract_features(trigger['ml_features'], event_data)
        return self.ml_model.predict_proba([features])[0][1]
```

### Approval Chain Management

```python
class ApprovalChain:
    def __init__(self, chain_definition: dict):
        self.definition = chain_definition
        self.current_level = 0
        
    def start_approval(self, process_instance: ProcessInstance, 
                      approval_data: dict):
        """Start approval process"""
        approval = ApprovalRequest(
            process_instance_id=process_instance.id,
            data=approval_data,
            chain_definition=self.definition,
            current_level=0,
            status='pending'
        )
        
        # Send to first approver
        self._send_approval_request(approval, self.definition['levels'][0])
        
        return approval
    
    def process_approval_response(self, approval_id: int, 
                                 response: str, approver_id: int):
        """Process approver's response"""
        approval = ApprovalRequest.query.get(approval_id)
        
        # Record response
        approval.responses.append({
            'level': approval.current_level,
            'approver_id': approver_id,
            'response': response,  # approved, rejected, delegated
            'timestamp': datetime.utcnow().isoformat(),
            'comments': request.json.get('comments', '')
        })
        
        if response == 'approved':
            self._advance_approval_level(approval)
        elif response == 'rejected':
            self._reject_approval(approval)
        elif response == 'delegated':
            self._delegate_approval(approval, request.json['delegate_to'])
```

## User Experience

### Process Designer Interface
1. **Drag-and-Drop Canvas**: Users drag process nodes from palette to canvas
2. **Node Configuration**: Click nodes to configure properties, conditions, and actions
3. **Connection Management**: Draw arrows between nodes to define process flow
4. **Real-time Validation**: Instant feedback on process definition errors
5. **Collaboration Support**: Multiple users can edit processes simultaneously

### Process Execution Dashboard  
1. **Instance Monitoring**: View all running, completed, and failed process instances
2. **Step-by-Step Progress**: Visual progress indicator showing current step
3. **Task Queues**: Personal task lists for approvals and user tasks
4. **Performance Analytics**: Process execution times, bottlenecks, and success rates

### Approval Interface
1. **Approval Inbox**: Centralized list of pending approvals
2. **Context-Rich Display**: Show relevant data and process history for decisions
3. **Delegation Options**: Forward approvals to colleagues with comments
4. **Mobile-Friendly**: Responsive design for mobile approval workflows

## Testing Strategy

### Unit Tests
```python
class TestProcessEngine(unittest.TestCase):
    """Test the core process execution engine"""
    
    def test_start_simple_process(self):
        """Verify basic process instantiation and execution"""
        # Purpose: Ensures the engine can start and execute simple linear processes
        definition = create_test_process_definition()
        engine = ProcessEngine(redis_client, celery_app)
        
        instance = engine.start_process(
            definition.id, 
            {'customer_id': 123}, 
            initiated_by=1
        )
        
        self.assertEqual(instance.status, 'running')
        self.assertIsNotNone(instance.current_step)
        # This test can fail if process engine has initialization issues
    
    def test_gateway_evaluation(self):
        """Test conditional gateway decision logic"""
        # Purpose: Validates that decision gateways route correctly based on data
        gateway_node = {
            'type': 'gateway',
            'conditions': [
                {'field': 'amount', 'operator': '>', 'value': 1000, 'target': 'approval'},
                {'default': True, 'target': 'auto_approve'}
            ]
        }
        
        # Test high amount routing
        context_high = {'amount': 5000}
        next_node = evaluate_gateway(gateway_node, context_high)
        self.assertEqual(next_node, 'approval')
        
        # Test low amount routing  
        context_low = {'amount': 500}
        next_node = evaluate_gateway(gateway_node, context_low)
        self.assertEqual(next_node, 'auto_approve')
        # This test can fail if gateway logic has bugs
```

### Integration Tests
```python
class TestProcessIntegration(FABTestCase):
    """Test process engine integration with Flask-AppBuilder"""
    
    def test_process_with_approval_chain(self):
        """Test complete process with multi-level approvals"""
        # Purpose: Ensures processes work end-to-end with real approval workflows
        process_def = self.create_expense_approval_process()
        
        # Start expense approval process
        with self.app.test_client() as client:
            self.login(client, 'employee', 'password')
            
            response = client.post('/process/start', json={
                'definition_id': process_def.id,
                'expense_data': {
                    'amount': 2500,
                    'category': 'travel',
                    'description': 'Conference attendance'
                }
            })
            
            self.assertEqual(response.status_code, 201)
            
            # Verify approval task created
            approval = ApprovalRequest.query.filter_by(
                process_instance_id=response.json['instance_id']
            ).first()
            self.assertIsNotNone(approval)
            # This test can fail if approval chain integration breaks
```

### E2E Tests
```python
class TestProcessDesigner(SeleniumTestCase):
    """End-to-end tests for the visual process designer"""
    
    def test_create_process_visually(self):
        """Test creating a process using drag-and-drop interface"""
        # Purpose: Validates the visual designer works for non-technical users
        driver = self.driver
        
        # Open process designer
        driver.get(f"{self.base_url}/process/designer/new")
        
        # Drag start node to canvas
        start_node = driver.find_element(By.CSS_SELECTOR, "[data-node-type='start']")
        canvas = driver.find_element(By.CLASS_NAME, "process-canvas")
        
        ActionChains(driver).drag_and_drop(start_node, canvas).perform()
        
        # Verify node appears on canvas
        canvas_nodes = driver.find_elements(By.CSS_SELECTOR, ".process-canvas .node")
        self.assertEqual(len(canvas_nodes), 1)
        # This test can fail if drag-and-drop functionality breaks
```

### Mocking Strategies
- **ML Model Mocking**: Mock ML predictions for consistent testing
- **Celery Task Mocking**: Mock async task execution for faster tests
- **Email/Notification Mocking**: Mock external notification systems

## Performance Considerations

### Process Execution Performance
- **Async Task Processing**: Use Celery for non-blocking process step execution
- **Redis Caching**: Cache frequently accessed process definitions and state
- **Database Indexing**: Index process instance status and current step fields
- **Batch Operations**: Process multiple instances in batches where possible

### Designer Interface Performance  
- **Canvas Virtualization**: Only render visible portions of large process diagrams
- **Debounced Saves**: Prevent excessive database writes during editing
- **Progressive Loading**: Load process definitions on demand
- **WebSocket Updates**: Real-time collaboration without polling

### Scalability Strategies
- **Horizontal Scaling**: Distribute process execution across multiple workers
- **Database Partitioning**: Partition process instances by date or tenant
- **CDN Integration**: Cache static designer assets
- **Connection Pooling**: Optimize database connections for high throughput

## Security Considerations

### Access Control
- **Process-Level Permissions**: Control who can create, edit, and execute processes
- **Step-Level Security**: Restrict access to specific process steps by role
- **Data Privacy**: Ensure sensitive data in process context is encrypted
- **Audit Trails**: Complete logging of all process actions and approvals

### Input Validation
- **Process Definition Validation**: Prevent malicious process structures
- **Context Data Sanitization**: Sanitize all user inputs in process context
- **ML Model Security**: Prevent adversarial attacks on trigger models
- **File Upload Security**: Secure handling of process-related file attachments

### External Integration Security
- **API Authentication**: Secure integration with external services
- **Rate Limiting**: Prevent abuse of process execution endpoints
- **Network Security**: Secure communication with external systems
- **Credential Management**: Secure storage of service credentials

## Documentation

### User Documentation
- **Process Designer Guide**: Step-by-step tutorial for creating workflows
- **Approval Management Manual**: Guide for setting up approval chains
- **Administrator Handbook**: Process engine configuration and maintenance
- **Integration Examples**: Sample processes for common business scenarios

### Developer Documentation  
- **API Reference**: Complete REST API documentation for process operations
- **Extension Guide**: How to create custom process node types
- **ML Integration Guide**: Adding custom ML models for smart triggers
- **Database Schema**: Complete schema documentation with relationships

### Training Materials
- **Video Tutorials**: Screen recordings of common process creation tasks
- **Best Practices Guide**: Recommended patterns for efficient processes
- **Troubleshooting Guide**: Common issues and resolution steps
- **Migration Guide**: Upgrading existing workflows to new process engine

## Implementation Phases

### Phase 1: MVP/Core Functionality
**Foundation & Basic Workflows**
- Core data models (ProcessDefinition, ProcessInstance, ProcessStep)
- Basic process execution engine with linear workflows
- Simple visual designer with drag-and-drop capability
- User task and service task node types
- Basic approval workflow (single-level)
- Process instance monitoring dashboard
- REST API for process operations

**Success Criteria:**
- Can create simple linear processes visually
- Execute processes with user tasks and approvals
- Monitor running process instances
- Basic security integration with Flask-AppBuilder

### Phase 2: Enhanced Features  
**Advanced Workflows & Intelligence**
- Decision gateways with conditional logic
- Multi-level approval chains with escalation
- Smart triggers with basic ML integration
- Process analytics and performance metrics
- Real-time collaboration on process design
- Process versioning and deployment
- Custom node type framework

**Success Criteria:**
- Support complex branching workflows
- ML-powered event detection working
- Performance analytics providing insights
- Multiple users can collaborate on process design

### Phase 3: Polish and Optimization
**Production Readiness & Advanced Features**
- Advanced ML models for intelligent automation  
- Process mining and optimization suggestions
- Mobile-responsive approval interface
- Advanced visualization and reporting
- Process template marketplace
- Performance optimizations and caching
- Comprehensive monitoring and alerting

**Success Criteria:**
- Production-grade performance and reliability
- Advanced analytics providing business insights
- Mobile workflow approval fully functional
- Comprehensive documentation and training materials

## Open Questions

1. **ML Model Selection**: Which ML algorithms should we use for different trigger types?
2. **Process Storage Format**: Should we use BPMN XML or custom JSON format for process definitions?
3. **Real-time Updates**: How frequently should we update process instance status in the UI?
4. **External Integrations**: Which external systems should have first-class integration support?
5. **Process Versioning**: How should we handle versioning and migration of active process instances?
6. **Performance Thresholds**: What are acceptable latency thresholds for process step execution?
7. **Multi-tenancy**: How should process definitions be isolated in multi-tenant deployments?

## References

### Related Flask-AppBuilder Components
- [Wizard Forms Implementation](../flask_appbuilder/forms/wizard.py) - State management patterns
- [Collaboration System](../flask_appbuilder/collaboration/) - Real-time sync patterns  
- [Security Framework](../flask_appbuilder/security/) - Permission integration
- [Mixin Architecture](../flask_appbuilder/mixins/) - Reusable component patterns

### External Libraries
- [NetworkX Documentation](https://networkx.org/documentation/) - Graph algorithms and data structures
- [Celery User Guide](https://docs.celeryq.dev/) - Distributed task execution
- [Redis Documentation](https://redis.io/docs/) - In-memory data structure store
- [SQLAlchemy-Utils](https://sqlalchemy-utils.readthedocs.io/) - Enhanced model utilities

### Design Patterns
- [Workflow Pattern](https://www.enterpriseintegrationpatterns.com/patterns/messaging/ProcessManager.html) - Enterprise workflow management
- [State Machine Pattern](https://refactoring.guru/design-patterns/state) - State transition management
- [Command Pattern](https://refactoring.guru/design-patterns/command) - Process step execution
- [Observer Pattern](https://refactoring.guru/design-patterns/observer) - Event-driven triggers