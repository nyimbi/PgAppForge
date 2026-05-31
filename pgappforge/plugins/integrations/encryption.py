"""AES-256-GCM credential vault for Integration Hub."""
from __future__ import annotations
import base64
import json
import secrets


def _derive_key(raw_key: str | bytes) -> bytes:
	"""Derive a 32-byte AES key from the configured secret."""
	if isinstance(raw_key, str):
		raw_key = raw_key.encode("utf-8")
	# Use SHA-256 hash of key for deterministic 32-byte derivation
	import hashlib
	return hashlib.sha256(raw_key).digest()


def encrypt_credentials(data: dict, secret_key: str | bytes) -> bytes:
	"""Encrypt a dict of credentials using AES-256-GCM.

	Returns bytes: base64-encoded nonce (12) + ciphertext + tag (16).
	"""
	try:
		from cryptography.hazmat.primitives.ciphers.aead import AESGCM
	except ImportError:
		raise RuntimeError("Install cryptography: pip install cryptography")
	key = _derive_key(secret_key)
	nonce = secrets.token_bytes(12)
	aesgcm = AESGCM(key)
	plaintext = json.dumps(data, default=str).encode("utf-8")
	ciphertext = aesgcm.encrypt(nonce, plaintext, None)
	combined = base64.b64encode(nonce + ciphertext)
	return combined


def decrypt_credentials(encrypted: bytes, secret_key: str | bytes) -> dict:
	"""Decrypt credentials encrypted with encrypt_credentials."""
	try:
		from cryptography.hazmat.primitives.ciphers.aead import AESGCM
	except ImportError:
		raise RuntimeError("Install cryptography: pip install cryptography")
	key = _derive_key(secret_key)
	combined = base64.b64decode(encrypted)
	nonce = combined[:12]
	ciphertext = combined[12:]
	aesgcm = AESGCM(key)
	plaintext = aesgcm.decrypt(nonce, ciphertext, None)
	return json.loads(plaintext.decode("utf-8"))
