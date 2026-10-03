"""Startup security assertions for a PgAppForge app.

Called from the app factory once the app object exists but before it serves a
request. These are configuration footguns, not attack paths: each one is a
setting whose default is safe but whose override is not, so failing at boot is
cheaper than discovering it in an incident.

Import and call :func:`assert_secure_config`; nothing here runs on import.
"""
from __future__ import annotations

import logging
import os

from flask import Flask

log = logging.getLogger(__name__)

# Matches the placeholder in pgappforge/config_example_enhanced.py. Copying the
# example config verbatim is the single most common deployment mistake.
PLACEHOLDER_SECRET_KEY = "your-secret-key-change-this-in-production"

MIN_SECRET_KEY_LENGTH = 20

# Values accepted as truthy for a boolean-ish config flag. Read from config,
# where the value may still be a string ("false" is truthy in Python).
_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})


class InsecureConfigurationError(RuntimeError):
	"""Raised when the app configuration is unsafe to run."""


def _is_truthy(value: object) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in _TRUTHY
	return bool(value)


def _is_production(app: Flask) -> bool:
	"""True when the app declares itself a production environment."""
	for key in ("ENV", "FLASK_ENV"):
		if str(app.config.get(key, "")).strip().lower() == "production":
			return True
	env = os.environ.get("ENV") or os.environ.get("FLASK_ENV")
	return bool(env) and env.strip().lower() == "production"


def assert_secure_config(app: Flask) -> None:
	"""Validate security-critical configuration, raising on anything unsafe.

	Raises:
		InsecureConfigurationError: on a missing, placeholder or weak
			SECRET_KEY, or on plugin security explicitly disabled in production.
	"""
	assert app is not None, "assert_secure_config() requires an app"

	secret_key = app.config.get("SECRET_KEY")
	if not secret_key:
		raise InsecureConfigurationError(
			"SECRET_KEY is not set. Flask sessions are signed with it; without "
			"it every session is forgeable."
		)
	if not isinstance(secret_key, str):
		raise InsecureConfigurationError(
			f"SECRET_KEY must be a string, got {type(secret_key).__name__}."
		)
	if secret_key == PLACEHOLDER_SECRET_KEY:
		raise InsecureConfigurationError(
			"SECRET_KEY is still the placeholder from "
			"config_example_enhanced.py. Set a unique random value of at "
			"least 20 characters."
		)
	if len(secret_key) < MIN_SECRET_KEY_LENGTH:
		raise InsecureConfigurationError(
			f"SECRET_KEY is {len(secret_key)} characters; "
			f"at least {MIN_SECRET_KEY_LENGTH} are required."
		)

	# Mirrors the check in base.py -- not moved, not replaced. base.py raises on
	# ENV == 'production'; this widens the net to FLASK_ENV and the environment
	# variables, since all three spellings reach Flask deployments in the wild.
	if app.config.get("PGAF_PLUGIN_SECURITY_STRICT") is False and _is_production(app):
		raise InsecureConfigurationError(
			"PGAF_PLUGIN_SECURITY_STRICT=False in a production environment. "
			"Set it to True or remove the setting."
		)

	# Not fatal: this leaks tracebacks rather than breaking correctness, so it is
	# logged at CRITICAL instead. Logging still happens outside debug, which is
	# the case worth shouting about -- debug off in production is the normal
	# configuration, so the flag alone is the thing that is wrong.
	if _is_truthy(app.config.get("PGAF_API_SHOW_STACKTRACE")) and not app.debug:
		log.critical(
			"PGAF_API_SHOW_STACKTRACE is enabled outside debug mode. API error "
			"responses will include tracebacks with file paths and query "
			"fragments. Unset it for any non-development deployment."
		)


__all__ = ["assert_secure_config", "InsecureConfigurationError"]