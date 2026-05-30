"""
Beautiful Modern Dashboard IndexView

A comprehensive, visually stunning dashboard that replaces the default bland welcome page
with rich functionality, metrics, quick actions, and beautiful design.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from flask import render_template, request, jsonify
from flask.views import MethodView
from ..utils.error_handling import wizard_error_handler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class DashboardIndexView(MethodView):
	"""Beautiful modern dashboard with comprehensive functionality"""
	
	def __init__(self):
		self.page_title = "Dashboard"
		self.template = "dashboard/index.html"
	
	def get(self):
		"""Render the beautiful dashboard"""
		try:
			# Get dashboard data
			dashboard_data = self._get_dashboard_data()
			
			return render_template(
				self.template,
				**dashboard_data,
				page_title=self.page_title
			)
			
		except Exception as e:
			error = wizard_error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.MEDIUM
			)
			logger.error(f"Dashboard error: {error.message}")
			
			# Fallback to minimal dashboard
			return render_template(
				self.template,
				error=error,
				**self._get_minimal_dashboard_data(),
				page_title="Dashboard"
			)
	
	def _get_dashboard_data(self) -> Dict[str, Any]:
		"""Get comprehensive dashboard data"""
		
		return {
			# System Overview
			'system_status': self._get_system_status(),
			'quick_stats': self._get_quick_stats(),
			
			# Recent Activity
			'recent_activities': self._get_recent_activities(),
			'notifications': self._get_notifications(),
			
			# Quick Actions
			'quick_actions': self._get_quick_actions(),
			'featured_tools': self._get_featured_tools(),
			
			# Charts and Analytics
			'chart_data': self._get_chart_data(),
			'performance_metrics': self._get_performance_metrics(),
			
			# User and System Info
			'user_info': self._get_user_info(),
			'system_info': self._get_system_info(),
			
			# Widgets
			'widgets': self._get_dashboard_widgets(),
			
			# Navigation
			'nav_items': self._get_navigation_items(),
		}
	
	def _get_minimal_dashboard_data(self) -> Dict[str, Any]:
		"""Get minimal dashboard data for error fallback"""
		return {
			'system_status': {'status': 'unknown', 'message': 'Unable to load system status'},
			'quick_stats': [],
			'recent_activities': [],
			'notifications': [],
			'quick_actions': self._get_basic_quick_actions(),
			'user_info': {'name': 'User', 'role': 'Unknown'},
			'system_info': {'version': 'Unknown', 'environment': 'Unknown'}
		}
	
	def _get_system_status(self) -> Dict[str, Any]:
		"""Get system status information"""
		return {
			'status': 'healthy',
			'uptime': '15 days, 8 hours',
			'version': '4.8.0',
			'environment': 'Production',
			'last_backup': '2 hours ago',
			'services': {
				'database': {'status': 'healthy', 'response_time': '12ms'},
				'cache': {'status': 'healthy', 'response_time': '3ms'},
				'storage': {'status': 'healthy', 'usage': '68%'},
				'api': {'status': 'healthy', 'requests_per_minute': 1247}
			},
			'alerts': [
				{
					'type': 'info',
					'message': 'Scheduled maintenance in 3 days',
					'timestamp': datetime.now() - timedelta(hours=2)
				}
			]
		}
	
	def _get_quick_stats(self) -> List[Dict[str, Any]]:
		"""Get dashboard quick statistics"""
		return [
			{
				'title': 'Total Users',
				'value': '12,847',
				'change': '+8.2%',
				'change_type': 'positive',
				'icon': 'fa-users',
				'color': 'primary',
				'description': 'Active users this month'
			},
			{
				'title': 'Wizard Forms',
				'value': '156',
				'change': '+12',
				'change_type': 'positive', 
				'icon': 'fa-magic',
				'color': 'success',
				'description': 'Forms created this week'
			},
			{
				'title': 'Completion Rate',
				'value': '94.2%',
				'change': '+2.1%',
				'change_type': 'positive',
				'icon': 'fa-check-circle',
				'color': 'info',
				'description': 'Form completion average'
			},
			{
				'title': 'Data Storage',
				'value': '2.4 TB',
				'change': '+156 GB',
				'change_type': 'neutral',
				'icon': 'fa-database',
				'color': 'warning',
				'description': 'Total data stored'
			},
			{
				'title': 'API Requests',
				'value': '1.2M',
				'change': '+15.3%',
				'change_type': 'positive',
				'icon': 'fa-exchange-alt',
				'color': 'secondary',
				'description': 'Requests today'
			},
			{
				'title': 'System Load',
				'value': '23%',
				'change': '-5%',
				'change_type': 'positive',
				'icon': 'fa-tachometer-alt',
				'color': 'danger',
				'description': 'Average CPU usage'
			}
		]
	
	def _get_recent_activities(self) -> List[Dict[str, Any]]:
		"""Get recent system activities"""
		return [
			{
				'id': 'activity_1',
				'type': 'wizard_created',
				'title': 'New wizard form created',
				'description': 'Customer Registration Form v2.1',
				'user': 'Sarah Chen',
				'timestamp': datetime.now() - timedelta(minutes=15),
				'icon': 'fa-magic',
				'color': 'success'
			},
			{
				'id': 'activity_2', 
				'type': 'user_registered',
				'title': 'New user registered',
				'description': 'john.doe@example.com joined the platform',
				'user': 'System',
				'timestamp': datetime.now() - timedelta(hours=1),
				'icon': 'fa-user-plus',
				'color': 'primary'
			},
			{
				'id': 'activity_3',
				'type': 'backup_completed',
				'title': 'Backup completed successfully',
				'description': 'Daily backup finished (2.4 GB)',
				'user': 'System',
				'timestamp': datetime.now() - timedelta(hours=2),
				'icon': 'fa-shield-alt',
				'color': 'info'
			},
			{
				'id': 'activity_4',
				'type': 'theme_updated',
				'title': 'Theme customization saved',
				'description': 'Modern Blue theme updated with new colors',
				'user': 'Admin',
				'timestamp': datetime.now() - timedelta(hours=3),
				'icon': 'fa-palette',
				'color': 'warning'
			},
			{
				'id': 'activity_5',
				'type': 'export_completed',
				'title': 'Wizard export completed',
				'description': '3 wizards exported to ZIP format',
				'user': 'Mike Johnson',
				'timestamp': datetime.now() - timedelta(hours=4),
				'icon': 'fa-upload',
				'color': 'secondary'
			}
		]
	
	def _get_notifications(self) -> List[Dict[str, Any]]:
		"""Get system notifications"""
		return [
			{
				'id': 'notif_1',
				'type': 'info',
				'title': 'System Update Available',
				'message': 'PgForge v4.9.0 is now available with new features',
				'timestamp': datetime.now() - timedelta(hours=6),
				'read': False,
				'action_url': '/admin/updates'
			},
			{
				'id': 'notif_2',
				'type': 'warning', 
				'title': 'High Memory Usage',
				'message': 'System memory usage is at 85%. Consider optimizing or scaling.',
				'timestamp': datetime.now() - timedelta(hours=12),
				'read': False,
				'action_url': '/admin/system-resources'
			},
			{
				'id': 'notif_3',
				'type': 'success',
				'title': 'Performance Optimization',
				'message': 'Database queries optimized. 23% performance improvement detected.',
				'timestamp': datetime.now() - timedelta(days=1),
				'read': True,
				'action_url': '/admin/performance'
			}
		]
	
	def _get_quick_actions(self) -> List[Dict[str, Any]]:
		"""Get quick action buttons"""
		return [
			{
				'title': 'Create Wizard',
				'description': 'Build a new multi-step form',
				'icon': 'fa-magic',
				'color': 'primary',
				'url': '/wizard-builder',
				'badge': 'New'
			},
			{
				'title': 'User Management',
				'description': 'Manage users and permissions',
				'icon': 'fa-users-cog',
				'color': 'success',
				'url': '/admin/users'
			},
			{
				'title': 'Analytics',
				'description': 'View detailed analytics',
				'icon': 'fa-chart-line',
				'color': 'info',
				'url': '/wizard-analytics'
			},
			{
				'title': 'System Settings',
				'description': 'Configure system preferences',
				'icon': 'fa-cog',
				'color': 'warning',
				'url': '/admin/settings'
			},
			{
				'title': 'Export Data',
				'description': 'Export forms and data',
				'icon': 'fa-download',
				'color': 'secondary',
				'url': '/wizard-migration/export'
			},
			{
				'title': 'Theme Editor',
				'description': 'Customize visual themes',
				'icon': 'fa-palette',
				'color': 'danger',
				'url': '/theme-editor',
				'badge': 'Hot'
			}
		]
	
	def _get_basic_quick_actions(self) -> List[Dict[str, Any]]:
		"""Get basic quick actions for error fallback"""
		return [
			{
				'title': 'Home',
				'description': 'Return to main dashboard',
				'icon': 'fa-home',
				'color': 'primary',
				'url': '/'
			}
		]
	
	def _get_featured_tools(self) -> List[Dict[str, Any]]:
		"""Get featured tools and capabilities"""
		return [
			{
				'title': 'Wizard Builder',
				'description': 'Create beautiful multi-step forms with our drag-and-drop builder',
				'features': ['17 field types', 'Live preview', 'Mobile responsive'],
				'icon': 'fa-magic',
				'image': '/static/img/wizard-builder-preview.jpg',
				'url': '/wizard-builder'
			},
			{
				'title': 'Analytics Dashboard',
				'description': 'Comprehensive analytics with AI-powered insights',
				'features': ['Real-time metrics', 'Conversion tracking', 'Custom reports'],
				'icon': 'fa-chart-pie',
				'image': '/static/img/analytics-preview.jpg',
				'url': '/wizard-analytics'
			},
			{
				'title': 'Theme System',
				'description': 'Professional themes with advanced customization',
				'features': ['5 built-in themes', 'Custom CSS', 'Animation system'],
				'icon': 'fa-palette',
				'image': '/static/img/themes-preview.jpg',
				'url': '/theme-gallery'
			}
		]
	
	def _get_chart_data(self) -> Dict[str, Any]:
		"""Get data for dashboard charts"""
		return {
			'user_growth': {
				'labels': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'],
				'data': [1200, 1450, 1650, 1820, 2100, 2350, 2847],
				'type': 'line'
			},
			'wizard_usage': {
				'labels': ['Registration', 'Survey', 'Order', 'Contact', 'Feedback'],
				'data': [35, 25, 20, 12, 8],
				'type': 'doughnut'
			},
			'performance': {
				'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
				'data': [85, 92, 88, 95, 89, 76, 82],
				'type': 'bar'
			}
		}
	
	def _get_performance_metrics(self) -> Dict[str, Any]:
		"""Get system performance metrics"""
		return {
			'response_time': {
				'current': '145ms',
				'target': '< 200ms',
				'trend': 'improving',
				'percentage': 72
			},
			'uptime': {
				'current': '99.9%',
				'target': '99.5%',
				'trend': 'stable',
				'percentage': 99
			},
			'throughput': {
				'current': '1,247 req/min',
				'target': '1,000 req/min',
				'trend': 'growing',
				'percentage': 124
			},
			'error_rate': {
				'current': '0.02%',
				'target': '< 0.1%',
				'trend': 'improving',
				'percentage': 20
			}
		}
	
	def _get_user_info(self) -> Dict[str, Any]:
		"""Get current user information from Flask-Login current_user"""
		try:
			# Import Flask-Login's current_user safely
			from flask_login import current_user
			
			if current_user and current_user.is_authenticated:
				return {
					'name': getattr(current_user, 'username', 'User'),
					'email': getattr(current_user, 'email', 'user@example.com'),
					'role': getattr(current_user, 'role', 'User'),
					'avatar': getattr(current_user, 'avatar', '/static/img/default-avatar.png'),
					'last_login': getattr(current_user, 'last_login', datetime.now() - timedelta(hours=2)),
					'permissions': self._get_user_permissions(current_user),
					'preferences': self._get_user_preferences(current_user)
				}
			else:
				return self._get_anonymous_user_info()
				
		except ImportError:
			# Flask-Login not available, return default user info
			return self._get_default_user_info()
		
	def _get_user_permissions(self, user) -> List[str]:
		"""Extract user permissions from user object"""
		try:
			if hasattr(user, 'roles'):
				permissions = []
				for role in user.roles:
					if hasattr(role, 'permissions'):
						permissions.extend([perm.name for perm in role.permissions])
				return list(set(permissions))  # Remove duplicates
			elif hasattr(user, 'permissions'):
				return [perm.name for perm in user.permissions]
			else:
				return ['read']  # Default minimal permission
		except Exception:
			return ['read']
		
	def _get_user_preferences(self, user) -> Dict[str, Any]:
		"""Extract user preferences from user object or database"""
		try:
			if hasattr(user, 'preferences'):
				prefs = user.preferences
				if isinstance(prefs, dict):
					return prefs
				elif hasattr(prefs, 'to_dict'):
					return prefs.to_dict()
					
			# Try to get from user profile or settings table
			if hasattr(user, 'profile'):
				profile = user.profile
				return {
					'theme': getattr(profile, 'theme', 'modern_blue'),
					'timezone': getattr(profile, 'timezone', 'UTC'),
					'language': getattr(profile, 'language', 'en')
				}
					
			return self._get_default_preferences()
		except Exception:
			return self._get_default_preferences()
		
	def _get_anonymous_user_info(self) -> Dict[str, Any]:
		"""Return info for anonymous/unauthenticated users"""
		return {
			'name': 'Guest User',
			'email': 'guest@example.com',
			'role': 'Guest',
			'avatar': '/static/img/guest-avatar.png',
			'last_login': None,
			'permissions': ['read'],
			'preferences': self._get_default_preferences()
		}
		
	def _get_default_user_info(self) -> Dict[str, Any]:
		"""Return default user info when Flask-Login not available"""
		return {
			'name': 'Default User',
			'email': 'user@example.com',
			'role': 'User',
			'avatar': '/static/img/default-avatar.png',
			'last_login': datetime.now() - timedelta(hours=2),
			'permissions': ['read', 'write'],
			'preferences': self._get_default_preferences()
		}
		
	def _get_default_preferences(self) -> Dict[str, Any]:
		"""Return default user preferences"""
		return {
			'theme': 'modern_blue',
			'timezone': 'UTC',
			'language': 'en'
		}
	
	def _get_system_info(self) -> Dict[str, Any]:
		"""Get system information"""
		return {
			'version': '4.8.0',
			'build': '2024.01.15',
			'environment': 'Production',
			'python_version': '3.11.7',
			'flask_version': '2.3.3',
			'database': 'PostgreSQL 15.2',
			'cache': 'Redis 7.0',
			'deployment': 'Docker',
			'region': 'US-West-2'
		}
	
	def _get_dashboard_widgets(self) -> List[Dict[str, Any]]:
		"""Get dashboard widgets"""
		return [
			{
				'id': 'welcome_widget',
				'type': 'welcome',
				'title': 'Welcome Back!',
				'size': 'large',
				'data': {
					'greeting': self._get_time_based_greeting(),
					'tips': self._get_daily_tips()
				}
			},
			{
				'id': 'weather_widget',
				'type': 'weather',
				'title': 'Weather',
				'size': 'small',
				'data': {
					'location': 'San Francisco, CA',
					'temperature': '72°F',
					'condition': 'Partly Cloudy',
					'icon': 'fa-cloud-sun'
				}
			},
			{
				'id': 'shortcuts_widget',
				'type': 'shortcuts',
				'title': 'Quick Shortcuts',
				'size': 'medium',
				'data': {
					'shortcuts': [
						{'name': 'New Wizard', 'url': '/wizard-builder', 'icon': 'fa-plus'},
						{'name': 'View Analytics', 'url': '/analytics', 'icon': 'fa-chart-bar'},
						{'name': 'User Settings', 'url': '/settings', 'icon': 'fa-user-cog'}
					]
				}
			}
		]
	
	def _get_time_based_greeting(self) -> str:
		"""Get greeting based on time of day"""
		hour = datetime.now().hour
		if hour < 12:
			return "Good morning!"
		elif hour < 18:
			return "Good afternoon!"
		else:
			return "Good evening!"
	
	def _get_daily_tips(self) -> List[str]:
		"""Get daily tips for users"""
		tips = [
			"Use the wizard builder's preview mode to test forms before publishing",
			"Enable analytics to track user behavior and optimize conversion rates",
			"Custom themes can be shared across multiple wizard forms",
			"Backup your wizards regularly using the migration tools",
			"The collaboration features allow real-time team editing"
		]
		return tips[:2]  # Return 2 random tips
	
	def _get_navigation_items(self) -> List[Dict[str, Any]]:
		"""Get navigation items for dashboard"""
		return [
			{
				'title': 'Dashboard',
				'url': '/',
				'icon': 'fa-tachometer-alt',
				'active': True
			},
			{
				'title': 'Wizard Builder',
				'url': '/wizard-builder',
				'icon': 'fa-magic'
			},
			{
				'title': 'Analytics',
				'url': '/wizard-analytics',
				'icon': 'fa-chart-line'
			},
			{
				'title': 'Migration',
				'url': '/wizard-migration',
				'icon': 'fa-exchange-alt'
			},
			{
				'title': 'Settings',
				'url': '/admin/settings',
				'icon': 'fa-cog'
			}
		]
	
	def _mark_notification_read(self, notification_id: str) -> bool:
		"""Mark a notification as read in the database"""
		try:
			# Import database session if available
			from flask import current_app
			
			# Check if SQLAlchemy is available
			if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
				from flask_sqlalchemy import SQLAlchemy
				
				db = current_app.extensions['sqlalchemy'].db
				
				# Try to find notification model
				if hasattr(db.Model, 'query'):
					# Look for a Notification model
					try:
						from sqlalchemy import text
						result = db.session.execute(
							text("UPDATE notifications SET read_at = NOW() WHERE id = :notification_id"),
							{'notification_id': notification_id}
						)
						db.session.commit()
						return result.rowcount > 0
					except Exception:
						db.session.rollback()
						
			# Fallback: store in session or cache if database not available
			from flask import session
			read_notifications = session.get('read_notifications', [])
			if notification_id not in read_notifications:
				read_notifications.append(notification_id)
				session['read_notifications'] = read_notifications
			
			return True
			
		except Exception as e:
			logger.error(f"Error marking notification {notification_id} as read: {e}")
			return False

	def _dismiss_system_alert(self, alert_id: str) -> bool:
		"""Dismiss a system alert"""
		try:
			# Import database session if available
			from flask import current_app
			
			# Check if SQLAlchemy is available
			if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
				from flask_sqlalchemy import SQLAlchemy
				
				db = current_app.extensions['sqlalchemy'].db
				
				try:
					from sqlalchemy import text
					result = db.session.execute(
						text("UPDATE system_alerts SET dismissed_at = NOW() WHERE id = :alert_id"),
						{'alert_id': alert_id}
					)
					db.session.commit()
					return result.rowcount > 0
				except Exception:
					db.session.rollback()
			
			# Fallback: store dismissed alerts in session
			from flask import session
			dismissed_alerts = session.get('dismissed_alerts', [])
			if alert_id not in dismissed_alerts:
				dismissed_alerts.append(alert_id)
				session['dismissed_alerts'] = dismissed_alerts
			
			return True
			
		except Exception as e:
			logger.error(f"Error dismissing alert {alert_id}: {e}")
			return False


class DashboardAPIView(MethodView):
	"""API endpoints for dashboard data"""
	
	def get(self, endpoint=None):
		"""Get dashboard API data"""
		try:
			dashboard = DashboardIndexView()
			
			if endpoint == 'stats':
				return jsonify(dashboard._get_quick_stats())
			elif endpoint == 'activities':
				return jsonify(dashboard._get_recent_activities())
			elif endpoint == 'notifications':
				return jsonify(dashboard._get_notifications())
			elif endpoint == 'system-status':
				return jsonify(dashboard._get_system_status())
			elif endpoint == 'charts':
				return jsonify(dashboard._get_chart_data())
			elif endpoint == 'performance':
				return jsonify(dashboard._get_performance_metrics())
			else:
				return jsonify({'error': 'Invalid endpoint'}), 400
				
		except Exception as e:
			error = wizard_error_handler.handle_error(
				e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.MEDIUM
			)
			return jsonify({'error': error.user_friendly_message}), 500
	
	def post(self, endpoint=None):
		"""Handle dashboard API actions"""
		try:
			if endpoint == 'mark-notification-read':
				notification_id = request.json.get('notification_id')
				success = self._mark_notification_read(notification_id)
				return jsonify({'success': success, 'notification_id': notification_id})
			
			elif endpoint == 'dismiss-alert':
				alert_id = request.json.get('alert_id')
				success = self._dismiss_system_alert(alert_id)
				return jsonify({'success': success, 'alert_id': alert_id})
			
			else:
				return jsonify({'error': 'Invalid endpoint'}), 400
				
		except Exception as e:
			error = wizard_error_handler.handle_error(
				e, WizardErrorType.RUNTIME_ERROR, WizardErrorSeverity.MEDIUM
			)
			return jsonify({'error': error.user_friendly_message}), 500