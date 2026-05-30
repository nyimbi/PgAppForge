"""
Enterprise Integration Suite

Provides enterprise-grade integration capabilities including SSO, LDAP,
API management, audit logging, and external system connectors.
"""

import json
import logging
import hashlib
import jwt
import threading
import asyncio
import ssl
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid
from urllib.parse import urlparse
import secrets

try:
	import ldap3
	LDAP_AVAILABLE = True
except ImportError:
	LDAP_AVAILABLE = False

try:
	import requests
	REQUESTS_AVAILABLE = True
except ImportError:
	REQUESTS_AVAILABLE = False

try:
	from cryptography.fernet import Fernet
	CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
	CRYPTOGRAPHY_AVAILABLE = False

import numpy as np
from sqlalchemy import text, create_engine
from sqlalchemy.pool import StaticPool

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType
from .performance_optimizer import get_performance_monitor, performance_cache

logger = logging.getLogger(__name__)


class IntegrationType(Enum):
	"""Types of enterprise integrations"""
	SSO_SAML = "sso_saml"
	SSO_OAUTH2 = "sso_oauth2"
	LDAP_DIRECTORY = "ldap_directory"
	REST_API = "rest_api"
	DATABASE_CONNECTOR = "database_connector"
	MESSAGE_QUEUE = "message_queue"
	WEBHOOK = "webhook"
	FILE_SYSTEM = "file_system"
	CLOUD_STORAGE = "cloud_storage"
	EMAIL_NOTIFICATION = "email_notification"


class AuthenticationMethod(Enum):
	"""Authentication methods for integrations"""
	BASIC_AUTH = "basic_auth"
	BEARER_TOKEN = "bearer_token"
	API_KEY = "api_key"
	OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
	CERTIFICATE = "certificate"
	KERBEROS = "kerberos"
	LDAP_BIND = "ldap_bind"


class AuditLevel(Enum):
	"""Audit logging levels"""
	MINIMAL = "minimal"
	STANDARD = "standard"
	DETAILED = "detailed"
	COMPREHENSIVE = "comprehensive"


class ConnectorStatus(Enum):
	"""Status of enterprise connectors"""
	ACTIVE = "active"
	INACTIVE = "inactive"
	ERROR = "error"
	CONFIGURING = "configuring"
	TESTING = "testing"


@dataclass
class EnterpriseCredential:
	"""
	Secure credential storage for enterprise integrations
	
	Attributes:
		credential_id: Unique credential identifier
		name: Human-readable credential name
		integration_type: Type of integration
		auth_method: Authentication method
		encrypted_data: Encrypted credential data
		metadata: Additional credential metadata
		created_at: Creation timestamp
		expires_at: Optional expiration timestamp
		last_used: Last usage timestamp
		is_active: Whether credential is active
	"""
	
	credential_id: str
	name: str
	integration_type: IntegrationType
	auth_method: AuthenticationMethod
	encrypted_data: str
	metadata: Dict[str, Any] = field(default_factory=dict)
	created_at: datetime = field(default_factory=datetime.utcnow)
	expires_at: Optional[datetime] = None
	last_used: Optional[datetime] = None
	is_active: bool = True
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization (excludes encrypted data)"""
		data = asdict(self)
		data["integration_type"] = self.integration_type.value
		data["auth_method"] = self.auth_method.value
		data["created_at"] = self.created_at.isoformat()
		data["expires_at"] = self.expires_at.isoformat() if self.expires_at else None
		data["last_used"] = self.last_used.isoformat() if self.last_used else None
		# Remove encrypted data for security
		del data["encrypted_data"]
		return data


@dataclass
class APIEndpoint:
	"""
	API endpoint configuration
	
	Attributes:
		endpoint_id: Unique endpoint identifier
		path: API endpoint path
		method: HTTP method
		description: Endpoint description
		authentication_required: Whether authentication is required
		rate_limit: Rate limiting configuration
		permissions: Required permissions
		input_schema: JSON schema for input validation
		output_schema: Expected output schema
		created_at: Creation timestamp
		is_active: Whether endpoint is active
		usage_stats: Usage statistics
	"""
	
	endpoint_id: str
	path: str
	method: str
	description: str = ""
	authentication_required: bool = True
	rate_limit: Dict[str, Any] = field(default_factory=lambda: {"requests_per_minute": 100})
	permissions: List[str] = field(default_factory=list)
	input_schema: Dict[str, Any] = field(default_factory=dict)
	output_schema: Dict[str, Any] = field(default_factory=dict)
	created_at: datetime = field(default_factory=datetime.utcnow)
	is_active: bool = True
	usage_stats: Dict[str, Any] = field(default_factory=lambda: {
		"total_requests": 0,
		"successful_requests": 0,
		"failed_requests": 0,
		"avg_response_time": 0.0
	})
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["created_at"] = self.created_at.isoformat()
		return data


@dataclass
class AuditLogEntry:
	"""
	Comprehensive audit log entry
	
	Attributes:
		log_id: Unique log entry identifier
		timestamp: Event timestamp
		user_id: User who performed the action
		action: Action performed
		resource: Resource affected
		details: Additional event details
		ip_address: Client IP address
		user_agent: Client user agent
		session_id: Session identifier
		integration_id: Related integration identifier
		severity: Event severity level
		outcome: Action outcome (success/failure)
		metadata: Additional metadata
	"""
	
	log_id: str
	timestamp: datetime
	user_id: str
	action: str
	resource: str
	details: Dict[str, Any] = field(default_factory=dict)
	ip_address: str = ""
	user_agent: str = ""
	session_id: str = ""
	integration_id: str = ""
	severity: str = "info"
	outcome: str = "success"
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["timestamp"] = self.timestamp.isoformat()
		return data


class SecureCredentialManager:
	"""
	Secure credential management system
	
	Handles encryption, storage, and retrieval of enterprise credentials
	with advanced security features.
	"""
	
	def __init__(self):
		self.credentials: Dict[str, EnterpriseCredential] = {}
		self.encryption_key = self._generate_encryption_key()
		self._lock = threading.RLock()
		
		if CRYPTOGRAPHY_AVAILABLE:
			self.cipher = Fernet(self.encryption_key)
		else:
			logger.warning("Cryptography not available - using base64 encoding (NOT secure for production)")
	
	def _generate_encryption_key(self) -> bytes:
		"""Generate encryption key for credentials"""
		if CRYPTOGRAPHY_AVAILABLE:
			return Fernet.generate_key()
		else:
			return base64.b64encode(secrets.token_bytes(32))
	
	def store_credential(self, name: str, integration_type: IntegrationType,
					   auth_method: AuthenticationMethod, credential_data: Dict[str, Any],
					   expires_at: datetime = None) -> str:
		"""
		Store encrypted credential
		
		Args:
			name: Human-readable name
			integration_type: Type of integration
			auth_method: Authentication method
			credential_data: Credential data to encrypt
			expires_at: Optional expiration time
			
		Returns:
			Credential ID
		"""
		from uuid_extensions import uuid7str
		
		credential_id = uuid7str()
		
		# Encrypt credential data
		encrypted_data = self._encrypt_data(credential_data)
		
		credential = EnterpriseCredential(
			credential_id=credential_id,
			name=name,
			integration_type=integration_type,
			auth_method=auth_method,
			encrypted_data=encrypted_data,
			expires_at=expires_at
		)
		
		with self._lock:
			self.credentials[credential_id] = credential
		
		logger.info(f"Stored credential {name} ({credential_id})")
		return credential_id
	
	def retrieve_credential(self, credential_id: str) -> Optional[Dict[str, Any]]:
		"""
		Retrieve and decrypt credential data
		
		Args:
			credential_id: Credential identifier
			
		Returns:
			Decrypted credential data or None if not found
		"""
		with self._lock:
			credential = self.credentials.get(credential_id)
		
		if not credential or not credential.is_active:
			return None
		
		# Check expiration
		if credential.expires_at and datetime.now(tz=timezone.utc) > credential.expires_at:
			logger.warning(f"Credential {credential_id} has expired")
			return None
		
		# Decrypt data
		try:
			decrypted_data = self._decrypt_data(credential.encrypted_data)
			
			# Update last used timestamp
			credential.last_used = datetime.now(tz=timezone.utc)
			
			return decrypted_data
		except Exception as e:
			logger.error(f"Failed to decrypt credential {credential_id}: {e}")
			return None
	
	def list_credentials(self, integration_type: IntegrationType = None) -> List[EnterpriseCredential]:
		"""List available credentials (without decrypting)"""
		with self._lock:
			credentials = list(self.credentials.values())
		
		if integration_type:
			credentials = [c for c in credentials if c.integration_type == integration_type]
		
		return [c for c in credentials if c.is_active]
	
	def delete_credential(self, credential_id: str) -> bool:
		"""Delete credential"""
		with self._lock:
			if credential_id in self.credentials:
				self.credentials[credential_id].is_active = False
				logger.info(f"Deleted credential {credential_id}")
				return True
		return False
	
	def _encrypt_data(self, data: Dict[str, Any]) -> str:
		"""Encrypt credential data"""
		json_data = json.dumps(data).encode()
		
		if CRYPTOGRAPHY_AVAILABLE:
			encrypted = self.cipher.encrypt(json_data)
			return base64.b64encode(encrypted).decode()
		else:
			# Fallback: base64 encoding (NOT secure)
			return base64.b64encode(json_data).decode()
	
	def _decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
		"""Decrypt credential data"""
		encrypted_bytes = base64.b64decode(encrypted_data.encode())
		
		if CRYPTOGRAPHY_AVAILABLE:
			decrypted = self.cipher.decrypt(encrypted_bytes)
			return json.loads(decrypted.decode())
		else:
			# Fallback: base64 decoding (NOT secure)
			return json.loads(encrypted_bytes.decode())


class LDAPIntegration:
	"""
	LDAP/Active Directory integration
	
	Provides user authentication and directory services integration
	with enterprise LDAP/AD systems.
	"""
	
	def __init__(self, credential_manager: SecureCredentialManager):
		self.credential_manager = credential_manager
		self.connections: Dict[str, Any] = {}
		self._lock = threading.RLock()
	
	def create_ldap_connection(self, credential_id: str, server_url: str,
							  base_dn: str, config: Dict[str, Any] = None) -> str:
		"""
		Create LDAP connection configuration
		
		Args:
			credential_id: LDAP credential ID
			server_url: LDAP server URL
			base_dn: Base distinguished name
			config: Additional configuration
			
		Returns:
			Connection ID
		"""
		if not LDAP_AVAILABLE:
			raise ImportError("ldap3 library not available")
		
		from uuid_extensions import uuid7str
		
		connection_id = uuid7str()
		config = config or {}
		
		connection_config = {
			"connection_id": connection_id,
			"credential_id": credential_id,
			"server_url": server_url,
			"base_dn": base_dn,
			"use_ssl": config.get("use_ssl", True),
			"port": config.get("port", 636 if config.get("use_ssl", True) else 389),
			"timeout": config.get("timeout", 30),
			"created_at": datetime.now(tz=timezone.utc)
		}
		
		with self._lock:
			self.connections[connection_id] = connection_config
		
		logger.info(f"Created LDAP connection {connection_id}")
		return connection_id
	
	def authenticate_user(self, connection_id: str, username: str, password: str) -> Dict[str, Any]:
		"""
		Authenticate user against LDAP
		
		Args:
			connection_id: LDAP connection ID
			username: Username to authenticate
			password: User password
			
		Returns:
			Authentication result with user information
		"""
		if not LDAP_AVAILABLE:
			return {"success": False, "error": "LDAP not available"}
		
		with self._lock:
			connection_config = self.connections.get(connection_id)
		
		if not connection_config:
			return {"success": False, "error": "Connection not found"}
		
		try:
			# Get LDAP credentials
			credentials = self.credential_manager.retrieve_credential(connection_config["credential_id"])
			if not credentials:
				return {"success": False, "error": "Invalid credentials"}
			
			# Create LDAP server
			server = ldap3.Server(
				connection_config["server_url"],
				port=connection_config["port"],
				use_ssl=connection_config["use_ssl"],
				connect_timeout=connection_config["timeout"]
			)
			
			# Bind with service account
			conn = ldap3.Connection(
				server,
				user=credentials.get("bind_dn"),
				password=credentials.get("bind_password"),
				auto_bind=True
			)
			
			# Search for user
			search_filter = f"(&(objectClass=person)(sAMAccountName={username}))"
			conn.search(
				connection_config["base_dn"],
				search_filter,
				attributes=['cn', 'mail', 'memberOf', 'displayName']
			)
			
			if not conn.entries:
				return {"success": False, "error": "User not found"}
			
			user_entry = conn.entries[0]
			user_dn = user_entry.entry_dn
			
			# Authenticate user
			user_conn = ldap3.Connection(server, user=user_dn, password=password)
			
			if user_conn.bind():
				# Extract user information
				user_info = {
					"username": username,
					"display_name": str(user_entry.displayName) if user_entry.displayName else username,
					"email": str(user_entry.mail) if user_entry.mail else "",
					"groups": [str(group) for group in user_entry.memberOf] if user_entry.memberOf else [],
					"dn": user_dn
				}
				
				user_conn.unbind()
				conn.unbind()
				
				return {
					"success": True,
					"user_info": user_info,
					"authenticated": True
				}
			else:
				conn.unbind()
				return {"success": False, "error": "Invalid password"}
		
		except Exception as e:
			logger.error(f"LDAP authentication error: {e}")
			return {"success": False, "error": str(e)}
	
	def search_users(self, connection_id: str, search_filter: str = None, 
					attributes: List[str] = None) -> Dict[str, Any]:
		"""Search LDAP directory for users"""
		if not LDAP_AVAILABLE:
			return {"success": False, "error": "LDAP not available"}
		
		attributes = attributes or ['cn', 'mail', 'sAMAccountName', 'displayName']
		search_filter = search_filter or "(objectClass=person)"
		
		with self._lock:
			connection_config = self.connections.get(connection_id)
		
		if not connection_config:
			return {"success": False, "error": "Connection not found"}
		
		try:
			# Get credentials and connect
			credentials = self.credential_manager.retrieve_credential(connection_config["credential_id"])
			if not credentials:
				return {"success": False, "error": "Invalid credentials"}
			
			server = ldap3.Server(
				connection_config["server_url"],
				port=connection_config["port"],
				use_ssl=connection_config["use_ssl"]
			)
			
			conn = ldap3.Connection(
				server,
				user=credentials.get("bind_dn"),
				password=credentials.get("bind_password"),
				auto_bind=True
			)
			
			# Search
			conn.search(
				connection_config["base_dn"],
				search_filter,
				attributes=attributes,
				size_limit=100
			)
			
			users = []
			for entry in conn.entries:
				user = {"dn": entry.entry_dn}
				for attr in attributes:
					if hasattr(entry, attr):
						value = getattr(entry, attr)
						user[attr] = str(value) if value else ""
				users.append(user)
			
			conn.unbind()
			
			return {
				"success": True,
				"users": users,
				"count": len(users)
			}
		
		except Exception as e:
			logger.error(f"LDAP search error: {e}")
			return {"success": False, "error": str(e)}


class APIManager:
	"""
	Enterprise API management system
	
	Manages API endpoints, rate limiting, authentication, and monitoring
	for enterprise API integrations.
	"""
	
	def __init__(self):
		self.endpoints: Dict[str, APIEndpoint] = {}
		self.api_keys: Dict[str, Dict[str, Any]] = {}
		self.rate_limits: Dict[str, Dict[str, Any]] = {}
		self._lock = threading.RLock()
	
	def register_endpoint(self, path: str, method: str, description: str = "",
						 authentication_required: bool = True,
						 rate_limit: Dict[str, Any] = None,
						 permissions: List[str] = None) -> str:
		"""Register new API endpoint"""
		from uuid_extensions import uuid7str
		
		endpoint_id = uuid7str()
		
		endpoint = APIEndpoint(
			endpoint_id=endpoint_id,
			path=path,
			method=method.upper(),
			description=description,
			authentication_required=authentication_required,
			rate_limit=rate_limit or {"requests_per_minute": 100},
			permissions=permissions or []
		)
		
		with self._lock:
			self.endpoints[endpoint_id] = endpoint
		
		logger.info(f"Registered API endpoint {method.upper()} {path}")
		return endpoint_id
	
	def generate_api_key(self, name: str, permissions: List[str] = None,
						expires_at: datetime = None) -> Dict[str, str]:
		"""Generate new API key"""
		api_key = secrets.token_urlsafe(32)
		api_secret = secrets.token_urlsafe(64)
		
		key_info = {
			"name": name,
			"api_key": api_key,
			"api_secret_hash": hashlib.sha256(api_secret.encode()).hexdigest(),
			"permissions": permissions or [],
			"created_at": datetime.now(tz=timezone.utc),
			"expires_at": expires_at,
			"is_active": True,
			"usage_count": 0,
			"last_used": None
		}
		
		with self._lock:
			self.api_keys[api_key] = key_info
		
		return {
			"api_key": api_key,
			"api_secret": api_secret
		}
	
	def validate_api_key(self, api_key: str, api_secret: str) -> Optional[Dict[str, Any]]:
		"""Validate API key and secret"""
		with self._lock:
			key_info = self.api_keys.get(api_key)
		
		if not key_info or not key_info["is_active"]:
			return None
		
		# Check expiration
		if key_info["expires_at"] and datetime.now(tz=timezone.utc) > key_info["expires_at"]:
			return None
		
		# Verify secret
		secret_hash = hashlib.sha256(api_secret.encode()).hexdigest()
		if secret_hash != key_info["api_secret_hash"]:
			return None
		
		# Update usage
		key_info["usage_count"] += 1
		key_info["last_used"] = datetime.now(tz=timezone.utc)
		
		return key_info
	
	def check_rate_limit(self, api_key: str, endpoint_id: str) -> bool:
		"""Check if request is within rate limits"""
		with self._lock:
			endpoint = self.endpoints.get(endpoint_id)
			if not endpoint:
				return False
			
			# Get rate limit for this key/endpoint
			limit_key = f"{api_key}:{endpoint_id}"
			current_time = datetime.now(tz=timezone.utc)
			
			if limit_key not in self.rate_limits:
				self.rate_limits[limit_key] = {
					"requests": [],
					"window_start": current_time
				}
			
			limit_info = self.rate_limits[limit_key]
			requests_per_minute = endpoint.rate_limit.get("requests_per_minute", 100)
			
			# Clean old requests (older than 1 minute)
			cutoff_time = current_time - timedelta(minutes=1)
			limit_info["requests"] = [
				req_time for req_time in limit_info["requests"]
				if req_time > cutoff_time
			]
			
			# Check if under limit
			if len(limit_info["requests"]) < requests_per_minute:
				limit_info["requests"].append(current_time)
				return True
			
			return False
	
	def get_endpoint_stats(self, endpoint_id: str) -> Dict[str, Any]:
		"""Get endpoint usage statistics"""
		with self._lock:
			endpoint = self.endpoints.get(endpoint_id)
			if not endpoint:
				return {}
			
			return endpoint.usage_stats.copy()
	
	def update_endpoint_stats(self, endpoint_id: str, response_time: float, success: bool):
		"""Update endpoint usage statistics"""
		with self._lock:
			endpoint = self.endpoints.get(endpoint_id)
			if not endpoint:
				return
			
			stats = endpoint.usage_stats
			stats["total_requests"] += 1
			
			if success:
				stats["successful_requests"] += 1
			else:
				stats["failed_requests"] += 1
			
			# Update average response time
			current_avg = stats["avg_response_time"]
			total_requests = stats["total_requests"]
			stats["avg_response_time"] = (current_avg * (total_requests - 1) + response_time) / total_requests


class AuditLogger:
	"""
	Comprehensive audit logging system
	
	Provides detailed audit trails for enterprise compliance
	and security monitoring.
	"""
	
	def __init__(self, audit_level: AuditLevel = AuditLevel.STANDARD):
		self.audit_level = audit_level
		self.audit_logs: List[AuditLogEntry] = []
		self.log_targets: List[str] = []  # External log targets
		self._lock = threading.RLock()
		
		# Start background log processing
		self._start_log_processor()
	
	def log_event(self, user_id: str, action: str, resource: str,
				 details: Dict[str, Any] = None, ip_address: str = "",
				 user_agent: str = "", session_id: str = "",
				 integration_id: str = "", severity: str = "info",
				 outcome: str = "success") -> str:
		"""
		Log audit event
		
		Args:
			user_id: User performing the action
			action: Action performed
			resource: Resource affected
			details: Additional event details
			ip_address: Client IP address
			user_agent: Client user agent
			session_id: Session identifier
			integration_id: Related integration ID
			severity: Event severity
			outcome: Action outcome
			
		Returns:
			Log entry ID
		"""
		from uuid_extensions import uuid7str
		
		log_id = uuid7str()
		
		log_entry = AuditLogEntry(
			log_id=log_id,
			timestamp=datetime.now(tz=timezone.utc),
			user_id=user_id,
			action=action,
			resource=resource,
			details=details or {},
			ip_address=ip_address,
			user_agent=user_agent,
			session_id=session_id,
			integration_id=integration_id,
			severity=severity,
			outcome=outcome
		)
		
		with self._lock:
			self.audit_logs.append(log_entry)
			
			# Keep only recent logs in memory
			if len(self.audit_logs) > 10000:
				self.audit_logs = self.audit_logs[-8000:]
		
		logger.info(f"Audit log: {user_id} {action} {resource} - {outcome}")
		return log_id
	
	def search_logs(self, filters: Dict[str, Any] = None, 
				   start_time: datetime = None, end_time: datetime = None,
				   limit: int = 100) -> List[AuditLogEntry]:
		"""Search audit logs with filters"""
		filters = filters or {}
		
		with self._lock:
			filtered_logs = self.audit_logs.copy()
		
		# Apply time filters
		if start_time:
			filtered_logs = [log for log in filtered_logs if log.timestamp >= start_time]
		if end_time:
			filtered_logs = [log for log in filtered_logs if log.timestamp <= end_time]
		
		# Apply other filters
		for field, value in filters.items():
			if hasattr(AuditLogEntry, field):
				filtered_logs = [
					log for log in filtered_logs 
					if getattr(log, field) == value
				]
		
		# Sort by timestamp (newest first) and limit
		filtered_logs.sort(key=lambda x: x.timestamp, reverse=True)
		return filtered_logs[:limit]
	
	def get_audit_statistics(self, hours_back: int = 24) -> Dict[str, Any]:
		"""Get audit statistics"""
		cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
		
		with self._lock:
			recent_logs = [
				log for log in self.audit_logs 
				if log.timestamp >= cutoff_time
			]
		
		if not recent_logs:
			return {"message": "No audit logs in specified period"}
		
		# Calculate statistics
		total_events = len(recent_logs)
		successful_events = len([log for log in recent_logs if log.outcome == "success"])
		failed_events = total_events - successful_events
		
		# Count by action
		action_counts = {}
		for log in recent_logs:
			action_counts[log.action] = action_counts.get(log.action, 0) + 1
		
		# Count by user
		user_counts = {}
		for log in recent_logs:
			user_counts[log.user_id] = user_counts.get(log.user_id, 0) + 1
		
		# Count by severity
		severity_counts = {}
		for log in recent_logs:
			severity_counts[log.severity] = severity_counts.get(log.severity, 0) + 1
		
		return {
			"total_events": total_events,
			"successful_events": successful_events,
			"failed_events": failed_events,
			"success_rate": successful_events / total_events if total_events > 0 else 0,
			"top_actions": sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:10],
			"top_users": sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10],
			"severity_distribution": severity_counts,
			"period_hours": hours_back
		}
	
	def _start_log_processor(self):
		"""Start background log processing thread"""
		def process_logs():
			import time
			while True:
				try:
					time.sleep(60)  # Process every minute
					
					# Here you could implement:
					# - Writing logs to external systems
					# - Log rotation
					# - Real-time alerting
					# - Log compression
					
					pass
				except Exception as e:
					logger.error(f"Log processor error: {e}")
		
		processor_thread = threading.Thread(target=process_logs, daemon=True)
		processor_thread.start()


class ExternalConnector:
	"""
	External system connector framework
	
	Provides standardized connectors for integrating with external
	systems like databases, message queues, and cloud services.
	"""
	
	def __init__(self, credential_manager: SecureCredentialManager, audit_logger: AuditLogger):
		self.credential_manager = credential_manager
		self.audit_logger = audit_logger
		self.connectors: Dict[str, Dict[str, Any]] = {}
		self._lock = threading.RLock()
	
	def create_database_connector(self, name: str, credential_id: str, 
								 connection_string: str, database_type: str) -> str:
		"""Create database connector"""
		from uuid_extensions import uuid7str
		
		connector_id = uuid7str()
		
		connector = {
			"connector_id": connector_id,
			"name": name,
			"type": "database",
			"credential_id": credential_id,
			"connection_string": connection_string,
			"database_type": database_type,
			"status": ConnectorStatus.CONFIGURING,
			"created_at": datetime.now(tz=timezone.utc),
			"last_tested": None,
			"test_results": None
		}
		
		with self._lock:
			self.connectors[connector_id] = connector
		
		return connector_id
	
	def create_rest_api_connector(self, name: str, credential_id: str,
								 base_url: str, headers: Dict[str, str] = None) -> str:
		"""Create REST API connector"""
		from uuid_extensions import uuid7str
		
		connector_id = uuid7str()
		
		connector = {
			"connector_id": connector_id,
			"name": name,
			"type": "rest_api",
			"credential_id": credential_id,
			"base_url": base_url,
			"headers": headers or {},
			"status": ConnectorStatus.CONFIGURING,
			"created_at": datetime.now(tz=timezone.utc),
			"last_tested": None,
			"test_results": None
		}
		
		with self._lock:
			self.connectors[connector_id] = connector
		
		return connector_id
	
	def test_connector(self, connector_id: str) -> Dict[str, Any]:
		"""Test connector connectivity"""
		with self._lock:
			connector = self.connectors.get(connector_id)
		
		if not connector:
			return {"success": False, "error": "Connector not found"}
		
		try:
			connector["status"] = ConnectorStatus.TESTING
			
			if connector["type"] == "database":
				result = self._test_database_connector(connector)
			elif connector["type"] == "rest_api":
				result = self._test_rest_api_connector(connector)
			else:
				result = {"success": False, "error": "Unknown connector type"}
			
			connector["last_tested"] = datetime.now(tz=timezone.utc)
			connector["test_results"] = result
			connector["status"] = ConnectorStatus.ACTIVE if result["success"] else ConnectorStatus.ERROR
			
			# Audit log
			self.audit_logger.log_event(
				user_id="system",
				action="test_connector",
				resource=f"connector:{connector_id}",
				details={"connector_name": connector["name"], "result": result},
				outcome="success" if result["success"] else "failure"
			)
			
			return result
			
		except Exception as e:
			logger.error(f"Connector test failed: {e}")
			connector["status"] = ConnectorStatus.ERROR
			return {"success": False, "error": str(e)}
	
	def _test_database_connector(self, connector: Dict[str, Any]) -> Dict[str, Any]:
		"""Test database connector"""
		try:
			# Get credentials
			credentials = self.credential_manager.retrieve_credential(connector["credential_id"])
			if not credentials:
				return {"success": False, "error": "Invalid credentials"}
			
			# Build connection string with credentials
			connection_string = connector["connection_string"]
			if "username" in credentials:
				connection_string = connection_string.replace("{username}", credentials["username"])
			if "password" in credentials:
				connection_string = connection_string.replace("{password}", credentials["password"])
			
			# Test connection
			engine = create_engine(connection_string, connect_args={"connect_timeout": 10})
			
			with engine.connect() as conn:
				# Simple test query
				result = conn.execute(text("SELECT 1"))
				row = result.fetchone()
				
				if row and row[0] == 1:
					return {
						"success": True,
						"message": "Database connection successful",
						"database_type": connector["database_type"]
					}
				else:
					return {"success": False, "error": "Unexpected test query result"}
		
		except Exception as e:
			return {"success": False, "error": f"Database connection failed: {str(e)}"}
	
	def _test_rest_api_connector(self, connector: Dict[str, Any]) -> Dict[str, Any]:
		"""Test REST API connector"""
		if not REQUESTS_AVAILABLE:
			return {"success": False, "error": "Requests library not available"}
		
		try:
			# Get credentials
			credentials = self.credential_manager.retrieve_credential(connector["credential_id"])
			if not credentials:
				return {"success": False, "error": "Invalid credentials"}
			
			# Prepare headers
			headers = connector["headers"].copy()
			
			# Add authentication
			if "api_key" in credentials:
				headers["Authorization"] = f"Bearer {credentials['api_key']}"
			elif "username" in credentials and "password" in credentials:
				auth = (credentials["username"], credentials["password"])
			else:
				auth = None
			
			# Test API connection
			response = requests.get(
				connector["base_url"],
				headers=headers,
				auth=auth if "auth" in locals() else None,
				timeout=10,
				verify=True
			)
			
			if response.status_code == 200:
				return {
					"success": True,
					"message": "API connection successful",
					"status_code": response.status_code,
					"response_time": response.elapsed.total_seconds()
				}
			else:
				return {
					"success": False,
					"error": f"API returned status code {response.status_code}",
					"status_code": response.status_code
				}
		
		except Exception as e:
			return {"success": False, "error": f"API connection failed: {str(e)}"}
	
	def get_connector_status(self, connector_id: str) -> Optional[Dict[str, Any]]:
		"""Get connector status"""
		with self._lock:
			connector = self.connectors.get(connector_id)
		
		if connector:
			return {
				"connector_id": connector_id,
				"name": connector["name"],
				"type": connector["type"],
				"status": connector["status"].value,
				"last_tested": connector["last_tested"].isoformat() if connector["last_tested"] else None,
				"test_results": connector["test_results"]
			}
		return None
	
	def list_connectors(self, connector_type: str = None) -> List[Dict[str, Any]]:
		"""List all connectors"""
		with self._lock:
			connectors = list(self.connectors.values())
		
		if connector_type:
			connectors = [c for c in connectors if c["type"] == connector_type]
		
		return [
			{
				"connector_id": c["connector_id"],
				"name": c["name"],
				"type": c["type"],
				"status": c["status"].value,
				"created_at": c["created_at"].isoformat()
			}
			for c in connectors
		]


class EnterpriseIntegrationSuite:
	"""
	Main enterprise integration suite
	
	Coordinates all enterprise integration components including
	SSO, LDAP, API management, audit logging, and external connectors.
	"""
	
	def __init__(self):
		self.credential_manager = SecureCredentialManager()
		self.ldap_integration = LDAPIntegration(self.credential_manager)
		self.api_manager = APIManager()
		self.audit_logger = AuditLogger()
		self.external_connector = ExternalConnector(self.credential_manager, self.audit_logger)
		self.sso_providers: Dict[str, Dict[str, Any]] = {}
		self._lock = threading.RLock()
		
		# Initialize default API endpoints
		self._initialize_default_endpoints()
		
		# Start monitoring threads
		self._start_monitoring()
	
	def _initialize_default_endpoints(self):
		"""Initialize default API endpoints"""
		default_endpoints = [
			{
				"path": "/api/v1/graphs",
				"method": "GET",
				"description": "List all graphs",
				"permissions": ["read_graphs"]
			},
			{
				"path": "/api/v1/graphs/{graph_id}/data",
				"method": "GET", 
				"description": "Get graph data",
				"permissions": ["read_graph_data"]
			},
			{
				"path": "/api/v1/graphs/{graph_id}/query",
				"method": "POST",
				"description": "Execute Cypher query",
				"permissions": ["execute_queries"]
			},
			{
				"path": "/api/v1/analytics/insights",
				"method": "GET",
				"description": "Get AI insights",
				"permissions": ["read_insights"]
			}
		]
		
		for endpoint in default_endpoints:
			self.api_manager.register_endpoint(**endpoint)
	
	def configure_sso_provider(self, provider_type: str, provider_name: str,
							  configuration: Dict[str, Any]) -> str:
		"""Configure SSO provider"""
		from uuid_extensions import uuid7str
		
		provider_id = uuid7str()
		
		sso_config = {
			"provider_id": provider_id,
			"provider_type": provider_type,
			"provider_name": provider_name,
			"configuration": configuration,
			"created_at": datetime.now(tz=timezone.utc),
			"is_active": True
		}
		
		with self._lock:
			self.sso_providers[provider_id] = sso_config
		
		self.audit_logger.log_event(
			user_id="system",
			action="configure_sso_provider",
			resource=f"sso_provider:{provider_id}",
			details={"provider_name": provider_name, "provider_type": provider_type}
		)
		
		logger.info(f"Configured SSO provider {provider_name} ({provider_id})")
		return provider_id
	
	def get_integration_overview(self, user_id: str = None) -> Dict[str, Any]:
		"""Get enterprise integration overview"""
		
		# Credential statistics
		credential_stats = {
			"total_credentials": len(self.credential_manager.credentials),
			"active_credentials": len([c for c in self.credential_manager.credentials.values() if c.is_active]),
			"by_type": {}
		}
		
		for credential in self.credential_manager.credentials.values():
			if credential.is_active:
				int_type = credential.integration_type.value
				credential_stats["by_type"][int_type] = credential_stats["by_type"].get(int_type, 0) + 1
		
		# API statistics
		api_stats = {
			"total_endpoints": len(self.api_manager.endpoints),
			"active_endpoints": len([e for e in self.api_manager.endpoints.values() if e.is_active]),
			"total_api_keys": len(self.api_manager.api_keys),
			"active_api_keys": len([k for k in self.api_manager.api_keys.values() if k["is_active"]])
		}
		
		# Connector statistics  
		connector_stats = {
			"total_connectors": len(self.external_connector.connectors),
			"active_connectors": len([
				c for c in self.external_connector.connectors.values() 
				if c["status"] == ConnectorStatus.ACTIVE
			]),
			"by_type": {}
		}
		
		for connector in self.external_connector.connectors.values():
			conn_type = connector["type"]
			connector_stats["by_type"][conn_type] = connector_stats["by_type"].get(conn_type, 0) + 1
		
		# Audit statistics
		audit_stats = self.audit_logger.get_audit_statistics(24)
		
		# SSO statistics
		sso_stats = {
			"total_providers": len(self.sso_providers),
			"active_providers": len([p for p in self.sso_providers.values() if p["is_active"]]),
			"by_type": {}
		}
		
		for provider in self.sso_providers.values():
			if provider["is_active"]:
				prov_type = provider["provider_type"]
				sso_stats["by_type"][prov_type] = sso_stats["by_type"].get(prov_type, 0) + 1
		
		return {
			"credential_management": credential_stats,
			"api_management": api_stats,
			"external_connectors": connector_stats,
			"audit_logging": audit_stats,
			"sso_integration": sso_stats,
			"integration_health": {
				"overall_status": "healthy",  # Could be computed based on connector tests
				"total_integrations": (
					credential_stats["active_credentials"] + 
					connector_stats["active_connectors"] + 
					sso_stats["active_providers"]
				)
			}
		}
	
	def _start_monitoring(self):
		"""Start background monitoring threads"""
		def monitor_integrations():
			import time
			while True:
				try:
					time.sleep(300)  # Monitor every 5 minutes
					
					# Test connector health
					for connector_id in list(self.external_connector.connectors.keys()):
						connector = self.external_connector.connectors[connector_id]
						if connector["status"] == ConnectorStatus.ACTIVE:
							# Periodic health check
							last_tested = connector.get("last_tested")
							if (not last_tested or 
								datetime.now(tz=timezone.utc) - last_tested > timedelta(hours=1)):
								self.external_connector.test_connector(connector_id)
					
					# Clean up expired credentials
					for credential in list(self.credential_manager.credentials.values()):
						if (credential.expires_at and 
							datetime.now(tz=timezone.utc) > credential.expires_at):
							credential.is_active = False
							
							self.audit_logger.log_event(
								user_id="system",
								action="credential_expired", 
								resource=f"credential:{credential.credential_id}",
								details={"credential_name": credential.name}
							)
					
				except Exception as e:
					logger.error(f"Integration monitoring error: {e}")
		
		monitor_thread = threading.Thread(target=monitor_integrations, daemon=True)
		monitor_thread.start()


# Global enterprise integration suite instance
_enterprise_integration_suite = None


def get_enterprise_integration_suite() -> EnterpriseIntegrationSuite:
	"""Get or create global enterprise integration suite instance"""
	global _enterprise_integration_suite
	if _enterprise_integration_suite is None:
		_enterprise_integration_suite = EnterpriseIntegrationSuite()
	return _enterprise_integration_suite