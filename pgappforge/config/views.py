from __future__ import annotations

import json
import logging
from typing import Any

from flask import flash, redirect, request, url_for
from flask_babel import lazy_gettext as _

from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access

from .models import AppConfig, AppConfigManager, BUILT_IN_DEFAULTS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLOR_KEYS: frozenset[str] = frozenset({
	"APP_PRIMARY_COLOR",
	"APP_SECONDARY_COLOR",
})

_BOOL_KEYS: frozenset[str] = frozenset({
	"FEATURES_OFFLINE_MODE",
	"FEATURES_VOICE_INPUT",
	"FEATURES_DARK_MODE",
	"FEATURES_ANIMATIONS",
	"FEATURES_EXPORT_CSV",
	"SECURITY_MFA_ENABLED",
})

_NUMBER_KEYS: frozenset[str] = frozenset({
	"SECURITY_SESSION_TIMEOUT",
	"SECURITY_MAX_FAILED_LOGINS",
	"SECURITY_PASSWORD_MIN_LENGTH",
	"EMAIL_SMTP_PORT",
})


def _infer_input_type(key: str, value: Any) -> str:
	"""Return an HTML <input> type string appropriate for *value*."""
	if key in _COLOR_KEYS:
		return "color"
	if key in _NUMBER_KEYS or (not isinstance(value, bool) and isinstance(value, (int, float))):
		return "number"
	if key in _BOOL_KEYS or isinstance(value, bool):
		return "checkbox"
	return "text"


def _coerce_value(key: str, raw: str | None) -> Any:
	"""
	Convert the raw form string back to the correct Python type.
	Booleans come through as "on" when checked, absent when unchecked.
	"""
	if key in _BOOL_KEYS:
		return raw == "on"
	if raw is None:
		return None
	if key in _NUMBER_KEYS:
		try:
			return int(raw)
		except ValueError:
			return float(raw)
	# Attempt JSON decode for complex stored types; fall back to plain string.
	try:
		return json.loads(raw)
	except (json.JSONDecodeError, TypeError):
		return raw


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class AppConfigView(BaseView):
	"""
	Admin UI for runtime application configuration.

	Routes
	------
	GET  /app-config/                    — category index with edit links
	GET  /app-config/category/<cat>      — form for all keys in category
	POST /app-config/save                — save submitted key/value pairs
	GET  /app-config/reset               — confirm reset page
	POST /app-config/reset               — execute reset to defaults
	"""

	route_base = "/app-config"
	default_view = "index"

	# ------------------------------------------------------------------
	# Index — category summary
	# ------------------------------------------------------------------

	@expose("/", methods=("GET",))
	@has_access
	def index(self) -> str:
		"""List all categories with entry counts and edit links."""
		session = self.appbuilder.get_session
		mgr = AppConfigManager(session)

		rows = mgr._all_rows()

		# Group by category
		categories: dict[str, list[AppConfig]] = {}
		for row in rows:
			categories.setdefault(row.category, []).append(row)

		# Seed defaults if the table is empty so the UI is never blank
		if not categories:
			mgr.reset_to_defaults()
			rows = mgr._all_rows()
			for row in rows:
				categories.setdefault(row.category, []).append(row)

		return self.render_template(
			"appbuilder/config/index.html",
			categories=categories,
			title=_("Application Configuration"),
		)

	# ------------------------------------------------------------------
	# Category form — all keys in a category on one page
	# ------------------------------------------------------------------

	@expose("/category/<string:name>", methods=("GET",))
	@has_access
	def category(self, name: str) -> str:
		"""Render an inline form for every config key in *name*."""
		session = self.appbuilder.get_session
		rows: list[AppConfig] = (
			session.query(AppConfig)
			.filter_by(category=name)
			.order_by(AppConfig.key)
			.all()
		)

		# Enrich each row with its inferred input type so the template is simple
		fields = [
			{
				"row": row,
				"input_type": _infer_input_type(row.key, row.value),
			}
			for row in rows
		]

		return self.render_template(
			"appbuilder/config/category.html",
			fields=fields,
			category_name=name,
			title=_(f"Configuration — {name.title()}"),
		)

	# ------------------------------------------------------------------
	# Save — POST target for the category form
	# ------------------------------------------------------------------

	@expose("/save", methods=("POST",))
	@has_access
	def save(self) -> Any:
		"""
		Persist submitted key/value pairs from the category form.

		The form sends:
		  - hidden ``category`` field
		  - one field per config key named after the key itself
		  - checkboxes absent from POST data when unchecked
		"""
		session = self.appbuilder.get_session
		category_name = request.form.get("category", "general")

		rows: list[AppConfig] = (
			session.query(AppConfig)
			.filter_by(category=category_name)
			.order_by(AppConfig.key)
			.all()
		)

		errors: list[str] = []
		for row in rows:
			if row.is_readonly:
				continue
			raw = request.form.get(row.key)
			# Checkboxes: absent from POST when unchecked
			if _infer_input_type(row.key, row.value) == "checkbox":
				raw = request.form.get(row.key, "off")
			try:
				new_value = _coerce_value(row.key, raw)
				row.value = new_value
			except Exception as exc:
				errors.append(f"{row.key}: {exc}")

		if errors:
			for msg in errors:
				flash(msg, "danger")
		else:
			try:
				session.commit()
				flash(_("Configuration saved."), "success")
			except Exception as exc:
				session.rollback()
				log.exception("Failed to save config for category %r", category_name)
				flash(str(exc), "danger")

		return redirect(url_for("AppConfigView.category", name=category_name))

	# ------------------------------------------------------------------
	# Reset to defaults — GET shows confirm page, POST executes
	# ------------------------------------------------------------------

	@expose("/reset", methods=("GET", "POST"))
	@has_access
	def reset(self) -> Any:
		"""GET: render confirmation page.  POST: reset all to built-in defaults."""
		if request.method == "POST":
			session = self.appbuilder.get_session
			mgr = AppConfigManager(session)
			try:
				mgr.reset_to_defaults()
				flash(_("Configuration reset to defaults."), "success")
			except Exception as exc:
				log.exception("Failed to reset config to defaults")
				flash(str(exc), "danger")
			return redirect(url_for("AppConfigView.index"))

		# GET — confirm page
		return self.render_template(
			"appbuilder/config/reset_confirm.html",
			title=_("Reset Configuration"),
			defaults=BUILT_IN_DEFAULTS,
		)
