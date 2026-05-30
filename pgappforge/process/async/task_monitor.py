"""
Task Monitoring and Management System.

Provides comprehensive monitoring, tracking, and management capabilities
for Celery tasks with performance analytics and error tracking.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
import threading
from enum import Enum

from pgappforge import db
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

from ..models.process_models import ProcessInstance, ProcessStep
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)

Base = declarative_base()


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    STARTED = "started"
    RETRY = "retry"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"


class TaskExecution(Base):
    """Model for tracking task execution."""
    
    __tablename__ = 'task_executions'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(String(255), unique=True, nullable=False)
    task_name = Column(String(255), nullable=False)
    tenant_id = Column(Integer, nullable=True)
    
    # Task details
    args = Column(JSONB, nullable=True)
    kwargs = Column(JSONB, nullable=True)
    priority = Column(Integer, default=5)
    queue = Column(String(100), nullable=True)
    
    # Execution tracking
    status = Column(String(50), default=TaskStatus.PENDING.value)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration = Column(Float, nullable=True)  # seconds
    
    # Results and errors
    result = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Process context
    process_instance_id = Column(Integer, nullable=True)
    process_step_id = Column(Integer, nullable=True)
    
    # Metadata
    worker_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskMonitor:
    """Monitor and track Celery task execution."""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._metrics_cache = {}
        self._recent_tasks = deque(maxlen=1000)  # Keep last 1000 tasks in memory
        self._performance_data = defaultdict(list)
    
    def record_task_start(self, task_id: str, task_name: str, 
                         args: tuple = None, kwargs: dict = None):
        """Record task start."""
        with self._lock:
            try:
                # Get or create task execution record
                task_execution = db.session.query(TaskExecution).filter_by(
                    task_id=task_id
                ).first()
                
                if not task_execution:
                    task_execution = TaskExecution(
                        task_id=task_id,
                        task_name=task_name,
                        tenant_id=TenantContext.get_current_tenant_id(),
                        args=args,
                        kwargs=kwargs
                    )
                    db.session.add(task_execution)
                
                task_execution.status = TaskStatus.STARTED.value
                task_execution.started_at = datetime.now(tz=timezone.utc)
                
                # Extract process context if available
                if kwargs:
                    task_execution.process_instance_id = kwargs.get('instance_id')
                    task_execution.process_step_id = kwargs.get('step_id')
                    task_execution.priority = kwargs.get('priority', 5)
                
                db.session.commit()
                
                # Add to recent tasks
                self._recent_tasks.append({
                    'task_id': task_id,
                    'task_name': task_name,
                    'started_at': task_execution.started_at,
                    'status': TaskStatus.STARTED.value
                })
                
                log.debug(f"Recorded task start: {task_id}")
                
            except Exception as e:
                log.error(f"Failed to record task start: {str(e)}")
                db.session.rollback()
    
    def record_task_complete(self, task_id: str, state: str, result: Any = None):
        """Record task completion."""
        with self._lock:
            try:
                task_execution = db.session.query(TaskExecution).filter_by(
                    task_id=task_id
                ).first()
                
                if not task_execution:
                    log.warning(f"Task execution not found for completion: {task_id}")
                    return
                
                task_execution.status = state.lower() if state else TaskStatus.SUCCESS.value
                task_execution.completed_at = datetime.now(tz=timezone.utc)
                task_execution.result = result if isinstance(result, (dict, list)) else None
                
                # Calculate duration
                if task_execution.started_at:
                    duration = (task_execution.completed_at - task_execution.started_at).total_seconds()
                    task_execution.duration = duration
                    
                    # Update performance data
                    self._performance_data[task_execution.task_name].append({
                        'duration': duration,
                        'timestamp': task_execution.completed_at,
                        'status': task_execution.status
                    })
                
                db.session.commit()
                
                log.debug(f"Recorded task completion: {task_id} - {state}")
                
            except Exception as e:
                log.error(f"Failed to record task completion: {str(e)}")
                db.session.rollback()
    
    def record_task_failure(self, task_id: str, error: str, traceback: str = None):
        """Record task failure."""
        with self._lock:
            try:
                task_execution = db.session.query(TaskExecution).filter_by(
                    task_id=task_id
                ).first()
                
                if not task_execution:
                    log.warning(f"Task execution not found for failure: {task_id}")
                    return
                
                task_execution.status = TaskStatus.FAILURE.value
                task_execution.error_message = error
                task_execution.traceback = traceback
                task_execution.completed_at = datetime.now(tz=timezone.utc)
                
                # Calculate duration if started
                if task_execution.started_at:
                    duration = (task_execution.completed_at - task_execution.started_at).total_seconds()
                    task_execution.duration = duration
                
                db.session.commit()
                
                log.error(f"Recorded task failure: {task_id} - {error}")
                
            except Exception as e:
                log.error(f"Failed to record task failure: {str(e)}")
                db.session.rollback()
    
    def record_task_retry(self, task_id: str, reason: str):
        """Record task retry."""
        with self._lock:
            try:
                task_execution = db.session.query(TaskExecution).filter_by(
                    task_id=task_id
                ).first()
                
                if not task_execution:
                    log.warning(f"Task execution not found for retry: {task_id}")
                    return
                
                task_execution.status = TaskStatus.RETRY.value
                task_execution.retry_count += 1
                task_execution.error_message = reason
                
                db.session.commit()
                
                log.warning(f"Recorded task retry: {task_id} - {reason} (attempt {task_execution.retry_count})")
                
            except Exception as e:
                log.error(f"Failed to record task retry: {str(e)}")
                db.session.rollback()
    
    def record_task_success(self, task_id: str, result: Any = None):
        """Record task success."""
        self.record_task_complete(task_id, TaskStatus.SUCCESS.value, result)
    
    def get_task_statistics(self, time_range: int = 24) -> Dict[str, Any]:
        """Get task execution statistics."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=time_range)
            
            # Base query
            base_query = db.session.query(TaskExecution).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.created_at >= cutoff_time
            )
            
            # Overall statistics
            total_tasks = base_query.count()
            successful_tasks = base_query.filter(
                TaskExecution.status == TaskStatus.SUCCESS.value
            ).count()
            failed_tasks = base_query.filter(
                TaskExecution.status == TaskStatus.FAILURE.value
            ).count()
            running_tasks = base_query.filter(
                TaskExecution.status == TaskStatus.STARTED.value
            ).count()
            
            # Success rate
            success_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0
            
            # Average duration for completed tasks
            completed_tasks = base_query.filter(
                TaskExecution.duration.isnot(None)
            ).all()
            
            avg_duration = 0
            if completed_tasks:
                avg_duration = sum(task.duration for task in completed_tasks) / len(completed_tasks)
            
            # Task distribution by type
            task_types = db.session.query(
                TaskExecution.task_name,
                db.func.count(TaskExecution.id).label('count')
            ).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.created_at >= cutoff_time
            ).group_by(TaskExecution.task_name).all()
            
            task_distribution = {task_name: count for task_name, count in task_types}
            
            # Queue distribution
            queue_stats = db.session.query(
                TaskExecution.queue,
                db.func.count(TaskExecution.id).label('count'),
                db.func.avg(TaskExecution.duration).label('avg_duration')
            ).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.created_at >= cutoff_time,
                TaskExecution.queue.isnot(None)
            ).group_by(TaskExecution.queue).all()
            
            queue_distribution = {
                queue or 'default': {
                    'count': count,
                    'avg_duration': round(float(avg_duration) if avg_duration else 0, 2)
                }
                for queue, count, avg_duration in queue_stats
            }
            
            return {
                'time_range_hours': time_range,
                'total_tasks': total_tasks,
                'successful_tasks': successful_tasks,
                'failed_tasks': failed_tasks,
                'running_tasks': running_tasks,
                'success_rate': round(success_rate, 2),
                'average_duration': round(avg_duration, 2),
                'task_distribution': task_distribution,
                'queue_distribution': queue_distribution,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            }
            
        except Exception as e:
            log.error(f"Failed to get task statistics: {str(e)}")
            return {'error': str(e)}
    
    def get_failed_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent failed tasks with details."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            failed_tasks = db.session.query(TaskExecution).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.status == TaskStatus.FAILURE.value
            ).order_by(TaskExecution.completed_at.desc()).limit(limit).all()
            
            failed_task_data = []
            for task in failed_tasks:
                failed_task_data.append({
                    'task_id': task.task_id,
                    'task_name': task.task_name,
                    'error_message': task.error_message,
                    'retry_count': task.retry_count,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                    'duration': task.duration,
                    'process_instance_id': task.process_instance_id,
                    'process_step_id': task.process_step_id,
                    'queue': task.queue,
                    'worker_name': task.worker_name
                })
            
            return failed_task_data
            
        except Exception as e:
            log.error(f"Failed to get failed tasks: {str(e)}")
            return []
    
    def get_running_tasks(self) -> List[Dict[str, Any]]:
        """Get currently running tasks."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            running_tasks = db.session.query(TaskExecution).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.status == TaskStatus.STARTED.value
            ).order_by(TaskExecution.started_at.desc()).all()
            
            running_task_data = []
            for task in running_tasks:
                # Calculate running duration
                running_duration = 0
                if task.started_at:
                    running_duration = (datetime.now(tz=timezone.utc) - task.started_at).total_seconds()
                
                running_task_data.append({
                    'task_id': task.task_id,
                    'task_name': task.task_name,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'running_duration': round(running_duration, 2),
                    'process_instance_id': task.process_instance_id,
                    'process_step_id': task.process_step_id,
                    'queue': task.queue,
                    'worker_name': task.worker_name,
                    'priority': task.priority
                })
            
            return running_task_data
            
        except Exception as e:
            log.error(f"Failed to get running tasks: {str(e)}")
            return []
    
    def get_performance_metrics(self, task_name: str = None) -> Dict[str, Any]:
        """Get performance metrics for tasks."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=24)
            
            query = db.session.query(TaskExecution).filter(
                TaskExecution.tenant_id == tenant_id,
                TaskExecution.created_at >= cutoff_time,
                TaskExecution.duration.isnot(None)
            )
            
            if task_name:
                query = query.filter(TaskExecution.task_name == task_name)
            
            tasks = query.all()
            
            if not tasks:
                return {'message': 'No performance data available'}
            
            durations = [task.duration for task in tasks]
            successful_tasks = [task for task in tasks if task.status == TaskStatus.SUCCESS.value]
            failed_tasks = [task for task in tasks if task.status == TaskStatus.FAILURE.value]
            
            # Performance metrics
            metrics = {
                'total_tasks': len(tasks),
                'successful_tasks': len(successful_tasks),
                'failed_tasks': len(failed_tasks),
                'success_rate': (len(successful_tasks) / len(tasks) * 100) if tasks else 0,
                'avg_duration': sum(durations) / len(durations),
                'min_duration': min(durations),
                'max_duration': max(durations),
                'median_duration': sorted(durations)[len(durations) // 2] if durations else 0
            }
            
            # Performance trends (hourly breakdown)
            hourly_stats = defaultdict(lambda: {'count': 0, 'total_duration': 0, 'failures': 0})
            
            for task in tasks:
                if task.started_at:
                    hour = task.started_at.replace(minute=0, second=0, microsecond=0)
                    hourly_stats[hour]['count'] += 1
                    hourly_stats[hour]['total_duration'] += task.duration
                    if task.status == TaskStatus.FAILURE.value:
                        hourly_stats[hour]['failures'] += 1
            
            hourly_data = []
            for hour, stats in sorted(hourly_stats.items()):
                avg_duration = stats['total_duration'] / stats['count'] if stats['count'] > 0 else 0
                failure_rate = (stats['failures'] / stats['count'] * 100) if stats['count'] > 0 else 0
                
                hourly_data.append({
                    'hour': hour.isoformat(),
                    'count': stats['count'],
                    'avg_duration': round(avg_duration, 2),
                    'failure_rate': round(failure_rate, 2)
                })
            
            metrics['hourly_breakdown'] = hourly_data
            
            # Round numeric values
            for key in ['success_rate', 'avg_duration', 'min_duration', 'max_duration', 'median_duration']:
                if key in metrics:
                    metrics[key] = round(metrics[key], 2)
            
            return metrics
            
        except Exception as e:
            log.error(f"Failed to get performance metrics: {str(e)}")
            return {'error': str(e)}
    
    def get_task_details(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific task."""
        try:
            task_execution = db.session.query(TaskExecution).filter_by(
                task_id=task_id
            ).first()
            
            if not task_execution:
                return None
            
            task_details = {
                'task_id': task_execution.task_id,
                'task_name': task_execution.task_name,
                'status': task_execution.status,
                'args': task_execution.args,
                'kwargs': task_execution.kwargs,
                'priority': task_execution.priority,
                'queue': task_execution.queue,
                'started_at': task_execution.started_at.isoformat() if task_execution.started_at else None,
                'completed_at': task_execution.completed_at.isoformat() if task_execution.completed_at else None,
                'duration': task_execution.duration,
                'result': task_execution.result,
                'error_message': task_execution.error_message,
                'traceback': task_execution.traceback,
                'retry_count': task_execution.retry_count,
                'process_instance_id': task_execution.process_instance_id,
                'process_step_id': task_execution.process_step_id,
                'worker_name': task_execution.worker_name,
                'created_at': task_execution.created_at.isoformat(),
                'updated_at': task_execution.updated_at.isoformat()
            }
            
            # Get process context if available
            if task_execution.process_instance_id:
                process_instance = db.session.query(ProcessInstance).get(
                    task_execution.process_instance_id
                )
                if process_instance:
                    task_details['process_context'] = {
                        'process_name': process_instance.definition.name,
                        'instance_status': process_instance.status,
                        'started_at': process_instance.started_at.isoformat() if process_instance.started_at else None
                    }
            
            if task_execution.process_step_id:
                process_step = db.session.query(ProcessStep).get(
                    task_execution.process_step_id
                )
                if process_step:
                    task_details['step_context'] = {
                        'node_id': process_step.node_id,
                        'node_type': process_step.node_type,
                        'step_status': process_step.status
                    }
            
            return task_details
            
        except Exception as e:
            log.error(f"Failed to get task details: {str(e)}")
            return None
    
    def cleanup_old_tasks(self, days_to_keep: int = 30):
        """Clean up old task execution records."""
        try:
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days_to_keep)
            
            deleted_count = db.session.query(TaskExecution).filter(
                TaskExecution.created_at < cutoff_date
            ).delete()
            
            db.session.commit()
            
            log.info(f"Cleaned up {deleted_count} old task execution records")
            return deleted_count
            
        except Exception as e:
            log.error(f"Failed to cleanup old tasks: {str(e)}")
            db.session.rollback()
            return 0
    
    def get_queue_health(self) -> Dict[str, Any]:
        """Get health status of task queues."""
        try:
            from .celery_config import get_celery
            celery_app = get_celery()
            
            inspect = celery_app.control.inspect()
            
            # Get queue lengths and worker info
            active_queues = inspect.active_queues() or {}
            reserved_tasks = inspect.reserved() or {}
            
            queue_health = {}
            
            for worker, queues in active_queues.items():
                for queue_info in queues:
                    queue_name = queue_info['name']
                    
                    if queue_name not in queue_health:
                        queue_health[queue_name] = {
                            'name': queue_name,
                            'workers': [],
                            'reserved_tasks': 0,
                            'status': 'healthy'
                        }
                    
                    queue_health[queue_name]['workers'].append(worker)
                    
                    # Add reserved tasks for this worker
                    if worker in reserved_tasks:
                        queue_health[queue_name]['reserved_tasks'] += len(reserved_tasks[worker])
            
            # Determine queue health status
            for queue_name, info in queue_health.items():
                if not info['workers']:
                    info['status'] = 'no_workers'
                elif info['reserved_tasks'] > 100:  # Arbitrary threshold
                    info['status'] = 'overloaded'
                else:
                    info['status'] = 'healthy'
            
            return {
                'queues': queue_health,
                'total_queues': len(queue_health),
                'healthy_queues': len([q for q in queue_health.values() if q['status'] == 'healthy']),
                'checked_at': datetime.now(tz=timezone.utc).isoformat()
            }
            
        except Exception as e:
            log.error(f"Failed to get queue health: {str(e)}")
            return {'error': str(e)}
    
    def get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent task activity."""
        recent_tasks = list(self._recent_tasks)[-limit:]
        recent_tasks.reverse()  # Most recent first
        return recent_tasks