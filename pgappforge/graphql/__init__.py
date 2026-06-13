"""
pgappforge/graphql
==================

Auto-generated GraphQL API layer for PgAppForge, backed by Strawberry.

Quick-start
-----------
In your Flask app factory::

    from pgappforge.graphql import add_graphql_view
    add_graphql_view(app, db_session_factory=db.session)

This registers a ``/graphql`` endpoint that serves both the GraphQL API and
an in-browser GraphiQL playground.  The endpoint is a no-op (with a log
message) when ``strawberry-graphql`` is not installed, so activating this
module never breaks apps that don't need GraphQL.

Install the optional dependency::

    pip install strawberry-graphql[flask]

Architecture
------------
- ``schema.py``  — auto-discovers SQLAlchemy models → dynamic Strawberry types
                   + list/get query fields; exposes ``create_schema()`` and
                   ``add_graphql_view()``.
- ``types.py``   — shared scalars (JSON, DateTime, Cursor) and base types
                   (PageInfo, ErrorType).
- ``views.py``   — Flask Blueprint wrapper around the Strawberry GraphQLView.

Public re-exports
-----------------
``add_graphql_view``  — register /graphql on a Flask app (preferred entry point).
``create_schema``     — build schema from an explicit model list.
``register_graphql_blueprint`` — blueprint-based registration (advanced).
"""
from __future__ import annotations

from pgappforge.graphql.schema import add_graphql_view, create_schema
from pgappforge.graphql.views import register_graphql_blueprint

__all__ = [
	"add_graphql_view",
	"create_schema",
	"register_graphql_blueprint",
]
