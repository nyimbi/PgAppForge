"""
Enterprise Integration View

Provides web interface for enterprise integration management including
SSO, LDAP, API management, audit logging, and external connectors.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.enterprise_integration import (
	get_enterprise_integration_suite,
	EnterpriseIntegrationSuite,
	IntegrationType,
	AuthenticationMethod,
	AuditLevel,
	ConnectorStatus
)
from ..database.graph_manager import get_graph_manager
from ..database.multi_graph_manager import get_graph_registry
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


class EnterpriseIntegrationView(BaseView):
	"""
	Enterprise integration management interface
	
	Provides comprehensive enterprise integration capabilities including
	credential management, SSO, LDAP, API management, and audit logging.
	"""
	
	route_base = "/enterprise"
	default_view = "index"
	
	def __init__(self):
		"""Initialize enterprise view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.integration_suite = None
	
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
	
	def _get_integration_suite(self) -> EnterpriseIntegrationSuite:
		"""Get or initialize enterprise integration suite"""
		try:
			return get_enterprise_integration_suite()
		except Exception as e:
			logger.error(f"Failed to initialize enterprise integration suite: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	@expose("/")
	@has_access
	@permission_name("can_manage_enterprise")
	def index(self):
		"""Enterprise integration dashboard"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			user_id = self._get_current_user_id()
			
			# Get integration overview
			overview = integration_suite.get_integration_overview(user_id)
			
			# Get available integration types
			integration_types = [
				{
					"value": it.value,
					"name": it.value.replace("_", " ").title(),
					"description": self._get_integration_description(it)
				}
				for it in IntegrationType
			]
			
			# Get authentication methods
			auth_methods = [
				{
					"value": am.value,
					"name": am.value.replace("_", " ").title(),
					"description": self._get_auth_method_description(am)
				}
				for am in AuthenticationMethod
			]
			
			return render_template(
				"enterprise/index.html",
				title="Enterprise Integration",
				overview=overview,
				integration_types=integration_types,
				auth_methods=auth_methods,
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in enterprise dashboard: {e}")
			flash(f"Error loading enterprise dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/credentials/")
	@has_access
	@permission_name("can_manage_enterprise")
	def credentials(self):
		"""Credential management interface"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			
			# Get credentials (without decrypted data)
			credentials = []
			for credential in integration_suite.credential_manager.list_credentials():
				credentials.append(credential.to_dict())
			
			return render_template(
				"enterprise/credentials.html",
				title="Credential Management",
				credentials=credentials
			)
			
		except Exception as e:
			logger.error(f"Error in credentials interface: {e}")
			flash(f"Error loading credentials interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/api-management/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_management(self):
		"""API management interface"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			
			# Get API endpoints
			endpoints = [endpoint.to_dict() for endpoint in integration_suite.api_manager.endpoints.values()]
			
			# Get API keys (without secrets)
			api_keys = []
			for key, info in integration_suite.api_manager.api_keys.items():
				key_info = info.copy()
				del key_info["api_secret_hash"]  # Remove sensitive data
				key_info["api_key"] = key
				api_keys.append(key_info)
			
			return render_template(
				"enterprise/api_management.html",
				title="API Management",
				endpoints=endpoints,
				api_keys=api_keys
			)
			
		except Exception as e:
			logger.error(f"Error in API management interface: {e}")
			flash(f"Error loading API management interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/connectors/")
	@has_access
	@permission_name("can_manage_enterprise")
	def connectors(self):
		"""External connectors interface"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			
			# Get connectors
			connectors = integration_suite.external_connector.list_connectors()
			
			return render_template(
				"enterprise/connectors.html",
				title="External Connectors",
				connectors=connectors
			)
			
		except Exception as e:
			logger.error(f"Error in connectors interface: {e}")
			flash(f"Error loading connectors interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/audit-logs/")
	@has_access
	@permission_name("can_manage_enterprise")
	def audit_logs(self):
		"""Audit logging interface"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			
			# Get recent audit logs
			recent_logs = integration_suite.audit_logger.search_logs(limit=100)
			logs_data = [log.to_dict() for log in recent_logs]
			
			# Get audit statistics
			audit_stats = integration_suite.audit_logger.get_audit_statistics()
			
			return render_template(
				"enterprise/audit_logs.html",
				title="Audit Logs",
				recent_logs=logs_data,
				audit_stats=audit_stats
			)
			
		except Exception as e:
			logger.error(f"Error in audit logs interface: {e}")
			flash(f"Error loading audit logs interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/sso-config/")
	@has_access
	@permission_name("can_manage_enterprise")
	def sso_config(self):
		"""SSO configuration interface"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			
			# Get SSO providers
			sso_providers = list(integration_suite.sso_providers.values())
			
			return render_template(
				"enterprise/sso_config.html",
				title="SSO Configuration",
				sso_providers=sso_providers
			)
			
		except Exception as e:
			logger.error(f"Error in SSO config interface: {e}")
			flash(f"Error loading SSO config interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	# API Endpoints
	
	@expose_api("post", "/api/credentials/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_create_credential(self):
		"""API endpoint to create credential"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			name = data.get("name")
			integration_type_str = data.get("integration_type")
			auth_method_str = data.get("auth_method")
			credential_data = data.get("credential_data")
			expires_at_str = data.get("expires_at")
			
			if not all([name, integration_type_str, auth_method_str, credential_data]):
				raise BadRequest("name, integration_type, auth_method, and credential_data are required")
			
			try:
				integration_type = IntegrationType(integration_type_str)
				auth_method = AuthenticationMethod(auth_method_str)
			except ValueError as e:
				raise BadRequest(f"Invalid enum value: {e}")
			
			# Parse expiration date if provided
			expires_at = None
			if expires_at_str:
				try:
					from datetime import datetime
					expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
				except ValueError:
					raise BadRequest("Invalid expires_at format")
			
			integration_suite = self._get_integration_suite()
			credential_id = integration_suite.credential_manager.store_credential(
				name=name,
				integration_type=integration_type,
				auth_method=auth_method,
				credential_data=credential_data,
				expires_at=expires_at
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.CREDENTIAL_CREATED,
				target=f"Credential: {name}",
				description=f"Created {integration_type_str} credential",
				details={
					"credential_id": credential_id,
					"integration_type": integration_type_str,
					"auth_method": auth_method_str
				}
			)
			
			return jsonify({
				"success": True,
				"credential_id": credential_id,
				"message": f"Credential '{name}' created successfully"
			})
			
		except Exception as e:
			logger.error(f"API error creating credential: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/credentials/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_get_credentials(self):
		"""API endpoint to get credentials"""
		try:
			self._ensure_admin_access()
			
			integration_type_str = request.args.get("integration_type")
			integration_type = None
			
			if integration_type_str:
				try:
					integration_type = IntegrationType(integration_type_str)
				except ValueError:
					raise BadRequest(f"Invalid integration_type: {integration_type_str}")
			
			integration_suite = self._get_integration_suite()
			credentials = integration_suite.credential_manager.list_credentials(integration_type)
			
			return jsonify({
				"success": True,
				"credentials": [cred.to_dict() for cred in credentials]
			})
			
		except Exception as e:
			logger.error(f"API error getting credentials: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("delete", "/api/credentials/<credential_id>/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_delete_credential(self, credential_id: str):
		"""API endpoint to delete credential"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			success = integration_suite.credential_manager.delete_credential(credential_id)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.CREDENTIAL_DELETED,
					target=f"Credential: {credential_id}",
					description="Deleted enterprise credential",
					details={"credential_id": credential_id}
				)
				
				return jsonify({
					"success": True,
					"message": f"Credential {credential_id} deleted successfully"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Credential not found"
				}), 404
			
		except Exception as e:
			logger.error(f"API error deleting credential: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/connectors/database/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_create_database_connector(self):
		"""API endpoint to create database connector"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			name = data.get("name")
			credential_id = data.get("credential_id")
			connection_string = data.get("connection_string")
			database_type = data.get("database_type")
			
			if not all([name, credential_id, connection_string, database_type]):
				raise BadRequest("name, credential_id, connection_string, and database_type are required")
			
			integration_suite = self._get_integration_suite()
			connector_id = integration_suite.external_connector.create_database_connector(
				name=name,
				credential_id=credential_id,
				connection_string=connection_string,
				database_type=database_type
			)
			
			return jsonify({
				"success": True,
				"connector_id": connector_id,
				"message": f"Database connector '{name}' created successfully"
			})
			
		except Exception as e:
			logger.error(f"API error creating database connector: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/connectors/rest-api/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_create_rest_api_connector(self):
		"""API endpoint to create REST API connector"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			name = data.get("name")
			credential_id = data.get("credential_id")
			base_url = data.get("base_url")
			headers = data.get("headers", {})
			
			if not all([name, credential_id, base_url]):
				raise BadRequest("name, credential_id, and base_url are required")
			
			integration_suite = self._get_integration_suite()
			connector_id = integration_suite.external_connector.create_rest_api_connector(
				name=name,
				credential_id=credential_id,
				base_url=base_url,
				headers=headers
			)
			
			return jsonify({
				"success": True,
				"connector_id": connector_id,
				"message": f"REST API connector '{name}' created successfully"
			})
			
		except Exception as e:
			logger.error(f"API error creating REST API connector: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/connectors/<connector_id>/test/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_test_connector(self, connector_id: str):
		"""API endpoint to test connector"""
		try:
			self._ensure_admin_access()
			
			integration_suite = self._get_integration_suite()
			result = integration_suite.external_connector.test_connector(connector_id)
			
			return jsonify({
				"success": True,
				"test_result": result
			})
			
		except Exception as e:
			logger.error(f"API error testing connector: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/connectors/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_get_connectors(self):
		"""API endpoint to get connectors"""
		try:
			self._ensure_admin_access()
			
			connector_type = request.args.get("type")
			
			integration_suite = self._get_integration_suite()
			connectors = integration_suite.external_connector.list_connectors(connector_type)
			
			return jsonify({
				"success": True,
				"connectors": connectors
			})
			
		except Exception as e:
			logger.error(f"API error getting connectors: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/api-keys/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_generate_api_key(self):
		"""API endpoint to generate API key"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			name = data.get("name")
			permissions = data.get("permissions", [])
			expires_at_str = data.get("expires_at")
			
			if not name:
				raise BadRequest("name is required")
			
			# Parse expiration date if provided
			expires_at = None
			if expires_at_str:
				try:
					from datetime import datetime
					expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
				except ValueError:
					raise BadRequest("Invalid expires_at format")
			
			integration_suite = self._get_integration_suite()
			key_data = integration_suite.api_manager.generate_api_key(
				name=name,
				permissions=permissions,
				expires_at=expires_at
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.API_KEY_CREATED,
				target=f"API Key: {name}",
				description="Generated new API key",
				details={
					"api_key": key_data["api_key"],
					"permissions": permissions
				}
			)
			
			return jsonify({
				"success": True,
				"api_key": key_data["api_key"],
				"api_secret": key_data["api_secret"],
				"message": f"API key '{name}' generated successfully",
				"warning": "Store the API secret securely - it will not be shown again"
			})
			
		except Exception as e:
			logger.error(f"API error generating API key: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/audit-logs/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_get_audit_logs(self):
		"""API endpoint to get audit logs"""
		try:
			self._ensure_admin_access()
			
			# Parse query parameters
			filters = {}
			for key in ["user_id", "action", "resource", "severity", "outcome"]:
				value = request.args.get(key)
				if value:
					filters[key] = value
			
			start_time_str = request.args.get("start_time")
			end_time_str = request.args.get("end_time")
			limit = int(request.args.get("limit", 100))
			
			start_time = None
			end_time = None
			
			if start_time_str:
				try:
					from datetime import datetime
					start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
				except ValueError:
					raise BadRequest("Invalid start_time format")
			
			if end_time_str:
				try:
					from datetime import datetime
					end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
				except ValueError:
					raise BadRequest("Invalid end_time format")
			
			integration_suite = self._get_integration_suite()
			logs = integration_suite.audit_logger.search_logs(
				filters=filters,
				start_time=start_time,
				end_time=end_time,
				limit=limit
			)
			
			return jsonify({
				"success": True,
				"logs": [log.to_dict() for log in logs],
				"count": len(logs)
			})
			
		except Exception as e:
			logger.error(f"API error getting audit logs: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/overview/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_get_overview(self):
		"""API endpoint to get integration overview"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			
			integration_suite = self._get_integration_suite()
			overview = integration_suite.get_integration_overview(user_id)
			
			return jsonify({
				"success": True,
				"overview": overview
			})
			
		except Exception as e:
			logger.error(f"API error getting overview: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/sso-provider/")
	@has_access
	@permission_name("can_manage_enterprise")
	def api_configure_sso_provider(self):
		"""API endpoint to configure SSO provider"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			provider_type = data.get("provider_type")
			provider_name = data.get("provider_name")
			configuration = data.get("configuration")
			
			if not all([provider_type, provider_name, configuration]):
				raise BadRequest("provider_type, provider_name, and configuration are required")
			
			integration_suite = self._get_integration_suite()
			provider_id = integration_suite.configure_sso_provider(
				provider_type=provider_type,
				provider_name=provider_name,
				configuration=configuration
			)
			
			return jsonify({
				"success": True,
				"provider_id": provider_id,
				"message": f"SSO provider '{provider_name}' configured successfully"
			})
			
		except Exception as e:
			logger.error(f"API error configuring SSO provider: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	def _get_integration_description(self, integration_type: IntegrationType) -> str:
		"""Get description for integration type"""
		descriptions = {
			IntegrationType.SSO_SAML: "SAML-based Single Sign-On integration",
			IntegrationType.SSO_OAUTH2: "OAuth2/OpenID Connect Single Sign-On",
			IntegrationType.LDAP_DIRECTORY: "LDAP/Active Directory integration",
			IntegrationType.REST_API: "REST API connector for external services",
			IntegrationType.DATABASE_CONNECTOR: "Database connectivity for external databases",
			IntegrationType.MESSAGE_QUEUE: "Message queue integration (RabbitMQ, Kafka, etc.)",
			IntegrationType.WEBHOOK: "Webhook endpoints for event notifications",
			IntegrationType.FILE_SYSTEM: "File system access and monitoring",
			IntegrationType.CLOUD_STORAGE: "Cloud storage integration (S3, Azure, GCP)",
			IntegrationType.EMAIL_NOTIFICATION: "Email notification services"
		}
		return descriptions.get(integration_type, "Unknown integration type")
	
	def _get_auth_method_description(self, auth_method: AuthenticationMethod) -> str:
		"""Get description for authentication method"""
		descriptions = {
			AuthenticationMethod.BASIC_AUTH: "HTTP Basic Authentication (username/password)",
			AuthenticationMethod.BEARER_TOKEN: "Bearer token authentication",
			AuthenticationMethod.API_KEY: "API key-based authentication",
			AuthenticationMethod.OAUTH2_CLIENT_CREDENTIALS: "OAuth2 client credentials flow",
			AuthenticationMethod.CERTIFICATE: "Client certificate authentication",
			AuthenticationMethod.KERBEROS: "Kerberos authentication",
			AuthenticationMethod.LDAP_BIND: "LDAP bind authentication"
		}
		return descriptions.get(auth_method, "Unknown authentication method")