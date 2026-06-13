"""
pgappforge/citizen_dev/views.py

FAB management UI for citizen-developer custom fields.

Registers two views:
  CustomFieldListView  — read-only table of all rows in pgaf_custom_field
  CustomFieldAdminView — simple JSON form to add/edit a custom field definition
                         (writes to pgaf_custom_field; does NOT alter the schema
                          at runtime — call apply_customizations() on next boot)

Usage in your app factory
--------------------------
::

    from pgappforge.citizen_dev.views import register_citizen_dev_views
    register_citizen_dev_views(appbuilder)
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLAlchemy model for the management table
# (mirrors the DDL created by runtime.create_custom_field_tables)
# ---------------------------------------------------------------------------

def _build_custom_field_model() -> Any:
	"""Build the CustomFieldRecord ORM model lazily to avoid import-time DB hits."""
	try:
		import sqlalchemy as sa
		from sqlalchemy.dialects.postgresql import JSONB
		from pgappforge.models.sqla import Model

		class CustomFieldRecord(Model):	# type: ignore[misc]
			"""ORM row in pgaf_custom_field (informational / UI only)."""
			__tablename__ = "pgaf_custom_field"
			__table_args__ = ({"extend_existing": True},)

			id			= sa.Column(sa.String(36), primary_key=True)
			table_name	= sa.Column(sa.String(100), nullable=False)
			field_name	= sa.Column(sa.String(100), nullable=False)
			field_type	= sa.Column(sa.String(30), nullable=False)
			label		= sa.Column(sa.String(200))
			required	= sa.Column(sa.Boolean, default=False)
			nullable	= sa.Column(sa.Boolean, default=True)
			max_length	= sa.Column(sa.Integer)
			choices		= sa.Column(JSONB, default=list)
			validators	= sa.Column(JSONB, default=list)
			visible_on	= sa.Column(JSONB, default=list)
			created_at	= sa.Column(sa.DateTime(timezone=True))

			def __repr__(self) -> str:
				return f"<CustomField {self.table_name}.{self.field_name}>"

		return CustomFieldRecord

	except Exception as exc:
		log.debug("citizen_dev.views: ORM model build failed: %s", exc)
		return None


# ---------------------------------------------------------------------------
# FAB ModelView (registered only when FAB is available)
# ---------------------------------------------------------------------------

def register_citizen_dev_views(appbuilder: Any) -> bool:
	"""Register custom-field management views with *appbuilder*.

	Returns True on success, False if FAB or the ORM model is unavailable
	(e.g. during unit tests that stub FAB).
	"""
	try:
		from pgappforge import ModelView		# type: ignore[import]
	except ImportError:
		log.debug("citizen_dev.views: ModelView not available — skipping registration")
		return False

	CustomFieldRecord = _build_custom_field_model()
	if CustomFieldRecord is None:
		return False

	try:
		from pgappforge.models.sqla.interface import SQLAInterface	# type: ignore[import]
	except ImportError:
		log.debug("citizen_dev.views: SQLAInterface not available — skipping")
		return False

	class CustomFieldView(ModelView):	# type: ignore[misc]
		"""Read-only view of all citizen-dev custom fields."""

		datamodel = SQLAInterface(CustomFieldRecord)

		list_title = "Custom Fields"
		show_title = "Custom Field Detail"

		list_columns = [
			"table_name", "field_name", "field_type",
			"label", "required", "nullable", "created_at",
		]
		show_columns = [
			"table_name", "field_name", "field_type", "label",
			"required", "nullable", "max_length",
			"choices", "validators", "visible_on", "created_at",
		]

		# Read-only: no add/edit/delete in the UI
		# (schema changes happen via YAML + restart)
		can_create = False
		can_edit = False
		can_delete = False

		search_columns = ["table_name", "field_name", "field_type"]

		label_columns = {
			"table_name": "Table",
			"field_name": "Column Name",
			"field_type": "Type",
			"created_at": "Added At",
		}

	try:
		appbuilder.add_view(
			CustomFieldView,
			"Custom Fields",
			icon="fa-th",
			category="Citizen Dev",
			category_icon="fa-puzzle-piece",
		)
		log.info("citizen_dev.views: CustomFieldView registered")
		return True
	except Exception as exc:
		log.warning("citizen_dev.views: registration failed: %s", exc)
		return False


# ---------------------------------------------------------------------------
# Lightweight REST helper (no FAB dependency)
# ---------------------------------------------------------------------------

def list_custom_fields_json(engine: Any, table_name: str | None = None) -> list[dict]:
	"""Return all rows from pgaf_custom_field as plain dicts.

	Optionally filter by *table_name*.  Useful for REST endpoints and tests
	without instantiating the full FAB view stack.
	"""
	import sqlalchemy as sa

	filters: list[str] = []
	params: dict[str, Any] = {}
	if table_name:
		filters.append("table_name = :tbl")
		params["tbl"] = table_name

	where = f"WHERE {' AND '.join(filters)}" if filters else ""
	sql = f"SELECT * FROM pgaf_custom_field {where} ORDER BY table_name, field_name"

	try:
		with engine.connect() as conn:
			rows = conn.execute(sa.text(sql), params).mappings().all()
			return [dict(r) for r in rows]
	except Exception as exc:
		log.warning("citizen_dev: list_custom_fields_json failed: %s", exc)
		return []


__all__ = [
	"register_citizen_dev_views",
	"list_custom_fields_json",
]
