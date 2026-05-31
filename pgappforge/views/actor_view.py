"""
ActorModelView — ModelView subclass that auto-configures from ActorConfig.

Provides:
  - Titles (list/add/edit/show) sourced from ActorConfig.display rather than
    hardcoded strings, so renaming Customer→Client happens in one JSON field.
  - A /search endpoint that calls ActorRegistry.search_all() across all
    registered actor types simultaneously.
  - actor_config property for template access.

Usage::

    class PatientView(ActorModelView):
        actor_role = "patient"
        datamodel = SQLAInterface(Patient)
        list_columns = ["actor_display_name", "actor_status", "actor_contact_email"]
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, TYPE_CHECKING

from flask import jsonify, request
from pgappforge.baseviews import BaseView, expose
from pgappforge.views import ModelView

if TYPE_CHECKING:
	from pgappforge.templates.core.actor import ActorConfig

log = logging.getLogger(__name__)


class ActorModelView(ModelView):
	"""ModelView that auto-configures titles from ActorConfig.

	Subclass and declare ``actor_role`` matching the registered ActorConfig::

	    class PatientView(ActorModelView):
	        actor_role = "patient"
	        datamodel = SQLAInterface(Patient)

	Titles default to the ActorConfig display labels.  Override any of
	``list_title``, ``add_title``, ``edit_title``, ``show_title`` in the
	subclass to customise further.
	"""

	actor_role: ClassVar[str] = ""

	def _init_titles(self) -> None:
		"""Override the standard title init to source labels from ActorConfig."""
		cfg = self._actor_config
		if cfg is not None:
			if not self.list_title:
				self.list_title = cfg.display.plural
			if not self.add_title:
				self.add_title = f"Add {cfg.display.singular}"
			if not self.edit_title:
				self.edit_title = f"Edit {cfg.display.singular}"
			if not self.show_title:
				self.show_title = cfg.display.singular
		super()._init_titles()

	@property
	def _actor_config(self) -> ActorConfig | None:
		if not self.actor_role:
			return None
		from pgappforge.templates.core.actor import ActorRegistry
		return ActorRegistry.instance().get(self.actor_role)


class ActorSearchView(BaseView):
	"""Standalone view providing a cross-actor search endpoint.

	Register once in your AppBuilder::

	    appbuilder.add_view_no_menu(ActorSearchView)

	Then call::

	    GET /actor-search/search?q=Smith&limit=10

	Returns::

	    {
	        "results": [
	            {"role": "patient", "display_name": "Jane Smith",
	             "contact_email": "jane@example.com", "status": "active",
	             "external_ids": {"mrn": "MRN-001"}},
	            ...
	        ],
	        "total": 3
	    }
	"""

	route_base = "/actor-search"
	default_view = "search"

	@expose("/search")
	def search(self) -> Any:
		query = request.args.get("q", "").strip()
		limit = min(int(request.args.get("limit", 20)), 100)
		if not query or len(query) < 2:
			return jsonify({"results": [], "total": 0, "error": "query must be ≥ 2 chars"})
		try:
			from pgappforge.templates.core.actor import ActorRegistry
			from flask import current_app
			# Obtain the SQLAlchemy session from the AppBuilder
			appbuilder = current_app.extensions.get("appbuilder")
			if appbuilder is None:
				return jsonify({"results": [], "total": 0, "error": "appbuilder not found"})
			session = appbuilder.session
			registry = ActorRegistry.instance()
			raw = registry.search_all(query, session, limit_per_actor=max(1, limit // max(1, len(registry.all_roles()))))
			results = [
				{
					"role": r.role,
					"sub_role": r.sub_role,
					"display_name": r.display_name,
					"contact_email": r.contact_email,
					"status": r.status,
					"external_ids": r.external_ids,
				}
				for r in raw
			]
			return jsonify({"results": results, "total": len(results)})
		except Exception as exc:
			log.exception("actor search failed")
			return jsonify({"results": [], "total": 0, "error": str(exc)}), 500
