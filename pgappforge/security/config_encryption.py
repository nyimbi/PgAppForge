"""
Secure Configuration Encryption System.

Provides encryption/decryption for sensitive tenant configuration values
using industry-standard cryptographic practices.
"""

import os
import secrets
import logging
import base64
import json
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app

log = logging.getLogger(__name__)

# Token format: pgaf:v2:<b64 salt>:<b64 ciphertext>
TOKEN_PREFIX_V2 = "pgaf:v2:"
TOKEN_PREFIX_V1 = "pgaf:v1:"

# PBKDF2 iteration counts, per format version.
ITERATIONS_V1 = 100_000
ITERATIONS_V2 = 600_000

# The hard-coded salt shipped in v1 was public in the source tree, so it salted
# nothing: anyone with the master key could brute-force a tenant config offline.
# v2 carries a per-ciphertext random salt instead.
LEGACY_SALT_V1 = b"fab-tenant-config-salt-v1"


def _process_salt() -> bytes:
	"""Resolve the encryption salt.

	PGAF_CONFIG_SALT wins when set. Otherwise a random 32-byte salt is minted
	once per process and every v2 ciphertext records its own salt alongside it,
	so the value stays decryptable within this process but not across a restart
	unless the salt is pinned.
	"""
	configured = os.environ.get("PGAF_CONFIG_SALT")
	if configured:
		return configured.encode()

	log.warning(
		"PGAF_CONFIG_SALT is unset: using an ephemeral random salt. "
		"Encrypted config values will NOT survive a process restart or a "
		"multi-process deployment. Set PGAF_CONFIG_SALT before going live."
	)
	return secrets.token_bytes(32)


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
		self._master_key: Optional[str] = None
		
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
	
	@staticmethod
	def _fernet_for(salt: bytes, iterations: int, master_key: str) -> Fernet:
		"""Derive a Fernet instance from a master key, salt and iteration count."""
		kdf = PBKDF2HMAC(
			algorithm=hashes.SHA256(),
			length=32,
			salt=salt,
			iterations=iterations,
		)
		derived_key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
		return Fernet(derived_key)
	
	def _setup_encryption_key(self):
		"""Set up encryption key from environment or generate new one."""
		try:
			# Get master key from environment
			master_key = os.environ.get('PGAF_CONFIG_MASTER_KEY')
			if not master_key:
				master_key = self.app.config.get('PGAF_CONFIG_MASTER_KEY')
			
			if not master_key:
				# In development, generate a key and warn
				if self.app.debug:
					master_key = Fernet.generate_key().decode()
					log.warning(
						"No PGAF_CONFIG_MASTER_KEY found. Generated temporary key for development. "
						"Set PGAF_CONFIG_MASTER_KEY environment variable for production."
					)
				else:
					raise ConfigEncryptionError(
						"PGAF_CONFIG_MASTER_KEY not found. This is required for production deployment."
					)
			
			self._master_key = master_key
			# Legacy salt is retained solely to keep v1 ciphertexts readable.
			self._salt = LEGACY_SALT_V1
			self._fernet = self._fernet_for(LEGACY_SALT_V1, ITERATIONS_V1, master_key)
			
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
			Token of the form ``pgaf:v2:<b64 salt>:<b64 ciphertext>``. The salt
			travels with the ciphertext so a rotating or pinned salt still reads
			back correctly.
			
		Raises:
			ConfigEncryptionError: If encryption fails
		"""
		try:
			if self._fernet is None:
				raise ConfigEncryptionError("Encryption system not initialized")
			
			# Convert value to JSON string
			json_value = json.dumps(value, separators=(',', ':'))
			
			# Fresh salt per ciphertext
			salt = _process_salt()
			fernet = self._fernet_for(salt, ITERATIONS_V2, self._master_key)
			
			# Encrypt the JSON string
			encrypted_bytes = fernet.encrypt(json_value.encode('utf-8'))
			
			# Fernet output is already urlsafe-b64; do not double-encode.
			b64_salt = base64.urlsafe_b64encode(salt).decode('ascii')
			b64_ciphertext = encrypted_bytes.decode('ascii')
			
			return f"{TOKEN_PREFIX_V2}{b64_salt}:{b64_ciphertext}"
			
		except Exception as e:
			log.error(f"Failed to encrypt configuration value: {e}")
			raise ConfigEncryptionError(f"Encryption failed: {e}")
	
	def _fernet_for_token(self, encrypted_value: str) -> tuple[Fernet, str]:
		"""Resolve the Fernet instance and ciphertext body implied by a token."""
		if not isinstance(encrypted_value, str):
			raise ConfigEncryptionError("Encrypted value must be a string")
		
		if self._master_key is None:
			raise ConfigEncryptionError("Encryption system not initialized")
		
		if encrypted_value.startswith(TOKEN_PREFIX_V2):
			parts = encrypted_value[len(TOKEN_PREFIX_V2):].split(":")
			if len(parts) != 2:
				raise ConfigEncryptionError("Malformed pgaf:v2 token")
			b64_salt, ciphertext = parts
			try:
				salt = base64.urlsafe_b64decode(b64_salt.encode('ascii'))
			except Exception as e:
				raise ConfigEncryptionError(f"Invalid token salt: {e}")
			fernet = self._fernet_for(salt, ITERATIONS_V2, self._master_key)
			# v2 stores the Fernet token verbatim; hand it over as-is.
		elif encrypted_value.startswith(TOKEN_PREFIX_V1):
			parts = encrypted_value[len(TOKEN_PREFIX_V1):].split(":")
			if len(parts) == 2:
				ciphertext = parts[1]
			else:
				ciphertext = encrypted_value[len(TOKEN_PREFIX_V1):]
			fernet = self._fernet_for(LEGACY_SALT_V1, ITERATIONS_V1, self._master_key)
		else:
			# Unprefixed: the original v1 output, which base64-encoded the
			# Fernet token a second time. Unwrap that layer to get back the token.
			ciphertext = base64.urlsafe_b64decode(encrypted_value.encode('ascii'))
			fernet = self._fernet_for(LEGACY_SALT_V1, ITERATIONS_V1, self._master_key)
		
		return fernet, ciphertext
	
	def decrypt_value(self, encrypted_value: str) -> Any:
		"""
		Decrypt a configuration value.
		
		Args:
			encrypted_value: Base64 encoded encrypted string
			
		Handles three forms:
		  - ``pgaf:v2:``  salt and iterations carried in the token (600k)
		  - ``pgaf:v1:``  legacy fixed salt, 100k iterations
		  - unprefixed    legacy v1 ciphertext as originally emitted
		  
		Returns:
			Original decrypted value
			
		Raises:
			ConfigEncryptionError: If decryption fails
		"""
		try:
			if self._fernet is None:
				raise ConfigEncryptionError("Encryption system not initialized")
			
			fernet, ciphertext = self._fernet_for_token(encrypted_value)
			
			# Fernet.decrypt does its own base64 decode of the token..
			decrypted_bytes = fernet.decrypt(ciphertext)
			
			# Parse JSON value
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
		# Prefix test only. The old base64-length heuristic matched any long
		# base64-looking string -- base64 API keys and bearer tokens -- and so
		# tried to decrypt plaintext, turning a bad guess into an exception.
		if not isinstance(value, str):
			return False
		return value.startswith(TOKEN_PREFIX_V2) or value.startswith(TOKEN_PREFIX_V1)
	
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
			
			# Set up new key. v2 tokens carry their own salt, so the new key
			# applies to them immediately; v1 tokens follow the legacy path.
			self._fernet = self._fernet_for(LEGACY_SALT_V1, ITERATIONS_V1, new_master_key)
			self._master_key = new_master_key
			
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