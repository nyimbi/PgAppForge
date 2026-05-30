"""
Flask-AppBuilder Workflow Core Integration

This module provides comprehensive workflow capabilities integrated directly into Flask-AppBuilder,
enabling every ModelView and form to be part of an orchestrated business process with form ordering,
state management, and intelligent routing.

Key Features:
- Workflow-aware ModelViews with form sequencing
- Dynamic CRUD operations based on workflow state
- Real-time collaborative workflows
- AI-powered workflow optimization
- Automatic workflow generation from model relationships
"""

__version__ = "1.0.0"
__author__ = "Flask-AppBuilder Workflow Team"

from .core import WorkflowEngine, WorkflowState, WorkflowStepDefinition
from .views import WorkflowModelView, WorkflowFormView
from .mixins import WorkflowMixin, WorkflowStateMixin
from .security import WorkflowPermission, DynamicRoleManager
from .widgets import WorkflowFormWidget, WorkflowProgressWidget, ConditionalFieldWidget
from .forms import WorkflowFormSequence, FormOrchestrator

__all__ = [
    'WorkflowEngine',
    'WorkflowState',
    'WorkflowStepDefinition',
    'WorkflowModelView',
    'WorkflowFormView',
    'WorkflowMixin',
    'WorkflowStateMixin',
    'WorkflowPermission',
    'DynamicRoleManager',
    'WorkflowFormWidget',
    'WorkflowProgressWidget',
    'ConditionalFieldWidget',
    'WorkflowFormSequence',
    'FormOrchestrator'
]