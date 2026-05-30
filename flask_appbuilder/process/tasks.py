"""
Celery Tasks for Process Engine.

Provides asynchronous task execution for process operations including
node execution, timer handling, and background process management.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from celery import Celery
from flask import current_app

from flask_appbuilder import db
from .models.process_models import ProcessInstance, ProcessStep, ProcessStepStatus
from .engine.process_engine import ProcessEngine

log = logging.getLogger(__name__)

# Celery app will be initialized by Flask-AppBuilder
celery = Celery('process_engine')


@celery.task(bind=True, max_retries=3)
def execute_node_async(self, instance_id: int, node_id: str, input_data: Dict[str, Any] = None):
    """Execute a process node asynchronously."""
    try:
        # Run async operation in event loop
        import asyncio
        
        async def _execute():
            # Get process instance
            instance = db.session.query(ProcessInstance).get(instance_id)
            if not instance:
                raise ValueError(f"Process instance {instance_id} not found")
            
            # Get node definition  
            node = instance.definition.get_node_by_id(node_id)
            if not node:
                raise ValueError(f"Node {node_id} not found in process definition")
            
            # Execute node using process engine
            engine = ProcessEngine()
            return await engine._execute_node(instance, node, input_data or {})
        
        # Run in new event loop to avoid conflicts
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            output_data = loop.run_until_complete(_execute())
            return {
                'success': True,
                'instance_id': instance_id,
                'node_id': node_id,
                'output_data': output_data
            }
        finally:
            loop.close()
            
    except Exception as e:
        log.error(f"Async node execution failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=2 ** self.request.retries, exc=e)
        
        return {'success': False, 'error': str(e)}


@celery.task(bind=True, max_retries=3)
def retry_step_async(self, step_id: int):
    """Retry a failed process step."""
    try:
        # Run async operation in event loop
        import asyncio
        
        async def _retry():
            step = db.session.query(ProcessStep).get(step_id)
            if not step:
                raise ValueError(f"Process step {step_id} not found")
            
            # Use process engine to retry step
            engine = ProcessEngine()
            return await engine._retry_step(step)
        
        # Run in new event loop to avoid conflicts
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_retry())
            return {'success': True, 'step_id': step_id, 'retry_result': result}
        finally:
            loop.close()
            
    except Exception as e:
        log.error(f"Step retry failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=2 ** self.request.retries, exc=e)
        
        return {'success': False, 'error': str(e)}


@celery.task
def complete_timer_step(step_id: int):
    """Complete a timer step when delay expires."""
    try:
        step = db.session.query(ProcessStep).get(step_id)
        if not step:
            log.error(f"Timer step {step_id} not found")
            return {'success': False, 'error': 'Step not found'}
        
        # Check if step is still waiting
        if step.status != ProcessStepStatus.WAITING.value:
            log.warning(f"Timer step {step_id} is no longer waiting (status: {step.status})")
            return {'success': False, 'error': 'Step not in waiting state'}
        
        # Mark step as completed
        step.mark_completed({'timer_completed': True, 'completed_at': datetime.now(tz=timezone.utc).isoformat()})
        db.session.commit()
        
        # Continue process execution
        instance = step.instance
        node = instance.definition.get_node_by_id(step.node_id)
        
        if node:
            engine = ProcessEngine()
            engine._continue_process_execution(instance, node, step.output_data or {})
        
        log.info(f"Timer step {step_id} completed successfully")
        return {'success': True, 'step_id': step_id}
        
    except Exception as e:
        log.error(f"Timer completion failed: {str(e)}")
        return {'success': False, 'error': str(e)}


@celery.task
def handle_step_timeout(step_id: int):
    """Handle step timeout."""
    try:
        step = db.session.query(ProcessStep).get(step_id)
        if not step:
            log.error(f"Step {step_id} not found for timeout handling")
            return {'success': False, 'error': 'Step not found'}
        
        # Check if step is still waiting
        if step.status != ProcessStepStatus.WAITING.value:
            log.info(f"Step {step_id} no longer waiting, timeout cancelled")
            return {'success': True, 'timeout_cancelled': True}
        
        # Get timeout action
        timeout_action = step.configuration.get('timeout_action', 'fail')
        
        if timeout_action == 'complete':
            # Complete step with timeout result
            step.mark_completed({
                'timeout_occurred': True,
                'timeout_action': 'complete',
                'completed_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
            # Continue process execution
            instance = step.instance
            node = instance.definition.get_node_by_id(step.node_id)
            
            if node:
                engine = ProcessEngine()
                engine._continue_process_execution(instance, node, step.output_data or {})
            
        elif timeout_action == 'skip':
            # Skip step
            step.status = ProcessStepStatus.SKIPPED.value
            step.error_message = 'Step timed out and was skipped'
            step.completed_at = datetime.now(tz=timezone.utc)
            
            # Continue process execution
            instance = step.instance
            node = instance.definition.get_node_by_id(step.node_id)
            
            if node:
                engine = ProcessEngine()
                engine._continue_process_execution(instance, node, {})
            
        else:  # timeout_action == 'fail' (default)
            # Fail step
            step.mark_failed('Step timed out', {
                'timeout_occurred': True,
                'timeout_action': 'fail',
                'timeout_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
            # This will trigger error handling in the process engine
        
        db.session.commit()
        
        log.warning(f"Step {step_id} timed out, action: {timeout_action}")
        return {
            'success': True,
            'step_id': step_id,
            'timeout_action': timeout_action,
            'timeout_handled': True
        }
        
    except Exception as e:
        log.error(f"Timeout handling failed: {str(e)}")
        return {'success': False, 'error': str(e)}


@celery.task
def cleanup_completed_processes():
    """Cleanup old completed process instances."""
    try:
        from datetime import timedelta
        
        # Get cleanup configuration
        retention_days = current_app.config.get('PROCESS_RETENTION_DAYS', 90)
        cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        
        # Find old completed processes
        old_processes = db.session.query(ProcessInstance).filter(
            ProcessInstance.status.in_(['completed', 'failed', 'cancelled']),
            ProcessInstance.completed_at < cutoff_date
        ).all()
        
        cleanup_count = 0
        for process in old_processes:
            # Archive or delete based on configuration
            archive_mode = current_app.config.get('PROCESS_ARCHIVE_MODE', 'delete')
            
            if archive_mode == 'archive':
                # Move to archive table (implementation depends on requirements)
                pass
            else:
                # Delete process and related data
                db.session.delete(process)
                cleanup_count += 1
        
        db.session.commit()
        
        log.info(f"Cleaned up {cleanup_count} old process instances")
        return {
            'success': True,
            'processes_cleaned': cleanup_count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
    except Exception as e:
        log.error(f"Process cleanup failed: {str(e)}")
        return {'success': False, 'error': str(e)}


@celery.task
def monitor_stuck_processes():
    """Monitor and handle stuck processes."""
    try:
        from datetime import timedelta
        
        # Find processes that haven't had activity in a while
        stuck_threshold = current_app.config.get('STUCK_PROCESS_HOURS', 24)
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=stuck_threshold)
        
        stuck_processes = db.session.query(ProcessInstance).filter(
            ProcessInstance.status == 'running',
            ProcessInstance.last_activity_at < cutoff_time
        ).all()
        
        handled_count = 0
        for process in stuck_processes:
            try:
                # Check if process is actually stuck
                if process.is_stuck(threshold_minutes=stuck_threshold * 60):
                    # Handle based on configuration
                    action = current_app.config.get('STUCK_PROCESS_ACTION', 'suspend')
                    
                    if action == 'suspend':
                        process.status = 'suspended'
                        process.suspended_at = datetime.now(tz=timezone.utc)
                        log.warning(f"Suspended stuck process {process.id}")
                        
                    elif action == 'cancel':
                        process.status = 'cancelled'
                        process.completed_at = datetime.now(tz=timezone.utc)
                        log.warning(f"Cancelled stuck process {process.id}")
                        
                    elif action == 'restart':
                        # Attempt to restart from current step
                        engine = ProcessEngine()
                        if process.current_step:
                            node = process.definition.get_node_by_id(process.current_step)
                            if node:
                                engine._execute_node(process, node, {})
                        log.info(f"Attempted restart of stuck process {process.id}")
                    
                    handled_count += 1
                
            except Exception as e:
                log.error(f"Error handling stuck process {process.id}: {str(e)}")
        
        db.session.commit()
        
        log.info(f"Handled {handled_count} stuck processes")
        return {
            'success': True,
            'stuck_processes_handled': handled_count,
            'threshold_hours': stuck_threshold
        }
        
    except Exception as e:
        log.error(f"Stuck process monitoring failed: {str(e)}")
        return {'success': False, 'error': str(e)}


@celery.task
def generate_process_metrics():
    """Generate process performance metrics."""
    try:
        from .models.process_models import ProcessMetric
        from sqlalchemy import func
        
        # Calculate daily metrics
        today = datetime.now(tz=timezone.utc).date()
        
        # Throughput metrics
        completed_today = db.session.query(func.count(ProcessInstance.id)).filter(
            func.date(ProcessInstance.completed_at) == today,
            ProcessInstance.status == 'completed'
        ).scalar()
        
        failed_today = db.session.query(func.count(ProcessInstance.id)).filter(
            func.date(ProcessInstance.completed_at) == today,
            ProcessInstance.status == 'failed'
        ).scalar()
        
        # Average duration
        avg_duration = db.session.query(func.avg(
            func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
        )).filter(
            func.date(ProcessInstance.completed_at) == today,
            ProcessInstance.status == 'completed'
        ).scalar()
        
        # Store metrics
        metrics = [
            ProcessMetric(
                metric_date=datetime.now(tz=timezone.utc),
                metric_type='daily_throughput',
                value=completed_today or 0
            ),
            ProcessMetric(
                metric_date=datetime.now(tz=timezone.utc),
                metric_type='daily_failures',
                value=failed_today or 0
            ),
            ProcessMetric(
                metric_date=datetime.now(tz=timezone.utc),
                metric_type='avg_duration',
                value=avg_duration or 0
            )
        ]
        
        for metric in metrics:
            db.session.add(metric)
        
        db.session.commit()
        
        log.info(f"Generated {len(metrics)} process metrics for {today}")
        return {
            'success': True,
            'metrics_generated': len(metrics),
            'date': today.isoformat()
        }
        
    except Exception as e:
        log.error(f"Metrics generation failed: {str(e)}")
        return {'success': False, 'error': str(e)}


# Periodic tasks configuration
@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Setup periodic background tasks."""
    
    # Cleanup completed processes daily at 2 AM
    sender.add_periodic_task(
        crontab(hour=2, minute=0),
        cleanup_completed_processes.s(),
        name='daily-process-cleanup'
    )
    
    # Monitor stuck processes every hour
    sender.add_periodic_task(
        crontab(minute=0),
        monitor_stuck_processes.s(),
        name='hourly-stuck-process-monitor'
    )
    
    # Generate metrics every 6 hours
    sender.add_periodic_task(
        crontab(minute=0, hour='*/6'),
        generate_process_metrics.s(),
        name='metrics-generation'
    )


@celery.task(bind=True, max_retries=3)
def start_process_async(self, instance_id: int):
    """Start a process instance asynchronously."""
    try:
        with current_app.app_context():
            instance = ProcessInstance.query.get(instance_id)
            if not instance:
                log.error(f"Process instance {instance_id} not found")
                return {"success": False, "error": "Process instance not found"}
            
            # Initialize async engine
            engine = ProcessEngine()
            
            # Run async start_process
            import asyncio
            result = asyncio.run(engine.start_process_from_instance(instance))
            
            return {
                "success": True,
                "instance_id": instance_id,
                "status": instance.status
            }
            
    except Exception as e:
        log.error(f"Failed to start process {instance_id}: {str(e)}")
        self.retry(countdown=60, exc=e)


@celery.task(bind=True, max_retries=3)
def resume_process_async(self, instance_id: int, resume_data: Dict[str, Any] = None):
    """Resume a suspended process asynchronously."""
    try:
        with current_app.app_context():
            # Initialize async engine
            engine = ProcessEngine()
            
            # Run async resume_process
            import asyncio
            result = asyncio.run(engine.resume_process(instance_id, resume_data=resume_data))
            
            return {
                "success": True,
                "instance_id": instance_id,
                "resumed": result
            }
            
    except Exception as e:
        log.error(f"Failed to resume process {instance_id}: {str(e)}")
        self.retry(countdown=60, exc=e)


@celery.task(bind=True, max_retries=3)
def continue_process_async(self, instance_id: int, node_id: str, step_data: Dict[str, Any] = None):
    """Continue process execution from a specific step asynchronously."""
    try:
        with current_app.app_context():
            instance = ProcessInstance.query.get(instance_id)
            if not instance:
                log.error(f"Process instance {instance_id} not found")
                return {"success": False, "error": "Process instance not found"}
            
            # Initialize async engine
            engine = ProcessEngine()
            
            # Run async continue execution
            import asyncio
            result = asyncio.run(engine.continue_from_step(instance, node_id, step_data))
            
            return {
                "success": True,
                "instance_id": instance_id,
                "node_id": node_id,
                "continued": result
            }
            
    except Exception as e:
        log.error(f"Failed to continue process {instance_id}: {str(e)}")
        self.retry(countdown=60, exc=e)


@celery.task(bind=True, max_retries=3)
def escalate_approval_request(self, request_id: int):
    """Escalate an approval request that has timed out."""
    try:
        with current_app.app_context():
            from .approval.chain_manager import EscalationManager
            
            escalation_manager = EscalationManager()
            
            # Run async escalation in event loop
            import asyncio
            result = asyncio.run(escalation_manager.escalate_request(request_id))
            
            return {
                "success": True,
                "request_id": request_id,
                "escalated": True
            }
            
    except Exception as e:
        log.error(f"Failed to escalate approval request {request_id}: {str(e)}")
        self.retry(countdown=300, exc=e)  # Retry after 5 minutes

