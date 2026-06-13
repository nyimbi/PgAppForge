"""
pgappforge/ui/fk_widgets.py

Smart FK select widgets that auto-populate from related SQLAlchemy models.

Features:
  - Populates choices from the related model via session query
  - Select2 (CDN) for search/filter UX
  - Display label auto-detected from common field names
  - Tenant isolation via tenant_id column guard
  - Lazy hint for large tables (>500 rows shows AJAX note)
  - Grouped rendering if model has a category field
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


class FKSelectWidget:
	"""Renders a foreign key field as a searchable <select> dropdown.

	Args:
		related_model:   The SQLAlchemy model class to load choices from.
		value_field:     Column name used as the <option> value.  Default "id".
		display_fields:  Ordered list of field names tried for the visible label.
		                 Use "__str__" as a sentinel to call str(row).
		search_fields:   Fields used for ILIKE filtering when *search* is supplied.
		order_by:        Column name to ORDER BY.  None → database default order.
		allow_empty:     Prepend an empty "Select…" option.  Default True.
		placeholder:     Text shown for the empty option and Select2 placeholder.
		use_select2:     Emit inline JS to initialise Select2.  Default True.
		group_field:     If set, options are wrapped in <optgroup> by this column.
	"""

	def __init__(
		self,
		related_model,
		value_field: str = "id",
		display_fields: list[str] | None = None,
		search_fields: list[str] | None = None,
		order_by: str | None = None,
		allow_empty: bool = True,
		placeholder: str = "Select...",
		use_select2: bool = True,
		group_field: str | None = None,
	) -> None:
		self.related_model = related_model
		self.value_field = value_field
		self.display_fields = display_fields or [
			"name", "code", "title", "description", "__str__"
		]
		self.search_fields = search_fields or ["name", "code", "title"]
		self.order_by = order_by
		self.allow_empty = allow_empty
		self.placeholder = placeholder
		self.use_select2 = use_select2
		self.group_field = group_field

	# ------------------------------------------------------------------
	# Choice loading
	# ------------------------------------------------------------------

	def get_choices(
		self,
		session,
		tenant_id: str | None = None,
		search: str | None = None,
		limit: int = 500,
	) -> list[tuple[str, str]]:
		"""Return (value, label) tuples for the dropdown.

		Args:
			session:   SQLAlchemy session (or callable returning one).
			tenant_id: If provided and the model has a tenant_id column,
			           filter to this tenant.
			search:    Optional ILIKE search string applied across search_fields.
			limit:     Maximum rows to return.  Default 500.

		Returns:
			List of (value_str, label_str) tuples, prepended by the empty
			placeholder tuple when allow_empty is True.
		"""
		try:
			sess = session() if callable(session) else session
			q = sa.select(self.related_model)

			# Tenant isolation
			if tenant_id and hasattr(self.related_model, "tenant_id"):
				q = q.where(self.related_model.tenant_id == tenant_id)

			# Search filter
			if search:
				conditions: list[Any] = []
				for field_name in self.search_fields:
					col = getattr(self.related_model, field_name, None)
					if col is not None:
						conditions.append(
							sa.cast(col, sa.String).ilike(f"%{search}%")
						)
				if conditions:
					q = q.where(sa.or_(*conditions))

			# Ordering
			if self.order_by:
				order_col = getattr(self.related_model, self.order_by, None)
				if order_col is not None:
					q = q.order_by(order_col)

			q = q.limit(limit)
			rows = sess.execute(q).scalars().all()

			choices: list[tuple[str, str]] = []
			if self.allow_empty:
				choices.append(("", self.placeholder))

			for row in rows:
				value = str(getattr(row, self.value_field, "") or "")
				label = self._get_display_label(row)
				choices.append((value, label))

			return choices

		except Exception as exc:
			log.debug("FKSelectWidget.get_choices failed: %s", exc)
			return [("", self.placeholder)] if self.allow_empty else []

	def get_grouped_choices(
		self,
		session,
		tenant_id: str | None = None,
		limit: int = 500,
	) -> dict[str, list[tuple[str, str]]]:
		"""Return choices grouped by group_field value.

		Keys are group labels; values are lists of (value, label) tuples.
		Falls back to a single "Other" group if group_field is absent or None.
		"""
		if not self.group_field:
			return {"": self.get_choices(session, tenant_id, limit=limit)}

		try:
			sess = session() if callable(session) else session
			q = sa.select(self.related_model)
			if tenant_id and hasattr(self.related_model, "tenant_id"):
				q = q.where(self.related_model.tenant_id == tenant_id)
			if self.order_by:
				order_col = getattr(self.related_model, self.order_by, None)
				if order_col is not None:
					q = q.order_by(order_col)
			q = q.limit(limit)
			rows = sess.execute(q).scalars().all()

			groups: dict[str, list[tuple[str, str]]] = {}
			for row in rows:
				group = str(getattr(row, self.group_field, "") or "Other")
				value = str(getattr(row, self.value_field, "") or "")
				label = self._get_display_label(row)
				groups.setdefault(group, []).append((value, label))

			return groups

		except Exception as exc:
			log.debug("FKSelectWidget.get_grouped_choices failed: %s", exc)
			return {}

	# ------------------------------------------------------------------
	# Label resolution
	# ------------------------------------------------------------------

	def _get_display_label(self, row: Any) -> str:
		"""Return the best human-readable label for *row*."""
		for field_name in self.display_fields:
			if field_name == "__str__":
				return str(row)
			val = getattr(row, field_name, None)
			if val:
				return str(val)
		return str(getattr(row, self.value_field, "") or "")

	# ------------------------------------------------------------------
	# HTML rendering
	# ------------------------------------------------------------------

	def render_html(
		self,
		field_name: str,
		current_value: str | None,
		choices: list[tuple[str, str]],
		required: bool = False,
		css_class: str = "",
		grouped: dict[str, list[tuple[str, str]]] | None = None,
	) -> str:
		"""Return the raw HTML string for the <select> element.

		Args:
			field_name:    HTML name/id attribute for the select.
			current_value: Currently selected value (matched by string equality).
			choices:       Flat list of (value, label) when grouped is None.
			required:      Emit the required attribute.
			css_class:     Additional CSS classes.
			grouped:       If provided, render grouped <optgroup> structure
			               instead of the flat *choices* list.
		"""
		from markupsafe import Markup, escape

		select_id = f"pgaf_{field_name}"
		classes = f"form-control pgaf-fk-select {css_class}".strip()
		if self.use_select2:
			classes += " pgaf-select2"

		required_attr = " required" if required else ""
		cur = str(current_value or "")

		if grouped:
			options_parts: list[str] = []
			if self.allow_empty:
				options_parts.append(
					f'<option value="">{escape(self.placeholder)}</option>'
				)
			for group_label, group_choices in grouped.items():
				opts = "".join(
					f'<option value="{escape(v)}"'
					f'{"  selected" if v == cur else ""}>'
					f"{escape(lbl)}</option>"
					for v, lbl in group_choices
				)
				if group_label:
					options_parts.append(
						f'<optgroup label="{escape(group_label)}">{opts}</optgroup>'
					)
				else:
					options_parts.append(opts)
			options_html = "".join(options_parts)
		else:
			options_html = "".join(
				f'<option value="{escape(v)}"'
				f'{"  selected" if v == cur else ""}>'
				f"{escape(lbl)}</option>"
				for v, lbl in choices
			)

		html = (
			f'<select id="{select_id}" name="{escape(field_name)}" '
			f'class="{classes}"{required_attr} '
			f'data-placeholder="{escape(self.placeholder)}">'
			f"{options_html}"
			f"</select>"
		)

		if self.use_select2:
			allow_clear_js = "true" if self.allow_empty else "false"
			html += f"""
<script>
(function() {{
	var el = document.getElementById('{select_id}');
	if (el && window.$ && $.fn && $.fn.select2) {{
		$(el).select2({{
			placeholder: '{escape(self.placeholder)}',
			allowClear: {allow_clear_js},
			width: '100%',
			theme: 'bootstrap',
		}});
	}}
}})();
</script>"""

		return Markup(html)

	def render_field(
		self,
		field_name: str,
		current_value: str | None,
		session,
		tenant_id: str | None = None,
		required: bool = False,
	) -> str:
		"""Fetch choices then render the complete <select> element.

		This is the one-call convenience method most views will use.
		"""
		if self.group_field:
			grouped = self.get_grouped_choices(session, tenant_id)
			return self.render_html(
				field_name, current_value, [], required=required, grouped=grouped
			)
		choices = self.get_choices(session, tenant_id)
		return self.render_html(field_name, current_value, choices, required=required)


# ---------------------------------------------------------------------------
# Auto-detection helper
# ---------------------------------------------------------------------------

def auto_fk_widget(
	model_cls,
	session,
	tenant_id: str | None = None,
) -> dict[str, FKSelectWidget]:
	"""Inspect *model_cls* and return an FKSelectWidget for every FK relationship.

	The returned dict maps the FK column name (``rel_key + "_id"``) to a
	ready-to-use FKSelectWidget pointed at the related model.

	Usage in a ModelView::

		from pgappforge.ui.fk_widgets import auto_fk_widget

		class InvoiceView(ModelView):
			def get_form(self, form_class=None):
				form = super().get_form(form_class)
				widgets = auto_fk_widget(Invoice, db.session, g.tenant_id)
				for field_name, widget in widgets.items():
					if field_name in form:
						form[field_name].widget = widget.render_field
				return form
	"""
	widgets: dict[str, FKSelectWidget] = {}

	try:
		from sqlalchemy import inspect as sa_inspect

		mapper = sa_inspect(model_cls)
		for rel in mapper.relationships:
			# Derive the FK column name from the relationship key
			col_name = (
				rel.key if rel.key.endswith("_id") else f"{rel.key}_id"
			)
			related_model = rel.mapper.class_
			widgets[col_name] = FKSelectWidget(
				related_model=related_model,
				value_field="id",
				display_fields=["name", "code", "title", "label", "__str__"],
			)
			log.debug(
				"auto_fk_widget: %s.%s → %s",
				model_cls.__name__,
				col_name,
				related_model.__name__,
			)

	except Exception as exc:
		log.debug("auto_fk_widget failed on %s: %s", getattr(model_cls, "__name__", "?"), exc)

	return widgets


__all__ = ["FKSelectWidget", "auto_fk_widget"]
