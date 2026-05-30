"""
Process Service - Synchronous Wrapper for Async ProcessEngine.

Provides synchronous interface for Flask-AppBuilder views to interact
with the async ProcessEngine, following Flask-AppBuilder patterns.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

from .process_engine import ProcessEngine
from ..models.process_models import ProcessDefinition, ProcessInstance, ProcessStep

log = logging.getLogger(__name__)


class ProcessService:
    """
    Synchronous wrapper for async ProcessEngine operations.
    
    Provides Flask-AppBuilder compatible synchronous interface while
    maintaining the async capabilities of the underlying ProcessEngine.
    """
    
    def __init__(self, engine: ProcessEngine = None):
        """Initialize the process service."""
        self.engine = engine or ProcessEngine()
        self._loop = None
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    def _get_loop(self):
        """Get or create event loop for async operations."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop
    
    def _run_async(self, coro):
        """Run async coroutine in sync context safely."""
        try:
            loop = self._get_loop()
            return loop.run_until_complete(coro)
        except Exception as e:
            log.error(f"Error running async operation: {e}")
            raise
    
    def start_process(self, definition_id: int, input_data: Dict[str, Any] = None,
                     initiated_by: int = None, instance_name: str = None,
                     priority: int = 5) -> ProcessInstance:
        """
        Start a new process instance synchronously.
        
        Args:
            definition_id: Process definition ID
            input_data: Initial process data
            initiated_by: User ID who initiated the process
            instance_name: Optional instance name
            priority: Process priority (1-10)
            
        Returns:
            Created ProcessInstance
            
        Raises:
            ProcessValidationError: If validation fails
            ProcessEngineError: If process start fails
        """
        try:
            log.info(f"Starting process {definition_id} for user {initiated_by}")
            
            # For high-priority or simple processes, run sync
            if priority <= 3:
                instance = self._run_async(
                    self.engine.start_process(
                        definition_id=definition_id,
                        input_data=input_data,
                        initiated_by=initiated_by,
                        instance_name=instance_name,
                        priority=priority
                    )
                )
                return instance
            else:
                # For lower priority processes, delegate to Celery
                from ..tasks import start_process_async
                
                # Create basic instance record first
                from flask_appbuilder import db
                definition = ProcessDefinition.query.get(definition_id)
                if not definition:
                    raise ValueError(f"Process definition {definition_id} not found")
                
                instance = ProcessInstance(
                    definition_id=definition_id,
                    definition=definition,
                    initiated_by=initiated_by,
                    instance_name=instance_name or f"Instance of {definition.name}",
                    priority=priority,
                    input_data=input_data or {},
                    status='pending'
                )
                
                db.session.add(instance)
                db.session.commit()
                
                # Start async execution
                start_process_async.delay(instance.id)
                
                return instance
                
        except Exception as e:
            log.error(f"Failed to start process {definition_id}: {e}")
            raise
    
    def resume_process(self, instance_id: int, resume_data: Dict[str, Any] = None) -> bool:
        """
        Resume a suspended process instance synchronously.
        
        Args:
            instance_id: Process instance ID to resume
            resume_data: Optional data for resumption
            
        Returns:
            True if resume was successful, False otherwise
        """
        try:
            log.info(f"Resuming process instance {instance_id}")
            
            # For Flask-AppBuilder views, delegate to Celery for async work
            from ..tasks import resume_process_async
            result = resume_process_async.delay(instance_id, resume_data)
            
            # Update instance status immediately for UI feedback
            from flask_appbuilder import db
            instance = ProcessInstance.query.get(instance_id)
            if instance and instance.status == 'suspended':
                instance.status = 'running'
                db.session.commit()
                return True
            
            return False
            
        except Exception as e:
            log.error(f"Failed to resume process {instance_id}: {e}")
            return False
    
    def continue_from_step(self, instance: ProcessInstance, node_id: str, 
                          step_data: Dict[str, Any] = None) -> bool:
        """
        Continue process execution from a specific step synchronously.
        
        Args:
            instance: Process instance
            node_id: Node ID to continue from
            step_data: Optional step data
            
        Returns:
            True if continuation was successful, False otherwise
        """
        try:
            log.info(f"Continuing process {instance.id} from node {node_id}")
            
            # Delegate to Celery for async execution
            from ..tasks import continue_process_async
            continue_process_async.delay(instance.id, node_id, step_data)
            
            return True
            
        except Exception as e:
            log.error(f"Failed to continue process {instance.id}: {e}")
            return False
    
    def get_process_status(self, instance_id: int) -> Dict[str, Any]:
        """
        Get current process status synchronously.
        
        Args:
            instance_id: Process instance ID
            
        Returns:
            Process status information
        """
        try:
            from flask_appbuilder import db
            instance = db.session.query(ProcessInstance).get(instance_id)
            
            if not instance:
                return {'error': 'Process instance not found'}
            
            return {
                'instance_id': instance.id,
                'status': instance.status,
                'progress_percentage': instance.progress_percentage,
                'current_step': instance.current_step,
                'started_at': instance.started_at.isoformat() if instance.started_at else None,
                'last_activity_at': instance.last_activity_at.isoformat() if instance.last_activity_at else None,
                'error_message': instance.error_message
            }
            
        except Exception as e:
            log.error(f"Failed to get process status {instance_id}: {e}")
            return {'error': str(e)}
    
    def cancel_process(self, instance_id: int, reason: str = None) -> bool:
        """
        Cancel a running process synchronously.
        
        Args:
            instance_id: Process instance ID to cancel
            reason: Optional cancellation reason
            
        Returns:
            True if cancellation was successful, False otherwise
        """
        try:
            from flask_appbuilder import db
            from datetime import datetime, timezone
            
            instance = ProcessInstance.query.get(instance_id)
            if not instance:
                return False
            
            # Update instance status
            if instance.status in ['running', 'suspended', 'pending']:
                instance.status = 'cancelled'
                instance.completed_at = datetime.now(tz=timezone.utc)
                if reason:
                    instance.error_message = f"Cancelled: {reason}"
                
                db.session.commit()
                
                log.info(f"Process {instance_id} cancelled successfully")
                return True
            
            return False
            
        except Exception as e:
            log.error(f"Failed to cancel process {instance_id}: {e}")
            return False
    
    def get_process_metrics(self, instance_id: int) -> Dict[str, Any]:
        """
        Get process execution metrics synchronously.
        
        Args:
            instance_id: Process instance ID
            
        Returns:
            Process metrics information
        """
        try:
            from flask_appbuilder import db
            from sqlalchemy import func
            
            instance = ProcessInstance.query.get(instance_id)
            if not instance:
                return {'error': 'Process instance not found'}
            
            # Get step metrics
            step_stats = db.session.query(
                ProcessStep.status,
                func.count(ProcessStep.id).label('count'),
                func.avg(ProcessStep.execution_time).label('avg_time')
            ).filter_by(instance_id=instance_id).group_by(ProcessStep.status).all()
            
            step_metrics = {}
            for stat in step_stats:
                step_metrics[stat.status] = {
                    'count': stat.count,
                    'avg_execution_time': float(stat.avg_time) if stat.avg_time else 0
                }
            
            return {
                'instance_id': instance.id,
                'total_steps': len(instance.steps),
                'step_metrics': step_metrics,
                'overall_execution_time': (
                    (instance.completed_at - instance.started_at).total_seconds()
                    if instance.started_at and instance.completed_at else None
                )
            }
            
        except Exception as e:
            log.error(f"Failed to get process metrics {instance_id}: {e}")
            return {'error': str(e)}


# Global process service instance for easy access
_process_service = None

def get_process_service() -> ProcessService:
    """Get the global process service instance."""
    global _process_service
    if _process_service is None:
        _process_service = ProcessService()
    return _process_service