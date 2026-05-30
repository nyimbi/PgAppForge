"""
Intelligent Business Process Engine for PgForge.

This module provides comprehensive business process automation capabilities including:
- Visual workflow designer with drag-and-drop interface
- ML-powered smart triggers and event detection
- Multi-level approval chains with escalation
- State machine-based process execution
- Real-time process monitoring and analytics
- Integration with PgForge security and multi-tenant architecture
"""

__version__ = "1.0.0"
__author__ = "PgForge Process Engine"

from .engine.process_engine import ProcessEngine
from .engine.process_service import ProcessService, get_process_service
from .manager import ProcessManager, get_process_manager
from .models.process_models import (
    ProcessDefinition,
    ProcessInstance,
    ProcessStep,
    ProcessLog,
    ApprovalRequest,
    SmartTrigger
)

__all__ = [
    'ProcessEngine',
    'ProcessService', 
    'ProcessManager',
    'get_process_service',
    'get_process_manager',
    'ProcessDefinition',
    'ProcessInstance', 
    'ProcessStep',
    'ProcessLog',
    'ApprovalRequest',
    'SmartTrigger'
]