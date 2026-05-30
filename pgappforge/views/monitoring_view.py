"""
Monitoring Dashboard View

Provides web interface for system monitoring, metrics visualization,
alert management, and health status tracking.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.monitoring_system import (
	get_monitoring_system,
	MonitoringSystem,
	AlertSeverity,
	AlertStatus,
	MetricType
)
from ..database.activity_tracker import (
	track_database_activity,
	ActivityType,
	ActivitySeverity
)
from ..utils.error_handling import (
	WizardErrorHandler,
	WizardErrorType,
	WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class MonitoringView(BaseView):
	"""
	Monitoring dashboard interface
	
	Provides comprehensive monitoring capabilities including metrics visualization,
	alert management, health monitoring, and system diagnostics.
	"""
	
	route_base = "/monitoring"
	default_view = "index"
	
	def __init__(self):
		"""Initialize monitoring view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.monitoring_system = None
	
	def _ensure_admin_access(self):
		"""Ensure current user has admin privileges"""
		try:
			from flask_login import current_user
			
			if not current_user or not current_user.is_authenticated:
				raise Forbidden("Authentication required")
			
			# Check if user has admin role
			if hasattr(current_user, "roles"):
				admin_roles = ["Admin", "admin", "Administrator", "administrator"]
				user_roles = [
					role.name if hasattr(role, "name") else str(role)
					for role in current_user.roles
				]
				
				if not any(role in admin_roles for role in user_roles):
					raise Forbidden("Administrator privileges required")
			else:
				# Fallback check for is_admin attribute
				if not getattr(current_user, "is_admin", False):
					raise Forbidden("Administrator privileges required")
					
		except Exception as e:
			logger.error(f"Admin access check failed: {e}")
			raise Forbidden("Access denied")
	
	def _get_current_user_id(self) -> str:
		"""Get current user ID"""
		try:
			from flask_login import current_user
			if current_user and current_user.is_authenticated:
				return str(current_user.id) if hasattr(current_user, 'id') else str(current_user)
			return "admin"
		except:
			return "admin"
	
	def _get_monitoring_system(self) -> MonitoringSystem:
		"""Get or initialize monitoring system"""
		try:
			return get_monitoring_system()
		except Exception as e:
			logger.error(f"Failed to initialize monitoring system: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	@expose("/")
	@has_access
	@permission_name("can_monitor_system")
	def index(self):
		"""Main monitoring dashboard"""
		try:
			self._ensure_admin_access()
			
			monitoring = self._get_monitoring_system()
			user_id = self._get_current_user_id()
			
			# Get dashboard data
			dashboard_data = monitoring.get_dashboard_data()
			
			# Get alert statistics
			alert_stats = self._get_alert_statistics(monitoring)
			
			# Get system info
			system_info = self._get_system_info()
			
			return render_template(
				"monitoring/index.html",
				title="System Monitoring Dashboard",
				dashboard_data=dashboard_data,
				alert_stats=alert_stats,
				system_info=system_info,
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in monitoring dashboard: {e}")
			flash(f"Error loading monitoring dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/metrics/")
	@has_access
	@permission_name("can_monitor_system")
	def metrics(self):
		"""Metrics visualization interface"""
		try:
			self._ensure_admin_access()
			
			monitoring = self._get_monitoring_system()
			
			# Get available metrics
			available_metrics = [
				{"name": "cpu_percent", "display_name": "CPU Usage (%)", "type": "gauge"},
				{"name": "memory_percent", "display_name": "Memory Usage (%)", "type": "gauge"},
				{"name": "disk_usage_percent", "display_name": "Disk Usage (%)", "type": "gauge"},
				{"name": "query_response_time", "display_name": "Query Response Time (s)", "type": "timer"},
				{"name": "error_rate", "display_name": "Error Rate (%)", "type": "gauge"},
				{"name": "active_sessions", "display_name": "Active Sessions", "type": "counter"},
				{"name": "database_connections", "display_name": "DB Connections", "type": "gauge"}
			]
			
			# Get metric summaries
			metric_summaries = {}
			for metric in available_metrics:
				try:
					summary = monitoring.metrics_collector.get_metric_summary(
						metric["name"], time_range_minutes=60
					)
					metric_summaries[metric["name"]] = summary
				except Exception as e:
					logger.error(f"Failed to get summary for {metric['name']}: {e}")
					metric_summaries[metric["name"]] = {"count": 0}
			
			return render_template(
				"monitoring/metrics.html",
				title="Metrics Dashboard",
				available_metrics=available_metrics,
				metric_summaries=metric_summaries
			)
			
		except Exception as e:
			logger.error(f"Error in metrics interface: {e}")
			flash(f"Error loading metrics interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/alerts/")
	@has_access
	@permission_name("can_monitor_system")
	def alerts(self):
		"""Alert management interface"""
		try:
			self._ensure_admin_access()
			
			monitoring = self._get_monitoring_system()
			
			# Get alerts
			active_alerts = monitoring.alert_manager.get_active_alerts()
			alert_history = monitoring.alert_manager.get_alert_history(hours=24)
			
			# Get alert statistics
			alert_stats = self._get_alert_statistics(monitoring)
			
			# Get available alert severities and statuses
			severities = [{"value": s.value, "name": s.value.title()} for s in AlertSeverity]
			statuses = [{"value": s.value, "name": s.value.title()} for s in AlertStatus]
			
			return render_template(
				"monitoring/alerts.html",
				title="Alert Management",
				active_alerts=[alert.to_dict() for alert in active_alerts],
				alert_history=[alert.to_dict() for alert in alert_history],
				alert_stats=alert_stats,
				severities=severities,
				statuses=statuses
			)
			
		except Exception as e:
			logger.error(f"Error in alerts interface: {e}")
			flash(f"Error loading alerts interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/health/")
	@has_access
	@permission_name("can_monitor_system")
	def health(self):
		"""System health monitoring interface"""
		try:
			self._ensure_admin_access()
			
			monitoring = self._get_monitoring_system()
			
			# Get health summary
			health_summary = monitoring.health_checker.get_system_health_summary()
			
			# Get individual health check results
			health_checks = monitoring.health_checker.run_all_health_checks()
			
			return render_template(
				"monitoring/health.html",
				title="System Health",
				health_summary=health_summary,
				health_checks=health_checks
			)
			
		except Exception as e:
			logger.error(f"Error in health interface: {e}")
			flash(f"Error loading health interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	def _get_alert_statistics(self, monitoring: MonitoringSystem) -> Dict[str, Any]:
		"""Get alert statistics"""
		try:
			active_alerts = monitoring.alert_manager.get_active_alerts()
			alert_history = monitoring.alert_manager.get_alert_history(hours=24)
			
			# Count by severity
			severity_counts = {s.value: 0 for s in AlertSeverity}
			for alert in active_alerts:
				severity_counts[alert.severity.value] += 1
			
			# Count by status
			status_counts = {s.value: 0 for s in AlertStatus}
			for alert in alert_history:
				status_counts[alert.status.value] += 1
			
			return {
				"total_active": len(active_alerts),
				"total_24h": len(alert_history),
				"severity_counts": severity_counts,
				"status_counts": status_counts,
				"critical_alerts": len([a for a in active_alerts if a.severity == AlertSeverity.CRITICAL]),
				"acknowledged_alerts": len([a for a in active_alerts if a.status == AlertStatus.ACKNOWLEDGED])
			}
		except Exception as e:
			logger.error(f"Failed to get alert statistics: {e}")
			return {}
	
	def _get_system_info(self) -> Dict[str, Any]:
		"""Get basic system information"""
		try:
			import psutil
			import platform
			from datetime import datetime
			
			return {
				"platform": platform.system(),
				"platform_version": platform.version(),
				"python_version": platform.python_version(),
				"cpu_count": psutil.cpu_count(),
				"total_memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
				"disk_total_gb": round(psutil.disk_usage('/').total / (1024**3), 2),
				"boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
				"uptime_hours": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1)
			}
		except Exception as e:
			logger.error(f"Failed to get system info: {e}")
			return {}
	
	# API Endpoints
	
	@expose_api("get", "/api/dashboard-data/")
	@has_access
	@permission_name("can_monitor_system")
	def api_get_dashboard_data(self):
		"""API endpoint to get dashboard data"""
		try:
			self._ensure_admin_access()
			
			monitoring = self._get_monitoring_system()
			dashboard_data = monitoring.get_dashboard_data()
			
			return jsonify({
				"success": True,
				"data": dashboard_data
			})
			
		except Exception as e:
			logger.error(f"API error getting dashboard data: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/metrics/<metric_name>/")
	@has_access
	@permission_name("can_monitor_system")
	def api_get_metric_data(self, metric_name: str):
		"""API endpoint to get specific metric data"""
		try:
			self._ensure_admin_access()
			
			time_range = int(request.args.get("time_range_minutes", 60))
			
			monitoring = self._get_monitoring_system()
			metrics = monitoring.metrics_collector.get_metrics(metric_name, time_range)
			summary = monitoring.metrics_collector.get_metric_summary(metric_name, time_range)
			
			return jsonify({
				"success": True,
				"metric_name": metric_name,
				"time_range_minutes": time_range,
				"data_points": [
					{
						"timestamp": m.timestamp.isoformat(),
						"value": m.value,
						"labels": m.labels
					}
					for m in metrics
				],
				"summary": summary
			})
			
		except Exception as e:
			logger.error(f"API error getting metric data: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/alerts/acknowledge/<alert_id>/")
	@has_access
	@permission_name("can_monitor_system")
	def api_acknowledge_alert(self, alert_id: str):
		"""API endpoint to acknowledge alert"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			
			monitoring = self._get_monitoring_system()
			success = monitoring.alert_manager.acknowledge_alert(alert_id, user_id)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.ALERT_ACKNOWLEDGED,
					target=f"Alert: {alert_id}",
					description="Acknowledged system alert",
					details={"alert_id": alert_id, "user_id": user_id}
				)
				
				return jsonify({
					"success": True,
					"message": "Alert acknowledged successfully"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Alert not found"
				}), 404
			
		except Exception as e:
			logger.error(f"API error acknowledging alert: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/alerts/suppress/<alert_id>/")
	@has_access
	@permission_name("can_monitor_system")
	def api_suppress_alert(self, alert_id: str):
		"""API endpoint to suppress alert"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			duration_minutes = data.get("duration_minutes", 60)
			
			monitoring = self._get_monitoring_system()
			success = monitoring.alert_manager.suppress_alert(alert_id, duration_minutes)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.ALERT_SUPPRESSED,
					target=f"Alert: {alert_id}",
					description=f"Suppressed system alert for {duration_minutes} minutes",
					details={"alert_id": alert_id, "duration_minutes": duration_minutes}
				)
				
				return jsonify({
					"success": True,
					"message": f"Alert suppressed for {duration_minutes} minutes"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Alert not found"
				}), 404
			
		except Exception as e:
			logger.error(f"API error suppressing alert: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/alerts/create/")
	@has_access
	@permission_name("can_monitor_system")
	def api_create_alert_rule(self):
		"""API endpoint to create new alert rule"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			name = data.get("name")
			condition = data.get("condition")
			threshold = data.get("threshold")
			severity_str = data.get("severity")
			description = data.get("description")
			
			if not all([name, condition, threshold is not None, severity_str, description]):
				raise BadRequest("name, condition, threshold, severity, and description are required")
			
			try:
				severity = AlertSeverity(severity_str)
			except ValueError:
				raise BadRequest(f"Invalid severity: {severity_str}")
			
			monitoring = self._get_monitoring_system()
			alert_id = monitoring.alert_manager.create_alert_rule(
				name=name,
				condition=condition,
				threshold=threshold,
				severity=severity,
				description=description,
				metadata=data.get("metadata", {})
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.ALERT_RULE_CREATED,
				target=f"Alert Rule: {name}",
				description="Created new alert rule",
				details={
					"alert_id": alert_id,
					"condition": condition,
					"threshold": threshold,
					"severity": severity_str
				}
			)
			
			return jsonify({
				"success": True,
				"alert_id": alert_id,
				"message": f"Alert rule '{name}' created successfully"
			})
			
		except Exception as e:
			logger.error(f"API error creating alert rule: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/health-check/")
	@has_access
	@permission_name("can_monitor_system")
	def api_health_check(self):
		"""API endpoint for health check"""
		try:
			self._ensure_admin_access()
			
			check_name = request.args.get("check")
			
			monitoring = self._get_monitoring_system()
			
			if check_name:
				# Run specific health check
				result = monitoring.health_checker.run_health_check(check_name)
				return jsonify({
					"success": True,
					"check_result": result
				})
			else:
				# Run all health checks
				results = monitoring.health_checker.run_all_health_checks()
				health_summary = monitoring.health_checker.get_system_health_summary()
				
				return jsonify({
					"success": True,
					"health_summary": health_summary,
					"check_results": results
				})
			
		except Exception as e:
			logger.error(f"API error in health check: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/notification-channel/")
	@has_access
	@permission_name("can_monitor_system")
	def api_add_notification_channel(self):
		"""API endpoint to add notification channel"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			channel_name = data.get("channel_name")
			channel_config = data.get("channel_config")
			
			if not all([channel_name, channel_config]):
				raise BadRequest("channel_name and channel_config are required")
			
			monitoring = self._get_monitoring_system()
			monitoring.alert_manager.add_notification_channel(channel_name, channel_config)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.NOTIFICATION_CHANNEL_ADDED,
				target=f"Notification Channel: {channel_name}",
				description="Added notification channel",
				details={"channel_name": channel_name, "channel_type": channel_config.get("type")}
			)
			
			return jsonify({
				"success": True,
				"message": f"Notification channel '{channel_name}' added successfully"
			})
			
		except Exception as e:
			logger.error(f"API error adding notification channel: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/custom-metric/")
	@has_access
	@permission_name("can_monitor_system")
	def api_record_custom_metric(self):
		"""API endpoint to record custom metric"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			metric_name = data.get("metric_name")
			metric_value = data.get("metric_value")
			metric_type_str = data.get("metric_type", "gauge")
			labels = data.get("labels", {})
			
			if not all([metric_name, metric_value is not None]):
				raise BadRequest("metric_name and metric_value are required")
			
			try:
				metric_type = MetricType(metric_type_str)
			except ValueError:
				raise BadRequest(f"Invalid metric_type: {metric_type_str}")
			
			from ..database.monitoring_system import Metric
			from datetime import datetime
			
			metric = Metric(
				name=metric_name,
				value=metric_value,
				timestamp=datetime.now(),
				labels=labels,
				metric_type=metric_type
			)
			
			monitoring = self._get_monitoring_system()
			monitoring.metrics_collector.record_metric(metric)
			
			return jsonify({
				"success": True,
				"message": f"Custom metric '{metric_name}' recorded successfully"
			})
			
		except Exception as e:
			logger.error(f"API error recording custom metric: {e}")
			return jsonify({"success": False, "error": str(e)}), 500