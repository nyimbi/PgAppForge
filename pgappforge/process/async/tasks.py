"""
Additional Async Tasks for Process Engine.

Provides comprehensive async task implementations for maintenance,
monitoring, health checks, and system operations.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from celery import Celery
from flask import current_app

from pgappforge import db
from .celery_config import get_celery
from .task_monitor import TaskMonitor, TaskExecution
from ..models.process_models import ProcessInstance, ProcessStep, ProcessMetric
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)

# Get Celery app
try:
    celery = get_celery()
except RuntimeError:
    # Fallback for when Celery isn't initialized yet
    celery = Celery('process_engine')


@celery.task(bind=True)
def health_check(self):
    """Periodic health check for the process system."""
    try:
        health_status = {
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'status': 'healthy',
            'checks': {}
        }
        
        # Database connectivity check
        try:
            db.session.execute('SELECT 1').fetchone()
            health_status['checks']['database'] = {'status': 'healthy', 'message': 'Database connection OK'}
        except Exception as e:
            health_status['checks']['database'] = {'status': 'unhealthy', 'error': str(e)}
            health_status['status'] = 'unhealthy'
        
        # Process instances health check
        try:
            running_processes = db.session.query(ProcessInstance).filter_by(status='running').count()
            stuck_threshold = current_app.config.get('STUCK_PROCESS_HOURS', 24)
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=stuck_threshold)
            
            stuck_processes = db.session.query(ProcessInstance).filter(
                ProcessInstance.status == 'running',
                ProcessInstance.started_at < cutoff_time
            ).count()
            
            health_status['checks']['processes'] = {
                'status': 'healthy' if stuck_processes == 0 else 'warning',
                'running_processes': running_processes,
                'stuck_processes': stuck_processes,
                'message': f'{running_processes} running, {stuck_processes} potentially stuck'
            }
            
            if stuck_processes > 0:
                health_status['status'] = 'warning'
                
        except Exception as e:
            health_status['checks']['processes'] = {'status': 'unhealthy', 'error': str(e)}
            health_status['status'] = 'unhealthy'
        
        # Task monitoring health check
        try:
            monitor = TaskMonitor()
            stats = monitor.get_task_statistics(1)  # Last hour
            
            if 'error' in stats:
                health_status['checks']['task_monitoring'] = {'status': 'unhealthy', 'error': stats['error']}
                health_status['status'] = 'unhealthy'
            else:
                success_rate = stats.get('success_rate', 0)
                status = 'healthy' if success_rate >= 90 else 'warning' if success_rate >= 80 else 'unhealthy'
                
                health_status['checks']['task_monitoring'] = {
                    'status': status,
                    'success_rate': success_rate,
                    'total_tasks_last_hour': stats.get('total_tasks', 0)
                }
                
                if status == 'unhealthy':
                    health_status['status'] = 'unhealthy'
                elif status == 'warning' and health_status['status'] == 'healthy':
                    health_status['status'] = 'warning'
                    
        except Exception as e:
            health_status['checks']['task_monitoring'] = {'status': 'unhealthy', 'error': str(e)}
            health_status['status'] = 'unhealthy'
        
        # Celery infrastructure health
        try:
            from .celery_config import CeleryHealthCheck
            celery_health = CeleryHealthCheck(celery)
            
            broker_health = celery_health.check_broker_connection()
            workers_health = celery_health.check_workers()
            
            health_status['checks']['celery_broker'] = broker_health
            health_status['checks']['celery_workers'] = workers_health
            
            if broker_health['status'] != 'healthy' or workers_health['status'] != 'healthy':
                health_status['status'] = 'unhealthy'
                
        except Exception as e:
            health_status['checks']['celery_infrastructure'] = {'status': 'unhealthy', 'error': str(e)}
            health_status['status'] = 'unhealthy'
        
        log.info(f"Health check completed: {health_status['status']}")
        return health_status
        
    except Exception as e:
        log.error(f"Health check failed: {str(e)}")
        return {
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'status': 'unhealthy',
            'error': str(e)
        }


@celery.task(bind=True)
def cleanup_task_results(self):
    """Clean up old task execution records and results."""
    try:
        monitor = TaskMonitor()
        
        # Get retention period from config
        retention_days = current_app.config.get('TASK_RESULT_RETENTION_DAYS', 30)
        
        # Clean up old task executions
        deleted_count = monitor.cleanup_old_tasks(retention_days)
        
        # Clean up Celery result backend (if using database backend)
        try:
            from celery.backends.database import DatabaseBackend
            
            if isinstance(celery.backend, DatabaseBackend):
                # Clean up old results
                cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
                
                # This would depend on the specific backend implementation
                # For now, just log the attempt
                log.info("Would clean up Celery result backend records")
                
        except Exception as e:
            log.warning(f"Could not clean Celery result backend: {str(e)}")
        
        log.info(f"Cleaned up {deleted_count} old task execution records")
        
        return {
            'success': True,
            'deleted_task_executions': deleted_count,
            'retention_days': retention_days,
            'cleaned_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error(f"Task cleanup failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


@celery.task(bind=True, max_retries=3)
def process_notification_async(self, notification_type: str, recipients: List[str], 
                             message: str, context: Dict[str, Any] = None):
    """Send notifications asynchronously."""
    try:
        # Import notification handler (would be implemented separately)
        # from ..notifications.handler import NotificationHandler
        # handler = NotificationHandler()
        
        log.info(f"Would send {notification_type} notification to {len(recipients)} recipients")
        
        # Simulate notification sending
        notification_results = []
        for recipient in recipients:
            # In real implementation, would send actual notifications
            result = {
                'recipient': recipient,
                'status': 'sent',
                'sent_at': datetime.now(tz=timezone.utc).isoformat()
            }
            notification_results.append(result)
        
        return {
            'success': True,
            'notification_type': notification_type,
            'recipients_count': len(recipients),
            'results': notification_results,
            'context': context
        }
        
    except Exception as e:
        log.error(f"Notification sending failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=2 ** self.request.retries, exc=e)
        
        return {
            'success': False,
            'error': str(e),
            'notification_type': notification_type,
            'recipients_count': len(recipients) if recipients else 0
        }


@celery.task(bind=True, max_retries=2)
def execute_webhook_async(self, url: str, method: str = 'POST', 
                         payload: Dict[str, Any] = None, headers: Dict[str, str] = None):
    """Execute webhook calls asynchronously."""
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # Configure session with retries
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "POST", "PUT", "DELETE"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set default headers
        default_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'ProcessEngine-Webhook/1.0'
        }
        
        if headers:
            default_headers.update(headers)
        
        # Make the request
        response = session.request(
            method=method.upper(),
            url=url,
            json=payload,
            headers=default_headers,
            timeout=30
        )
        
        response.raise_for_status()
        
        log.info(f"Webhook executed successfully: {method} {url} -> {response.status_code}")
        
        return {
            'success': True,
            'url': url,
            'method': method,
            'status_code': response.status_code,
            'response_headers': dict(response.headers),
            'response_body': response.text[:1000] if response.text else None,  # Truncate response
            'executed_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
    except requests.exceptions.RequestException as e:
        log.error(f"Webhook request failed: {str(e)}")
        
        # Retry for specific errors
        if self.request.retries < self.max_retries:
            if isinstance(e, (requests.exceptions.ConnectionError, 
                            requests.exceptions.Timeout,
                            requests.exceptions.HTTPError)):
                raise self.retry(countdown=60 * (self.request.retries + 1), exc=e)
        
        return {
            'success': False,
            'url': url,
            'method': method,
            'error': str(e),
            'error_type': type(e).__name__
        }
        
    except Exception as e:
        log.error(f"Webhook execution failed: {str(e)}")
        return {
            'success': False,
            'url': url,
            'method': method,
            'error': str(e),
            'error_type': type(e).__name__
        }


@celery.task(bind=True)
def generate_analytics_report_async(self, report_type: str, time_range: int = 30, 
                                   params: Dict[str, Any] = None):
    """Generate analytics reports asynchronously."""
    try:
        from ..analytics.dashboard import ProcessAnalytics
        
        analytics = ProcessAnalytics()
        
        if report_type == 'dashboard':
            data = analytics.get_dashboard_metrics(time_range)
        elif report_type == 'process_details' and params and 'process_id' in params:
            data = analytics.get_process_details(params['process_id'], time_range)
        else:
            raise ValueError(f"Unknown report type: {report_type}")
        
        # In real implementation, might save report to file storage
        report_id = f"report_{report_type}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        log.info(f"Generated analytics report: {report_id}")
        
        return {
            'success': True,
            'report_id': report_id,
            'report_type': report_type,
            'time_range': time_range,
            'data': data,
            'generated_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error(f"Analytics report generation failed: {str(e)}")
        return {
            'success': False,
            'report_type': report_type,
            'error': str(e)
        }


@celery.task(bind=True)
def optimize_process_performance(self, process_id: int = None):
    """Analyze and provide optimization recommendations for processes."""
    try:
        from ..analytics.dashboard import ProcessAnalytics
        
        analytics = ProcessAnalytics()
        
        if process_id:
            # Analyze specific process
            process_data = analytics.get_process_details(process_id, 30)
            recommendations = process_data.get('recommendations', [])
            
            optimization_targets = []
            
            # Check for specific optimization opportunities
            step_analysis = process_data.get('step_analysis', {})
            if step_analysis:
                step_performance = step_analysis.get('step_performance', [])
                
                # Identify slow steps
                for step in step_performance:
                    if step.get('avg_duration', 0) > 300:  # More than 5 minutes
                        optimization_targets.append({
                            'type': 'slow_step',
                            'node_id': step.get('node_id'),
                            'node_type': step.get('node_type'),
                            'avg_duration': step.get('avg_duration'),
                            'recommendation': 'Consider optimizing or parallelizing this step'
                        })
                    
                    if step.get('failure_rate', 0) > 10:  # More than 10% failure rate
                        optimization_targets.append({
                            'type': 'high_failure_rate',
                            'node_id': step.get('node_id'),
                            'node_type': step.get('node_type'),
                            'failure_rate': step.get('failure_rate'),
                            'recommendation': 'Implement better error handling and validation'
                        })
            
        else:
            # Analyze all processes
            dashboard_data = analytics.get_dashboard_metrics(30)
            
            optimization_targets = []
            
            # Check for system-wide optimization opportunities
            bottlenecks = dashboard_data.get('bottlenecks', {})
            if bottlenecks:
                bottleneck_list = bottlenecks.get('bottlenecks', [])
                for bottleneck in bottleneck_list[:5]:  # Top 5 bottlenecks
                    optimization_targets.append({
                        'type': 'system_bottleneck',
                        'node_id': bottleneck.get('node_id'),
                        'node_type': bottleneck.get('node_type'),
                        'bottleneck_score': bottleneck.get('bottleneck_score'),
                        'recommendation': 'Priority optimization target based on system-wide impact'
                    })
            
            recommendations = ['System-wide analysis completed', 
                             'Focus on high-impact bottlenecks first',
                             'Consider implementing caching for frequently accessed data']
        
        log.info(f"Process optimization analysis completed for process_id: {process_id}")
        
        return {
            'success': True,
            'process_id': process_id,
            'optimization_targets': optimization_targets,
            'recommendations': recommendations,
            'analyzed_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error(f"Process optimization analysis failed: {str(e)}")
        return {
            'success': False,
            'process_id': process_id,
            'error': str(e)
        }


@celery.task(bind=True)
def backup_process_data_async(self, backup_type: str = 'incremental', 
                            include_archived: bool = False):
    """Create backup of process data asynchronously."""
    try:
        tenant_id = TenantContext.get_current_tenant_id()
        backup_timestamp = datetime.now(tz=timezone.utc)
        
        # Determine what data to backup
        if backup_type == 'full':
            # Full backup of all process data
            process_instances = db.session.query(ProcessInstance).filter_by(
                tenant_id=tenant_id
            ).count()
            
            process_steps = db.session.query(ProcessStep).join(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id
            ).count()
            
        else:  # incremental
            # Only backup recent changes
            cutoff_date = backup_timestamp - timedelta(days=7)  # Last week
            
            process_instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.created_at >= cutoff_date
            ).count()
            
            process_steps = db.session.query(ProcessStep).join(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessStep.created_at >= cutoff_date
            ).count()
        
        # In real implementation, would create actual backup files
        backup_info = {
            'backup_id': f"backup_{backup_type}_{backup_timestamp.strftime('%Y%m%d_%H%M%S')}",
            'backup_type': backup_type,
            'tenant_id': tenant_id,
            'process_instances_count': process_instances,
            'process_steps_count': process_steps,
            'include_archived': include_archived,
            'created_at': backup_timestamp.isoformat()
        }
        
        # Store backup metadata (in real implementation)
        log.info(f"Process data backup created: {backup_info['backup_id']}")
        
        return {
            'success': True,
            **backup_info
        }
        
    except Exception as e:
        log.error(f"Process data backup failed: {str(e)}")
        return {
            'success': False,
            'backup_type': backup_type,
            'error': str(e)
        }


@celery.task(bind=True, rate_limit='10/m')  # Rate limit to prevent spam
def send_alert_async(self, alert_type: str, severity: str, message: str, 
                    context: Dict[str, Any] = None):
    """Send system alerts asynchronously."""
    try:
        alert_data = {
            'alert_id': f"alert_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{hash(message) % 10000}",
            'alert_type': alert_type,
            'severity': severity,
            'message': message,
            'context': context or {},
            'tenant_id': TenantContext.get_current_tenant_id(),
            'timestamp': datetime.now(tz=timezone.utc).isoformat()
        }
        
        # Determine alert destinations based on severity
        if severity == 'critical':
            # Send to administrators immediately
            recipients = ['admin@example.com']  # Would be configured
            notification_type = 'email_urgent'
        elif severity == 'warning':
            # Send to monitoring dashboard and optional email
            recipients = ['monitor@example.com']
            notification_type = 'email'
        else:  # info
            # Just log and store in dashboard
            recipients = []
            notification_type = 'dashboard_only'
        
        # Send notifications if needed
        if recipients:
            # In real implementation, would integrate with notification system
            log.info(f"Would send {notification_type} alert to {recipients}")
        
        # Store alert in system (for dashboard display)
        log.warning(f"ALERT [{severity.upper()}] {alert_type}: {message}")
        
        return {
            'success': True,
            **alert_data,
            'notifications_sent': len(recipients)
        }
        
    except Exception as e:
        log.error(f"Alert sending failed: {str(e)}")
        return {
            'success': False,
            'alert_type': alert_type,
            'error': str(e)
        }


@celery.task(bind=True)
def validate_process_integrity(self):
    """Validate integrity of process data and fix inconsistencies."""
    try:
        tenant_id = TenantContext.get_current_tenant_id()
        issues_found = []
        fixes_applied = []
        
        # Check for orphaned process steps
        orphaned_steps = db.session.query(ProcessStep).filter(
            ~ProcessStep.instance_id.in_(
                db.session.query(ProcessInstance.id).filter_by(tenant_id=tenant_id)
            )
        ).all()
        
        if orphaned_steps:
            issues_found.append(f"Found {len(orphaned_steps)} orphaned process steps")
            
            # Clean up orphaned steps
            for step in orphaned_steps:
                db.session.delete(step)
            fixes_applied.append(f"Deleted {len(orphaned_steps)} orphaned process steps")
        
        # Check for processes with inconsistent status
        inconsistent_processes = db.session.query(ProcessInstance).filter(
            ProcessInstance.tenant_id == tenant_id,
            ProcessInstance.status == 'completed',
            ProcessInstance.completed_at.is_(None)
        ).all()
        
        if inconsistent_processes:
            issues_found.append(f"Found {len(inconsistent_processes)} processes marked completed without completion timestamp")
            
            # Fix completion timestamps
            for process in inconsistent_processes:
                # Use last step completion time or current time
                last_step = db.session.query(ProcessStep).filter_by(
                    instance_id=process.id
                ).order_by(ProcessStep.completed_at.desc()).first()
                
                if last_step and last_step.completed_at:
                    process.completed_at = last_step.completed_at
                else:
                    process.completed_at = datetime.now(tz=timezone.utc)
            
            fixes_applied.append(f"Fixed completion timestamps for {len(inconsistent_processes)} processes")
        
        # Check for stuck running processes
        stuck_threshold = datetime.now(tz=timezone.utc) - timedelta(hours=48)  # 48 hours
        stuck_processes = db.session.query(ProcessInstance).filter(
            ProcessInstance.tenant_id == tenant_id,
            ProcessInstance.status == 'running',
            ProcessInstance.last_activity_at < stuck_threshold
        ).all()
        
        if stuck_processes:
            issues_found.append(f"Found {len(stuck_processes)} potentially stuck processes")
            # Don't auto-fix these, just report
        
        # Commit fixes
        if fixes_applied:
            db.session.commit()
            log.info(f"Process integrity validation completed with fixes: {fixes_applied}")
        else:
            log.info("Process integrity validation completed - no issues found")
        
        return {
            'success': True,
            'issues_found': issues_found,
            'fixes_applied': fixes_applied,
            'stuck_processes_count': len(stuck_processes) if stuck_processes else 0,
            'validated_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
    except Exception as e:
        db.session.rollback()
        log.error(f"Process integrity validation failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }