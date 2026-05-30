"""
pgappforge.forms.layout_manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Persistent, per-view form layout configuration.

FormLayout stores field ordering, widget overrides, labels, help text,
required flags, and conditional visibility rules as a JSONB document.
FormLayoutManager provides the read/write/apply API consumed by
FormLayoutEditorView and the FAB view mixin.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge import Model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLAlchemy model
# ---------------------------------------------------------------------------

class FormLayout(Model):
	"""Persists the admin-configured layout for a single (view, form_type) pair.

	layout_config is a list of field-config dicts::

		[
			{
				"field_name":   "first_name",
				"widget_type":  "BS3TextFieldWidget",
				"label":        "First Name",
				"help_text":    "Legal first name",
				"required":     true,
				"order":        0,
				"visible_when": {"field": "status", "equals": "active"}  # or null
			},
			...
		]
	"""

	__tablename__ = "pgf_form_layout"
	__allow_unmapped__ = True

	__table_args__ = (
		UniqueConstraint("view_name", "form_type", name="uq_pgf_form_layout_view_type"),
	)

	id = Column(Integer, primary_key=True)
	view_name = Column(String(128), nullable=False, index=True)
	form_type = Column(String(16), nullable=False)	# "add" | "edit"
	layout_config = Column(JSONB, nullable=False, default=list)

	def __repr__(self) -> str:
		return f"<FormLayout {self.view_name!r} {self.form_type!r}>"


# ---------------------------------------------------------------------------
# Field-config schema helpers
# ---------------------------------------------------------------------------

#: Complete set of widget names surfaced in the editor dropdown.
AVAILABLE_WIDGETS: list[str] = [
	"BS3TextFieldWidget",
	"BS3TextAreaFieldWidget",
	"BS3PasswordFieldWidget",
	"BS3SelectFieldWidget",
	"BS3SelectMultipleFieldWidget",
	"Select2Widget",
	"Select2ManyWidget",
	"Select2AJAXWidget",
	"DatePickerWidget",
	"DateTimePickerWidget",
]


def _default_field_config(field_name: str, order: int) -> dict[str, Any]:
	"""Return a well-structured field config with defaults."""
	return {
		"field_name": field_name,
		"widget_type": "BS3TextFieldWidget",
		"label": field_name.replace("_", " ").title(),
		"help_text": "",
		"required": False,
		"order": order,
		"visible_when": None,
	}


def _validate_field_config(cfg: dict[str, Any]) -> dict[str, Any]:
	"""Return a copy of *cfg* with all required keys present and sane."""
	defaults = _default_field_config(cfg.get("field_name", ""), cfg.get("order", 0))
	merged = {**defaults, **cfg}

	# Ensure visible_when is either None or {"field": str, "equals": any}
	vw = merged.get("visible_when")
	if vw is not None:
		if not (isinstance(vw, dict) and "field" in vw and "equals" in vw):
			log.warning("Discarding malformed visible_when for field %r: %r", merged["field_name"], vw)
			merged["visible_when"] = None

	# widget_type must be a known widget (or at least a non-empty string)
	if not merged.get("widget_type"):
		merged["widget_type"] = "BS3TextFieldWidget"

	return merged


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class FormLayoutManager:
	"""Read/write/apply form layout configurations.

	Usage::

		mgr = FormLayoutManager(db_session)
		layout = mgr.get_layout("EmployeeView", "add")
		form   = mgr.apply_layout(form, layout)

	All database I/O is isolated here — the rest of the system is
	oblivious to the storage format.
	"""

	def __init__(self, session: Any) -> None:
		"""
		Args:
			session: An active SQLAlchemy ``Session`` (or scoped-session proxy).
		"""
		self._session = session

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def get_layout(self, view_name: str, form_type: str) -> list[dict[str, Any]]:
		"""Return the persisted layout for *(view_name, form_type)*.

		Returns an empty list when no layout has been saved yet — callers
		should treat that as "use the default form field order".
		"""
		record = self._fetch(view_name, form_type)
		if record is None:
			return []
		raw: list[dict[str, Any]] = record.layout_config or []
		return sorted(
			[_validate_field_config(c) for c in raw],
			key=lambda c: c["order"],
		)

	def save_layout(
		self,
		view_name: str,
		form_type: str,
		layout: list[dict[str, Any]],
	) -> None:
		"""Persist *layout* for *(view_name, form_type)*.

		Creates a new record or overwrites the existing one.  Each entry
		in *layout* must at minimum contain ``"field_name"``; all other
		keys are filled from :func:`_validate_field_config` defaults.

		Args:
			view_name:  Class name of the ModelView (e.g. ``"EmployeeView"``).
			form_type:  ``"add"`` or ``"edit"``.
			layout:     List of field-config dicts in desired display order.

		Raises:
			ValueError: if *form_type* is not ``"add"`` or ``"edit"``.
		"""
		if form_type not in ("add", "edit"):
			raise ValueError(f"form_type must be 'add' or 'edit', got {form_type!r}")

		validated = [
			{**_validate_field_config(c), "order": idx}
			for idx, c in enumerate(layout)
		]

		record = self._fetch(view_name, form_type)
		if record is None:
			record = FormLayout(view_name=view_name, form_type=form_type)
			self._session.add(record)

		record.layout_config = validated
		self._session.commit()
		log.info("Saved form layout for %s/%s (%d fields)", view_name, form_type, len(validated))

	def reset_layout(self, view_name: str, form_type: str) -> None:
		"""Delete any saved layout so the view reverts to its defaults.

		No-op if no layout exists.
		"""
		record = self._fetch(view_name, form_type)
		if record is not None:
			self._session.delete(record)
			self._session.commit()
			log.info("Reset form layout for %s/%s", view_name, form_type)

	def apply_layout(self, form: Any, layout: list[dict[str, Any]]) -> Any:
		"""Reorder and annotate form fields according to *layout*.

		Fields present in *layout* are kept (in layout order); fields not
		mentioned are dropped from the rendered set.  When *layout* is
		empty the original form is returned unchanged.

		The function mutates only the *field ordering* on the form's
		``_fields`` OrderedDict, plus ``label`` / ``description`` /
		``flags.required`` if those are overridden in *layout*.  It never
		adds or removes field objects — it only resequences and annotates
		existing ones so WTForms validation still works correctly.

		Args:
			form:    A WTForms form instance (already instantiated).
			layout:  Output of :meth:`get_layout`.

		Returns:
			The same *form* object, mutated in place.
		"""
		if not layout:
			return form

		from collections import OrderedDict

		field_map: dict[str, Any] = dict(form._fields)
		new_fields: OrderedDict[str, Any] = OrderedDict()

		for cfg in layout:
			fname = cfg["field_name"]
			if fname not in field_map:
				log.debug("Layout references unknown field %r on %s — skipping", fname, type(form).__name__)
				continue

			field = field_map[fname]

			# Override label
			if cfg.get("label"):
				field.label.text = cfg["label"]

			# Override help / description (stored on field.description by WTForms)
			if cfg.get("help_text") is not None:
				field.description = cfg["help_text"]

			# Override required flag (read by templates via field.flags.required)
			try:
				field.flags.required = bool(cfg.get("required", False))
			except AttributeError:
				pass	# some field types don't expose flags

			new_fields[fname] = field

		form._fields = new_fields
		return form

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _fetch(self, view_name: str, form_type: str) -> FormLayout | None:
		try:
			from sqlalchemy import select
			stmt = (
				select(FormLayout)
				.where(FormLayout.view_name == view_name)
				.where(FormLayout.form_type == form_type)
				.limit(1)
			)
			result = self._session.execute(stmt)
			return result.scalars().first()
		except Exception:
			log.exception("Error fetching FormLayout for %s/%s", view_name, form_type)
			return None
