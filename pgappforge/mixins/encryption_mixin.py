"""
encryption_mixin.py

Column-level encryption for SQLAlchemy models in PgForge applications,
backed by PostgreSQL pgcrypto.  Transparently encrypts designated fields on write
and decrypts on read, with support for key rotation, field-level access policies,
and deterministic (searchable) vs. non-deterministic (IND-CCA2) ciphertext.

Design notes
------------
- Encryption happens inside the database via ``pgp_sym_encrypt`` / ``pgp_sym_decrypt``
  (OpenPGP symmetric, pgcrypto extension).  The Python layer never stores plaintext
  in the database column; it stores the pgcrypto ciphertext blob (bytea/text).
- Key rotation: the mixin keeps a *key ring* keyed by integer version.  The active
  version is stored per-row so old rows can still be decrypted after a key change.
- Deterministic mode uses ``digest(plaintext||salt, 'sha256')`` for HMAC tokens
  stored in a side-column so equality searches remain possible without exposing
  plaintext.  Non-deterministic mode stores no HMAC and is fully opaque.
- All encryption/decryption SQL is emitted as parameterised literals; no key
  material appears in log output.
- The mixin depends only on SQLAlchemy, psycopg2/psycopg, and stdlib.  The
  ``cryptography`` package is used *client-side* for key derivation only and is
  imported with a guarded try/except so the mixin loads even without it.

PostgreSQL requirements
-----------------------
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

Usage
-----
    class Patient(EncryptionMixin, Model):
        __tablename__ = "patients"
        id   = Column(Integer, primary_key=True)
        name = Column(String(200))          # plain column, not encrypted

        __encrypted_fields__ = ["ssn", "dob", "notes"]
        __encryption_key__   = "change-me-in-production"

    p = Patient(name="Alice")
    p.set_encrypted("ssn", "123-45-6789")
    session.add(p); session.flush()
    print(p.get_decrypted("ssn"))   # "123-45-6789"

Author: Nyimbi Odero
Version: 2.0 (SQLAlchemy 2.x, Python 3.12+, PostgreSQL pgcrypto)
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import warnings
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import Column, DateTime, Index, Integer, LargeBinary, Text, event, select, text
from sqlalchemy.ext.mutable import MutableDict, MutableList

try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
except ImportError:  # non-PostgreSQL or stripped SQLAlchemy build
	from sqlalchemy import JSON as _JSONB  # type: ignore[assignment]

# Use JSONB on PostgreSQL, plain JSON elsewhere — transparent to the mixin
JSONB = _JSONB

try:
	from sqlalchemy.orm import declared_attr, Mapped, mapped_column
	_SA2 = True
except ImportError:
	from sqlalchemy.ext.declarative import declared_attr  # type: ignore[no-redef]
	_SA2 = False

# ---------------------------------------------------------------------------
# Optional: cryptography package for PBKDF2 key derivation
# ---------------------------------------------------------------------------
try:
	from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
	from cryptography.hazmat.primitives import hashes as _crypto_hashes
	from cryptography.hazmat.backends import default_backend as _crypto_backend
	import base64 as _b64
	_HAS_CRYPTOGRAPHY = True
except ImportError:
	_HAS_CRYPTOGRAPHY = False

# ---------------------------------------------------------------------------
# Flask-SQLAlchemy session accessor — FSA 2.x and 3.x compatible
# ---------------------------------------------------------------------------
try:
	from flask_sqlalchemy import SQLAlchemy as _FSA

	def _get_session():
		from flask import current_app
		ext = current_app.extensions.get("sqlalchemy")
		if ext is None:
			raise RuntimeError("No Flask-SQLAlchemy extension found on current_app")
		db = ext if isinstance(ext, _FSA) else getattr(ext, "db", ext)
		return db.session

except ImportError:
	def _get_session():  # type: ignore[misc]
		raise RuntimeError("flask_sqlalchemy is required")

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel for "no value provided" — distinct from None
# ---------------------------------------------------------------------------
_MISSING: object = object()

# ---------------------------------------------------------------------------
# Default pgcrypto cipher options
# ---------------------------------------------------------------------------
_DEFAULT_CIPHER_ALGO = "aes256"
_DEFAULT_PGP_OPTIONS = f"cipher-algo={_DEFAULT_CIPHER_ALGO}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
	return datetime.now(tz=timezone.utc)


def _derive_key(passphrase: str, salt: bytes, iterations: int = 200_000) -> str:
	"""
	PBKDF2-HMAC-SHA256 key derivation when the ``cryptography`` package is
	present.  Falls back to a single SHA-256 hash of the passphrase (acceptable
	for dev/test; NOT for production without the cryptography package).
	"""
	if _HAS_CRYPTOGRAPHY:
		kdf = PBKDF2HMAC(
			algorithm=_crypto_hashes.SHA256(),
			length=32,
			salt=salt,
			iterations=iterations,
			backend=_crypto_backend(),
		)
		raw = kdf.derive(passphrase.encode())
		return _b64.b64encode(raw).decode()
	else:
		# Deterministic fallback — warn once per process
		warnings.warn(
			"EncryptionMixin: 'cryptography' package not installed; "
			"using SHA-256 passphrase hash instead of PBKDF2. "
			"Install cryptography>=41.0 for production use.",
			RuntimeWarning,
			stacklevel=4,
		)
		return hashlib.sha256(passphrase.encode() + salt).hexdigest()


def _hmac_token(plaintext: str, key: str) -> str:
	"""
	Deterministic HMAC-SHA256 token for equality-searchable encrypted fields.
	Uses HMAC (keyed hash) so the token cannot be reversed without the key.
	"""
	mac = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), key.encode(), 1)
	return mac.hex()


# ---------------------------------------------------------------------------
# Key Ring
# ---------------------------------------------------------------------------

class KeyRing:
	"""
	Manages multiple encryption key versions.

	Key versions are positive integers.  Version 0 is reserved.  The highest
	loaded version is always the *active* (write) version.

	Example::

		ring = KeyRing()
		ring.add_key(1, "old-passphrase")
		ring.add_key(2, "new-passphrase")   # active
		ring.get_active()   # -> (2, "new-passphrase")
		ring.get(1)         # -> "old-passphrase"  (still readable)
	"""

	def __init__(self) -> None:
		self._keys: dict[int, str] = {}

	def add_key(self, version: int, passphrase: str) -> None:
		"""Register *passphrase* as key for *version*."""
		if version < 1:
			raise ValueError(f"Key version must be >= 1, got {version}")
		self._keys[version] = passphrase

	def get(self, version: int) -> str:
		"""Return passphrase for *version*.

		Raises:
			KeyError: version not registered.
		"""
		try:
			return self._keys[version]
		except KeyError:
			raise KeyError(f"Encryption key version {version} not registered in KeyRing")

	def get_active(self) -> tuple[int, str]:
		"""Return (version, passphrase) for the highest registered version.

		Raises:
			RuntimeError: key ring is empty.
		"""
		if not self._keys:
			raise RuntimeError("KeyRing is empty — register at least one key version")
		version = max(self._keys)
		return version, self._keys[version]

	@property
	def active_version(self) -> int:
		version, _ = self.get_active()
		return version

	def versions(self) -> list[int]:
		"""Return sorted list of registered versions."""
		return sorted(self._keys)

	def __len__(self) -> int:
		return len(self._keys)

	def __repr__(self) -> str:  # pragma: no cover
		return f"KeyRing(versions={self.versions()}, active={self.active_version if self._keys else None})"


# ---------------------------------------------------------------------------
# Encrypted column descriptor
# ---------------------------------------------------------------------------

class _EncryptedFieldDescriptor:
	"""
	Non-data descriptor that intercepts attribute access on ``EncryptionMixin``
	subclasses for registered encrypted field names.

	On **get**: returns the in-memory plaintext cache if populated; otherwise
	returns the sentinel ``_MISSING`` so callers know decryption has not yet
	occurred.

	On **set**: stores the value in the per-instance plaintext cache and marks
	the instance as dirty for that field.  Actual encryption happens in the
	SQLAlchemy ``before_insert`` / ``before_update`` event listeners.
	"""

	def __init__(self, field_name: str) -> None:
		self._field = field_name
		self._cache_attr = f"_enc_plain_{field_name}"
		self._dirty_attr = f"_enc_dirty_{field_name}"

	def __set_name__(self, owner: type, name: str) -> None:
		self._attr_name = name

	def __get__(self, obj: Any, objtype: type | None = None) -> Any:
		if obj is None:
			return self
		return getattr(obj, self._cache_attr, _MISSING)

	def __set__(self, obj: Any, value: Any) -> None:
		setattr(obj, self._cache_attr, value)
		setattr(obj, self._dirty_attr, True)


# ---------------------------------------------------------------------------
# Core Mixin
# ---------------------------------------------------------------------------

class EncryptionMixin:
	"""
	Column-level encryption mixin for PgForge / SQLAlchemy models,
	backed by PostgreSQL pgcrypto.

	Overview
	--------
	- Designated fields (``__encrypted_fields__``) are stored as pgcrypto
	  ciphertext in ``TEXT`` columns named ``<field>_enc``.
	- Plaintext is never persisted to the Python-side model attribute or
	  the unencrypted column; it lives only in the in-memory cache and in the
	  pgcrypto-encrypted database column.
	- ``set_encrypted(field, value)`` / ``get_decrypted(field)`` are the
	  primary write/read APIs.  They emit ``pgp_sym_encrypt`` / ``pgp_sym_decrypt``
	  SQL against the live session connection.
	- Deterministic fields store an HMAC-SHA256 token in a ``<field>_hmac``
	  ``TEXT`` column, enabling ``WHERE`` equality searches without revealing
	  plaintext.
	- ``rotate_keys(session)`` re-encrypts every row with the current active
	  key version.
	- Access policies (``__encryption_access_policy__``) allow per-field
	  read/write control via a callable predicate.
	- An ``_enc_audit`` JSONB column records every encrypt/decrypt event when
	  ``__encryption_audit__`` is ``True``.

	Class-level configuration attributes
	-------------------------------------
	``__encrypted_fields__`` : list[str]
		Field names to encrypt.  Each field ``foo`` gets a ``foo_enc`` TEXT
		column and optionally a ``foo_hmac`` TEXT column.

	``__deterministic_fields__`` : list[str]
		Subset of ``__encrypted_fields__`` where HMAC tokens are stored for
		equality search.  Values must be equal-comparison safe (e.g. SSNs,
		emails — NOT free-form text).

	``__encryption_key__`` : str | None
		Single-version passphrase shorthand.  When set, automatically
		populates ``__key_ring__`` at version 1.  Prefer ``__key_ring__``
		for production.

	``__key_ring__`` : KeyRing | None
		Pre-configured ``KeyRing`` instance.  Takes precedence over
		``__encryption_key__``.

	``__pgp_cipher_options__`` : str
		pgcrypto cipher options string (default: ``"cipher-algo=aes256"``).

	``__encryption_audit__`` : bool
		When ``True`` (default ``False``), persist audit records to
		``_enc_audit`` JSONB column.

	``__encryption_access_policy__`` : dict[str, Callable[[str, str], bool]]
		``{field_name: callable(field_name, "read"|"write") -> bool}``
		Raise ``PermissionError`` when the callable returns ``False``.

	``__encryption_nullable__`` : bool
		When ``True`` (default), ``NULL`` plaintext is stored as ``NULL``
		ciphertext without error.

	``__pbkdf2_salt__`` : bytes | None
		Static PBKDF2 salt.  If ``None``, a random 16-byte salt is generated
		once per class and stored in ``_enc_pbkdf2_salt``; that value is
		persisted in the ``_enc_key_salt`` column so decryption is
		reproducible across restarts.

	``__pbkdf2_iterations__`` : int
		PBKDF2 iteration count (default: 200 000).  Lower only for testing.

	Columns added (via ``declared_attr``)
	--------------------------------------
	For each field ``foo`` in ``__encrypted_fields__``:
		- ``foo_enc``  — TEXT, nullable, stores pgcrypto ciphertext
		- ``foo_hmac`` — TEXT, nullable, HMAC token (deterministic fields only)

	Always added:
		- ``_enc_key_version`` — INTEGER, active key version used to encrypt row
		- ``_enc_key_salt``    — TEXT, hex-encoded PBKDF2 salt for this row
		- ``_enc_updated_at``  — TIMESTAMP WITH TIME ZONE, last encrypt timestamp
		- ``_enc_audit``       — JSONB, audit log (present when __encryption_audit__)

	Indexes
	-------
	- BTREE on ``_enc_key_version`` for rotation queries
	- BTREE on each ``foo_hmac`` column for deterministic equality searches
	"""

	# ------------------------------------------------------------------
	# Class-level configuration knobs
	# ------------------------------------------------------------------
	__encrypted_fields__: list[str] = []
	__deterministic_fields__: list[str] = []
	__encryption_key__: str | None = None
	__key_ring__: KeyRing | None = None
	__pgp_cipher_options__: str = _DEFAULT_PGP_OPTIONS
	__encryption_audit__: bool = False
	__encryption_access_policy__: dict[str, Callable[[str, str], bool]] = {}
	__encryption_nullable__: bool = True
	__pbkdf2_salt__: bytes | None = None
	__pbkdf2_iterations__: int = 200_000

	# ------------------------------------------------------------------
	# Internal: key ring bootstrapping
	# ------------------------------------------------------------------

	@classmethod
	def _get_key_ring(cls) -> KeyRing:
		"""
		Return the effective KeyRing for this class.

		Priority: ``__key_ring__`` > single ``__encryption_key__`` > error.
		"""
		if cls.__key_ring__ is not None:
			return cls.__key_ring__
		if cls.__encryption_key__:
			ring = KeyRing()
			ring.add_key(1, cls.__encryption_key__)
			# Cache so we don't reconstruct on every call
			cls.__key_ring__ = ring
			return ring
		raise RuntimeError(
			f"{cls.__name__}: set __encryption_key__ or __key_ring__ before using encryption"
		)

	@classmethod
	def _get_active_passphrase(cls) -> tuple[int, str]:
		"""Return (version, raw_passphrase) for the active key."""
		return cls._get_key_ring().get_active()

	@classmethod
	def _passphrase_for_version(cls, version: int) -> str:
		"""Return raw passphrase for *version*."""
		return cls._get_key_ring().get(version)

	# ------------------------------------------------------------------
	# Columns (declared_attr so SQLAlchemy maps them per concrete class)
	# ------------------------------------------------------------------

	@declared_attr
	def _enc_key_version(cls):
		"""Active key version used to encrypt this row."""
		if _SA2:
			return mapped_column(
				Integer,
				nullable=False,
				default=1,
				index=True,
				comment="pgcrypto key version used to encrypt this row",
			)
		return Column(
			"_enc_key_version",
			Integer,
			nullable=False,
			default=1,
			index=True,
			comment="pgcrypto key version used to encrypt this row",
		)

	@declared_attr
	def _enc_key_salt(cls):
		"""Hex-encoded PBKDF2 salt specific to this row."""
		if _SA2:
			return mapped_column(
				Text,
				nullable=True,
				comment="Hex-encoded PBKDF2 salt used during key derivation for this row",
			)
		return Column(
			"_enc_key_salt",
			Text,
			nullable=True,
			comment="Hex-encoded PBKDF2 salt for this row",
		)

	@declared_attr
	def _enc_updated_at(cls):
		"""Timestamp of last encrypt/re-encrypt operation."""
		if _SA2:
			return mapped_column(
				DateTime(timezone=True),
				nullable=True,
				comment="Timestamp of last encryption operation on this row",
			)
		return Column(
			"_enc_updated_at",
			DateTime(timezone=True),
			nullable=True,
			comment="Timestamp of last encryption operation on this row",
		)

	@declared_attr
	def _enc_audit(cls):
		"""JSONB audit log of encrypt/decrypt events (only populated when __encryption_audit__ is True)."""
		if _SA2:
			return mapped_column(
				MutableList.as_mutable(JSONB),
				nullable=True,
				comment="Audit log of encryption/decryption events",
			)
		return Column(
			"_enc_audit",
			MutableList.as_mutable(JSONB),
			nullable=True,
			comment="Audit log of encryption/decryption events",
		)

	# ------------------------------------------------------------------
	# Per-field column factory (called once per field per class at class creation)
	# ------------------------------------------------------------------

	@classmethod
	def _make_enc_columns(cls) -> dict[str, Any]:
		"""
		Build ``{column_name: Column}`` for every field in ``__encrypted_fields__``.

		Returns a dict of column name -> Column that the concrete subclass
		should merge into its ``__table_args__`` or be injected via the
		``__init_subclass__`` hook.
		"""
		cols: dict[str, Any] = {}
		for field in cls.__encrypted_fields__:
			enc_col_name = f"{field}_enc"
			cols[enc_col_name] = Column(
				enc_col_name,
				Text,
				nullable=True,
				comment=f"pgcrypto ciphertext for field '{field}'",
			)
			if field in cls.__deterministic_fields__:
				hmac_col_name = f"{field}_hmac"
				cols[hmac_col_name] = Column(
					hmac_col_name,
					Text,
					nullable=True,
					index=True,  # BTREE; enables WHERE foo_hmac = :token
					comment=f"HMAC-SHA256 token for deterministic search on '{field}'",
				)
		return cols

	# ------------------------------------------------------------------
	# __init_subclass__: inject per-field columns automatically
	# ------------------------------------------------------------------

	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)
		# Only inject if the subclass declares __encrypted_fields__ directly
		# and has a __tablename__ (i.e. is a concrete mapped class, not another mixin)
		if not getattr(cls, "__tablename__", None):
			return
		for col_name, col_obj in cls._make_enc_columns().items():
			if not hasattr(cls, col_name):
				setattr(cls, col_name, col_obj)

	# ------------------------------------------------------------------
	# Salt management
	# ------------------------------------------------------------------

	def _ensure_salt(self) -> bytes:
		"""
		Return the PBKDF2 salt for this instance, generating and persisting a
		fresh one if none exists yet.
		"""
		if self.__class__.__pbkdf2_salt__ is not None:
			# Class-level static salt (dev/test only)
			return self.__class__.__pbkdf2_salt__

		if self._enc_key_salt:
			return bytes.fromhex(self._enc_key_salt)

		salt = os.urandom(16)
		self._enc_key_salt = salt.hex()
		return salt

	# ------------------------------------------------------------------
	# Access policy enforcement
	# ------------------------------------------------------------------

	def _check_access(self, field: str, mode: str) -> None:
		"""
		Enforce ``__encryption_access_policy__``.

		Args:
			field: encrypted field name
			mode:  ``"read"`` or ``"write"``

		Raises:
			PermissionError: policy callable returns ``False``.
		"""
		policy = self.__encryption_access_policy__.get(field)
		if policy is not None and not policy(field, mode):
			raise PermissionError(
				f"Access denied: {mode} on encrypted field '{field}' "
				f"for {type(self).__name__}"
			)

	# ------------------------------------------------------------------
	# Primary write API
	# ------------------------------------------------------------------

	def set_encrypted(self, field: str, value: str | None) -> None:
		"""
		Stage *value* for encryption into the ``<field>_enc`` column.

		Encryption is performed lazily during the SQLAlchemy ``before_insert``
		or ``before_update`` event.  This method only caches the plaintext
		in memory and marks the field dirty.

		Args:
			field: Name of an ``__encrypted_fields__`` member.
			value: Plaintext to encrypt, or ``None``.

		Raises:
			ValueError:      field not in ``__encrypted_fields__``.
			ValueError:      value is ``None`` and ``__encryption_nullable__`` is ``False``.
			PermissionError: access policy denies write.
		"""
		if field not in self.__encrypted_fields__:
			raise ValueError(
				f"'{field}' is not an encrypted field. "
				f"Add it to {type(self).__name__}.__encrypted_fields__"
			)
		if value is None and not self.__encryption_nullable__:
			raise ValueError(f"Encrypted field '{field}' does not accept NULL")
		self._check_access(field, "write")
		setattr(self, f"_enc_plain_{field}", value)
		setattr(self, f"_enc_dirty_{field}", True)

	def set_many_encrypted(self, **kwargs: str | None) -> None:
		"""Set multiple encrypted fields in one call.

		Args:
			**kwargs: field=plaintext pairs.

		Raises:
			ValueError: any field not registered.
		"""
		for field, value in kwargs.items():
			self.set_encrypted(field, value)

	# ------------------------------------------------------------------
	# Primary read API
	# ------------------------------------------------------------------

	def get_decrypted(self, field: str, *, session: Any = None) -> str | None:
		"""
		Decrypt and return the plaintext for *field*.

		The decrypted value is cached in-memory after the first call.
		Subsequent calls within the same instance lifetime return the cache.

		Args:
			field:   Name of an ``__encrypted_fields__`` member.
			session: SQLAlchemy session.  If ``None``, resolved via Flask app context.

		Returns:
			Decrypted plaintext string, or ``None`` if the ciphertext is NULL.

		Raises:
			ValueError:      field not in ``__encrypted_fields__``.
			PermissionError: access policy denies read.
			RuntimeError:    decryption fails (wrong key version, corrupted data).
		"""
		if field not in self.__encrypted_fields__:
			raise ValueError(f"'{field}' is not an encrypted field")
		self._check_access(field, "read")

		cache_key = f"_enc_plain_{field}"
		cached = getattr(self, cache_key, _MISSING)
		if cached is not _MISSING:
			return cached  # type: ignore[return-value]

		ciphertext_col = f"{field}_enc"
		ciphertext = getattr(self, ciphertext_col, None)
		if ciphertext is None:
			return None

		key_version = self._enc_key_version or 1
		salt = bytes.fromhex(self._enc_key_salt) if self._enc_key_salt else b""
		passphrase = self._passphrase_for_version(key_version)
		derived = _derive_key(passphrase, salt, self.__pbkdf2_iterations__)

		sess = session or _get_session()
		try:
			row = sess.execute(
				text("SELECT pgp_sym_decrypt(:ciphertext::bytea, :key)"),
				{"ciphertext": ciphertext, "key": derived},
			).one()
			plaintext: str | None = row[0]
		except Exception as exc:
			_log.error(
				"Decryption failed for %s.%s (key_version=%d): %s",
				type(self).__name__, field, key_version, exc,
			)
			raise RuntimeError(
				f"Failed to decrypt field '{field}' on {type(self).__name__}: {exc}"
			) from exc

		setattr(self, cache_key, plaintext)

		if self.__encryption_audit__:
			self._record_audit_event("decrypt", field, key_version)

		return plaintext

	def get_many_decrypted(self, *fields: str, session: Any = None) -> dict[str, str | None]:
		"""Decrypt multiple fields, returning a ``{field: plaintext}`` dict."""
		return {f: self.get_decrypted(f, session=session) for f in fields}

	# ------------------------------------------------------------------
	# Internal: flush plaintext to ciphertext columns
	# ------------------------------------------------------------------

	def _flush_encrypted_fields(self, session: Any | None = None) -> None:
		"""
		Encrypt all dirty plaintext caches into their ``<field>_enc`` columns.

		Called by the ``before_insert`` and ``before_update`` event listeners.
		Idempotent: fields not marked dirty are skipped.
		"""
		if not self.__encrypted_fields__:
			return

		active_version, passphrase = self._get_active_passphrase()
		salt = self._ensure_salt()
		derived = _derive_key(passphrase, salt, self.__pbkdf2_iterations__)

		sess = session or _get_session()
		any_dirty = False

		for field in self.__encrypted_fields__:
			dirty_flag = f"_enc_dirty_{field}"
			if not getattr(self, dirty_flag, False):
				continue

			plaintext = getattr(self, f"_enc_plain_{field}", None)

			if plaintext is None:
				setattr(self, f"{field}_enc", None)
				if field in self.__deterministic_fields__:
					setattr(self, f"{field}_hmac", None)
			else:
				try:
					row = sess.execute(
						text(
							"SELECT pgp_sym_encrypt(:plaintext, :key, :options)"
						),
						{
							"plaintext": plaintext,
							"key": derived,
							"options": self.__pgp_cipher_options__,
						},
					).one()
					ciphertext = row[0]
				except Exception as exc:
					_log.error(
						"Encryption failed for %s.%s: %s",
						type(self).__name__, field, exc,
					)
					raise RuntimeError(
						f"Failed to encrypt field '{field}' on {type(self).__name__}: {exc}"
					) from exc

				setattr(self, f"{field}_enc", ciphertext)

				if field in self.__deterministic_fields__:
					token = _hmac_token(plaintext, derived)
					setattr(self, f"{field}_hmac", token)

			setattr(self, dirty_flag, False)
			any_dirty = True

		if any_dirty:
			self._enc_key_version = active_version
			self._enc_updated_at = _utcnow()
			if self.__encryption_audit__:
				self._record_audit_event("encrypt", ",".join(self.__encrypted_fields__), active_version)

	# ------------------------------------------------------------------
	# Key rotation
	# ------------------------------------------------------------------

	@classmethod
	def rotate_keys(
		cls,
		session: Any,
		*,
		batch_size: int = 100,
		target_version: int | None = None,
	) -> int:
		"""
		Re-encrypt every row that is not yet on the current (or *target_version*) key.

		The operation is performed in batches of *batch_size* rows.  Each batch
		is committed independently so the table remains accessible during rotation.

		Args:
			session:        Active SQLAlchemy session.
			batch_size:     Rows processed per transaction.
			target_version: Key version to rotate to.  Defaults to the active version.

		Returns:
			Total number of rows re-encrypted.

		Raises:
			RuntimeError: KeyRing is not configured or rotation fails.
		"""
		ring = cls._get_key_ring()
		dest_version, dest_passphrase = (
			(target_version, ring.get(target_version))
			if target_version is not None
			else ring.get_active()
		)

		stmt = select(cls).where(cls._enc_key_version != dest_version)
		rows = session.execute(stmt).scalars().all()

		total = 0
		for i in range(0, len(rows), batch_size):
			chunk = rows[i : i + batch_size]
			for obj in chunk:
				try:
					obj._rotate_row(session, dest_version, dest_passphrase)
					total += 1
				except Exception as exc:
					pk = getattr(obj, "id", "?")
					_log.error("Key rotation failed for %s pk=%s: %s", cls.__name__, pk, exc)
			try:
				session.flush()
				session.commit()
			except Exception as exc:
				session.rollback()
				raise RuntimeError(f"Key rotation batch commit failed: {exc}") from exc

		_log.info("Rotated %d %s row(s) to key version %d", total, cls.__name__, dest_version)
		return total

	def _rotate_row(self, session: Any, dest_version: int, dest_passphrase: str) -> None:
		"""
		Re-encrypt this single row from its current key to *dest_version*.

		Decrypts with the current row key, re-encrypts with *dest_passphrase*,
		stores new ciphertext, and updates ``_enc_key_version``.
		"""
		src_version = self._enc_key_version or 1
		if src_version == dest_version:
			return  # already on target

		salt = bytes.fromhex(self._enc_key_salt) if self._enc_key_salt else b""

		src_passphrase = self._passphrase_for_version(src_version)
		src_derived = _derive_key(src_passphrase, salt, self.__pbkdf2_iterations__)
		dest_derived = _derive_key(dest_passphrase, salt, self.__pbkdf2_iterations__)

		for field in self.__encrypted_fields__:
			ciphertext = getattr(self, f"{field}_enc", None)
			if ciphertext is None:
				continue

			# Decrypt with old key
			try:
				row = session.execute(
					text("SELECT pgp_sym_decrypt(:ct::bytea, :key)"),
					{"ct": ciphertext, "key": src_derived},
				).one()
				plaintext: str | None = row[0]
			except Exception as exc:
				raise RuntimeError(
					f"Rotation decrypt failed for field '{field}': {exc}"
				) from exc

			if plaintext is None:
				continue

			# Re-encrypt with new key
			try:
				row2 = session.execute(
					text("SELECT pgp_sym_encrypt(:pt, :key, :opts)"),
					{
						"pt": plaintext,
						"key": dest_derived,
						"opts": self.__pgp_cipher_options__,
					},
				).one()
				setattr(self, f"{field}_enc", row2[0])
			except Exception as exc:
				raise RuntimeError(
					f"Rotation re-encrypt failed for field '{field}': {exc}"
				) from exc

			if field in self.__deterministic_fields__:
				setattr(self, f"{field}_hmac", _hmac_token(plaintext, dest_derived))

			# Invalidate plaintext cache to force fresh decrypt on next access
			cache_key = f"_enc_plain_{field}"
			if hasattr(self, cache_key):
				delattr(self, cache_key)

		self._enc_key_version = dest_version
		self._enc_updated_at = _utcnow()

	# ------------------------------------------------------------------
	# Deterministic search helpers
	# ------------------------------------------------------------------

	@classmethod
	def search_by_encrypted(cls, session: Any, field: str, plaintext: str):
		"""
		Find rows where the deterministic HMAC token matches *plaintext*.

		Only works for fields in ``__deterministic_fields__``.

		Args:
			session:   Active SQLAlchemy session.
			field:     Encrypted field name (must be deterministic).
			plaintext: Value to search for.

		Returns:
			``ScalarResult`` of matching model instances.

		Raises:
			ValueError: field is not deterministic.
			RuntimeError: KeyRing not configured.
		"""
		if field not in cls.__deterministic_fields__:
			raise ValueError(
				f"'{field}' is not in {cls.__name__}.__deterministic_fields__. "
				"Only deterministic fields support equality search."
			)
		# Derive token using the active key — assumes all searchable rows
		# have been rotated to the current key version.
		_, passphrase = cls._get_active_passphrase()
		# Use a zero-length salt for the token search: HMAC is over the derived key
		# which itself incorporates the per-row salt, but for search we need a
		# consistent token per plaintext+key pair.  We use the passphrase directly
		# so that after rotation (same passphrase, new version int) the HMAC is stable.
		token = _hmac_token(plaintext, passphrase)
		hmac_col = getattr(cls, f"{field}_hmac")
		stmt = select(cls).where(hmac_col == token)
		return session.execute(stmt).scalars()

	# ------------------------------------------------------------------
	# Introspection helpers
	# ------------------------------------------------------------------

	@classmethod
	def get_encryption_status(cls, session: Any) -> dict[str, Any]:
		"""
		Return a summary of encryption coverage across all rows.

		Returns::

			{
			    "model":          str,
			    "encrypted_fields": list[str],
			    "deterministic_fields": list[str],
			    "active_key_version": int,
			    "key_versions_in_use": list[int],
			    "rows_per_version": dict[int, int],
			    "rows_needing_rotation": int,
			    "total_rows": int,
			}
		"""
		ring = cls._get_key_ring()
		active_version = ring.active_version

		from sqlalchemy import func as _func
		version_counts_stmt = (
			select(cls._enc_key_version, _func.count())
			.select_from(cls)
			.group_by(cls._enc_key_version)
		)
		rows_per_version: dict[int, int] = {
			int(v): int(c)
			for v, c in session.execute(version_counts_stmt).all()
		}

		total = sum(rows_per_version.values())
		current_count = rows_per_version.get(active_version, 0)

		return {
			"model": cls.__name__,
			"encrypted_fields": list(cls.__encrypted_fields__),
			"deterministic_fields": list(cls.__deterministic_fields__),
			"active_key_version": active_version,
			"key_versions_in_use": sorted(rows_per_version.keys()),
			"rows_per_version": rows_per_version,
			"rows_needing_rotation": total - current_count,
			"total_rows": total,
		}

	def is_field_encrypted(self, field: str) -> bool:
		"""Return ``True`` if the ``<field>_enc`` column contains a non-NULL value."""
		if field not in self.__encrypted_fields__:
			return False
		return getattr(self, f"{field}_enc", None) is not None

	def clear_decrypted_cache(self, *fields: str) -> None:
		"""
		Evict in-memory plaintext cache for *fields* (all encrypted fields if none given).

		Use after committing a row to avoid stale plaintext surviving across
		unit-of-work boundaries.
		"""
		targets = fields if fields else self.__encrypted_fields__
		for field in targets:
			cache_key = f"_enc_plain_{field}"
			if hasattr(self, cache_key):
				delattr(self, cache_key)

	# ------------------------------------------------------------------
	# Audit logging
	# ------------------------------------------------------------------

	def _record_audit_event(self, operation: str, field: str, key_version: int) -> None:
		"""Append an audit record to ``_enc_audit`` JSONB list."""
		if self._enc_audit is None:
			self._enc_audit = []
		event_record: dict[str, Any] = {
			"op": operation,
			"field": field,
			"key_version": key_version,
			"ts": _utcnow().isoformat(),
		}
		self._enc_audit.append(event_record)

	def get_audit_log(self, *, field: str | None = None, operation: str | None = None) -> list[dict[str, Any]]:
		"""
		Return filtered audit events from ``_enc_audit``.

		Args:
			field:     Filter by encrypted field name.
			operation: Filter by operation type (``"encrypt"`` or ``"decrypt"``).

		Returns:
			List of matching audit event dicts in insertion order.
		"""
		if not self._enc_audit:
			return []
		records = list(self._enc_audit)
		if field is not None:
			records = [r for r in records if r.get("field") == field]
		if operation is not None:
			records = [r for r in records if r.get("op") == operation]
		return records

	def clear_audit_log(self) -> None:
		"""Truncate the in-memory (and next-flush) ``_enc_audit`` list."""
		self._enc_audit = []


# ---------------------------------------------------------------------------
# SQLAlchemy event listeners — encrypt on write
# ---------------------------------------------------------------------------

@event.listens_for(EncryptionMixin, "before_insert", propagate=True)
def _encrypt_before_insert(mapper: Any, connection: Any, target: EncryptionMixin) -> None:
	"""Flush dirty plaintext caches to pgcrypto ciphertext before INSERT."""
	if not target.__encrypted_fields__:
		return
	try:
		# For INSERT we need a bound session; use the connection's engine session
		from sqlalchemy.orm import Session
		sess = Session.object_session(target) or _get_session()
		target._flush_encrypted_fields(sess)
	except Exception as exc:
		_log.error(
			"before_insert encryption error on %s: %s",
			type(target).__name__, exc,
		)
		raise


@event.listens_for(EncryptionMixin, "before_update", propagate=True)
def _encrypt_before_update(mapper: Any, connection: Any, target: EncryptionMixin) -> None:
	"""Flush dirty plaintext caches to pgcrypto ciphertext before UPDATE."""
	if not target.__encrypted_fields__:
		return
	# Only process fields that are marked dirty to avoid unnecessary re-encryption
	any_dirty = any(
		getattr(target, f"_enc_dirty_{f}", False)
		for f in target.__encrypted_fields__
	)
	if not any_dirty:
		return
	try:
		from sqlalchemy.orm import Session
		sess = Session.object_session(target) or _get_session()
		target._flush_encrypted_fields(sess)
	except Exception as exc:
		_log.error(
			"before_update encryption error on %s: %s",
			type(target).__name__, exc,
		)
		raise


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
	"EncryptionMixin",
	"KeyRing",
]
