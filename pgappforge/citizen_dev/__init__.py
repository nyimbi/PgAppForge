"""
pgappforge/citizen_dev

Citizen-developer configuration layer — YAML-first custom fields and views.

Allows non-developers to extend PgAppForge models with extra columns and
list-view filters by dropping YAML files into a ``custom_fields/`` directory.
No Python required.

Quick start
-----------
1. Create ``custom_fields/my_model.yaml`` (see the example in the project
   root ``custom_fields/`` directory).

2. Call in your app factory::

       from pgappforge.citizen_dev import setup_citizen_dev
       setup_citizen_dev(app, engine, appbuilder=appbuilder)

   This creates the metadata table, applies YAML-defined columns, and
   registers the management UI view.

3. Custom columns are visible in ``pgaf_custom_field`` and available on the
   next application boot.

Public API
----------
load_customizations(directory)    — parse *.yaml files → ModuleCustomization list
apply_customizations(engine)      — ALTER TABLE … ADD COLUMN IF NOT EXISTS …
create_custom_field_tables(engine) — create pgaf_custom_field metadata table
get_applied_customizations()      — return applied customizations for inspection
register_citizen_dev_views(ab)    — register FAB management UI
setup_citizen_dev(app, engine)    — one-shot convenience wrapper
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.citizen_dev.config import (
	SUPPORTED_FIELD_TYPES,
	CustomFieldDef,
	CustomFilterDef,
	ModuleCustomization,
	load_customizations,
)
from pgappforge.citizen_dev.runtime import (
	apply_customizations,
	create_custom_field_tables,
	get_applied_customizations,
)
from pgappforge.citizen_dev.views import (
	register_citizen_dev_views,
	list_custom_fields_json,
)

log = logging.getLogger(__name__)


def setup_citizen_dev(
	app: Any,
	engine: Any,
	appbuilder: Any = None,
	custom_fields_dir: str = "custom_fields",
) -> int:
	"""One-shot initialisation for the citizen-dev layer.

	Performs, in order:

	1. ``create_custom_field_tables(engine)``  — idempotent DDL
	2. ``apply_customizations(engine, ...)``  — ALTER TABLE for new columns
	3. ``register_citizen_dev_views(appbuilder)`` — optional FAB UI

	Parameters
	----------
	app:
		The Flask application instance (used for app context guard).
	engine:
		SQLAlchemy engine.
	appbuilder:
		Optional :class:`pgappforge.AppBuilder` instance.  When provided,
		the management UI view is registered.
	custom_fields_dir:
		Directory to scan for ``*.yaml`` customization files.

	Returns
	-------
	int
		Number of columns added to the database.
	"""
	try:
		create_custom_field_tables(engine)
	except Exception as exc:
		log.warning("citizen_dev: metadata table creation failed: %s", exc)

	added = apply_customizations(engine, custom_fields_dir=custom_fields_dir)

	if appbuilder is not None:
		register_citizen_dev_views(appbuilder)

	log.info("citizen_dev: setup complete — %d column(s) added", added)
	return added


__all__ = [
	# config
	"SUPPORTED_FIELD_TYPES",
	"CustomFieldDef",
	"CustomFilterDef",
	"ModuleCustomization",
	"load_customizations",
	# runtime
	"apply_customizations",
	"create_custom_field_tables",
	"get_applied_customizations",
	# views
	"register_citizen_dev_views",
	"list_custom_fields_json",
	# convenience
	"setup_citizen_dev",
]
