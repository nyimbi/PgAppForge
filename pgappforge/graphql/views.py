"""
pgappforge/graphql/views.py

Flask view that mounts the GraphQL endpoint at /graphql with GraphiQL playground.

This module is intentionally thin — it delegates all schema construction to
pgappforge.graphql.schema.  Import and use ``add_graphql_view`` instead of
registering this blueprint directly unless you need fine-grained control.

Usage::

    # Preferred — app factory
    from pgappforge.graphql import add_graphql_view
    add_graphql_view(app, db_session_factory=db.session)

    # Manual blueprint registration (advanced)
    from pgappforge.graphql.views import graphql_bp
    app.register_blueprint(graphql_bp)
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def register_graphql_blueprint(app, db_session_factory=None) -> bool:
	"""Register the /graphql endpoint on *app* via a Flask Blueprint.

	Returns True if registration succeeded, False if strawberry is missing.

	This is a thin wrapper around ``add_graphql_view`` that also registers a
	blueprint so the URL shows up in ``url_map`` with a clean ``graphql.``
	prefix.
	"""
	try:
		import strawberry
		from strawberry.flask.views import GraphQLView
		from flask import Blueprint
	except ImportError:
		log.info(
			"GraphQL: strawberry-graphql not installed — blueprint skipped. "
			"Install with: pip install strawberry-graphql[flask]"
		)
		return False

	try:
		from pgappforge.graphql.schema import create_schema

		schema = create_schema()

		def _get_context() -> dict[str, Any]:
			from flask import current_app
			try:
				if callable(db_session_factory):
					session = db_session_factory()
				elif db_session_factory is not None:
					session = db_session_factory
				else:
					session = current_app.appbuilder.get_session()
			except Exception:
				session = None
			return {"session": session}

		bp = Blueprint("graphql", __name__, url_prefix="")
		bp.add_url_rule(
			"/graphql",
			view_func=GraphQLView.as_view(
				"graphql_view",
				schema=schema,
				graphiql=True,
				get_context=_get_context,
			),
		)
		app.register_blueprint(bp)
		log.info("GraphQL: blueprint registered — visit /graphql for GraphiQL playground")
		return True
	except Exception as exc:
		log.warning("GraphQL: blueprint registration failed — %s", exc)
		return False


__all__ = ["register_graphql_blueprint"]
