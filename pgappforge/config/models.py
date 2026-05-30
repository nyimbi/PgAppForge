from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge import Model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in defaults — 15+ sensible application settings across 4 categories
# ---------------------------------------------------------------------------

BUILT_IN_DEFAULTS: dict[str, dict[str, Any]] = {
	# appearance
	"APP_TITLE": {
		"value": "My Application",
		"category": "appearance",
		"label": "Application Title",
		"description": "Displayed in the browser tab and top navbar.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"APP_DESCRIPTION": {
		"value": "Powered by PgAppForge",
		"category": "appearance",
		"label": "Application Description",
		"description": "Short tagline shown on the login page.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"APP_LOGO_URL": {
		"value": "/static/appbuilder/img/logo.png",
		"category": "appearance",
		"label": "Logo URL",
		"description": "Absolute or relative URL to the application logo image.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"APP_THEME": {
		"value": "default",
		"category": "appearance",
		"label": "UI Theme",
		"description": "Bootstrap Bootswatch theme name (e.g. cosmo, flatly, darkly).",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"APP_PRIMARY_COLOR": {
		"value": "#3498db",
		"category": "appearance",
		"label": "Primary Color",
		"description": "Hex color used for primary action buttons and highlights.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"APP_SECONDARY_COLOR": {
		"value": "#2ecc71",
		"category": "appearance",
		"label": "Secondary Color",
		"description": "Hex color used for secondary UI elements.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	# security
	"SECURITY_SESSION_TIMEOUT": {
		"value": 3600,
		"category": "security",
		"label": "Session Timeout (seconds)",
		"description": "Idle time in seconds before an authenticated session expires.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"SECURITY_MAX_FAILED_LOGINS": {
		"value": 5,
		"category": "security",
		"label": "Max Failed Login Attempts",
		"description": "Account locked after this many consecutive failed attempts.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"SECURITY_PASSWORD_MIN_LENGTH": {
		"value": 8,
		"category": "security",
		"label": "Minimum Password Length",
		"description": "Minimum number of characters required for passwords.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"SECURITY_MFA_ENABLED": {
		"value": False,
		"category": "security",
		"label": "Enable MFA",
		"description": "Require multi-factor authentication for all users.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	# features
	"FEATURES_OFFLINE_MODE": {
		"value": False,
		"category": "features",
		"label": "Offline Mode",
		"description": "Cache assets for offline use via service worker.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"FEATURES_VOICE_INPUT": {
		"value": False,
		"category": "features",
		"label": "Voice Input",
		"description": "Enable speech-to-text in supported form fields.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"FEATURES_DARK_MODE": {
		"value": False,
		"category": "features",
		"label": "Dark Mode",
		"description": "Apply a dark colour scheme globally.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"FEATURES_ANIMATIONS": {
		"value": True,
		"category": "features",
		"label": "UI Animations",
		"description": "Enable transition animations between views.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"FEATURES_EXPORT_CSV": {
		"value": True,
		"category": "features",
		"label": "CSV Export",
		"description": "Allow users to export list views as CSV.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	# email
	"EMAIL_FROM_ADDRESS": {
		"value": "noreply@example.com",
		"category": "email",
		"label": "From Address",
		"description": "Sender address used for all outbound application email.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"EMAIL_SUPPORT_ADDRESS": {
		"value": "support@example.com",
		"category": "email",
		"label": "Support Address",
		"description": "Address surfaced to users for help requests.",
		"is_sensitive": False,
		"is_readonly": False,
	},
	"EMAIL_SMTP_PORT": {
		"value": 587,
		"category": "email",
		"label": "SMTP Port",
		"description": "Port for outbound SMTP connections (typically 25, 465, or 587).",
		"is_sensitive": False,
		"is_readonly": False,
	},
}


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class AppConfig(Model):
	"""
	Persistent key/value configuration store.

	Values are typed JSON (JSONB on PostgreSQL) so the same column can hold a
	string, integer, boolean, list, or dict without a schema migration when the
	application adds a new setting.
	"""

	__tablename__ = "app_config"
	__allow_unmapped__ = True

	__table_args__ = (
		Index("ix_app_config_category", "category"),
		Index(
			"ix_app_config_key_gin",
			"key",
			postgresql_using="gin",
			postgresql_ops={"key": "gin_trgm_ops"},
		),
	)

	id = Column(
		String(36),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	key = Column(String(128), unique=True, nullable=False, index=True)
	value = Column(JSONB, nullable=False)
	category = Column(String(64), nullable=False, default="general")
	label = Column(String(256), nullable=True)
	description = Column(Text, nullable=True)
	is_sensitive = Column(Boolean, nullable=False, default=False)
	is_readonly = Column(Boolean, nullable=False, default=False)
	created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
	updated_at = Column(
		DateTime,
		nullable=False,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)

	def __repr__(self) -> str:
		return f"<AppConfig {self.key}={self.value!r}>"

	def display_value(self) -> Any:
		"""Return masked value for sensitive keys, raw value otherwise."""
		if self.is_sensitive:
			return "••••••••"
		return self.value


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class AppConfigManager:
	"""
	Thin service layer over AppConfig.

	Usage::

		mgr = AppConfigManager(db.session)
		mgr.set("APP_TITLE", "Acme Portal", category="appearance")
		title = mgr.get("APP_TITLE", default="Untitled")
	"""

	def __init__(self, session: Any) -> None:
		self._session = session

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def get(self, key: str, default: Any = None) -> Any:
		"""Return the stored value for *key*, or *default* if absent."""
		row = self._session.query(AppConfig).filter_by(key=key).one_or_none()
		if row is None:
			return default
		return row.value

	def set(
		self,
		key: str,
		value: Any,
		*,
		category: str = "general",
		label: str | None = None,
		description: str | None = None,
		is_sensitive: bool = False,
		is_readonly: bool = False,
	) -> None:
		"""
		Upsert *key* with *value*.  A readonly entry raises ValueError on
		subsequent writes (initial write is always permitted).
		"""
		row = self._session.query(AppConfig).filter_by(key=key).one_or_none()
		if row is not None:
			if row.is_readonly:
				raise ValueError(
					f"Config key {key!r} is read-only and cannot be changed at runtime."
				)
			row.value = value
			row.updated_at = datetime.utcnow()
			if label is not None:
				row.label = label
			if description is not None:
				row.description = description
		else:
			row = AppConfig(
				key=key,
				value=value,
				category=category,
				label=label,
				description=description,
				is_sensitive=is_sensitive,
				is_readonly=is_readonly,
			)
			self._session.add(row)

		try:
			self._session.commit()
		except Exception:
			self._session.rollback()
			raise

	def get_category(self, category: str) -> dict[str, Any]:
		"""Return {key: value} mapping for every entry in *category*."""
		rows = (
			self._session.query(AppConfig)
			.filter_by(category=category)
			.order_by(AppConfig.key)
			.all()
		)
		return {r.key: r.value for r in rows}

	def bulk_set(self, config_dict: dict[str, Any], *, category: str = "general") -> None:
		"""
		Upsert multiple keys in a single transaction.

		*config_dict* values may be plain values *or* dicts with the keys
		``value``, ``category``, ``label``, ``description``, ``is_sensitive``,
		``is_readonly`` for richer metadata.
		"""
		try:
			for key, payload in config_dict.items():
				if isinstance(payload, dict) and "value" in payload:
					cat = payload.get("category", category)
					label = payload.get("label")
					description = payload.get("description")
					is_sensitive = bool(payload.get("is_sensitive", False))
					is_readonly = bool(payload.get("is_readonly", False))
					val = payload["value"]
				else:
					cat = category
					label = None
					description = None
					is_sensitive = False
					is_readonly = False
					val = payload

				row = self._session.query(AppConfig).filter_by(key=key).one_or_none()
				if row is not None:
					if row.is_readonly:
						continue
					row.value = val
					row.updated_at = datetime.utcnow()
					if label is not None:
						row.label = label
					if description is not None:
						row.description = description
				else:
					row = AppConfig(
						key=key,
						value=val,
						category=cat,
						label=label,
						description=description,
						is_sensitive=is_sensitive,
						is_readonly=is_readonly,
					)
					self._session.add(row)

			self._session.commit()
		except Exception:
			self._session.rollback()
			raise

	def reset_to_defaults(self) -> None:
		"""
		Seed the database with BUILT_IN_DEFAULTS.  Existing non-readonly entries
		are overwritten; readonly entries are left unchanged.
		"""
		self.bulk_set(BUILT_IN_DEFAULTS)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _all_rows(self) -> list[AppConfig]:
		return (
			self._session.query(AppConfig)
			.order_by(AppConfig.category, AppConfig.key)
			.all()
		)

	def _categories(self) -> list[str]:
		from sqlalchemy import distinct
		rows = (
			self._session.query(distinct(AppConfig.category))
			.order_by(AppConfig.category)
			.all()
		)
		return [r[0] for r in rows]
