"""
Comprehensive Performance Monitoring for Approval Workflows

Advanced performance monitoring system with metrics collection, alerting,
dashboard integration, and real-time performance analysis.
"""

import time
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import json

try:
    import prometheus_client
    from prometheus_client import Counter, Histogram, Gauge, Summary
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

try:
    import statsd
    STATSD_AVAILABLE = True
except ImportError:
    STATSD_AVAILABLE = False

log = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics collected."""
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"
    SUMMARY = "summary"
    TIMER = "timer"


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class PerformanceMetric:
    """Performance metric data point."""
    name: str
    value: Union[int, float]
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    
@dataclass
class PerformanceAlert:
    """Performance alert definition."""
    name: str
    condition: Callable[[float], bool]
    level: AlertLevel
    message: str
    cooldown_seconds: int = 300
    last_triggered: Optional[datetime] = None


@dataclass
class ApprovalMetrics:
    """Aggregated approval performance metrics."""
    total_approvals: int = 0
    successful_approvals: int = 0
    failed_approvals: int = 0
    average_duration: float = 0.0
    p95_duration: float = 0.0
    p99_duration: float = 0.0
    throughput_per_minute: float = 0.0
    error_rate: float = 0.0
    slow_approval_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)


from abc import ABC, abstractmethod

class MonitoringBackend(ABC):
    """Base class for monitoring backends with safe default implementations."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', True)

    def send_metric(self, metric: PerformanceMetric):
        """Send metric to monitoring backend."""
        if not self.enabled:
            return

        # Safe default implementation - log to standard logger
        log.info(f"Performance Metric - {metric.name}: {metric.value} "
                f"(duration: {metric.duration}ms, timestamp: {metric.timestamp})")

    def send_alert(self, alert: PerformanceAlert):
        """Send alert to monitoring backend."""
        if not self.enabled:
            return

        # Safe default implementation - log alert
        log.warning(f"Performance Alert - {alert.alert_type}: {alert.message} "
                   f"(severity: {alert.severity}, threshold: {alert.threshold})")


class PrometheusBackend(MonitoringBackend):
    """Prometheus monitoring backend."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        if not PROMETHEUS_AVAILABLE:
            log.warning("Prometheus client not available")
            self.enabled = False
            return
        
        self._metrics = {}
        self._setup_prometheus_metrics()
    
    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics."""
        self._metrics = {
            'approval_duration': Histogram(
                'approval_duration_seconds',
                'Time spent processing approval requests',
                ['workflow_type', 'step', 'status']
            ),
            'approval_total': Counter(
                'approval_total',
                'Total number of approval requests',
                ['workflow_type', 'status']
            ),
            'approval_queue_size': Gauge(
                'approval_queue_size',
                'Number of pending approval requests',
                ['workflow_type']
            ),
            'approval_error_rate': Gauge(
                'approval_error_rate',
                'Approval error rate percentage',
                ['workflow_type']
            ),
            'connection_pool_utilization': Gauge(
                'connection_pool_utilization_percent',
                'Database connection pool utilization',
                []
            ),
            'cache_hit_rate': Gauge(
                'approval_cache_hit_rate',
                'Approval cache hit rate percentage',
                []
            )
        }
    
    def send_metric(self, metric: PerformanceMetric):
        """Send metric to Prometheus."""
        if not self.enabled:
            return
        
        metric_name = metric.name.replace('-', '_')
        labels = list(metric.labels.values()) if metric.labels else []
        
        if metric_name in self._metrics:
            if metric.metric_type == MetricType.COUNTER:
                self._metrics[metric_name].labels(*labels).inc(metric.value)
            elif metric.metric_type == MetricType.HISTOGRAM:
                self._metrics[metric_name].labels(*labels).observe(metric.value)
            elif metric.metric_type == MetricType.GAUGE:
                self._metrics[metric_name].labels(*labels).set(metric.value)
        else:
            log.debug(f"Unknown Prometheus metric: {metric_name}")


class StatsDBackend(MonitoringBackend):
    """StatsD monitoring backend."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        if not STATSD_AVAILABLE:
            log.warning("StatsD client not available")
            self.enabled = False
            return
        
        self.client = statsd.StatsClient(
            host=config.get('host', 'localhost'),
            port=config.get('port', 8125),
            prefix=config.get('prefix', 'approval.')
        )
    
    def send_metric(self, metric: PerformanceMetric):
        """Send metric to StatsD."""
        if not self.enabled:
            return
        
        metric_name = metric.name.replace('-', '_')
        
        if metric.metric_type == MetricType.COUNTER:
            self.client.incr(metric_name, metric.value)
        elif metric.metric_type == MetricType.TIMER:
            self.client.timing(metric_name, metric.value)
        elif metric.metric_type == MetricType.GAUGE:
            self.client.gauge(metric_name, metric.value)


class CustomBackend(MonitoringBackend):
    """Custom monitoring backend for internal metrics storage."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.metrics_store = defaultdict(list)
        self.max_metrics_per_type = config.get('max_metrics_per_type', 1000)
        self._lock = threading.RLock()
    
    def send_metric(self, metric: PerformanceMetric):
        """Store metric internally."""
        if not self.enabled:
            return
        
        with self._lock:
            metrics_list = self.metrics_store[metric.name]
            metrics_list.append(metric)
            
            # Keep only recent metrics
            if len(metrics_list) > self.max_metrics_per_type:
                metrics_list.pop(0)
    
    def get_metrics(self, metric_name: str, 
                   since: Optional[datetime] = None) -> List[PerformanceMetric]:
        """Get stored metrics."""
        with self._lock:
            metrics = self.metrics_store.get(metric_name, [])
            
            if since:
                metrics = [m for m in metrics if m.timestamp >= since]
            
            return metrics.copy()
    
    def get_metric_summary(self, metric_name: str, 
                          duration_minutes: int = 60) -> Dict[str, Any]:
        """Get metric summary for specified duration."""
        since = datetime.now(tz=timezone.utc) - timedelta(minutes=duration_minutes)
        metrics = self.get_metrics(metric_name, since)
        
        if not metrics:
            return {'count': 0, 'values': []}
        
        values = [m.value for m in metrics]
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'values': values,
            'first_timestamp': metrics[0].timestamp.isoformat(),
            'last_timestamp': metrics[-1].timestamp.isoformat()
        }


class ApprovalPerformanceMonitor:
    """
    Comprehensive performance monitoring for approval workflows.
    
    Features:
    - Multi-backend metric collection (Prometheus, StatsD, Custom)
    - Real-time performance tracking and alerting
    - Dashboard data generation
    - Performance analysis and optimization recommendations
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize performance monitor."""
        self.config = config or {}
        self._backends: List[MonitoringBackend] = []
        self._alerts: List[PerformanceAlert] = []
        self._metrics_cache = deque(maxlen=10000)
        self._performance_history = defaultdict(deque)
        self._lock = threading.RLock()
        
        # Performance thresholds
        self.slow_approval_threshold = self.config.get('slow_approval_threshold', 2.0)
        self.critical_approval_threshold = self.config.get('critical_approval_threshold', 5.0)
        self.error_rate_threshold = self.config.get('error_rate_threshold', 5.0)
        
        self._setup_backends()
        self._setup_alerts()
        
        log.info("ApprovalPerformanceMonitor initialized")
    
    def _setup_backends(self):
        """Setup monitoring backends."""
        backends_config = self.config.get('backends', {})
        
        # Prometheus backend
        if backends_config.get('prometheus', {}).get('enabled', False):
            self._backends.append(PrometheusBackend(backends_config['prometheus']))
        
        # StatsD backend
        if backends_config.get('statsd', {}).get('enabled', False):
            self._backends.append(StatsDBackend(backends_config['statsd']))
        
        # Custom backend (always enabled for internal metrics)
        custom_config = backends_config.get('custom', {'enabled': True})
        self._custom_backend = CustomBackend(custom_config)
        self._backends.append(self._custom_backend)
        
        log.info(f"Initialized {len(self._backends)} monitoring backends")
    
    def _setup_alerts(self):
        """Setup performance alerts."""
        self._alerts = [
            PerformanceAlert(
                name="slow_approval_rate",
                condition=lambda rate: rate > 10.0,  # More than 10% slow approvals
                level=AlertLevel.WARNING,
                message="High rate of slow approvals detected",
                cooldown_seconds=300
            ),
            PerformanceAlert(
                name="approval_error_rate",
                condition=lambda rate: rate > self.error_rate_threshold,
                level=AlertLevel.CRITICAL,
                message="High approval error rate detected",
                cooldown_seconds=180
            ),
            PerformanceAlert(
                name="critical_approval_duration",
                condition=lambda duration: duration > self.critical_approval_threshold,
                level=AlertLevel.EMERGENCY,
                message="Critical approval duration detected",
                cooldown_seconds=60
            ),
            PerformanceAlert(
                name="connection_pool_exhaustion",
                condition=lambda utilization: utilization > 95.0,
                level=AlertLevel.CRITICAL,
                message="Database connection pool near exhaustion",
                cooldown_seconds=120
            )
        ]
    
    @contextmanager
    def track_approval_metrics(self, approval_id: int, 
                              workflow_type: str = "default",
                              step: int = 0):
        """
        Context manager to track approval performance metrics.
        
        Args:
            approval_id: Unique approval identifier
            workflow_type: Type of workflow being processed
            step: Workflow step number
        """
        start_time = time.time()
        start_memory = self._get_memory_usage()
        labels = {
            'workflow_type': workflow_type,
            'step': str(step),
            'approval_id': str(approval_id)
        }
        
        try:
            # Track approval start
            self._send_metric(PerformanceMetric(
                name='approval_started',
                value=1,
                metric_type=MetricType.COUNTER,
                labels=labels
            ))
            
            yield
            
            # Track successful completion
            duration = time.time() - start_time
            memory_used = self._get_memory_usage() - start_memory
            
            success_labels = {**labels, 'status': 'success'}
            
            self._send_metric(PerformanceMetric(
                name='approval_duration',
                value=duration,
                metric_type=MetricType.HISTOGRAM,
                labels=success_labels
            ))
            
            self._send_metric(PerformanceMetric(
                name='approval_memory_usage',
                value=memory_used,
                metric_type=MetricType.HISTOGRAM,
                labels=success_labels
            ))
            
            self._send_metric(PerformanceMetric(
                name='approval_total',
                value=1,
                metric_type=MetricType.COUNTER,
                labels=success_labels
            ))
            
            # Check for slow approval
            if duration > self.slow_approval_threshold:
                log.warning(f"Slow approval: {approval_id} took {duration:.2f}s")
                self._send_metric(PerformanceMetric(
                    name='slow_approval_total',
                    value=1,
                    metric_type=MetricType.COUNTER,
                    labels=labels
                ))
                
                # Check for critical duration
                if duration > self.critical_approval_threshold:
                    self._trigger_alert('critical_approval_duration', duration)
            
            # Store performance history
            self._store_performance_data(approval_id, duration, True, workflow_type, step)
            
        except Exception as e:
            # Track failure
            duration = time.time() - start_time
            error_labels = {**labels, 'status': 'error', 'error_type': type(e).__name__}
            
            self._send_metric(PerformanceMetric(
                name='approval_duration',
                value=duration,
                metric_type=MetricType.HISTOGRAM,
                labels=error_labels
            ))
            
            self._send_metric(PerformanceMetric(
                name='approval_total',
                value=1,
                metric_type=MetricType.COUNTER,
                labels=error_labels
            ))
            
            self._send_metric(PerformanceMetric(
                name='approval_errors_total',
                value=1,
                metric_type=MetricType.COUNTER,
                labels=error_labels
            ))
            
            # Store failure in performance history
            self._store_performance_data(approval_id, duration, False, workflow_type, step)
            
            log.error(f"Approval {approval_id} failed after {duration:.2f}s: {e}")
            raise
        
        finally:
            # Always track completion
            total_duration = time.time() - start_time
            self._send_metric(PerformanceMetric(
                name='approval_completed',
                value=1,
                metric_type=MetricType.COUNTER,
                labels=labels
            ))
    
    def track_connection_pool_metrics(self, metrics: Dict[str, Any]):
        """Track database connection pool metrics."""
        utilization = metrics.get('utilization_percent', 0)
        
        self._send_metric(PerformanceMetric(
            name='connection_pool_utilization',
            value=utilization,
            metric_type=MetricType.GAUGE
        ))
        
        self._send_metric(PerformanceMetric(
            name='connection_pool_active',
            value=metrics.get('active_connections', 0),
            metric_type=MetricType.GAUGE
        ))
        
        self._send_metric(PerformanceMetric(
            name='connection_pool_idle',
            value=metrics.get('idle_connections', 0),
            metric_type=MetricType.GAUGE
        ))
        
        # Check for high utilization
        if utilization > 95.0:
            self._trigger_alert('connection_pool_exhaustion', utilization)
    
    def track_cache_metrics(self, hit_rate: float, cache_size: int):
        """Track approval cache performance metrics."""
        self._send_metric(PerformanceMetric(
            name='cache_hit_rate',
            value=hit_rate,
            metric_type=MetricType.GAUGE
        ))
        
        self._send_metric(PerformanceMetric(
            name='cache_size',
            value=cache_size,
            metric_type=MetricType.GAUGE
        ))
    
    def track_bulk_operation_metrics(self, operation_count: int, 
                                   total_duration: float,
                                   success_count: int,
                                   failure_count: int):
        """Track bulk operation performance metrics."""
        throughput = operation_count / total_duration if total_duration > 0 else 0
        error_rate = (failure_count / operation_count * 100) if operation_count > 0 else 0
        
        self._send_metric(PerformanceMetric(
            name='bulk_operation_throughput',
            value=throughput,
            metric_type=MetricType.GAUGE,
            labels={'operation_type': 'approval'}
        ))
        
        self._send_metric(PerformanceMetric(
            name='bulk_operation_error_rate',
            value=error_rate,
            metric_type=MetricType.GAUGE,
            labels={'operation_type': 'approval'}
        ))
        
        # Check error rate
        if error_rate > self.error_rate_threshold:
            self._trigger_alert('approval_error_rate', error_rate)
    
    def _send_metric(self, metric: PerformanceMetric):
        """Send metric to all configured backends."""
        with self._lock:
            # Cache metric
            self._metrics_cache.append(metric)
            
            # Send to backends
            for backend in self._backends:
                try:
                    backend.send_metric(metric)
                except Exception as e:
                    log.error(f"Failed to send metric to backend {type(backend).__name__}: {e}")
    
    def _trigger_alert(self, alert_name: str, value: float):
        """Trigger performance alert if conditions are met."""
        for alert in self._alerts:
            if alert.name == alert_name:
                # Check cooldown
                if (alert.last_triggered and 
                    (datetime.now(tz=timezone.utc) - alert.last_triggered).total_seconds() < alert.cooldown_seconds):
                    return
                
                # Check condition
                if alert.condition(value):
                    alert.last_triggered = datetime.now(tz=timezone.utc)
                    
                    log.log(
                        logging.WARNING if alert.level == AlertLevel.WARNING else logging.ERROR,
                        f"ALERT [{alert.level.value.upper()}] {alert.message}: {value}"
                    )
                    
                    # Send alert to backends
                    for backend in self._backends:
                        try:
                            if hasattr(backend, 'send_alert'):
                                backend.send_alert(alert)
                        except Exception as e:
                            log.error(f"Failed to send alert to backend: {e}")
                
                break
    
    def _store_performance_data(self, approval_id: int, duration: float,
                              success: bool, workflow_type: str, step: int):
        """Store performance data for analysis."""
        with self._lock:
            performance_data = {
                'approval_id': approval_id,
                'duration': duration,
                'success': success,
                'workflow_type': workflow_type,
                'step': step,
                'timestamp': datetime.now(tz=timezone.utc)
            }
            
            # Store in workflow-specific history
            history_key = f"{workflow_type}_{step}"
            self._performance_history[history_key].append(performance_data)
            
            # Limit history size
            if len(self._performance_history[history_key]) > 1000:
                self._performance_history[history_key].popleft()
    
    def _get_memory_usage(self) -> int:
        """Get current memory usage in bytes."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except ImportError:
            return 0
    
    def get_approval_metrics(self, duration_minutes: int = 60) -> ApprovalMetrics:
        """Get aggregated approval metrics for specified duration."""
        since = datetime.now(tz=timezone.utc) - timedelta(minutes=duration_minutes)
        
        # Get metrics from custom backend
        duration_metrics = self._custom_backend.get_metrics('approval_duration', since)
        success_metrics = self._custom_backend.get_metrics('approval_total', since)
        error_metrics = self._custom_backend.get_metrics('approval_errors_total', since)
        slow_metrics = self._custom_backend.get_metrics('slow_approval_total', since)
        
        if not duration_metrics:
            return ApprovalMetrics()
        
        # Calculate aggregated metrics
        durations = [m.value for m in duration_metrics]
        durations.sort()
        
        total_approvals = len(duration_metrics)
        successful_approvals = len([m for m in success_metrics if m.labels.get('status') == 'success'])
        failed_approvals = len(error_metrics)
        
        return ApprovalMetrics(
            total_approvals=total_approvals,
            successful_approvals=successful_approvals,
            failed_approvals=failed_approvals,
            average_duration=sum(durations) / len(durations) if durations else 0,
            p95_duration=durations[int(len(durations) * 0.95)] if durations else 0,
            p99_duration=durations[int(len(durations) * 0.99)] if durations else 0,
            throughput_per_minute=total_approvals / duration_minutes,
            error_rate=(failed_approvals / total_approvals * 100) if total_approvals > 0 else 0,
            slow_approval_count=len(slow_metrics)
        )
    
    def get_performance_dashboard_data(self) -> Dict[str, Any]:
        """Get performance data formatted for dashboard display."""
        metrics_60min = self.get_approval_metrics(60)
        metrics_24h = self.get_approval_metrics(1440)
        
        # Get recent performance trends
        recent_metrics = []
        for i in range(12):  # Last 12 hours, hourly
            hour_start = datetime.now(tz=timezone.utc) - timedelta(hours=i+1)
            hour_end = datetime.now(tz=timezone.utc) - timedelta(hours=i)
            hour_metrics = self.get_approval_metrics_for_period(hour_start, hour_end)
            recent_metrics.append({
                'timestamp': hour_start.isoformat(),
                'throughput': hour_metrics.throughput_per_minute * 60,  # per hour
                'avg_duration': hour_metrics.average_duration,
                'error_rate': hour_metrics.error_rate
            })
        
        return {
            'current_metrics': {
                'last_hour': metrics_60min.__dict__,
                'last_24_hours': metrics_24h.__dict__
            },
            'trends': {
                'hourly': list(reversed(recent_metrics))
            },
            'alerts': {
                'active_alerts': [
                    {
                        'name': alert.name,
                        'level': alert.level.value,
                        'message': alert.message,
                        'last_triggered': alert.last_triggered.isoformat() if alert.last_triggered else None
                    }
                    for alert in self._alerts
                    if alert.last_triggered and 
                    (datetime.now(tz=timezone.utc) - alert.last_triggered).total_seconds() < 3600
                ]
            },
            'performance_recommendations': self._generate_performance_recommendations(metrics_60min)
        }
    
    def get_approval_metrics_for_period(self, start: datetime, end: datetime) -> ApprovalMetrics:
        """Get approval metrics for specific time period."""
        duration_metrics = [
            m for m in self._custom_backend.get_metrics('approval_duration')
            if start <= m.timestamp <= end
        ]
        
        if not duration_metrics:
            return ApprovalMetrics()
        
        durations = [m.value for m in duration_metrics]
        durations.sort()
        
        success_count = len([m for m in duration_metrics if m.labels.get('status') == 'success'])
        error_count = len([m for m in duration_metrics if m.labels.get('status') == 'error'])
        
        duration_minutes = (end - start).total_seconds() / 60
        
        return ApprovalMetrics(
            total_approvals=len(duration_metrics),
            successful_approvals=success_count,
            failed_approvals=error_count,
            average_duration=sum(durations) / len(durations),
            p95_duration=durations[int(len(durations) * 0.95)] if durations else 0,
            p99_duration=durations[int(len(durations) * 0.99)] if durations else 0,
            throughput_per_minute=len(duration_metrics) / duration_minutes if duration_minutes > 0 else 0,
            error_rate=(error_count / len(duration_metrics) * 100) if duration_metrics else 0,
            slow_approval_count=len([d for d in durations if d > self.slow_approval_threshold])
        )
    
    def _generate_performance_recommendations(self, metrics: ApprovalMetrics) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        if metrics.error_rate > 5.0:
            recommendations.append(f"High error rate ({metrics.error_rate:.1f}%) - investigate error causes")
        
        if metrics.p95_duration > 3.0:
            recommendations.append(f"95th percentile duration is high ({metrics.p95_duration:.2f}s) - optimize slow paths")
        
        if metrics.slow_approval_count > metrics.total_approvals * 0.1:
            recommendations.append("More than 10% of approvals are slow - consider performance tuning")
        
        if metrics.throughput_per_minute < 1.0:
            recommendations.append("Low throughput detected - check for bottlenecks")
        
        if not recommendations:
            recommendations.append("Performance metrics are within acceptable ranges")
        
        return recommendations
    
    def export_metrics(self, format_type: str = 'json') -> str:
        """Export performance metrics in specified format."""
        dashboard_data = self.get_performance_dashboard_data()
        
        if format_type.lower() == 'json':
            return json.dumps(dashboard_data, indent=2, default=str)
        elif format_type.lower() == 'prometheus':
            return self._export_prometheus_format()
        else:
            raise ValueError(f"Unsupported export format: {format_type}")
    
    def _export_prometheus_format(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        metrics = self.get_approval_metrics(60)
        
        lines.append(f"# HELP approval_total_count Total number of approvals in last hour")
        lines.append(f"# TYPE approval_total_count gauge")
        lines.append(f"approval_total_count {metrics.total_approvals}")
        
        lines.append(f"# HELP approval_error_rate_percent Approval error rate percentage")
        lines.append(f"# TYPE approval_error_rate_percent gauge")
        lines.append(f"approval_error_rate_percent {metrics.error_rate}")
        
        lines.append(f"# HELP approval_average_duration_seconds Average approval duration")
        lines.append(f"# TYPE approval_average_duration_seconds gauge")
        lines.append(f"approval_average_duration_seconds {metrics.average_duration}")
        
        return '\n'.join(lines)


# Global performance monitor instance
_performance_monitor: Optional[ApprovalPerformanceMonitor] = None


def get_performance_monitor(config: Optional[Dict[str, Any]] = None) -> ApprovalPerformanceMonitor:
    """Get or create global performance monitor."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = ApprovalPerformanceMonitor(config)
    return _performance_monitor


def initialize_performance_monitoring(config: Dict[str, Any]) -> ApprovalPerformanceMonitor:
    """Initialize global performance monitoring."""
    global _performance_monitor
    _performance_monitor = ApprovalPerformanceMonitor(config)
    log.info("Performance monitoring initialized")
    return _performance_monitor