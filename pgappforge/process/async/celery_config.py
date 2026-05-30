"""
Celery Configuration for Process Engine.

Provides comprehensive Celery setup with task scheduling, monitoring,
error handling, and integration with the business process engine.
"""

import logging
import os
from datetime import timedelta
from typing import Dict, Any, Optional

from celery import Celery
from celery.schedules import crontab
from kombu import Queue, Exchange

log = logging.getLogger(__name__)


class CeleryConfig:
    """Celery configuration for process engine."""
    
    # Broker settings
    broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    
    # Task settings
    task_serializer = 'json'
    result_serializer = 'json'
    accept_content = ['json']
    timezone = 'UTC'
    enable_utc = True
    
    # Task execution settings
    task_always_eager = os.environ.get('CELERY_ALWAYS_EAGER', 'false').lower() == 'true'
    task_eager_propagates = True
    task_ignore_result = False
    task_store_eager_result = True
    
    # Task retry settings
    task_default_retry_delay = 60  # 1 minute
    task_max_retries = 3
    task_retry_backoff = True
    task_retry_backoff_max = 3600  # 1 hour
    task_retry_jitter = True
    
    # Worker settings
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 1000
    worker_disable_rate_limits = False
    
    # Task routes - route different types of tasks to different queues
    task_routes = {
        'pgappforge.process.tasks.execute_node_async': {'queue': 'process_execution'},
        'pgappforge.process.tasks.retry_step_async': {'queue': 'process_retry'},
        'pgappforge.process.tasks.complete_timer_step': {'queue': 'process_timers'},
        'pgappforge.process.tasks.handle_step_timeout': {'queue': 'process_timeouts'},
        'pgappforge.process.tasks.cleanup_completed_processes': {'queue': 'maintenance'},
        'pgappforge.process.tasks.monitor_stuck_processes': {'queue': 'monitoring'},
        'pgappforge.process.tasks.generate_process_metrics': {'queue': 'analytics'},
        'pgappforge.process.async.tasks.*': {'queue': 'process_async'},
        'pgappforge.process.ml.tasks.*': {'queue': 'ml_processing'},
        'pgappforge.process.approval.tasks.*': {'queue': 'approvals'},
        'pgappforge.process.notification.tasks.*': {'queue': 'notifications'}
    }
    
    # Queue definitions
    task_queues = (
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('process_execution', Exchange('process'), routing_key='process.execution'),
        Queue('process_retry', Exchange('process'), routing_key='process.retry'),
        Queue('process_timers', Exchange('process'), routing_key='process.timers'),
        Queue('process_timeouts', Exchange('process'), routing_key='process.timeouts'),
        Queue('process_async', Exchange('process'), routing_key='process.async'),
        Queue('ml_processing', Exchange('ml'), routing_key='ml.processing'),
        Queue('approvals', Exchange('approval'), routing_key='approval.requests'),
        Queue('notifications', Exchange('notification'), routing_key='notification.send'),
        Queue('maintenance', Exchange('system'), routing_key='system.maintenance'),
        Queue('monitoring', Exchange('system'), routing_key='system.monitoring'),
        Queue('analytics', Exchange('system'), routing_key='system.analytics')
    )
    
    # Default queue
    task_default_queue = 'default'
    task_default_exchange = 'default'
    task_default_exchange_type = 'direct'
    task_default_routing_key = 'default'
    
    # Beat schedule for periodic tasks
    beat_schedule = {
        'cleanup-completed-processes': {
            'task': 'pgappforge.process.tasks.cleanup_completed_processes',
            'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
            'options': {'queue': 'maintenance'}
        },
        'monitor-stuck-processes': {
            'task': 'pgappforge.process.tasks.monitor_stuck_processes',
            'schedule': crontab(minute=0),  # Every hour
            'options': {'queue': 'monitoring'}
        },
        'generate-process-metrics': {
            'task': 'pgappforge.process.tasks.generate_process_metrics',
            'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
            'options': {'queue': 'analytics'}
        },
        'train-ml-models': {
            'task': 'pgappforge.process.ml.tasks.train_models_periodic',
            'schedule': crontab(hour=3, minute=0, day_of_week=1),  # Weekly on Monday at 3 AM
            'options': {'queue': 'ml_processing'}
        },
        'process-health-check': {
            'task': 'pgappforge.process.async.tasks.health_check',
            'schedule': timedelta(minutes=5),  # Every 5 minutes
            'options': {'queue': 'monitoring'}
        },
        'cleanup-old-task-results': {
            'task': 'pgappforge.process.async.tasks.cleanup_task_results',
            'schedule': crontab(hour=1, minute=0),  # Daily at 1 AM
            'options': {'queue': 'maintenance'}
        }
    }
    
    # Result backend settings
    result_expires = 3600  # 1 hour
    result_backend_transport_options = {
        'master_name': 'mymaster'
    }
    
    # Security settings
    worker_hijack_root_logger = False
    worker_log_color = False
    
    # Monitoring settings
    task_send_sent_event = True
    task_track_started = True
    worker_send_task_events = True
    
    # Error handling
    task_reject_on_worker_lost = True
    task_acks_late = True
    
    # Performance settings
    broker_transport_options = {
        'priority_steps': list(range(10)),
        'sep': ':',
        'queue_order_strategy': 'priority'
    }


def create_celery_app(app=None) -> Celery:
    """Create and configure Celery app."""
    celery = Celery('process_engine')
    
    # Update configuration
    celery.config_from_object(CeleryConfig)
    
    if app:
        # Initialize Celery with Flask app context
        class ContextTask(celery.Task):
            """Make celery tasks work with Flask app context."""
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)
        
        celery.Task = ContextTask
        
        # Update config from Flask app
        celery.conf.update(app.config)
    
    # Register error handlers
    register_error_handlers(celery)
    
    # Register custom signals
    register_signals(celery)
    
    log.info("Celery app created and configured")
    return celery


def register_error_handlers(celery: Celery):
    """Register error handlers for Celery tasks."""
    
    @celery.signals.task_failure.connect
    def task_failure_handler(sender=None, task_id=None, exception=None, 
                           traceback=None, einfo=None, **kwargs):
        """Handle task failures."""
        log.error(f"Task {task_id} failed: {exception}")
        
        # Store failure information for monitoring
        try:
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor()
            monitor.record_task_failure(task_id, str(exception), traceback)
        except Exception as e:
            log.error(f"Failed to record task failure: {e}")
    
    @celery.signals.task_retry.connect
    def task_retry_handler(sender=None, task_id=None, reason=None, 
                         einfo=None, **kwargs):
        """Handle task retries."""
        log.warning(f"Task {task_id} retrying: {reason}")
        
        try:
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor()
            monitor.record_task_retry(task_id, str(reason))
        except Exception as e:
            log.error(f"Failed to record task retry: {e}")
    
    @celery.signals.task_success.connect
    def task_success_handler(sender=None, task_id=None, result=None, **kwargs):
        """Handle task success."""
        try:
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor()
            monitor.record_task_success(task_id, result)
        except Exception as e:
            log.error(f"Failed to record task success: {e}")


def register_signals(celery: Celery):
    """Register custom signals for task monitoring."""
    
    @celery.signals.task_prerun.connect
    def task_prerun_handler(sender=None, task_id=None, task=None, args=None, 
                          kwargs=None, **kwds):
        """Handle task pre-run."""
        log.debug(f"Starting task {task_id}: {sender}")
        
        try:
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor()
            monitor.record_task_start(task_id, sender, args, kwargs)
        except Exception as e:
            log.error(f"Failed to record task start: {e}")
    
    @celery.signals.task_postrun.connect
    def task_postrun_handler(sender=None, task_id=None, task=None, args=None,
                           kwargs=None, retval=None, state=None, **kwds):
        """Handle task post-run."""
        log.debug(f"Finished task {task_id}: {state}")
        
        try:
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor()
            monitor.record_task_complete(task_id, state, retval)
        except Exception as e:
            log.error(f"Failed to record task completion: {e}")
    
    @celery.signals.worker_ready.connect
    def worker_ready_handler(sender=None, **kwargs):
        """Handle worker ready signal."""
        log.info(f"Celery worker ready: {sender}")
    
    @celery.signals.worker_shutdown.connect
    def worker_shutdown_handler(sender=None, **kwargs):
        """Handle worker shutdown signal."""
        log.info(f"Celery worker shutting down: {sender}")


def get_task_priority(task_name: str, kwargs: Dict[str, Any] = None) -> int:
    """Determine task priority based on task type and context."""
    # Default priority (5 = normal)
    priority = 5
    
    # High priority tasks (0-2)
    if any(high_priority in task_name for high_priority in [
        'handle_step_timeout', 'process_failure', 'approval_escalation'
    ]):
        priority = 1
    
    # Medium-high priority tasks (3-4)
    elif any(med_high in task_name for med_high in [
        'execute_node_async', 'complete_timer_step', 'approval_notification'
    ]):
        priority = 3
    
    # Low priority tasks (6-8)
    elif any(low_priority in task_name for low_priority in [
        'cleanup', 'generate_metrics', 'train_models'
    ]):
        priority = 7
    
    # Very low priority tasks (9)
    elif 'archive' in task_name or 'backup' in task_name:
        priority = 9
    
    # Adjust based on context
    if kwargs:
        # High priority for urgent processes
        if kwargs.get('priority') == 'urgent':
            priority = max(0, priority - 2)
        elif kwargs.get('priority') == 'low':
            priority = min(9, priority + 2)
        
        # Time-sensitive operations
        if kwargs.get('timeout') and kwargs.get('timeout') < 300:  # Less than 5 minutes
            priority = max(0, priority - 1)
    
    return priority


class CeleryHealthCheck:
    """Health check utilities for Celery infrastructure."""
    
    def __init__(self, celery_app: Celery):
        self.celery_app = celery_app
    
    def check_broker_connection(self) -> Dict[str, Any]:
        """Check broker connectivity."""
        try:
            # Test broker connection
            conn = self.celery_app.broker_connection()
            conn.ensure_connection(max_retries=3, interval_start=1)
            
            return {
                'status': 'healthy',
                'broker_url': self.celery_app.conf.broker_url,
                'connected': True
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'broker_url': self.celery_app.conf.broker_url,
                'connected': False,
                'error': str(e)
            }
    
    def check_result_backend(self) -> Dict[str, Any]:
        """Check result backend connectivity."""
        try:
            # Test result backend
            backend = self.celery_app.backend
            
            # Try to get a non-existent result to test connection
            test_result = backend.get_result('test_connection_check')
            
            return {
                'status': 'healthy',
                'backend_url': self.celery_app.conf.result_backend,
                'connected': True
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'backend_url': self.celery_app.conf.result_backend,
                'connected': False,
                'error': str(e)
            }
    
    def check_workers(self) -> Dict[str, Any]:
        """Check active workers."""
        try:
            inspect = self.celery_app.control.inspect()
            
            # Get active workers
            stats = inspect.stats()
            active_queues = inspect.active_queues()
            
            if not stats:
                return {
                    'status': 'unhealthy',
                    'active_workers': 0,
                    'workers': [],
                    'error': 'No active workers found'
                }
            
            workers = []
            for worker_name, worker_stats in stats.items():
                worker_info = {
                    'name': worker_name,
                    'status': 'active',
                    'processed_tasks': worker_stats.get('total', 0),
                    'queues': active_queues.get(worker_name, []) if active_queues else []
                }
                workers.append(worker_info)
            
            return {
                'status': 'healthy',
                'active_workers': len(workers),
                'workers': workers
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'active_workers': 0,
                'workers': [],
                'error': str(e)
            }
    
    def check_queues(self) -> Dict[str, Any]:
        """Check queue status and lengths."""
        try:
            with self.celery_app.broker_connection() as conn:
                # Get queue information
                queues_info = []
                
                for queue in self.celery_app.conf.task_queues:
                    try:
                        # Get queue length
                        queue_obj = conn.SimpleQueue(queue.name)
                        length = queue_obj.qsize()
                        queue_obj.close()
                        
                        queues_info.append({
                            'name': queue.name,
                            'length': length,
                            'exchange': queue.exchange.name,
                            'routing_key': queue.routing_key,
                            'status': 'healthy'
                        })
                        
                    except Exception as e:
                        queues_info.append({
                            'name': queue.name,
                            'length': -1,
                            'exchange': queue.exchange.name,
                            'routing_key': queue.routing_key,
                            'status': 'error',
                            'error': str(e)
                        })
                
                return {
                    'status': 'healthy',
                    'queues': queues_info
                }
                
        except Exception as e:
            return {
                'status': 'unhealthy',
                'queues': [],
                'error': str(e)
            }
    
    def get_comprehensive_health(self) -> Dict[str, Any]:
        """Get comprehensive health check results."""
        health_checks = {
            'broker': self.check_broker_connection(),
            'result_backend': self.check_result_backend(),
            'workers': self.check_workers(),
            'queues': self.check_queues()
        }
        
        # Determine overall health
        overall_healthy = all(
            check['status'] == 'healthy' 
            for check in health_checks.values()
        )
        
        return {
            'overall_status': 'healthy' if overall_healthy else 'unhealthy',
            'timestamp': log.info.__defaults__[0] if hasattr(log.info, '__defaults__') else None,
            'checks': health_checks
        }


# Global Celery instance
celery_app: Optional[Celery] = None


def init_celery(app=None) -> Celery:
    """Initialize Celery with Flask application."""
    global celery_app
    
    if celery_app is None:
        celery_app = create_celery_app(app)
        log.info("Celery initialized successfully")
    
    return celery_app


def get_celery() -> Celery:
    """Get the Celery app instance."""
    global celery_app
    
    if celery_app is None:
        raise RuntimeError("Celery not initialized. Call init_celery() first.")
    
    return celery_app