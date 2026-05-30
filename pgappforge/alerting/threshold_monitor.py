"""
Threshold Monitor for continuous metric evaluation.

Provides automated monitoring of metrics against configured thresholds
with support for various evaluation strategies and monitoring intervals.
"""

import logging
import threading
import time
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass

log = logging.getLogger(__name__)


class ThresholdCondition(Enum):
    """Threshold condition types."""
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUALS = "=="
    NOT_EQUALS = "!="
    RANGE = "range"  # Special condition for value ranges
    PERCENT_CHANGE = "percent_change"  # Percentage change from baseline


@dataclass
class MonitoringConfig:
    """
    Configuration for threshold monitoring.
    """
    interval_seconds: int = 60  # How often to check
    max_history_size: int = 1000  # How many historical values to keep
    enable_baseline_calculation: bool = True  # Calculate baselines for percent change
    baseline_window_hours: int = 24  # Window for baseline calculation
    evaluation_timeout_seconds: int = 10  # Timeout for metric evaluation
    parallel_evaluation: bool = True  # Evaluate metrics in parallel


class ThresholdMonitor:
    """
    Continuous threshold monitoring system.
    
    Monitors registered metrics at configurable intervals and evaluates
    them against alert rules using the alert manager.
    """
    
    def __init__(self, alert_manager, config: Optional[MonitoringConfig] = None):
        """
        Initialize threshold monitor.
        
        Args:
            alert_manager: AlertManager instance
            config: Monitoring configuration
        """
        self.alert_manager = alert_manager
        self.config = config or MonitoringConfig()
        
        self._monitoring = False
        self._monitor_thread = None
        self._stop_event = threading.Event()
        
        # Metric history for baseline calculations
        self._metric_history: Dict[str, List[tuple]] = {}  # metric_name -> [(timestamp, value), ...]
        
        # Cached baselines
        self._baselines: Dict[str, float] = {}
        self._baseline_last_calculated: Dict[str, datetime] = {}
        
        # Custom evaluators for complex conditions
        self._custom_evaluators: Dict[str, Callable] = {}
        
        # Monitoring statistics
        self._stats = {
            'evaluations_total': 0,
            'evaluations_successful': 0,
            'evaluations_failed': 0,
            'alerts_triggered': 0,
            'last_evaluation_time': None,
            'average_evaluation_duration': 0.0
        }
        
        log.info("Threshold Monitor initialized")
    
    def start_monitoring(self):
        """Start continuous monitoring in background thread."""
        if self._monitoring:
            log.warning("Monitor is already running")
            return
        
        self._monitoring = True
        self._stop_event.clear()
        
        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            name="ThresholdMonitor",
            daemon=True
        )
        self._monitor_thread.start()
        
        log.info(f"Started threshold monitoring with {self.config.interval_seconds}s interval")
    
    def stop_monitoring(self):
        """Stop continuous monitoring."""
        if not self._monitoring:
            return
        
        self._monitoring = False
        self._stop_event.set()
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
            if self._monitor_thread.is_alive():
                log.warning("Monitor thread did not stop gracefully")
        
        log.info("Stopped threshold monitoring")
    
    def is_monitoring(self) -> bool:
        """Check if monitoring is currently active."""
        return self._monitoring and self._monitor_thread and self._monitor_thread.is_alive()
    
    def _monitoring_loop(self):
        """Main monitoring loop that runs in background thread."""
        log.info("Monitoring loop started")
        
        while not self._stop_event.wait(self.config.interval_seconds):
            try:
                start_time = time.time()
                
                # Evaluate all alert rules
                new_alerts = self._evaluate_all_rules()
                
                # Update statistics
                evaluation_duration = time.time() - start_time
                self._update_stats(len(new_alerts), evaluation_duration, success=True)
                
                log.debug(f"Monitoring cycle completed in {evaluation_duration:.2f}s, {len(new_alerts)} alerts triggered")
                
            except Exception as e:
                log.error(f"Error in monitoring loop: {e}")
                self._update_stats(0, 0, success=False)
        
        log.info("Monitoring loop stopped")
    
    def _evaluate_all_rules(self) -> List:
        """Evaluate all enabled alert rules."""
        try:
            # Update metric history first
            self._update_metric_history()
            
            # Update baselines if needed
            self._update_baselines()
            
            # Let alert manager evaluate rules
            new_alerts = self.alert_manager.evaluate_alert_rules()
            
            return new_alerts
            
        except Exception as e:
            log.error(f"Error evaluating alert rules: {e}")
            return []
    
    def _update_metric_history(self):
        """Update historical values for all monitored metrics."""
        try:
            current_time = datetime.now()
            
            # Get all unique metrics from alert rules
            metrics = set()
            for rule in self.alert_manager.get_alert_rules(enabled_only=True):
                metrics.add(rule.metric_name)
            
            # Update history for each metric
            for metric_name in metrics:
                value = self.alert_manager.get_metric_value(metric_name)
                if value is not None:
                    self._add_to_history(metric_name, current_time, value)
            
        except Exception as e:
            log.error(f"Error updating metric history: {e}")
    
    def _add_to_history(self, metric_name: str, timestamp: datetime, value: float):
        """Add a value to metric history."""
        if metric_name not in self._metric_history:
            self._metric_history[metric_name] = []
        
        history = self._metric_history[metric_name]
        history.append((timestamp, value))
        
        # Limit history size
        if len(history) > self.config.max_history_size:
            history.pop(0)
        
        # Clean old entries
        cutoff_time = timestamp - timedelta(hours=self.config.baseline_window_hours * 2)
        self._metric_history[metric_name] = [
            (t, v) for t, v in history if t > cutoff_time
        ]
    
    def _update_baselines(self):
        """Update baseline calculations for metrics."""
        if not self.config.enable_baseline_calculation:
            return
        
        try:
            current_time = datetime.now()
            
            for metric_name in self._metric_history.keys():
                # Check if baseline needs updating (every hour)
                last_calculated = self._baseline_last_calculated.get(metric_name)
                if (last_calculated and 
                    current_time - last_calculated < timedelta(hours=1)):
                    continue
                
                baseline = self._calculate_baseline(metric_name)
                if baseline is not None:
                    self._baselines[metric_name] = baseline
                    self._baseline_last_calculated[metric_name] = current_time
                    
                    log.debug(f"Updated baseline for {metric_name}: {baseline:.2f}")
        
        except Exception as e:
            log.error(f"Error updating baselines: {e}")
    
    def _calculate_baseline(self, metric_name: str) -> Optional[float]:
        """Calculate baseline value for a metric."""
        try:
            if metric_name not in self._metric_history:
                return None
            
            history = self._metric_history[metric_name]
            if len(history) < 10:  # Need at least 10 data points
                return None
            
            # Get values from the baseline window
            cutoff_time = datetime.now() - timedelta(hours=self.config.baseline_window_hours)
            baseline_values = [
                value for timestamp, value in history 
                if timestamp > cutoff_time
            ]
            
            if len(baseline_values) < 5:
                return None
            
            # Calculate average as baseline (could use median or other methods)
            return sum(baseline_values) / len(baseline_values)
            
        except Exception as e:
            log.error(f"Error calculating baseline for {metric_name}: {e}")
            return None
    
    def get_baseline(self, metric_name: str) -> Optional[float]:
        """Get current baseline value for a metric."""
        return self._baselines.get(metric_name)
    
    def get_metric_history(self, metric_name: str, 
                          hours: Optional[int] = None) -> List[tuple]:
        """
        Get metric history.
        
        Args:
            metric_name: Name of the metric
            hours: Number of hours of history (None for all)
            
        Returns:
            List of (timestamp, value) tuples
        """
        if metric_name not in self._metric_history:
            return []
        
        history = self._metric_history[metric_name]
        
        if hours is not None:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            history = [(t, v) for t, v in history if t > cutoff_time]
        
        return history
    
    def register_custom_evaluator(self, condition_name: str, evaluator_func: Callable):
        """
        Register a custom threshold evaluator.
        
        Args:
            condition_name: Name of the custom condition
            evaluator_func: Function that takes (current_value, threshold, history) and returns bool
        """
        self._custom_evaluators[condition_name] = evaluator_func
        log.info(f"Registered custom evaluator: {condition_name}")
    
    def evaluate_custom_condition(self, condition_name: str, 
                                 current_value: float,
                                 threshold_value: float,
                                 metric_name: str) -> bool:
        """
        Evaluate a custom condition.
        
        Args:
            condition_name: Name of the custom condition
            current_value: Current metric value
            threshold_value: Threshold value
            metric_name: Name of the metric
            
        Returns:
            True if condition is met
        """
        if condition_name not in self._custom_evaluators:
            log.error(f"Unknown custom condition: {condition_name}")
            return False
        
        try:
            evaluator = self._custom_evaluators[condition_name]
            history = self.get_metric_history(metric_name, hours=24)
            
            return evaluator(current_value, threshold_value, history)
            
        except Exception as e:
            log.error(f"Error evaluating custom condition {condition_name}: {e}")
            return False
    
    def evaluate_percent_change_condition(self, current_value: float,
                                        threshold_percent: float,
                                        metric_name: str) -> bool:
        """
        Evaluate percentage change condition against baseline.
        
        Args:
            current_value: Current metric value
            threshold_percent: Threshold percentage (e.g., 20 for 20% increase)
            metric_name: Name of the metric
            
        Returns:
            True if percentage change exceeds threshold
        """
        try:
            baseline = self.get_baseline(metric_name)
            if baseline is None or baseline == 0:
                log.debug(f"No baseline available for {metric_name}")
                return False
            
            percent_change = ((current_value - baseline) / baseline) * 100
            
            # Check if change exceeds threshold (can be positive or negative)
            return abs(percent_change) >= abs(threshold_percent)
            
        except Exception as e:
            log.error(f"Error evaluating percent change condition: {e}")
            return False
    
    def evaluate_range_condition(self, current_value: float,
                               threshold_range: tuple) -> bool:
        """
        Evaluate if value is outside acceptable range.
        
        Args:
            current_value: Current metric value
            threshold_range: Tuple of (min_value, max_value)
            
        Returns:
            True if value is outside the range
        """
        try:
            min_val, max_val = threshold_range
            return current_value < min_val or current_value > max_val
            
        except (ValueError, TypeError) as e:
            log.error(f"Error evaluating range condition: {e}")
            return False
    
    def _update_stats(self, alerts_triggered: int, duration: float, success: bool):
        """Update monitoring statistics."""
        self._stats['evaluations_total'] += 1
        
        if success:
            self._stats['evaluations_successful'] += 1
        else:
            self._stats['evaluations_failed'] += 1
        
        self._stats['alerts_triggered'] += alerts_triggered
        self._stats['last_evaluation_time'] = datetime.now().isoformat()
        
        # Update average evaluation duration (simple moving average)
        if success:
            current_avg = self._stats['average_evaluation_duration']
            total_successful = self._stats['evaluations_successful']
            
            # Simple moving average
            self._stats['average_evaluation_duration'] = (
                (current_avg * (total_successful - 1) + duration) / total_successful
            )
    
    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        return {
            **self._stats,
            'is_monitoring': self.is_monitoring(),
            'config': {
                'interval_seconds': self.config.interval_seconds,
                'max_history_size': self.config.max_history_size,
                'enable_baseline_calculation': self.config.enable_baseline_calculation,
                'baseline_window_hours': self.config.baseline_window_hours
            },
            'metric_history_sizes': {
                metric: len(history) for metric, history in self._metric_history.items()
            },
            'available_baselines': list(self._baselines.keys()),
            'custom_evaluators': list(self._custom_evaluators.keys())
        }
    
    def force_evaluation(self) -> List:
        """Force immediate evaluation of all alert rules."""
        log.info("Force evaluation requested")
        
        try:
            start_time = time.time()
            new_alerts = self._evaluate_all_rules()
            duration = time.time() - start_time
            
            self._update_stats(len(new_alerts), duration, success=True)
            
            log.info(f"Force evaluation completed: {len(new_alerts)} alerts triggered")
            return new_alerts
            
        except Exception as e:
            log.error(f"Error in force evaluation: {e}")
            self._update_stats(0, 0, success=False)
            return []
    
    def clear_history(self, metric_name: Optional[str] = None):
        """
        Clear metric history.
        
        Args:
            metric_name: Specific metric to clear, or None for all metrics
        """
        if metric_name:
            if metric_name in self._metric_history:
                del self._metric_history[metric_name]
                log.info(f"Cleared history for metric: {metric_name}")
        else:
            self._metric_history.clear()
            self._baselines.clear()
            self._baseline_last_calculated.clear()
            log.info("Cleared all metric history")
    
    def get_metric_trend(self, metric_name: str, hours: int = 24) -> Optional[Dict[str, Any]]:
        """
        Get trend information for a metric.
        
        Args:
            metric_name: Name of the metric
            hours: Number of hours to analyze
            
        Returns:
            Dictionary with trend information
        """
        try:
            history = self.get_metric_history(metric_name, hours)
            if len(history) < 2:
                return None
            
            values = [v for _, v in history]
            timestamps = [t for t, _ in history]
            
            # Calculate basic trend metrics
            first_value = values[0]
            last_value = values[-1]
            min_value = min(values)
            max_value = max(values)
            avg_value = sum(values) / len(values)
            
            # Calculate trend direction (simple linear trend)
            if len(values) >= 3:
                # Simple linear regression slope
                n = len(values)
                x_values = list(range(n))
                
                sum_x = sum(x_values)
                sum_y = sum(values)
                sum_xy = sum(x * y for x, y in zip(x_values, values))
                sum_xx = sum(x * x for x in x_values)
                
                slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
                trend_direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "stable"
            else:
                trend_direction = "unknown"
            
            return {
                'metric_name': metric_name,
                'period_hours': hours,
                'data_points': len(values),
                'first_value': first_value,
                'last_value': last_value,
                'min_value': min_value,
                'max_value': max_value,
                'average_value': avg_value,
                'trend_direction': trend_direction,
                'value_change': last_value - first_value,
                'percent_change': ((last_value - first_value) / first_value * 100) if first_value != 0 else 0,
                'baseline': self.get_baseline(metric_name),
                'start_time': timestamps[0].isoformat(),
                'end_time': timestamps[-1].isoformat()
            }
            
        except Exception as e:
            log.error(f"Error getting trend for {metric_name}: {e}")
            return None