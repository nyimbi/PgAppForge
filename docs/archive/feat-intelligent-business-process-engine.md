# PgAppForge: Business Process Enhancements

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Four focused enhancements that add basic business process capabilities to PgAppForge by building on existing components like ModelView, AuditMixin, and the security system.

## Features

### F1: Model State Tracking (1 week)
Add state management to existing PgAppForge models using a new mixin.

#### Technical Implementation
```python
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import Column, String, Text

class StateTrackingMixin(AuditMixin):
    """Add state management to PgAppForge models"""
    
    status = Column(String(50), default='draft')
    status_reason = Column(Text)
    
    def transition_to(self, new_status, reason=None):
        """Change status with audit trail"""
        old_status = self.status
        self.status = new_status
        self.status_reason = reason
        
        # Triggers existing AuditMixin change tracking
        return f"Status changed from {old_status} to {new_status}"

# Usage with existing ModelView
class ProcessModelView(ModelView):
    datamodel = SQLAInterface(ProcessModel)
    list_columns = ['name', 'status', 'created_by', 'created_on']
    edit_form_extra_fields = {
        'status': SelectField(
            'Status',
            choices=[('draft', 'Draft'), ('active', 'Active'), ('completed', 'Completed')]
        )
    }
```

#### Dependencies
- None (builds on existing AuditMixin)

#### Testing
```python
class TestStateTrackingMixin(FABTestCase):
    def test_status_transition(self):
        obj = TestModel(name="test")
        result = obj.transition_to('active', 'Ready for use')
        self.assertEqual(obj.status, 'active')
        self.assertEqual(obj.status_reason, 'Ready for use')
```

### F2: Approval Workflow Widget (1 week)
A widget that adds simple approval functionality to existing PgAppForge forms.

#### Technical Implementation
```python
from pgappforge.widgets import FormWidget
from pgappforge.security.decorators import has_access, permission_name

class ApprovalWidget(FormWidget):
    """Simple approval widget for PgAppForge forms"""
    
    template = 'appbuilder/widgets/approval.html'
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.approval_required = kwargs.get('approval_required', False)
    
    def render_approval_buttons(self, obj):
        """Render approval/rejection buttons if user has permission"""
        if not self.approval_required or obj.status != 'pending_approval':
            return ''
        
        return self.render_template(
            'widgets/approval_buttons.html',
            object_id=obj.id,
            can_approve=self.can_approve_user()
        )
    
    def can_approve_user(self):
        """Check if current user can approve using existing security"""
        from flask_login import current_user
        return current_user.has_permission('approve_records')

class ApprovalModelView(ModelView):
    """ModelView with approval capability"""
    
    edit_widget = ApprovalWidget
    
    @expose('/approve/<int:pk>')
    @has_access
    @permission_name('approve')
    def approve(self, pk):
        """Approve a record"""
        obj = self.datamodel.get(pk)
        obj.status = 'approved'
        obj.status_reason = 'Approved by admin'
        self.datamodel.edit(obj)
        
        # Send notification using existing patterns
        self._send_approval_notification(obj)
        
        flash('Record approved successfully', 'success')
        return redirect(self.get_redirect())
```

#### Dependencies
- Existing PgAppForge security system
- Existing widget infrastructure

#### Testing
```python
class TestApprovalWidget(FABTestCase):
    def test_approval_permission_required(self):
        self.login_user('approver')
        response = self.client.post('/approve/1')
        self.assertEqual(response.status_code, 200)
```

### F3: Process Status Chart (1 week)
A chart widget that extends BaseChartView to display process status distribution.

#### Technical Implementation
```python
from pgappforge.charts.views import BaseChartView
from pgappforge.models.group import GroupByProcessData

class ProcessStatusChartView(BaseChartView):
    """Chart showing process status distribution"""
    
    datamodel = SQLAInterface(ProcessModel)
    chart_title = 'Process Status Overview'
    chart_type = 'PieChart'
    chart_3d = 'true'
    
    group_by_columns = ['status']
    
    @expose('/chart')
    @has_access
    def chart(self):
        """Render process status chart using existing chart infrastructure"""
        
        # Use existing PgAppForge chart patterns
        group_by = GroupByProcessData(
            self.datamodel,
            ['status'],
            'count'
        )
        
        chart_data = group_by.apply_filter_and_group()
        
        return self.render_template(
            self.chart_template,
            chart_data=chart_data,
            chart_title=self.chart_title,
            chart_type=self.chart_type
        )

# Integration with existing dashboard
class ProcessDashboardView(BaseView):
    """Dashboard showing process metrics"""
    
    route_base = '/process-dashboard'
    
    @expose('/')
    @has_access
    def index(self):
        """Main process dashboard"""
        status_chart = ProcessStatusChartView()
        
        return self.render_template(
            'process/dashboard.html',
            status_chart_widget=status_chart.chart()
        )
```

#### Dependencies
- Existing PgAppForge chart system (`pgappforge.charts.views`)
- Existing widget infrastructure

#### Testing
```python
class TestProcessStatusChart(FABTestCase):
    def test_chart_data_generation(self):
        chart_view = ProcessStatusChartView()
        data = chart_view.get_chart_data()
        self.assertIn('draft', [item['label'] for item in data])
```

### F4: Basic Email Notifications (1 week)
Simple notification system using existing Flask-Mail integration.

#### Technical Implementation
```python
from flask_mail import Message
from pgappforge.hooks import before_model_update
from flask import current_app

class NotificationService:
    """Simple notification service using existing Flask-Mail"""
    
    def __init__(self, mail=None):
        self.mail = mail or current_app.extensions.get('mail')
    
    def send_status_notification(self, obj, old_status, new_status):
        """Send email notification for status changes"""
        
        if not self.mail or not self._should_notify(old_status, new_status):
            return
        
        # Use existing Flask-Mail patterns
        msg = Message(
            subject=f'Status Update: {obj.name}',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[self._get_notification_recipients(obj)]
        )
        
        msg.body = self._generate_notification_body(obj, old_status, new_status)
        
        try:
            self.mail.send(msg)
        except Exception as e:
            current_app.logger.warning(f'Failed to send notification: {e}')
    
    def _should_notify(self, old_status, new_status):
        """Simple logic to determine if notification should be sent"""
        notify_transitions = [
            ('pending_approval', 'approved'),
            ('pending_approval', 'rejected'),
            ('draft', 'submitted')
        ]
        return (old_status, new_status) in notify_transitions
    
    def _get_notification_recipients(self, obj):
        """Get email recipients using existing user relationships"""
        recipients = []
        
        # Notify creator (uses existing AuditMixin relationship)
        if hasattr(obj, 'created_by') and obj.created_by:
            recipients.append(obj.created_by.email)
        
        # Notify assigned users if applicable
        if hasattr(obj, 'assigned_to') and obj.assigned_to:
            recipients.append(obj.assigned_to.email)
        
        return list(filter(None, recipients))

# Integration with existing model update hooks
@before_model_update
def notify_on_status_change(mapper, connection, target):
    """Automatic notification on status changes"""
    
    if hasattr(target, 'status'):
        # Get old status from session
        old_status = getattr(target, '_original_status', None)
        new_status = target.status
        
        if old_status and old_status != new_status:
            notification_service = NotificationService()
            notification_service.send_status_notification(target, old_status, new_status)
```

#### Dependencies
- Existing Flask-Mail integration (already in setup.py)
- Existing PgAppForge hook system

#### Testing
```python
class TestNotificationService(FABTestCase):
    def test_status_change_notification(self):
        with mail.record_messages() as outbox:
            obj = TestModel()
            obj.transition_to('approved')
            self.assertEqual(len(outbox), 1)
            self.assertIn('Status Update', outbox[0].subject)
```

## Implementation Plan

### Week 1: Model State Tracking
- Implement StateTrackingMixin
- Add to mixin registry
- Create basic tests
- Update documentation

### Week 2: Approval Workflow Widget  
- Create ApprovalWidget base class
- Implement approval permissions
- Add approval endpoints
- Create approval templates

### Week 3: Process Status Chart
- Extend BaseChartView for process status
- Create dashboard integration
- Add chart configuration options
- Test with existing chart system

### Week 4: Basic Email Notifications
- Implement NotificationService
- Add model change hooks
- Configure email templates
- Test notification delivery

## Success Metrics
- All four features integrate seamlessly with existing PgAppForge patterns
- No breaking changes to existing applications
- Test coverage > 90% for new components
- Features can be adopted independently
- Documentation covers integration with existing PgAppForge components

## Migration Strategy
These features are designed as additive enhancements:
- StateTrackingMixin can be added to existing models without breaking changes
- ApprovalWidget is optional and doesn't affect existing forms
- ProcessStatusChart is a new view that doesn't modify existing functionality
- NotificationService is opt-in via configuration

Existing PgAppForge applications can adopt these features incrementally without disruption.