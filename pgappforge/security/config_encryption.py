"""
Secure Configuration Encryption System.

Provides encryption/decryption for sensitive tenant configuration values
using industry-standard cryptographic practices.
"""

import os
import logging
import base64
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app

log = logging.getLogger(__name__)


class ConfigEncryptionError(Exception):
	"""Exception raised when configuration encryption/decryption fails."""
	pass


class ConfigEncryption:
	"""
	Handles encryption and decryption of sensitive tenant configuration values.
	
	Uses Fernet symmetric encryption (AES 128 in CBC mode) with PBKDF2 key derivation
	for secure handling of sensitive data like API keys, passwords, and credentials.
	"""
	
	def __init__(self, app=None):
		self.app = app
		self._fernet = None
		self._salt = None
		
		if app:
			self.init_app(app)
	
	def init_app(self, app):
		"""Initialize encryption system with Flask app."""
		self.app = app
		self._setup_encryption_key()
		
		# Store reference in app extensions
		if not hasattr(app, 'extensions'):
			app.extensions = {}
		app.extensions['config_encryption'] = self
	
	def _setup_encryption_key(self):
		"""Set up encryption key from environment or generate new one."""
		try:
			# Get master key from environment
			master_key = os.environ.get('FAB_CONFIG_MASTER_KEY')
			if not master_key:
				master_key = self.app.config.get('FAB_CONFIG_MASTER_KEY')
			
			if not master_key:
				# In development, generate a key and warn
				if self.app.debug:
					master_key = Fernet.generate_key().decode()
					log.warning(
						"No FAB_CONFIG_MASTER_KEY found. Generated temporary key for development. "
						"Set FAB_CONFIG_MASTER_KEY environment variable for production."
					)
				else:
					raise ConfigEncryptionError(
						"FAB_CONFIG_MASTER_KEY not found. This is required for production deployment."
					)
			
			# Get or generate salt
			self._salt = os.environ.get('FAB_CONFIG_SALT', 'fab-tenant-config-salt-v1').encode()
			
			# Derive encryption key using PBKDF2
			kdf = PBKDF2HMAC(
				algorithm=hashes.SHA256(),
				length=32,
				salt=self._salt,
				iterations=100000,
			)
			
			derived_key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
			self._fernet = Fernet(derived_key)
			
			log.info("Configuration encryption system initialized successfully")
			
		except Exception as e:
			log.error(f"Failed to initialize configuration encryption: {e}")
			raise ConfigEncryptionError(f"Encryption initialization failed: {e}")
	
	def encrypt_value(self, value: Any) -> str:
		"""
		Encrypt a configuration value.
		
		Args:
			value: The value to encrypt (will be JSON serialized)
			
		Returns:
			Base64 encoded encrypted string
			
		Raises:
			ConfigEncryptionError: If encryption fails
		"""
		try:
			if self._fernet is None:
				raise ConfigEncryptionError("Encryption system not initialized")
			
			# Convert value to JSON string
			import json
			json_value = json.dumps(value, separators=(',', ':'))
			
			# Encrypt the JSON string
			encrypted_bytes = self._fernet.encrypt(json_value.encode('utf-8'))
			
			# Return base64 encoded encrypted data
			return base64.urlsafe_b64encode(encrypted_bytes).decode('ascii')
			
		except Exception as e:
			log.error(f"Failed to encrypt configuration value: {e}")
			raise ConfigEncryptionError(f"Encryption failed: {e}")
	
	def decrypt_value(self, encrypted_value: str) -> Any:
		"""
		Decrypt a configuration value.
		
		Args:
			encrypted_value: Base64 encoded encrypted string
			
		Returns:
			Original decrypted value
			
		Raises:
			ConfigEncryptionError: If decryption fails
		"""
		try:
			if self._fernet is None:
				raise ConfigEncryptionError("Encryption system not initialized")
			
			# Decode from base64
			encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode('ascii'))
			
			# Decrypt the data
			decrypted_bytes = self._fernet.decrypt(encrypted_bytes)
			
			# Parse JSON value
			import json
			return json.loads(decrypted_bytes.decode('utf-8'))
			
		except InvalidToken:
			log.error("Invalid encryption token - data may be corrupted or tampered with")
			raise ConfigEncryptionError("Invalid encryption token")
		except json.JSONDecodeError as e:
			log.error(f"Failed to parse decrypted JSON: {e}")
			raise ConfigEncryptionError(f"JSON parse error: {e}")
		except Exception as e:
			log.error(f"Failed to decrypt configuration value: {e}")
			raise ConfigEncryptionError(f"Decryption failed: {e}")
	
	def is_encrypted(self, value: str) -> bool:
		"""
		Check if a value appears to be encrypted.
		
		Args:
			value: Value to check
			
		Returns:
			True if value appears to be encrypted
		"""
		try:
			# Check if it's a base64 string of reasonable length for encrypted data
			if not isinstance(value, str):
				return False
			
			if len(value) < 50:  # Minimum length for Fernet encrypted data
				return False
			
			# Try to decode as base64
			base64.urlsafe_b64decode(value.encode('ascii'))
			return True
			
		except Exception:
			return False
	
	def rotate_key(self, new_master_key: str, re_encrypt_all: bool = False):
		"""
		Rotate encryption key and optionally re-encrypt all data.
		
		Args:
			new_master_key: New master key
			re_encrypt_all: Whether to re-encrypt all existing data
			
		Raises:
			ConfigEncryptionError: If key rotation fails
		"""
		try:
			if re_encrypt_all:
				# This would need to be implemented to update all encrypted configs
				# in the database - complex operation requiring careful coordination
				log.warning("Full data re-encryption not yet implemented")
			
			# Update the encryption key
			old_fernet = self._fernet
			
			# Set up new key
			kdf = PBKDF2HMAC(
				algorithm=hashes.SHA256(),
				length=32,
				salt=self._salt,
				iterations=100000,
			)
			
			derived_key = base64.urlsafe_b64encode(kdf.derive(new_master_key.encode()))
			self._fernet = Fernet(derived_key)
			
			log.info("Encryption key rotated successfully")
			
		except Exception as e:
			log.error(f"Failed to rotate encryption key: {e}")
			raise ConfigEncryptionError(f"Key rotation failed: {e}")


# Global encryption instance
_config_encryption = None


def get_config_encryption():
	"""Get global configuration encryption instance."""
	global _config_encryption
	
	if _config_encryption is None:
		if current_app:
			_config_encryption = current_app.extensions.get('config_encryption')
		
		if _config_encryption is None:
			_config_encryption = ConfigEncryption()
	
	return _config_encryption


def encrypt_sensitive_value(value: Any) -> str:
	"""Encrypt a sensitive configuration value."""
	encryption = get_config_encryption()
	return encryption.encrypt_value(value)


def decrypt_sensitive_value(encrypted_value: str) -> Any:
	"""Decrypt a sensitive configuration value."""
	encryption = get_config_encryption()
	return encryption.decrypt_value(encrypted_value)


def is_value_encrypted(value: str) -> bool:
	"""Check if a value is encrypted."""
	encryption = get_config_encryption()
	return encryption.is_encrypted(value)