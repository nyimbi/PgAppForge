"""
pgappforge/graphql/schema.py

Auto-generate a Strawberry GraphQL schema from SQLAlchemy models.

Each registered SQLAlchemy model gets:
  - A dynamic Strawberry @type with one Optional[str] field per column
  - A query field  ``list_<name>(limit, offset)`` → list of that type
  - A query field  ``get_<name>(id)``              → nullable single record

The bare Query always includes health() and version() sentinel fields so
the schema is valid even when no models are discovered.

Usage (app factory)::

    from pgappforge.graphql import add_graphql_view
    add_graphql_view(app, db_session_factory=db.session)

or, when you need the schema object directly::

    from pgappforge.graphql.schema import create_schema
    schema = create_schema(models=[MyModel, OtherModel])
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_all_subclasses(cls) -> list:
	"""Recursively collect all concrete subclasses of *cls*."""
	result = []
	for sub in cls.__subclasses__():
		result.append(sub)
		result.extend(_get_all_subclasses(sub))
	return result


def _model_to_dict(obj: Any) -> dict:
	"""Shallow-serialize a SQLAlchemy row to a plain dict (all values as str|None)."""
	result = {}
	try:
		for col in obj.__table__.columns:
			val = getattr(obj, col.name, None)
			result[col.name] = str(val) if val is not None else None
	except Exception as exc:
		log.debug("_model_to_dict error for %r: %s", obj, exc)
	return result


def _model_to_strawberry_type(model_cls):
	"""Convert a SQLAlchemy model class to a Strawberry @type with Optional[str] fields.

	The returned type is a freshly-constructed class — safe to register once.
	Returns None if strawberry is not installed or model has no table.
	"""
	try:
		import strawberry as sb
	except ImportError:
		return None

	if not hasattr(model_cls, "__table__"):
		return None

	# Build annotations dict — all fields Optional[str]
	annotations: dict[str, Any] = {}
	defaults: dict[str, Any] = {}
	for col in model_cls.__table__.columns:
		annotations[col.name] = Optional[str]
		defaults[col.name] = None

	ns = {"__annotations__": annotations, **defaults}
	raw_type = type(model_cls.__name__, (), ns)
	return sb.type(raw_type)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_schema(models: list | None = None):
	"""Create a Strawberry GraphQL schema from SQLAlchemy models.

	Args:
		models: Explicit list of SQLAlchemy model classes to expose.
		        When None, auto-discovers all subclasses of ``pgappforge.models.sqla.Model``.

	Returns:
		strawberry.Schema — ready to mount on Flask.

	Raises:
		ImportError — if strawberry-graphql is not installed (caller should catch).
	"""
	import strawberry

	# ── Discover models ──────────────────────────────────────────────
	if models is None:
		try:
			from pgappforge.models.sqla import Model as _Base
			models = [
				m for m in _get_all_subclasses(_Base)
				if hasattr(m, "__tablename__")
			]
			log.debug("GraphQL: auto-discovered %d models", len(models))
		except Exception as exc:
			log.warning("GraphQL: model discovery failed — %s", exc)
			models = []

	# ── Build per-model types + resolver factories ────────────────────
	# We accumulate (field_name, resolver, return_annotation) triples then
	# assemble a single Query class via type() at the end.

	query_fields: list[tuple[str, Any, Any]] = []

	for model_cls in models:
		try:
			sb_type = _model_to_strawberry_type(model_cls)
			if sb_type is None:
				continue

			model_name = model_cls.__name__
			list_name  = f"list_{model_name.lower()}"
			get_name   = f"get_{model_name.lower()}"

			# list resolver
			def _make_list(m, t):
				def _resolver(info: strawberry.types.Info, limit: int = 100, offset: int = 0) -> list:
					try:
						from sqlalchemy import select
						session = info.context.get("session")
						if session is None:
							return []
						rows = session.execute(
							select(m).limit(min(limit, 1000)).offset(max(offset, 0))
						).scalars().all()
						return [t(**_model_to_dict(r)) for r in rows]
					except Exception as exc:
						log.warning("GraphQL list_%s error: %s", m.__name__, exc)
						return []
				_resolver.__name__ = f"resolve_{list_name}"
				return _resolver

			# get-by-id resolver
			def _make_get(m, t):
				def _resolver(info: strawberry.types.Info, id: str) -> Optional[Any]:
					try:
						from sqlalchemy import select
						session = info.context.get("session")
						if session is None:
							return None
						pk_col = list(m.__table__.primary_key.columns)[0]
						row = session.execute(
							select(m).where(pk_col == id)
						).scalar_one_or_none()
						return t(**_model_to_dict(row)) if row else None
					except Exception as exc:
						log.warning("GraphQL get_%s error: %s", m.__name__, exc)
						return None
				_resolver.__name__ = f"resolve_{get_name}"
				return _resolver

			query_fields.append((list_name, _make_list(model_cls, sb_type), list[sb_type]))
			query_fields.append((get_name,  _make_get(model_cls, sb_type),  Optional[sb_type]))
			log.debug("GraphQL: added query fields for %s", model_name)

		except Exception as exc:
			log.debug("GraphQL: skipped %s — %s", getattr(model_cls, "__name__", "?"), exc)

	# ── Assemble Query type ───────────────────────────────────────────
	@strawberry.type
	class Query:
		@strawberry.field(description="Health check — returns 'ok'.")
		def health(self) -> str:
			return "ok"

		@strawberry.field(description="Framework version string.")
		def version(self) -> str:
			return "4.8.0"

	# Inject dynamic fields onto the Query class using strawberry.field()
	for field_name, resolver_fn, return_type in query_fields:
		try:
			sf = strawberry.field(resolver=resolver_fn, description=f"Auto-generated field: {field_name}")
			setattr(Query, field_name, sf)
		except Exception as exc:
			log.debug("GraphQL: could not attach field %s — %s", field_name, exc)

	# ── Mutation stub ─────────────────────────────────────────────────
	@strawberry.type
	class Mutation:
		@strawberry.field(description="Placeholder — full mutations available via auto-generated schema.")
		def placeholder(self) -> str:
			return "ok"

	schema = strawberry.Schema(query=Query, mutation=Mutation)
	log.info("GraphQL: schema created with %d auto-generated query fields", len(query_fields))
	return schema


def add_graphql_view(app, db_session_factory=None) -> None:
	"""Register /graphql endpoint (with GraphiQL playground) on a Flask app.

	Args:
		app: Flask application instance.
		db_session_factory: Callable or session object injected into GraphQL context.
		                    When None, falls back to ``app.appbuilder.get_session()``.

	Silently skips registration (with a log message) when strawberry-graphql
	is not installed so the rest of the app continues to function.

	Example::

		from pgappforge.graphql import add_graphql_view
		add_graphql_view(app, db_session_factory=db.session)
	"""
	try:
		import strawberry
		from strawberry.flask.views import GraphQLView
	except ImportError:
		log.info(
			"GraphQL: strawberry-graphql not installed — /graphql endpoint skipped. "
			"Install with: pip install strawberry-graphql[flask]"
		)
		return

	try:
		schema = create_schema()

		def _get_context():
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

		app.add_url_rule(
			"/graphql",
			view_func=GraphQLView.as_view(
				"graphql_view",
				schema=schema,
				graphiql=True,
				get_context=_get_context,
			),
		)
		log.info("GraphQL: /graphql endpoint registered (GraphiQL enabled)")
	except Exception as exc:
		log.warning("GraphQL: setup failed — %s", exc)


__all__ = ["create_schema", "add_graphql_view"]
