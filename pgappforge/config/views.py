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
})

_NUMBER_KEYS: frozenset[str] = frozenset({
	"SECURITY_SESSION_TIMEOUT",
	"SECURITY_MAX_FAILED_LOGINS",
})

_APPEARANCE_CATEGORY = "appearance"


def _infer_input_type(key: str, value: Any) -> str:
	"""Return an HTML <input> type appropriate for *value*."""
	if key in _COLOR_KEYS:
		return "color"
	if key in _NUMBER_KEYS or isinstance(value, (int, float)):
		return "number"
	if key in _BOOL_KEYS or isinstance(value, bool):
		return "checkbox"
	return "text"


def _coerce_value(key: str, raw: str) -> Any:
	"""
	Convert the raw form string back to the correct Python type.
	Booleans come through as "on" / absent from POST data.
	"""
	if key in _BOOL_KEYS:
		return raw == "on"
	if key in _NUMBER_KEYS:
		return int(raw) if raw.isdigit() else float(raw)
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
	GET  /app-config/                      — category index with search
	GET  /app-config/category/<name>       — configs for one category
	GET/POST /app-config/edit/<key>        — edit a single config entry
	GET  /app-config/preview               — live appearance preview panel
	"""

	route_base = "/app-config"
	default_view = "index"

	# ------------------------------------------------------------------
	# Index — category summary + search
	# ------------------------------------------------------------------

	@expose("/", methods=("GET",))
	@has_access
	def index(self) -> str:
		"""List all categories; honour ?q= for a simple key/label search."""
		session = self._db_session()
		mgr = AppConfigManager(session)

		query = request.args.get("q", "").strip().lower()

		rows = mgr._all_rows()
		if query:
			rows = [
				r for r in rows
				if query in r.key.lower()
				or (r.label and query in r.label.lower())
				or query in r.category.lower()
			]

		# Group by category for the template
		categories: dict[str, list[AppConfig]] = {}
		for row in rows:
			categories.setdefault(row.category, []).append(row)

		return self.render_template(
			"appbuilder/config/index.html",
			categories=categories,
			query=query,
			title=_("Application Configuration"),
		)

	# ------------------------------------------------------------------
	# Category view
	# ------------------------------------------------------------------

	@expose("/category/<string:name>", methods=("GET",))
	@has_access
	def category(self, name: str) -> str:
		session = self._db_session()
		rows = (
			session.query(AppConfig)
			.filter_by(category=name)
			.order_by(AppConfig.key)
			.all()
		)
		return self.render_template(
			"appbuilder/config/category.html",
			rows=rows,
			category_name=name,
			title=_(f"Configuration — {name.title()}"),
		)

	# ------------------------------------------------------------------
	# Edit single key
	# ------------------------------------------------------------------

	@expose("/edit/<path:key>", methods=("GET", "POST"))
	@has_access
	def edit(self, key: str) -> Any:
		session = self._db_session()
		row = session.query(AppConfig).filter_by(key=key).one_or_none()

		if row is None:
			flash(_(f"Config key '{key}' not found."), "danger")
			return redirect(url_for("AppConfigView.index"))

		if row.is_readonly:
			flash(_(f"'{key}' is read-only and cannot be edited."), "warning")
			return redirect(url_for("AppConfigView.category", name=row.category))

		if request.method == "POST":
			raw = request.form.get("value", "")
			# Checkboxes are absent from POST data when unchecked
			if key in _BOOL_KEYS:
				raw = request.form.get("value", "")
			try:
				new_value = _coerce_value(key, raw)
				mgr = AppConfigManager(session)
				mgr.set(
					key,
					new_value,
					category=row.category,
					label=row.label,
					description=row.description,
					is_sensitive=row.is_sensitive,
					is_readonly=row.is_readonly,
				)
				flash(_(f"'{row.label or key}' saved successfully."), "success")
				return redirect(url_for("AppConfigView.category", name=row.category))
			except Exception as exc:
				log.exception("Failed to save config key %r", key)
				flash(str(exc), "danger")

		input_type = _infer_input_type(key, row.value)
		is_appearance = row.category == _APPEARANCE_CATEGORY

		return self.render_template(
			"appbuilder/config/edit.html",
			row=row,
			input_type=input_type,
			is_appearance=is_appearance,
			title=_(f"Edit — {row.label or key}"),
		)

	# ------------------------------------------------------------------
	# Appearance live preview (GET only, returns partial JSON payload
	# suitable for an AJAX refresh of the preview panel)
	# ------------------------------------------------------------------

	@expose("/preview", methods=("GET",))
	@has_access
	def preview(self) -> Any:
		"""
		Renders a self-contained preview panel showing the current
		appearance settings applied to a dummy Bootstrap 3 card.
		"""
		session = self._db_session()
		mgr = AppConfigManager(session)
		appearance = mgr.get_category(_APPEARANCE_CATEGORY)

		return self.render_template(
			"appbuilder/config/preview.html",
			appearance=appearance,
			title=_("Appearance Preview"),
		)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _db_session(self) -> Any:
		"""Retrieve the SQLAlchemy session from the appbuilder context."""
		return self.appbuilder.get_session
